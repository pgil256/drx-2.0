"""Preparation/finalization boundaries using the real worker and serial parser."""
import pytest
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
    assert prepared and prepared[0][-2:] == ["L1|BASELINE", "V50,50,100"]
    assert not any(c.startswith("P") for c in prepared[0])
    assert finished[0][0] and worker.completed.is_set() and link.baseline_valid
    assert link.commands[-4:] == ["P0|0", "X", "I120", "L1|BASELINE"]
    pressure = [c for c in link.commands if c.startswith("P")]
    assert pressure == ["P20|50", "P30|50", "P40|50", "P50|50", "P0|0"]
    if pulse:
        assert "J250" in link.commands and "JS" in link.commands


@pytest.mark.parametrize("stage", ["center", "baseline", "pressure", "final_home", "final_baseline"])
def test_failed_stage_never_reports_success_or_replays(protocol_clock, stage):
    link = NB2Controller()
    worker = make_protocol(ser=link, duration=1)
    link.factor = worker.config.calibration
    link.a_zero = int(worker.config.AMarks.get("0.0", worker.config.AMarks.get("0")))
    failures, finished, prepared = [], [], []
    worker.signals.prepared.connect(lambda *a: prepared.append(a))
    worker.signals.operation_failed.connect(failures.append)
    worker.signals.finished.connect(finished.append)
    baseline_count = 0
    def hook(command, replies):
        nonlocal baseline_count
        if command == "L1|BASELINE":
            baseline_count += 1
        fail = ((stage == "center" and command.startswith("K"))
                or (stage == "baseline" and baseline_count == 1 and command.startswith("L1"))
                or (stage == "pressure" and command.startswith("P"))
                or (stage == "final_home" and command == "I120")
                or (stage == "final_baseline" and baseline_count == 2 and command.startswith("L1")))
        return [] if fail else replies
    link.hook = hook
    worker.run()
    assert finished == [False] and failures and worker.completed.is_set()
    assert not link.baseline_valid
    assert link.commands[-1] == "X"
    assert "Y" not in link.commands
    if stage in ("center", "baseline"):
        assert not prepared and not any(c.startswith("P") for c in link.commands)


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
    state.received_at -= 3
    assert state.caption(True) == "Pressure stale"
    state.fault = "PRESSURE_LIMIT"
    assert "fault" in state.caption(True)
