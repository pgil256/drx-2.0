"""The global exception hook must log and keep the app alive.

PyQt5 >= 5.5 calls qFatal() when a Python exception escapes a slot, which
would kill the kiosk UI (and its on-screen STOP) mid-treatment. kneespa.main()
installs a hook that records the traceback instead; these tests pin that.
"""
import sys

import pytest

import kneespa


@pytest.mark.unit
def test_excepthook_logs_and_does_not_raise(monkeypatch, capsys):
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    kneespa._install_excepthook()
    assert sys.excepthook is not sys.__excepthook__

    try:
        raise KeyError("0.0")
    except KeyError:
        exc_type, exc, tb = sys.exc_info()

    sys.excepthook(exc_type, exc, tb)  # must not raise
    err = capsys.readouterr().err
    assert "UNHANDLED EXCEPTION" in err
    assert "KeyError" in err and "0.0" in err


@pytest.mark.unit
def test_excepthook_defers_keyboard_interrupt(monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    seen = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: seen.append(a[0]))
    kneespa._install_excepthook()

    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert seen == [KeyboardInterrupt]
