"""Explicit window facades for controller tests; no hardware window is constructed."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt5.QtCore import QThreadPool, QTimer

from controllers.protocol_controller import ProtocolController
from helpers.treatment_session import TreatmentSession
from ui.modals import PatientModal
from fixtures.protocols import make_arduino
from ui.screens.setup import SetupScreen
from ui.screens.support import SupportScreen
from ui.screens.treatment import TreatmentScreen
from ui.widgets.treatment_status_panel import TreatmentStatusPanel


def make_shell() -> SimpleNamespace:
    """Provide bounded view APIs and concrete settings for controller decisions."""
    treatment = MagicMock(spec_set=TreatmentScreen)
    treatment.settings_values.return_value = {
        "max_pressure": 50, "max_left": 10, "max_right": 10,
        "duration": 12, "pulse_rate": 2.4,
    }
    treatment.selected_protocol.return_value = 2
    setup = MagicMock(spec_set=SetupScreen)
    setup.row_value.return_value = 0.0
    return SimpleNamespace(
        treatment=treatment, setup=setup, support=MagicMock(spec_set=SupportScreen),
        patient_modal=MagicMock(spec_set=PatientModal),
        video_modal=SimpleNamespace(cleanup=MagicMock()),
        setEnabled=MagicMock(), login_succeeded=MagicMock(), login_failed=MagicMock(), logout=MagicMock(),
        set_access_role=MagicMock(),
    )


def make_worker_double() -> MagicMock:
    """Expose lifecycle operations and connectable signals without starting work."""
    worker = MagicMock(spec_set=[
        "pause", "resume", "stop", "cancel", "request_live_angle", "request_live_pressure",
        "request_live_pulse_rate", "duration", "is_running", "is_paused", "signals",
    ])
    worker.duration = 60
    worker.is_running = False
    worker.is_paused = False
    worker.signals = SimpleNamespace(**{
        name: MagicMock(spec_set=["connect", "disconnect", "emit"])
        for name in ("finished", "progress", "reset_needed", "motor_speed_failed",
                     "prepared", "baseline_changed", "operation_failed")
    })
    return worker


def make_window(state: str = "idle") -> SimpleNamespace:
    """Build the protocol facade with actual values for each lifecycle gate.

    Unknown attributes raise AttributeError. Retired dialogs/adapters are absent;
    tests that model historical consumers must install them explicitly.
    """
    config = SimpleNamespace(
        calibrated=True, marks_valid=True, scale_calibrated=True, a_factor=1900,
        AMarks={"0.0": 160}, BMarks={"0.0": 1900}, CMarks={"0.0": 1450},
        calibration=-28369.0,
        save_protocol_defaults=MagicMock(), ensure_device_id=MagicMock(return_value="test-device"),
    )
    worker = make_worker_double()
    worker.is_running = state in ("starting", "running", "stopping")
    window = SimpleNamespace(
        protocol_state=state, protocol_running=worker.is_running,
        protocol_stop_requested=False, protocol_value="2", protocol_duration=720,
        protocol_start_time=None, mid_protocol_warning_shown=False,
        reset_in_progress=False, initial_setup_complete=True,
        _closing=False, _physical_stop_active=False, _calibration_active=False,
        _no_automatic_recovery=False, on_baseline_changed=MagicMock(),
        connection=SimpleNamespace(cancel_reset=MagicMock()),
        patients=SimpleNamespace(clear_session=MagicMock()),
        machine_sign_in=SimpleNamespace(
            clear=MagicMock(), timer=SimpleNamespace(stop=MagicMock()),
            treatment_finished=MagicMock(),
        ),
        _block_active_treatment_exit=MagicMock(return_value=False),
        _patient_lookup_id=0, _paused_at=None, _prev_settings={},
        cloud_patient={"patient_id": "test-patient"},
        _treatment_patient={"patient_id": "test-patient"},
        current_user={"username": "Dr", "status": "user"},
        current_use_pulse_setting=True, current_pulse_rate=2.4,
        last_measured_pressure=None, worker=worker, config=config,
        shell=make_shell(), arduino=make_arduino(), arduino_thread=None,
        protocol_timer=MagicMock(spec_set=QTimer), threadpool=MagicMock(spec_set=QThreadPool),
        treatment_panel=MagicMock(spec_set=TreatmentStatusPanel),
        loading_spinner=MagicMock(spec_set=["show", "hide"]),
        logger=MagicMock(spec_set=logging.Logger),
        cloud_client=SimpleNamespace(
            enabled=True, lookup_pin=MagicMock(), post_treatment_async=MagicMock(),
            close=MagicMock(),
        ),
        _duration_minutes=MagicMock(return_value=12),
        ensure_arduino_connection=MagicMock(return_value=True),
        set_to_c_distance=MagicMock(return_value=True),
        _show_timed_error=MagicMock(), _show_safety_alert=MagicMock(),
        _warn_uncalibrated=MagicMock(), stop_actuators=MagicMock(),
        reset_arduino=MagicMock(), reset_extra_button_clicked=MagicMock(),
        _release_leg_gpio=MagicMock(), _start_leg_reset_gpio=MagicMock(),
        _finish_leg_reset=MagicMock(), disable_actuator_controls=MagicMock(),
        enable_actuator_controls=MagicMock(), reset_setup_readings=MagicMock(),
    )
    window.threadpool.activeThreadCount.return_value = 0
    window.protocol = ProtocolController(window)
    if state in ("running", "stopping"):
        window.protocol._session = TreatmentSession("test-patient", 2, 720)
    window.set_protocol_state = window.protocol.set_state
    return window


def make_stub() -> SimpleNamespace:
    """Extend the explicit protocol facade for unbound window wiring methods."""
    window = make_window()
    window.actuator_a = "12"
    window.actuator_b = "13"
    window.actuator_c = "14"
    window.auth = SimpleNamespace(handle_login=MagicMock())
    window.csv = SimpleNamespace(add_user=MagicMock())
    window.safety = SimpleNamespace(on_status=MagicMock())
    window.protocol = MagicMock(spec_set=ProtocolController)
    window._is_admin = MagicMock(return_value=False)
    window._block_active_treatment_exit = MagicMock(return_value=False)
    window._confirm_mid_protocol_change = MagicMock(return_value=True)
    window.set_to_distance = MagicMock(return_value=True)
    for name in (
        "close", "_seed_modern_run_inputs", "_reflect_setup", "_setup_reset", "_leg_jog",
        "move_actuator", "_apply_setup_pressure", "reset_flexion_button_clicked",
        "stop_leg_movement", "stop_position_flexion_button", "emergency_stop_clicked",
        "email_admin",
        "_show_patient_modal", "_on_patient_edit", "_on_mark_default",
    ):
        setattr(window, name, MagicMock())
    return window


class ConnectionWindow:
    """Connection/reset facade with observable errors and control callbacks."""

    def __init__(self) -> None:
        self.arduino = make_arduino()
        self.config = SimpleNamespace()
        self.config.AMarks = {"0.0": 160}
        self.config.BMarks = {"0.0": 1900}
        self.config.calibration = -28369.0
        self.config.scale_calibrated = True
        self.reset_in_progress = False
        self.initial_setup_complete = False
        self.loading_spinner = MagicMock(spec_set=["show", "hide"])
        self.shell = make_shell()
        self.protocol_state = "idle"
        self.protocol_running = False
        self.treatment_panel = MagicMock(spec_set=TreatmentStatusPanel)
        self.protocol = ProtocolController(self)
        self.set_protocol_state = self.protocol.set_state
        self.threadpool = MagicMock(spec_set=QThreadPool)
        self.logger = MagicMock(spec_set=logging.Logger)
        self.on_baseline_changed = MagicMock()
        self.errors = []
        self.reset_readings = 0
        self.leg_resets = 0

    def _show_timed_error(self, message: str) -> None:
        self.errors.append(message)

    def disable_actuator_controls(self) -> None:
        pass

    def reset_setup_readings(self) -> None:
        self.reset_readings += 1

    def reset_extra_button_clicked(self) -> None:
        self.leg_resets += 1

    def _release_leg_gpio(self) -> None:
        pass

    def enable_actuator_controls(self) -> None:
        pass
