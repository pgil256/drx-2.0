"""Offline contracts for support-ticket email delivery."""

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
SENDING = ("sending", "Sending request…")
FAILURE_PREFIX = "Failed to send ticket"


def ticket_form():
    return {
        "name": "Dr. Zoë", "email": "clinician@example.test",
        "subject": "Controller disconnects", "description": ISSUE,
        "issue": "Connection issue",
    }


@pytest.fixture
def email_run(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Control SMTP and thread execution without constructing the hardware UI."""
    settings = {
        "SENDER_EMAIL": "kiosk@example.test",
        "SENDER_PASSWORD": "test-password",
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
        current_user={"username": "Dr. Zoë", "status": "admin"},
        config=SimpleNamespace(ensure_device_id=Mock(return_value="dev123")),
        logger=Mock(spec=logging.Logger),
        shell=SimpleNamespace(support=Mock()),
        support_email_result=Mock(),
        arduino=SimpleNamespace(connected=True, firmware_version="service-test"),
        protocol_state="idle",
    )
    window._send_support_email = partial(KneeSpa._send_support_email, window)
    return SimpleNamespace(
        window=window, settings=settings, smtp=smtp, server=server,
        thread=thread, thread_factory=thread_factory,
    )


def queue_ticket(run: SimpleNamespace) -> Callable[[], None]:
    """Queue one daemon worker and check feedback before allowing SMTP to run."""
    KneeSpa._on_submit_ticket(run.window, ticket_form())
    run.window.shell.support.set_delivery_state.assert_called_once_with(*SENDING)
    run.thread_factory.assert_called_once()
    assert run.thread_factory.call_args.kwargs["daemon"] is True
    run.thread.start.assert_called_once_with()
    run.smtp.assert_not_called()
    return run.thread_factory.call_args.kwargs["target"]


def sent_message(run: SimpleNamespace):
    return message_from_string(run.server.sendmail.call_args.args[2], policy=policy.default)


def test_message_and_transport_contract(
    email_run: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    run = email_run
    deliver = queue_ticket(run)
    ticket = run.window._pending_support_ticket[1]
    # Queued work retains the message, destination and credentials captured when
    # the form was submitted, even if another operator logs in or configuration changes.
    for key in run.settings:
        run.settings[key] = "changed"
    run.window.current_user = None
    deliver()

    run.smtp.assert_called_once_with("smtp.example.test", 465, timeout=15)
    run.smtp.return_value.__enter__.assert_called_once_with()
    run.smtp.return_value.__exit__.assert_called_once_with(None, None, None)
    run.server.login.assert_called_once_with("kiosk@example.test", "test-password")
    run.server.sendmail.assert_called_once()
    sender, recipient, serialized = run.server.sendmail.call_args.args
    assert sender == "kiosk@example.test"
    assert recipient == "tickets@example.test"
    message = message_from_string(serialized, policy=policy.default)
    assert str(message["From"]) == sender
    assert str(message["To"]) == recipient
    assert str(message["Reply-To"]) == "clinician@example.test"
    assert message.get_content_type() == "text/plain"
    assert str(message["Subject"]) == ticket["subject"]
    assert message.get_content() == ticket["body"]
    success = f"Ticket sent. Request reference: {ticket['reference']}."
    assert capsys.readouterr().out == success + "\n"
    run.window.support_email_result.emit.assert_called_once_with(True, success)
    run.window.config.ensure_device_id.assert_called_once_with()
    assert run.server.method_calls == [
        call.login("kiosk@example.test", "test-password"),
        call.sendmail(sender, recipient, serialized),
    ]
    run.window.logger.error.assert_not_called()


@pytest.mark.parametrize("success", [True, False])
def test_delivery_feedback_prevents_duplicate_requests_and_allows_retry(email_run, success):
    """Queued delivery is distinct from completion, with retry restored by the GUI slot."""
    run = email_run
    deliver = queue_ticket(run)
    KneeSpa._on_submit_ticket(run.window, ticket_form())
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
    run.thread.start.side_effect = RuntimeError("Thread unavailable")
    KneeSpa._on_submit_ticket(run.window, ticket_form())
    assert not run.window._support_mail_busy
    assert run.window.shell.support.set_delivery_state.call_args.args[0] == "failed"
    run.smtp.assert_not_called()


@pytest.mark.parametrize("missing", ["SENDER_EMAIL", "SENDER_PASSWORD", "TICKET_EMAIL"])
def test_missing_credentials_log_without_connecting(
    email_run: SimpleNamespace, missing: str, capsys: pytest.CaptureFixture[str],
) -> None:
    run = email_run
    run.settings[missing] = ""
    queue_ticket(run)()

    run.smtp.assert_not_called()
    diagnostic = f"{FAILURE_PREFIX}: SMTP credentials are not configured"
    run.window.logger.error.assert_called_once_with(diagnostic)
    assert diagnostic in capsys.readouterr().out
    assert run.window.support_email_result.emit.call_args.args[0] is False


@pytest.mark.parametrize("stage", ["connect", "enter", "login", "sendmail", "exit"])
def test_smtp_failures_are_logged_by_the_worker(
    email_run: SimpleNamespace, stage: str, capsys: pytest.CaptureFixture[str],
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
    queue_ticket(run)()

    diagnostic = f"{FAILURE_PREFIX}: {stage} failed"
    run.window.logger.error.assert_called_once_with(diagnostic)
    output = capsys.readouterr().out
    assert diagnostic in output
    assert "Ticket sent" not in output
    if stage in ("connect", "enter", "login"):
        run.server.sendmail.assert_not_called()
    assert run.window.support_email_result.emit.call_args.args[0] is False


@pytest.mark.parametrize("user", [None, {}, {"username": "Operator"}])
@pytest.mark.parametrize("device_failure", [False, True])
def test_ticket_identity_fallbacks(
    email_run: SimpleNamespace, user: Optional[Dict[str, str]], device_failure: bool
) -> None:
    run = email_run
    run.window.current_user = user
    if device_failure:
        run.window.config.ensure_device_id.side_effect = OSError("config unavailable")
    queue_ticket(run)()

    body = sent_message(run).get_content()
    assert f"Device ID: {'Unavailable' if device_failure else 'dev123'}\n" in body
    assert f"Operator: {'Operator' if user else 'Not signed in'}\n" in body
    assert run.window.logger.exception.call_count == int(device_failure)
    run.window.logger.error.assert_not_called()


def test_form_sends_reply_address_versions_and_stable_retry_reference(email_run):
    run = email_run
    run.window.cloud_client = SimpleNamespace(device_id="cloud-device-01")
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
    message = sent_message(run)
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
    form = ticket_form()
    form[key] = value
    KneeSpa._on_submit_ticket(run.window, form)
    run.thread_factory.assert_not_called()
    assert run.window.shell.support.set_delivery_state.call_args.args[0] == "invalid"
