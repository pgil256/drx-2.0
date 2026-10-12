"""systemd watchdog pings: inert without systemd, GUI-thread timer with it."""

import os
import socket

import pytest

from helpers import watchdog

pytestmark = pytest.mark.unit


@pytest.fixture
def no_systemd(monkeypatch):
    for name in ("NOTIFY_SOCKET", "WATCHDOG_USEC", "WATCHDOG_PID"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(watchdog, "notify", lambda state: messages.append(state) or True)
    return messages


def test_everything_is_inert_when_systemd_did_not_start_the_app(no_systemd, qtbot):
    assert watchdog.notify("WATCHDOG=1") is False
    assert watchdog.watchdog_interval_ms() == 0
    assert watchdog.start_watchdog() is None
    watchdog.extend_watchdog_for_shutdown(None)


@pytest.mark.parametrize("usec, pid, expected", [
    ("60000000", None, 30000),
    ("60000000", "self", 30000),
    ("60000000", "1", 0),         # the watchdog belongs to another process
    ("1000000", None, 1000),      # never ping faster than once a second
    ("0", None, 0),
    ("soon", None, 0),
    ("60000000", "main", 0),
])
def test_ping_interval_is_half_the_unit_timeout(no_systemd, monkeypatch, usec, pid, expected):
    monkeypatch.setenv("WATCHDOG_USEC", usec)
    if pid:
        monkeypatch.setenv("WATCHDOG_PID", str(os.getpid()) if pid == "self" else pid)
    assert watchdog.watchdog_interval_ms() == expected


def test_timer_pings_at_once_and_then_from_the_event_loop(no_systemd, monkeypatch, sent, qtbot):
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    timer = watchdog.start_watchdog()
    try:
        assert timer.isActive() and timer.interval() == 30000
        # The unit timeout is restored first: an in-app restart inherits the
        # previous run's long shutdown deadline.
        assert sent == ["WATCHDOG_USEC=60000000", "WATCHDOG=1"]
        timer.timeout.emit()
        assert sent == ["WATCHDOG_USEC=60000000", "WATCHDOG=1", "WATCHDOG=1"]
    finally:
        timer.stop()


def test_shutdown_stops_the_timer_and_extends_the_deadline(no_systemd, monkeypatch, sent, qtbot):
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    timer = watchdog.start_watchdog()
    del sent[:]
    watchdog.extend_watchdog_for_shutdown(timer)
    assert not timer.isActive()
    assert sent == ["WATCHDOG_USEC=%d" % (watchdog.SHUTDOWN_GRACE_S * 1000000), "WATCHDOG=1"]


def test_notify_survives_a_missing_socket(no_systemd, monkeypatch, tmp_path):
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "absent"))
    assert watchdog.notify("WATCHDOG=1") is False


@pytest.mark.skipif(os.name != "posix", reason="sd_notify uses unix datagram sockets")
def test_notify_sends_one_datagram_to_the_notify_socket(no_systemd, monkeypatch, tmp_path):
    path = str(tmp_path / "notify")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind(path)
        server.settimeout(2)
        monkeypatch.setenv("NOTIFY_SOCKET", path)
        assert watchdog.notify("WATCHDOG=1") is True
        assert server.recv(64) == b"WATCHDOG=1"
