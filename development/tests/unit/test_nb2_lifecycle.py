"""Preparation/finalization boundaries using the real worker and serial parser."""
import pytest
from controllers.safety_monitor import SafetyMonitor
from fixtures.controllers import make_window
from fixtures.nb2 import NB2Controller
from fixtures.protocols import make_protocol
from helpers.measurement_state import MeasurementState

pytestmark = pytest.mark.unit

@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("protocol", ["1", "2", "3", "4"])
@pytest.mark.parametrize("pulse", [False, True])
def test_full_protocol_orders_preparation_and_final_baseline(protocol_clock, v2, protocol, pulse):
    link = NB2Controller(v2)
    worker = make_protocol(ser=link, protocol=protocol, use_pulse=pulse,
                           pulse_rate=4, duration=1, motor_speeds={})
    link.factor = worker.config.calibration
    link.a_zero = int(worker.config.AMarks.get("0.0", worker.config.AMarks.get("0")))
    prepared, finished = [], []
    worker.signals.prepared.connect(lambda *args: prepared.append(list(link.commands)))
    worker.signals.finished.connect(lambda value: finished.append((value, list(link.commands))))
    worker.run()
    assert prepared and prepared[0][-2:] == ["L1|BASELINE", "V50,50,50"]
    # The axial actuator is confirmed home before the centre and the tare: a
    # load left by Setup pressure must never be zeroed and then added to.
    assert prepared[0][:3] == ["X", "HF1", "I120"]
    centre = next(i for i, c in enumerate(prepared[0]) if c.startswith("K"))
    assert 2 < centre < prepared[0].index("L1|BASELINE")
    assert not any(c.startswith("P") for c in prepared[0])
    assert finished[0][0] and worker.completed.is_set() and link.baseline_valid
    assert link.commands[-3] == "X"
    assert link.commands[-2].startswith("R|")
    assert link.commands[-1] == "L1|HOME|" + link.commands[-2][2:]
    pressure = [c for c in link.commands if c.startswith("P")]
    assert pressure == ["P20|50", "P30|50", "P40|50", "P50|50"]
    assert worker.treatment_completed and worker.outcome == "completed"
    if pulse:
        assert "J250" in link.commands and "JS" in link.commands


@pytest.mark.parametrize("stage", ["start_home", "center", "baseline", "pressure", "final_home",
                                   "final_baseline"])
def test_failed_stage_never_reports_success_or_replays(protocol_clock, stage):
    link = NB2Controller()
    worker = make_protocol(ser=link, duration=1)
    link.factor = worker.config.calibration
    link.a_zero = int(worker.config.AMarks.get("0.0", worker.config.AMarks.get("0")))
    failures, finished, prepared = [], [], []
    worker.signals.prepared.connect(lambda *a: prepared.append(a))
    worker.signals.operation_failed.connect(failures.append)
    worker.signals.finished.connect(finished.append)
    baseline_count = home_count = 0
    def hook(command, replies):
        nonlocal baseline_count, home_count
        if command == "L1|BASELINE":
            baseline_count += 1
        if command == "I120":
            home_count += 1
        fail = ((stage == "start_home" and home_count == 1 and command == "I120")
                or (stage == "center" and command.startswith("K"))
                or (stage == "baseline" and baseline_count == 1 and command.startswith("L1"))
                or (stage == "pressure" and command.startswith("P"))
                or (stage == "final_home" and command.startswith("R|"))
                or (stage == "final_baseline" and command.startswith("L1|HOME|")))
        return [] if fail else replies
    link.hook = hook
    worker.run()
    assert finished == [False] and worker.completed.is_set()
    if stage.startswith("final_"):
        assert worker.treatment_completed and worker.outcome == "completed_cleanup_failed"
        assert worker.cleanup_warning
    else:
        assert failures
    assert not link.baseline_valid
    assert link.commands[-1] == "X"
    assert "Y" not in link.commands
    if stage in ("start_home", "center", "baseline"):
        assert not prepared and not any(c.startswith("P") for c in link.commands)
    if stage == "start_home":
        # Nothing else moves and nothing is zeroed without a confirmed home.
        assert not any(c.startswith(("K", "L1")) for c in link.commands)


def test_start_home_outside_the_band_is_not_a_confirmation(protocol_clock):
    link = NB2Controller()
    worker = make_protocol(ser=link, duration=1)
    link.factor = worker.config.calibration
    link.a_zero = int(worker.config.AMarks.get("0.0", worker.config.AMarks.get("0")))
    finished = []
    worker.signals.finished.connect(finished.append)
    stuck = link.a_zero + 2000
    link.hook = lambda command, replies: (
        ["MOTION_DONE|I|{}|{}".format(link.a_zero, stuck), "DONE"] if command == "I120" else replies)
    worker.run()
    assert finished == [False]
    assert not any(c.startswith(("K", "L1", "P")) for c in link.commands)


@pytest.mark.parametrize("stage", ["center", "baseline", "pressure", "final_home"])
def test_stop_button_during_an_operation_sends_nothing_more(protocol_clock, stage):
    """After the button the firmware releases the load itself; an X ends that.

    The window's own handler has not run here, as when the worker sees the
    failure first.
    """
    link = NB2Controller()
    worker = make_protocol(ser=link, duration=1)
    link.factor = worker.config.calibration
    link.a_zero = int(worker.config.AMarks.get("0.0", worker.config.AMarks.get("0")))
    failures, finished, pressed = [], [], []
    worker.signals.operation_failed.connect(failures.append)
    worker.signals.finished.connect(finished.append)
    def hook(command, replies):
        press = ((stage == "center" and command.startswith("K"))
                 or (stage == "baseline" and command.startswith("L1"))
                 or (stage == "pressure" and command.startswith("P"))
                 or (stage == "final_home" and command == "I120"))
        if press and not pressed:
            pressed.append(len(link.commands))
            return ["ERROR: Stop button pressed"]
        return replies
    link.hook = hook
    worker.run()
    assert pressed and link.commands[pressed[0]:] == []
    # The window's physical-stop handling reports it, not a worker failure.
    assert finished == [False] and not failures and worker.completed.is_set()
    worker.stop()  # the later completion cleanup must not send X or P0 either
    assert link.commands[pressed[0]:] == []


def test_late_baseline_reply_after_cancel_cannot_reenable(protocol_clock):
    link = NB2Controller()
    worker = make_protocol(ser=link)
    finished = []
    worker.signals.finished.connect(finished.append)
    def hook(command, replies):
        if command == "L1|BASELINE":
            worker.cancel()
        return replies
    link.hook = hook
    worker.run()
    assert finished == [False]
    assert not link.baseline_valid
    assert link.commands[-1] == "L1|BASELINE"


def set_up_device(link, state):
    """A window facade with the real safety monitor and stop controller, on a
    link that has already had its connection's boot banner."""
    link.handle_com("Ready to Go")
    link.baseline_valid = True
    window = make_window(state)
    window.arduino = link
    window.safety = SafetyMonitor(window)
    link.unexpected_reboot.connect(window.safety.on_controller_restart)
    return window


@pytest.mark.parametrize("v2", [False, True])
def test_reboot_during_hold_ends_the_run_as_a_fault_without_p0(protocol_clock, v2):
    link = NB2Controller(v2)
    window = set_up_device(link, "running")
    worker = make_protocol(ser=link, duration=1)
    window.worker = worker
    link.factor = worker.config.calibration
    link.a_zero = int(worker.config.AMarks.get("0.0", worker.config.AMarks.get("0")))
    finished, failures, rebooted_after = [], [], []
    worker.signals.finished.connect(finished.append)
    worker.signals.operation_failed.connect(failures.append)

    def reboot_once_while_holding():
        if "P50|50" in link.commands and not rebooted_after:
            rebooted_after.append(len(link.commands))
            link.handle_com("Ready to Go")

    protocol_clock.on_sleep = reboot_once_while_holding
    worker.run()

    # Outputs stopped and telemetry kept on; the worker sent nothing of its own.
    assert link.commands[rebooted_after[0]:] == ["X", "X", "HF1"]
    assert [c for c in link.commands if c.startswith("P")] == [
        "P20|50", "P30|50", "P40|50", "P50|50"]
    assert finished == [False] and not failures and worker.completed.is_set()
    assert window.protocol._session.outcome == "fault"
    assert window.protocol_state == "fault" and window._no_automatic_recovery
    assert not window.initial_setup_complete
    assert not link.baseline_valid
    window.on_baseline_changed.assert_called_with(False)
    assert window._measurement_fault == "CONTROLLER_RESTARTED"
    window._show_safety_alert.assert_called_once()
    alert = window._show_safety_alert.call_args[0][0]
    assert "restarted" in alert and "Reset" in alert
    window.treatment_panel.set_fault.assert_called_once()
    window.reset_arduino.assert_not_called()


def test_reboot_while_idle_locks_setup_and_asks_for_reset():
    link = NB2Controller()
    window = set_up_device(link, "idle")
    window.worker = None

    link.handle_com("Ready to Go")

    # Outputs stopped; nothing moves and no reset starts by itself.
    assert link.commands == ["X", "X", "HF1"]
    assert not window.initial_setup_complete  # Setup motion is locked
    assert window.protocol_state == "fault" and window._no_automatic_recovery
    assert not link.baseline_valid
    window.on_baseline_changed.assert_called_with(False)
    window.shell.setup.set_reset_enabled.assert_called_with(True)
    window.reset_arduino.assert_not_called()
    window._show_safety_alert.assert_called_once()
    alert = window._show_safety_alert.call_args[0][0]
    assert "restarted" in alert and "Reset" in alert


def test_measurement_status_never_fabricates_live_zero(monkeypatch):
    state = MeasurementState()
    assert state.caption(False) == "Waiting for controller"
    assert state.caption(True) == "Waiting for pressure"
    state.receive({"valid": False, "age_ms": -1})
    assert state.caption(True) == "Pressure unavailable"
    state.receive({"valid": True, "age_ms": 0})
    assert state.caption(True) == "Pressure zero required"
    state.baseline_valid = True
    assert state.caption(True) == "Pressure live"
    # Idle status arrives every 5 s, so a 3 s gap is normal until a protocol streams at 1 Hz.
    state.received_at -= 3
    assert state.caption(True) == "Pressure live"
    state.protocol_running = True
    assert state.caption(True) == "Pressure stale"
    state.protocol_running = False
    state.received_at -= 5
    assert state.caption(True) == "Pressure stale"
    state.fault = "PRESSURE_LIMIT"
    assert "fault" in state.caption(True)
