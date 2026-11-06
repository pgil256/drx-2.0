"""An operator STOP or on-screen emergency stop always releases traction.

Hazard: phase 2 of both stop chains sent P0 only through the treatment
worker. After pressure was applied from the Setup screen there is no worker,
and a finished worker that an earlier physical stop had marked declined to
release, so the load stayed on until the recovery reset re-homed the axial
actuator, up to RELEASE_WAIT_S later. Fault stops keep "no automatic
movement", and a physical stop leaves the firmware's own release in control.
"""
from unittest.mock import MagicMock

import pytest

import controllers.protocol_controller as pc_mod
import controllers.stop_controller as sc_mod
from fixtures.controllers import make_window
from fixtures.protocols import make_protocol

pytestmark = pytest.mark.unit

PHASES = ("_stop_phase2", "_emergency_stop_phase2")


@pytest.fixture(autouse=True)
def no_timers(monkeypatch):
    # The phases schedule their successors; these tests drive one phase.
    monkeypatch.setattr(pc_mod, "QTimer", MagicMock())
    monkeypatch.setattr(sc_mod, "QTimer", MagicMock())


def phase_of(window, name):
    """A stop phase, wherever it lives (StopController, or not yet moved)."""
    stops = window.protocol.stops
    return getattr(stops if hasattr(stops, name) else window.protocol, name)


def sent(window):
    return [call[0][0] for call in window.arduino.send.call_args_list]


@pytest.mark.parametrize("phase", PHASES)
def test_stop_without_a_worker_releases_pressure(phase):
    window = make_window()
    window.worker = None

    phase_of(window, phase)()

    assert sent(window) == ["P0"]


@pytest.mark.parametrize("phase", PHASES)
def test_a_worker_that_released_is_not_repeated(phase):
    window = make_window()
    window.worker.stop.return_value = True

    phase_of(window, phase)()

    window.worker.stop.assert_called_once_with()
    assert sent(window) == []


@pytest.mark.parametrize("phase", PHASES)
def test_a_worker_that_declined_still_gets_a_release(phase):
    # A finished worker keeps _firmware_stopped from an earlier physical stop.
    window = make_window()
    window.worker.stop.return_value = False

    phase_of(window, phase)()

    assert sent(window) == ["P0"]


@pytest.mark.parametrize("phase", PHASES)
def test_active_physical_stop_leaves_the_firmware_release_alone(phase):
    window = make_window()
    window.worker = None
    window._physical_stop_active = True

    phase_of(window, phase)()

    assert sent(window) == []


def test_an_unsendable_release_is_logged():
    window = make_window()
    window.worker = None
    window.arduino.send.return_value = False

    window.protocol.stops._stop_phase2()

    window.logger.error.assert_called_once()


def test_fault_stop_still_sends_no_release():
    window = make_window()
    window.worker = None

    window.protocol.stop_without_recovery("PRESSURE_LIMIT", fault=True)
    window.protocol.stops._stop_phase2()
    window.protocol._emergency_stop_phase2()

    assert "P0" not in sent(window)


def test_worker_stop_reports_whether_it_queued_the_release():
    worker = make_protocol()
    assert worker.stop() is True
    assert [c[0][0] for c in worker.arduino.send.call_args_list] == ["X", "P0", "HF0"]

    worker = make_protocol()
    worker.cancel(firmware_stopped=True)
    worker.arduino.send.reset_mock()
    assert worker.stop() is False
    worker.arduino.send.assert_not_called()

    worker = make_protocol()
    worker.arduino.send.side_effect = lambda command: command != "P0"
    assert worker.stop() is False
