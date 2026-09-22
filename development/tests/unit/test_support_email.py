"""Offline contracts for assistance and support-ticket email delivery."""

from email import message_from_string, policy
from functools import partial
import logging
from types import SimpleNamespace
from typing import Callable, Dict, Optional
from unittest.mock import MagicMock, Mock, call

import pytest

import kneespa
from kneespa import KneeSpa

pytestmark = pytest.mark.unit

ISSUE = "Pressure won't rise.\nChecked the café outlet."
ACKNOWLEDGEMENT = "Support ticket is being sent."


@pytest.fixture
def email_run(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Control SMTP and thread execution without constructing the hardware UI."""
    settings = {
        "SENDER_EMAIL": "kiosk@example.test",
        "SENDER_PASSWORD": "test-password",
        "RECEIVER_EMAIL": "assistance@example.test",
        "TICKET_EMAIL": "tickets@example.test",
        "SMTP_SERVER": "smtp.example.test",
        "SMTP_PORT": 465,
    }
    monkeypatch.setattr(kneespa, "EMAIL_CONFIG", settings)
    server = MagicMock(spec=kneespa.smtplib.SMTP_SSL)
    smtp = MagicMock(spec=kneespa.smtplib.SMTP_SSL)
    smtp.return_value.__enter__.return_value = server
    thread = Mock(spec=kneespa.threading.Thread)
    thread_factory = Mock(return_value=thread)
    monkeypatch.setattr(kneespa.smtplib, "SMTP_SSL", smtp)
    monkeypatch.setattr(kneespa.threading, "Thread", thread_factory)
    window = SimpleNamespace(
        username="Dr. Zoë",
        user_email="clinician@example.test",
        user_status="admin",
        current_user={"username": "Dr. Zoë", "status": "admin"},
        config=SimpleNamespace(ensure_device_id=Mock(return_value="dev123")),
        logger=Mock(spec=logging.Logger),
        _show_timed_error=Mock(),
    )
    window.email_admin = partial(KneeSpa.email_admin, window)
    window.submit_ticket = partial(KneeSpa.submit_ticket, window)
    window._send_support_email = partial(KneeSpa._send_support_email, window)
    return SimpleNamespace(
        window=window, settings=settings, smtp=smtp, server=server,
        thread=thread, thread_factory=thread_factory,
    )


def queue_email(run: SimpleNamespace, kind: str) -> Callable[[], None]:
    """Queue one daemon worker and check feedback before allowing SMTP to run."""
    if kind == "assistance":
        run.window.email_admin()
        run.window._show_timed_error.assert_not_called()
    else:
        run.window.submit_ticket(ISSUE)
        run.window._show_timed_error.assert_called_once_with(ACKNOWLEDGEMENT)
    run.thread_factory.assert_called_once()
    assert run.thread_factory.call_args.kwargs["daemon"] is True
    run.thread.start.assert_called_once_with()
    run.smtp.assert_not_called()
    return run.thread_factory.call_args.kwargs["target"]


def failure_prefix(kind: str) -> str:
    """Return the existing diagnostic for each public workflow."""
    return "Failed to send assistance email" if kind == "assistance" else "Failed to send ticket"


@pytest.mark.parametrize("kind", ["assistance", "ticket"])
def test_message_and_transport_contract(
    email_run: SimpleNamespace, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run = email_run
    deliver = queue_email(run, kind)
    # Queued work retains the message, destination and credentials captured by
    # the UI call, even if another operator logs in or configuration changes.
    for key in run.settings:
        run.settings[key] = "changed"
    run.window.username = "Another operator"
    run.window.current_user = None
    deliver()

    run.smtp.assert_called_once_with("smtp.example.test", 465, timeout=15)
    run.smtp.return_value.__enter__.assert_called_once_with()
    run.smtp.return_value.__exit__.assert_called_once_with(None, None, None)
    run.server.login.assert_called_once_with("kiosk@example.test", "test-password")
    run.server.sendmail.assert_called_once()
    sender, recipient, serialized = run.server.sendmail.call_args.args
    assert sender == "kiosk@example.test"
    message = message_from_string(serialized, policy=policy.default)
    assert str(message["From"]) == sender
    assert str(message["To"]) == recipient
    assert message.get_content_type() == "text/plain"
    if kind == "assistance":
        assert recipient == "assistance@example.test"
        assert str(message["Subject"]) == "Assistance Request"
        body = (
            "User Dr. Zoë with email clinician@example.test and status admin "
            "is requesting assistance."
        )
        assert message.get_content() == body
        assert capsys.readouterr().out == body + "\nAssistance request email sent successfully.\n"
        run.window.config.ensure_device_id.assert_not_called()
    else:
        assert recipient == "tickets@example.test"
        assert str(message["Subject"]) == "[KneeSpa dev123] Support ticket"
        assert message.get_content() == f"Device: dev123\nUser: Dr. Zoë (admin)\n\nIssue:\n{ISSUE}"
        assert capsys.readouterr().out == "Support ticket sent successfully.\n"
        run.window.config.ensure_device_id.assert_called_once_with()
        run.window._show_timed_error.assert_called_once_with(ACKNOWLEDGEMENT)
    assert run.server.method_calls == [
        call.login("kiosk@example.test", "test-password"),
        call.sendmail(sender, recipient, serialized),
    ]
    run.window.logger.error.assert_not_called()


@pytest.mark.parametrize("success", [True, False])
def test_delivery_feedback_prevents_duplicate_requests_and_allows_retry(email_run, success):
    """Queued delivery is distinct from completion, with retry restored by the GUI slot."""
    run = email_run
    run.window.shell = SimpleNamespace(support=Mock())
    run.window.support_email_result = Mock()
    deliver = queue_email(run, "ticket")
    run.window.shell.support.set_delivery_state.assert_called_once_with(
        "sending", "Sending request…",
    )
    run.window.email_admin()
    run.thread_factory.assert_called_once()
    if not success:
        run.server.sendmail.side_effect = OSError("Offline test failure")
    deliver()
    result = run.window.support_email_result.emit.call_args.args
    assert result[0] is success
    KneeSpa._on_support_email_result(run.window, *result)
    assert not run.window._support_mail_busy
    assert run.window.shell.support.set_delivery_state.call_args.args[0] == (
        "sent" if success else "failed"
    )


def test_worker_start_failure_leaves_support_retryable(email_run):
    run = email_run
    run.window.shell = SimpleNamespace(support=Mock())
    run.thread.start.side_effect = RuntimeError("Thread unavailable")
    run.window.email_admin()
    assert not run.window._support_mail_busy
    assert run.window.shell.support.set_delivery_state.call_args.args[0] == "failed"
    run.smtp.assert_not_called()


@pytest.mark.parametrize("kind", ["assistance", "ticket"])
@pytest.mark.parametrize("missing", ["SENDER_EMAIL", "SENDER_PASSWORD", "recipient"])
def test_missing_credentials_log_without_connecting(
    email_run: SimpleNamespace, kind: str, missing: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = email_run
    if missing == "recipient":
        missing = "RECEIVER_EMAIL" if kind == "assistance" else "TICKET_EMAIL"
    run.settings[missing] = ""
    queue_email(run, kind)()

    run.smtp.assert_not_called()
    diagnostic = f"{failure_prefix(kind)}: SMTP credentials are not configured"
    run.window.logger.error.assert_called_once_with(diagnostic)
    assert diagnostic in capsys.readouterr().out
    if kind == "ticket":
        run.window._show_timed_error.assert_called_once_with(ACKNOWLEDGEMENT)
    else:
        run.window._show_timed_error.assert_not_called()


@pytest.mark.parametrize("kind", ["assistance", "ticket"])
@pytest.mark.parametrize("stage", ["connect", "enter", "login", "sendmail", "exit"])
def test_smtp_failures_are_logged_by_the_worker(
    email_run: SimpleNamespace, kind: str, stage: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = email_run
    operation = {
        "connect": run.smtp,
        "enter": run.smtp.return_value.__enter__,
        "login": run.server.login,
        "sendmail": run.server.sendmail,
        "exit": run.smtp.return_value.__exit__,
    }[stage]
    operation.side_effect = OSError(f"{stage} failed")
    queue_email(run, kind)()

    diagnostic = f"{failure_prefix(kind)}: {stage} failed"
    run.window.logger.error.assert_called_once_with(diagnostic)
    output = capsys.readouterr().out
    assert diagnostic in output
    assert "sent successfully" not in output
    if stage in ("connect", "enter", "login"):
        run.server.sendmail.assert_not_called()
    if kind == "ticket":
        run.window._show_timed_error.assert_called_once_with(ACKNOWLEDGEMENT)
    else:
        run.window._show_timed_error.assert_not_called()


@pytest.mark.parametrize("user", [None, {}, {"username": "Operator"}])
@pytest.mark.parametrize("device_failure", [False, True])
def test_ticket_identity_fallbacks(
    email_run: SimpleNamespace, user: Optional[Dict[str, str]], device_failure: bool
) -> None:
    run = email_run
    run.window.current_user = user
    if device_failure:
        run.window.config.ensure_device_id.side_effect = OSError("config unavailable")
    queue_email(run, "ticket")()

    message = message_from_string(run.server.sendmail.call_args.args[2], policy=policy.default)
    device_id = "unknown" if device_failure else "dev123"
    username = "Operator" if user else "unknown"
    assert str(message["Subject"]) == f"[KneeSpa {device_id}] Support ticket"
    assert message.get_content() == f"Device: {device_id}\nUser: {username} ()\n\nIssue:\n{ISSUE}"
    run.window.logger.error.assert_not_called()


def ticket_form():
    return {
        "name": "Dr. Zoë", "email": "clinician@example.test",
        "subject": "Controller disconnects", "description": ISSUE,
        "issue": "Connection issue",
    }


def test_form_sends_reply_address_versions_and_stable_retry_reference(email_run):
    run = email_run
    run.window.shell = SimpleNamespace(support=Mock())
    run.window.support_email_result = Mock()
    run.window.arduino = SimpleNamespace(connected=True, firmware_version="service-test")
    run.window.cloud_client = SimpleNamespace(device_id="cloud-device-01")
    run.window.protocol_state = "idle"
    KneeSpa._on_submit_ticket(run.window, ticket_form())
    deliver = run.thread_factory.call_args.kwargs["target"]
    KneeSpa._on_submit_ticket(run.window, ticket_form())
    assert run.thread_factory.call_count == 1
    run.server.sendmail.side_effect = OSError("Offline")
    deliver()
    result = run.window.support_email_result.emit.call_args.args
    KneeSpa._on_support_email_result(run.window, *result)
    first = run.window._pending_support_ticket[1]
    KneeSpa._on_submit_ticket(run.window, ticket_form())
    assert run.window._pending_support_ticket[1] is first
    run.server.sendmail.side_effect = None
    run.thread_factory.call_args.kwargs["target"]()
    message = message_from_string(run.server.sendmail.call_args.args[2], policy=policy.default)
    assert str(message["Reply-To"]) == "clinician@example.test"
    assert first["reference"] in str(message["Subject"])
    for expected in ("cloud-device-01", "service-test", ISSUE, "Software version:", "idle"):
        assert expected in message.get_content()
    result = run.window.support_email_result.emit.call_args.args
    assert result[0] is True
    assert first["reference"] in result[1]
    KneeSpa._on_support_email_result(run.window, *result)
    assert run.window._pending_support_ticket is None


@pytest.mark.parametrize("key,value", [
    ("name", ""), ("email", "missing-at"), ("email", "ok@example.test\nBcc: victim@example.test"),
    ("subject", ""), ("subject", "Subject\r\nBcc: victim@example.test"),
    ("description", ""), ("description", "x" * 4001),
])
def test_invalid_form_never_queues_email(email_run, key, value):
    run = email_run
    run.window.shell = SimpleNamespace(support=Mock())
    form = ticket_form()
    form[key] = value
    KneeSpa._on_submit_ticket(run.window, form)
    run.thread_factory.assert_not_called()
    assert run.window.shell.support.set_delivery_state.call_args.args[0] == "invalid"
