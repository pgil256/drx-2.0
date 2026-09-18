"""Session identity, pause timing and one terminal record despite cleanup races."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from controllers.protocol_controller import ProtocolController
from controllers.safety_monitor import SafetyMonitor
from fixtures.controllers import make_window, make_worker_double
from helpers import treatment_session
from helpers.treatment_session import TreatmentSession

pytestmark = pytest.mark.unit
END = {"max_pressure_lb": 50, "max_left_deg": 0, "max_right_deg": 20, "pulse_rate_hz": 0}


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 100.0}
    origin = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

    class WallClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return origin + timedelta(seconds=state["now"] - 100)

    monkeypatch.setattr(treatment_session.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(treatment_session, "datetime", WallClock)
    return state


def new_session(clock):
    # Explicit clock because dataclass default factories bind at class creation.
    return TreatmentSession(str(uuid4()), 4, 720, started_clock=clock["now"])


def test_stop_while_paused_keeps_wall_time_and_excludes_pauses(clock):
    session = new_session(clock)
    clock["now"] += 10
    session.pause()
    clock["now"] += 40
    session.resume()
    clock["now"] += 20
    session.pause()
    clock["now"] += 30
    session.latch("stopped")
    record = session.finish(END)
    assert record["actual_duration_s"] == 30
    assert record["planned_duration_s"] == 720
    wall_elapsed = (datetime.fromisoformat(record["ended_at"])
                    - datetime.fromisoformat(record["started_at"]))
    assert wall_elapsed == timedelta(seconds=100)
    assert record["settings_at_end"]["pulse_rate_hz"] == 0
    assert record["settings_at_end"]["max_left_deg"] == 0


def test_latched_record_is_single_immutable_snapshot(clock):
    session = new_session(clock)
    clock["now"] += 7
    session.latch("fault")
    record = session.finish(END)
    stored = deepcopy(record)
    UUID(record["client_record_id"])
    record["settings_at_end"]["max_pressure_lb"] = 80
    session.latch("completed")
    assert session.finish(END) is None
    assert session.record == stored
    assert session.outcome == "fault"
    assert session.actual_duration_s == 7


def test_unlinked_session_never_creates_cloud_record(clock):
    session = TreatmentSession(None, 1, 300)
    session.latch("completed")
    assert session.finish(END) is None
    assert session.finalized


def dispatch(monkeypatch, patient=True):
    window = make_window()
    window.cloud_patient = {"patient_id": str(uuid4())} if patient else None
    controller = window.protocol
    worker = make_worker_double()
    monkeypatch.setattr(
        "controllers.protocol_controller.protocols.Protocols", lambda *a, **kw: worker
    )
    assert controller.start_protocol()
    return window, controller, worker


@pytest.mark.parametrize("success,outcome", [(True, "completed"), (False, "fault")])
def test_duplicate_worker_completion_captures_original_plan(monkeypatch, qtbot, success, outcome):
    window, controller, worker = dispatch(monkeypatch)
    original_patient = window.cloud_patient["patient_id"]
    session = controller._session
    window.protocol_duration = 0  # Timer/reset cleanup must not change the captured plan.
    window.protocol_start_time = None
    window.protocol_value = "3"
    window.cloud_patient = {"patient_id": str(uuid4())}
    finish = worker.signals.finished.connect.call_args.args[0]
    finish(success)
    finish(False)
    record = window.cloud_client.post_treatment_async.call_args.args[0]
    assert window.cloud_client.post_treatment_async.call_count == 1
    assert record["patient_id"] == original_patient
    assert record["protocol_number"] == 2
    assert record["planned_duration_s"] == 720
    assert record["outcome"] == outcome
    assert record["client_record_id"] == session.client_record_id
    assert record["actual_duration_s"] < 720


def test_stop_latch_survives_reset_and_late_success(monkeypatch, qtbot):
    window, controller, worker = dispatch(monkeypatch)
    monkeypatch.setattr("controllers.protocol_controller.QTimer.singleShot", lambda *a: None)
    controller.stop_protocol()
    window.protocol_stop_requested = False  # Reset completed before the queued finish arrived.
    window.protocol_state = "idle"
    worker.signals.finished.connect.call_args.args[0](True)
    assert window.cloud_client.post_treatment_async.call_count == 1
    assert window.cloud_client.post_treatment_async.call_args.args[0]["outcome"] == "stopped"


def test_physical_stop_records_fault_once_without_serial_stop(monkeypatch, qtbot):
    window, controller, worker = dispatch(monkeypatch)
    SafetyMonitor(window).on_physical_stop()
    worker.signals.finished.connect.call_args.args[0](False)
    assert window.cloud_client.post_treatment_async.call_count == 1
    assert window.cloud_client.post_treatment_async.call_args.args[0]["outcome"] == "fault"
    window.stop_actuators.assert_not_called()
    worker.cancel.assert_called_once_with(firmware_stopped=True)


def test_finalized_fault_does_not_automatically_release_or_home(monkeypatch, qtbot):
    window, controller, worker = dispatch(monkeypatch)
    # Command-fault handling sends X, while worker.stop owns the subsequent
    # P0 pressure release. Recording first must not swallow that cleanup.
    controller.set_state("fault")
    assert controller._session.finalized
    finish = worker.signals.finished.connect.call_args.args[0]
    finish(False)
    finish(False)
    worker.stop.assert_not_called()
    window.cloud_client.post_treatment_async.assert_called_once()
    assert window.protocol_state == "fault"


def test_failed_worker_requires_explicit_recovery(monkeypatch, qtbot):
    window, controller, worker = dispatch(monkeypatch)
    worker.signals.finished.connect.call_args.args[0](False)
    worker.signals.reset_needed.connect.assert_not_called()
    window.reset_arduino.assert_not_called()
    assert window.protocol_state == "fault"
    assert window.cloud_client.post_treatment_async.call_count == 1


def test_old_worker_cannot_finalize_or_reset_new_run(monkeypatch, qtbot):
    window, controller, first = dispatch(monkeypatch)
    first.signals.finished.connect.call_args.args[0](True)
    second = make_worker_double()
    monkeypatch.setattr(
        "controllers.protocol_controller.protocols.Protocols", lambda *a, **kw: second
    )
    assert controller.start_protocol()
    session = controller._session
    first.signals.finished.connect.call_args.args[0](False)
    first.signals.operation_failed.connect.call_args.args[0]("late fault")
    assert not session.finalized
    window.reset_arduino.assert_not_called()
    second.signals.finished.connect.call_args.args[0](True)
    assert window.cloud_client.post_treatment_async.call_count == 2


def test_failed_dispatch_has_no_session_or_upload(monkeypatch, qtbot):
    window = make_window()
    monkeypatch.setattr("controllers.protocol_controller.protocols.Protocols",
                        lambda *a, **kw: make_worker_double())
    window.threadpool.start.side_effect = RuntimeError("dispatch failed")
    assert window.protocol.start_protocol() is False
    assert window.protocol._session is None
    assert not window.protocol_running
    window.protocol.protocol_completed(False)
    window.cloud_client.post_treatment_async.assert_not_called()


def test_pending_patient_lookup_blocks_dispatch(qtbot):
    window = make_window()
    window._patient_lookup_pending = True
    assert window.protocol.start_protocol() is False
    assert window.protocol._session is None
    window.threadpool.start.assert_not_called()


def test_cleanup_finish_signal_cannot_reenter_finalizer(monkeypatch, qtbot):
    window, controller, worker = dispatch(monkeypatch)
    finish = worker.signals.finished.connect.call_args.args[0]
    worker.stop.side_effect = lambda: finish(False)
    finish(True)
    worker.stop.assert_not_called()
    window.cloud_client.post_treatment_async.assert_called_once()
    assert controller._session.record["outcome"] == "completed"


def test_snapshot_precedes_cleanup_and_upload_follows_release(monkeypatch, qtbot):
    window, controller, worker = dispatch(monkeypatch)
    original = deepcopy(window.shell.treatment.settings_values.return_value)

    def cleanup():
        window.cloud_client.post_treatment_async.assert_not_called()
        window.shell.treatment.settings_values.return_value["max_pressure"] = 10
        window.protocol_duration = 0

    worker.stop.side_effect = cleanup
    worker.signals.finished.connect.call_args.args[0](True)
    record = window.cloud_client.post_treatment_async.call_args.args[0]
    assert record["settings_at_end"]["max_pressure_lb"] == original["max_pressure"]
    assert record["planned_duration_s"] == 720


def test_manual_treatment_keeps_local_start_checks(monkeypatch, qtbot):
    window, controller, worker = dispatch(monkeypatch, patient=False)
    worker.signals.finished.connect.call_args.args[0](True)
    window.cloud_client.post_treatment_async.assert_not_called()
    assert controller._session.finalized
    window.current_user = None
    assert controller.start_protocol() is False
