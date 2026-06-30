"""Unit tests for the Phase-3 controller signal handlers.

Like test_actuator_controls / test_conversions, these call ``KneeSpa`` methods
UNBOUND against a MagicMock ``self`` so no Qt window / Arduino is constructed.
They verify the view↔backend wiring: login routing, Setup jog/go/stop mapping
(incl. the fixed lateral-stop), Treatment run-state, Mark-As-Default clamping,
and the support-ticket fallback.
"""

from unittest.mock import MagicMock

import pytest

import kneespa
from kneespa import KneeSpa
from helpers.secure_auth import SecureAuthHelper

pytestmark = pytest.mark.unit


def make_stub():
    stub = MagicMock()
    stub.actuator_a = "12"
    stub.actuator_b = "13"
    stub.actuator_c = "14"
    return stub


# ----- auth -----
class TestLogin:
    def test_valid_pin_logs_in(self):
        stub = make_stub()
        user = {"username": "Dr. Vasquez", "email": "v@x", "status": "admin"}
        stub.users = {SecureAuthHelper.hash_pin("4242"): user}
        KneeSpa._on_login_attempt(stub, "4242")
        assert stub.current_user == user
        stub.shell.login_succeeded.assert_called_once_with("Dr. Vasquez", goto="protocols")
        stub.shell.login_failed.assert_not_called()

    def test_invalid_pin_fails(self):
        stub = make_stub()
        stub.users = {SecureAuthHelper.hash_pin("4242"): {"username": "X"}}
        KneeSpa._on_login_attempt(stub, "0000")
        stub.shell.login_failed.assert_called_once()
        stub.shell.login_succeeded.assert_not_called()

    def test_logout_clears_user(self):
        stub = make_stub()
        KneeSpa._on_logout(stub)
        assert stub.current_user is None
        stub.shell.logout.assert_called_once()


# ----- Setup jog -----
class TestSetupJog:
    def test_axial_fwd_calls_move_actuator(self):
        stub = make_stub()
        KneeSpa._on_setup_jog(stub, "axial", "fwd")
        stub.move_actuator.assert_called_once_with("12", None, "04", 1)

    def test_lateral_rev_fast(self):
        stub = make_stub()
        KneeSpa._on_setup_jog(stub, "lateral", "rev_fast")
        stub.move_actuator.assert_called_once_with("14", None, "20", -1)

    def test_horizontal_fwd_fast(self):
        stub = make_stub()
        KneeSpa._on_setup_jog(stub, "horizontal", "fwd_fast")
        stub.move_actuator.assert_called_once_with("13", None, "20", 1)

    def test_reset_routes_to_setup_reset(self):
        stub = make_stub()
        KneeSpa._on_setup_jog(stub, "axial", "reset")
        stub._setup_reset.assert_called_once_with("axial")
        stub.move_actuator.assert_not_called()

    def test_leg_length_routes_to_leg_jog(self):
        stub = make_stub()
        KneeSpa._on_setup_jog(stub, "leg_length", "fwd")
        stub._leg_jog.assert_called_once_with("fwd")
        stub.move_actuator.assert_not_called()

    def test_pressure_jog_sends_no_command(self):
        stub = make_stub()
        KneeSpa._on_setup_jog(stub, "pressure", "fwd")
        stub.move_actuator.assert_not_called()
        stub._reflect_setup.assert_called_once()


class TestSetupReset:
    def test_axial_reset(self):
        stub = make_stub()
        KneeSpa._setup_reset(stub, "axial")
        stub.reset_flexion_button_clicked.assert_called_once_with("12")

    def test_lateral_reset(self):
        stub = make_stub()
        KneeSpa._setup_reset(stub, "lateral")
        stub.reset_flexion_button_clicked.assert_called_once_with("14")

    def test_leg_reset(self):
        stub = make_stub()
        KneeSpa._setup_reset(stub, "leg_length")
        stub.reset_extra_button_clicked.assert_called_once()


# ----- Setup stop (the lateral-stop bug is FIXED here) -----
class TestSetupStop:
    @pytest.mark.parametrize("key,expected", [
        ("axial", "X12"),
        ("horizontal", "X13"),
        ("lateral", "X14"),    # FIXED: legacy sent X12
        ("pressure", "X12"),   # pressure rides the axial channel
    ])
    def test_stop_sends_correct_actuator(self, key, expected):
        stub = make_stub()
        KneeSpa._on_setup_stop(stub, key)
        stub.arduino.send.assert_called_once_with(expected)

    def test_leg_stop_uses_stop_leg_movement(self):
        stub = make_stub()
        KneeSpa._on_setup_stop(stub, "leg_length")
        stub.stop_leg_movement.assert_called_once()
        stub.arduino.send.assert_not_called()


# ----- Setup go -----
class TestSetupGo:
    def test_axial_go_calls_set_to_distance(self):
        stub = make_stub()
        stub.shell.setup.row_value.return_value = 3.0
        stub.config.a_factor = 1900
        KneeSpa._on_setup_go(stub, "axial")
        stub.set_to_distance.assert_called_once_with(3.0, "12", 1900)

    def test_lateral_go_calls_set_to_c_distance(self):
        stub = make_stub()
        stub.shell.setup.row_value.return_value = 10.0
        KneeSpa._on_setup_go(stub, "lateral")
        stub.set_to_c_distance.assert_called_once_with(10.0)

    def test_pressure_go_routes_to_apply_pressure(self):
        stub = make_stub()
        KneeSpa._on_setup_go(stub, "pressure")
        stub._apply_setup_pressure.assert_called_once()

    def test_apply_pressure_clamps_above_max(self):
        stub = make_stub()
        stub.shell.setup.row_value.return_value = 95.0  # above PRESSURE_MAX (80)
        KneeSpa._apply_setup_pressure(stub)
        stub.arduino.send.assert_called_once_with("P80")

    def test_apply_pressure_clamps_below_min(self):
        stub = make_stub()
        stub.shell.setup.row_value.return_value = 2.0  # below MIN_PRESSURE (10)
        KneeSpa._apply_setup_pressure(stub)
        stub.arduino.send.assert_called_once_with("P10")


# ----- Treatment run-state -----
class TestTreatmentRunState:
    def test_protocol_selected_sets_value(self):
        stub = make_stub()
        KneeSpa._on_protocol_selected(stub, 3)
        assert stub.protocol_value == "3"

    def test_pause_calls_worker_and_sets_state(self):
        stub = make_stub()
        stub.protocol_running = True
        stub._paused_at = None
        KneeSpa._on_treatment_pause(stub)
        stub.worker.pause.assert_called_once()
        stub.shell.treatment.set_run_state.assert_called_with(running=True, paused=True)

    def test_resume_calls_worker_and_sets_state(self):
        stub = make_stub()
        stub.protocol_running = True
        stub._paused_at = 1000.0
        stub.protocol_start_time = 900.0
        KneeSpa._on_treatment_resume(stub)
        stub.worker.resume.assert_called_once()
        assert stub._paused_at is None
        stub.shell.treatment.set_run_state.assert_called_with(running=True, paused=False)

    def test_estop_triggers_stop_and_resets_ui(self):
        stub = make_stub()
        KneeSpa._on_estop(stub)
        stub.emergency_stop_clicked.assert_called_once()
        assert stub.protocol_running is False
        stub.shell.treatment.set_run_state.assert_called_with(running=False, paused=False)


# ----- settings / mark-as-default -----
class TestSettings:
    def test_setting_max_left_forced_negative(self):
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = True
        stub._prev_settings = {}
        KneeSpa._on_setting_changed(stub, "max_left", 15)
        assert stub.worker.max_left == -15

    def test_setting_pulse_rate_sets_use_pulse(self):
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = True
        stub._prev_settings = {}
        KneeSpa._on_setting_changed(stub, "pulse_rate", 0)
        assert stub.worker.pulse_rate == 0
        assert stub.worker.use_pulse is False

    def test_duration_change_does_not_touch_running_worker(self):
        """Duration is pre-run only — a stray live change must NOT mutate the
        worker's duration (which could silently end the treatment)."""
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = True
        stub._prev_settings = {}
        stub._clamp_minutes = KneeSpa._clamp_minutes
        before = stub.worker.duration
        KneeSpa._on_setting_changed(stub, "duration", 6)
        assert stub.worker.duration is before  # untouched

    def test_mark_default_clamps_to_constants(self):
        stub = make_stub()
        stub._clamp_minutes = KneeSpa._clamp_minutes  # real staticmethod
        stub.shell.treatment.settings_values.return_value = {
            "max_pressure": 95, "max_left": 25, "max_right": 18, "pulse_rate": 7,
            "duration": 99,
        }
        KneeSpa._on_mark_default(stub)
        # 95->80 (PRESSURE_MAX), 25->20 (lateral), 18 ok, 7->5 (pulse max),
        # 99->30 (PROTOCOL_MINUTES_MAX)
        stub.config.save_protocol_defaults.assert_called_once_with(80, 20, 18, 5, 30)


class TestDuration:
    def test_clamp_minutes_bounds_and_rounds(self):
        assert KneeSpa._clamp_minutes(99) == 30      # PROTOCOL_MINUTES_MAX
        assert KneeSpa._clamp_minutes(1) == 5        # PROTOCOL_MINUTES_MIN
        assert KneeSpa._clamp_minutes(12.4) == 12    # rounds
        assert KneeSpa._clamp_minutes("bad") == 12   # default on garbage

    def test_duration_minutes_reads_slider(self):
        stub = make_stub()
        stub._clamp_minutes = KneeSpa._clamp_minutes
        stub.shell.treatment.settings_values.return_value = {"duration": 18}
        assert KneeSpa._duration_minutes(stub) == 18

    def test_duration_minutes_defaults_when_unavailable(self):
        stub = make_stub()
        stub._clamp_minutes = KneeSpa._clamp_minutes
        stub.shell.treatment.settings_values.side_effect = RuntimeError("no shell")
        assert KneeSpa._duration_minutes(stub) == 12  # DEFAULT_PROTOCOL_MINUTES


# ----- support ticket -----
class TestSupport:
    def test_issue_activated_remembers_question(self):
        stub = make_stub()
        KneeSpa._on_issue_activated(stub, "Pressure not reaching target")
        assert stub._selected_issue == "Pressure not reaching target"

    def test_submit_ticket_without_creds_is_handled(self):
        stub = make_stub()
        stub.current_user = {"username": "Dr", "status": "admin"}
        stub.config.ensure_device_id.return_value = "dev123"
        # No SMTP creds in the test env -> graceful failure, no exception.
        KneeSpa.submit_ticket(stub, "Device won't start")
        stub._show_timed_error.assert_called_once()

    def test_assistance_reads_current_user(self):
        stub = make_stub()
        stub.current_user = {"username": "Dr", "email": "d@x", "status": "admin"}
        KneeSpa.handle_assistance_request(stub)
        assert stub.username == "Dr"
        assert stub.user_email == "d@x"
        stub.email_admin.assert_called_once()


# ----- live telemetry wiring (medical-device "telemetry updates live") -----
class TestTelemetry:
    def test_worker_status_drives_live_status(self):
        stub = make_stub()
        # CMarks: degrees -> position. pos_c=150 sits halfway between the
        # 0deg(100) and 10deg(200) marks, so the angle approximates to 5.0.
        stub.config.CMarks = {"0.0": 100, "10.0": 200, "20.0": 300}
        KneeSpa._on_worker_status(stub, 500, 0, 150, 42)
        stub.shell.treatment.set_pressure.assert_called_once_with(42)
        stub.shell.treatment.set_angle.assert_called_once_with(pytest.approx(5.0))

    @pytest.mark.parametrize("text,phase", [
        ("Pulsing at target pressure", "pulsing"),
        ("Oscillating limb", "oscillating"),
        ("Moving to lateral angle", "positioning"),
        ("Protocol complete", "complete"),
    ])
    def test_worker_progress_maps_to_phase(self, text, phase):
        stub = make_stub()
        KneeSpa._on_worker_progress(stub, text)
        stub.shell.treatment.set_phase.assert_called_with(phase)
