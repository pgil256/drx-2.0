"""Unit tests for the modern view <-> backend wiring in kneespa.py.

Like test_actuator_controls / test_conversions, these call ``KneeSpa`` methods
UNBOUND against an explicit facade without constructing the hardware window;
the login flow uses a real AppShell and AuthController. Gate W separately tests
the actual constructor and control signals.
They verify the seam between the AppShell view layer and the FAILSAFE
controllers: login delegation, Setup jog/go/stop mapping (incl. the fixed
lateral-stop routing), Treatment run-state, Mark-As-Default clamping, the
support-ticket fallback, and controller presentation.
"""

from functools import partial
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import pytest
from PyQt5.QtCore import QObject
from PyQt5.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from controllers.auth_controller import AuthController
from helpers.secure_auth import SecureAuthHelper
from kneespa import KneeSpa
from fixtures.controllers import make_stub
from controllers.protocol_controller import ProtocolController
from ui.app_shell import AppShell, PAGES

pytestmark = pytest.mark.unit


# ----- cloud patient lookup result (external data) -----
class TestCloudLookupResult:
    def test_non_dict_result_is_reported_as_unavailable(self):
        stub = make_stub()
        stub.protocol_running = False
        KneeSpa._on_cloud_lookup_done(stub, 0, ["not", "a", "patient"])
        assert "Cloud unavailable" in stub.shell.treatment.set_patient_error.call_args.args[0]
        assert stub.cloud_patient is None

    def test_garbage_setting_rejects_entire_patient_plan(self):
        stub = make_stub()
        stub.protocol_running = False
        KneeSpa._on_cloud_lookup_done(stub, 0, {
            "patient_id": 7, "display_name": "Jane D.",
            "settings": {"max_pressure_lb": "sixty", "duration_min": 15,
                         "max_left_deg": None, "protocol_number": "3"},
        })
        stub.shell.treatment.set_patient.assert_not_called()
        stub.shell.treatment.set_settings.assert_not_called()
        stub.shell.treatment.select_protocol.assert_not_called()
        assert stub.cloud_patient is None

    def test_lookup_resolving_mid_treatment_is_ignored(self):
        stub = make_stub()
        stub.protocol_running = True
        KneeSpa._on_cloud_lookup_done(stub, 0, {
            "patient_id": 7, "display_name": "Jane D.",
            "settings": {"max_pressure_lb": 70},
        })
        stub.shell.treatment.set_settings.assert_not_called()
        stub.shell.treatment.select_protocol.assert_not_called()
        stub.shell.treatment.set_patient.assert_not_called()


# ----- stop paths must alarm, never raise -----
class TestStopGuards:
    def test_row_stop_with_no_transport_alarms_instead_of_raising(self):
        stub = make_stub()
        stub.arduino = None
        KneeSpa.stop_position_flexion_button(stub, "12")
        stub._show_timed_error.assert_called_once()
        assert "STOP NOT DELIVERED" in stub._show_timed_error.call_args[0][0]


# ----- auth (verification itself lives in controllers.auth_controller) -----
class TestLogin:
    @pytest.mark.parametrize("outcome", ["success", "invalid", "locked"])
    def test_modal_submission_through_auth_preserves_login_gating(
        self, qtbot: QtBot, tmp_path: Path, outcome: str
    ) -> None:
        """Real modal/auth flow works without legacy login fields or dialogs."""
        shell = AppShell()
        qtbot.addWidget(shell)
        user = {"username": "Test clinician", "status": "user"}
        stub = SimpleNamespace(
            shell=shell,
            current_user=None,
            protocol_running=False,
            machine_sign_in=SimpleNamespace(clear=MagicMock()),
            login_pin="",
            users={SecureAuthHelper.hash_pin_secure("7531"): user},
            _show_timed_error=MagicMock(),
            _show_patient_modal=MagicMock(),
            _on_patient_edit=MagicMock(),
            patients=SimpleNamespace(clear_session=MagicMock()),
        )
        stub._is_admin = partial(KneeSpa._is_admin, stub)
        stub.update_ui_after_login = partial(KneeSpa.update_ui_after_login, stub)
        stub.auth = AuthController(stub, state_path=str(tmp_path / "auth_state.json"))
        if outcome == "locked":
            stub.auth.lockout_until = time.time() + 60
        shell.login_attempted.connect(partial(KneeSpa._on_login_attempt, stub))
        shell.nav_rail.navigate.emit("protocols")
        assert shell.stack.currentIndex() == PAGES.index("home")
        assert not shell.login_modal.isHidden()

        keypad = shell.login_modal._keypad
        buttons = {button.text(): button for button in keypad.findChildren(QPushButton)}
        for digit in ("0000" if outcome == "invalid" else "7531"):
            buttons[digit].click()

        assert stub.login_pin == ""
        if outcome == "success":
            assert stub.current_user == user
            assert shell.login_modal.isHidden()
            assert shell.stack.currentIndex() == PAGES.index("protocols")
            assert shell.top_bar._name.text() == user["username"]
            stub._show_timed_error.assert_not_called()
        else:
            assert stub.current_user is None
            assert not shell.login_modal.isHidden()
            assert keypad.value() == ""
            assert shell.login_modal._error.text() == "Invalid PIN. Please try again."
            stub._show_timed_error.assert_called_once()
            shell.nav_rail.navigate.emit("setup")
            assert shell.stack.currentIndex() == PAGES.index("home")

    def test_login_attempt_seeds_pin_and_delegates(self):
        """The modal submits the whole PIN; the window buffers it and hands
        off to AuthController (salted verify + lockout)."""
        stub = make_stub()
        KneeSpa._on_login_attempt(stub, "4242")
        assert stub.login_pin == "4242"
        stub.auth.handle_login.assert_called_once()

    def test_failed_login_shows_modal_error(self):
        """If AuthController did not produce a user, the modal shows the
        inline failure (specifics arrive via the timed error box)."""
        stub = make_stub()
        stub.current_user = None
        KneeSpa._on_login_attempt(stub, "0000")
        stub.shell.login_failed.assert_called_once()

    def test_successful_login_skips_modal_error(self):
        stub = make_stub()
        stub.current_user = {"username": "Dr. Vasquez"}
        KneeSpa._on_login_attempt(stub, "4242")
        stub.shell.login_failed.assert_not_called()

    def test_update_ui_after_login_drives_shell(self):
        stub = make_stub()
        stub.shell._current = "protocols"
        stub.current_user = {"username": "Dr. Vasquez"}
        stub._is_admin.return_value = False
        KneeSpa.update_ui_after_login(stub)
        stub.shell.login_succeeded.assert_called_once_with(
            "Dr. Vasquez", title="Clinician", is_admin=False
        )
        stub.patients.clear_session.assert_called_once()

    def test_update_ui_after_login_admin_title(self):
        stub = make_stub()
        stub.shell._current = "protocols"
        stub.current_user = {"username": "Administrator", "status": "admin"}
        stub._is_admin.return_value = True
        KneeSpa.update_ui_after_login(stub)
        stub.shell.login_succeeded.assert_called_once_with(
            "Administrator", title="Administrator",
            is_admin=True,
        )

    def test_is_admin_checks_current_user_status(self):
        stub = make_stub()
        stub.current_user = {"username": "Admin", "status": "admin"}
        assert KneeSpa._is_admin(stub)
        stub.current_user = {"username": "User", "status": "user"}
        assert not KneeSpa._is_admin(stub)
        stub.current_user = None
        assert not KneeSpa._is_admin(stub)

    def test_logout_clears_user(self):
        stub = make_stub()
        stub._block_active_treatment_exit.return_value = False
        KneeSpa._on_logout(stub)
        assert stub.current_user is None
        stub.shell.logout.assert_called_once()
        stub.patients.clear_session.assert_called_once()

    def test_exit_app_closes_window(self):
        """Exit App routes through self.close() so closeEvent runs the full
        hardware cleanup (Arduino disconnect + GPIO)."""
        stub = make_stub()
        stub._block_active_treatment_exit.return_value = False
        KneeSpa._on_exit_app(stub)
        stub.close.assert_called_once()

    def test_exit_app_blocked_during_treatment(self):
        stub = make_stub()
        stub._block_active_treatment_exit.return_value = True
        KneeSpa._on_exit_app(stub)
        stub.close.assert_not_called()

    def test_logout_blocked_during_treatment(self):
        """Logging out mid-treatment would drop the operator's session while
        traction is applied; the nav guard blocks it."""
        stub = make_stub()
        stub._block_active_treatment_exit.return_value = True
        user = {"username": "Dr"}
        stub.current_user = user
        KneeSpa._on_logout(stub)
        assert stub.current_user == user
        stub.shell.logout.assert_not_called()


# ----- treatment navigation warning -----
class TestTreatmentNavigation:
    def test_confirmed_navigation_leaves_treatment_screen(self, qtbot: QtBot) -> None:
        shell = AppShell()
        qtbot.addWidget(shell)
        shell.set_user("Dr")
        shell.navigate("protocols")
        confirmation = MagicMock(return_value=True)
        shell.set_nav_confirmation(confirmation)

        shell.nav_rail.navigate.emit("home")

        confirmation.assert_called_once_with("protocols", "home")
        assert shell._current == "home"

    def test_cancelled_navigation_stays_on_treatment_screen(self, qtbot: QtBot) -> None:
        shell = AppShell()
        qtbot.addWidget(shell)
        shell.set_user("Dr")
        shell.navigate("protocols")
        shell.set_nav_confirmation(MagicMock(return_value=False))

        shell.nav_rail.navigate.emit("help")

        assert shell._current == "protocols"


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
        stub._reflect_setup.assert_not_called()  # target editing is not a command or measurement


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

    def test_pressure_reset_sends_real_release(self):
        stub = make_stub()
        KneeSpa._setup_reset(stub, "pressure")
        stub.arduino.send.assert_called_once_with("P0")
        stub._reflect_setup.assert_not_called()
        # The treatment banner is reserved for protocol stops: set_stopping()
        # here had no matching set_idle(), so "STOPPING - RELEASING TRACTION"
        # stayed over the top bar until the next treatment or Arduino reset.
        stub.treatment_panel.set_stopping.assert_not_called()
        stub.loading_spinner.hide.assert_called_once()


# ----- Setup stop -----
# Routed through the base stop paths (bare 'X' + link-down alarm). The row
# still resolves the CORRECT actuator identity (the legacy lateral-stop bug
# mapped lateral to the axial channel).
class TestSetupStop:
    @pytest.mark.parametrize("key,expected", [
        ("axial", "12"),
        ("horizontal", "13"),
        ("lateral", "14"),     # FIXED: legacy routed lateral to actuator 12
        ("pressure", "12"),    # pressure rides the axial channel
    ])
    def test_stop_routes_correct_actuator(self, key, expected):
        stub = make_stub()
        KneeSpa._on_setup_stop(stub, key)
        stub.stop_position_flexion_button.assert_called_once_with(expected)

    def test_leg_stop_uses_stop_leg_movement(self):
        stub = make_stub()
        KneeSpa._on_setup_stop(stub, "leg_length")
        stub.stop_leg_movement.assert_called_once()
        stub.stop_position_flexion_button.assert_not_called()


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

    def test_leg_go_uses_tracked_leg_controller(self):
        stub = make_stub()
        stub.shell.setup.row_value.return_value = 1.25
        stub.leg = MagicMock()
        stub.leg.move_to.return_value = True
        result = KneeSpa._on_setup_go(stub, "leg_length")
        assert result is True
        stub.leg.move_to.assert_called_once_with(1.25)
        stub.disable_actuator_controls.assert_not_called()
        stub.loading_spinner.show.assert_not_called()

    def test_horizontal_go_uses_calibrated_absolute_position(self):
        stub = make_stub()
        stub.shell.setup.row_value.return_value = -10
        stub.config.BMarks = {
            "-25": 0, "-20": 380, "-15": 760, "-10": 1140,
            "-5": 1520, "0": 1900, "5": 2280,
        }
        KneeSpa._on_setup_go(stub, "horizontal")
        stub.arduino.send.assert_called_once_with("I131140")

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

    def test_start_seeds_inputs_then_delegates(self):
        """START goes through the ProtocolController state machine (confirm
        dialog + connection check), after seeding the modern slider values."""
        stub = make_stub()
        stub.protocol_state = "idle"
        KneeSpa.start_or_stop_protocol(stub)
        stub._seed_modern_run_inputs.assert_called_once()
        stub.protocol.start_or_stop.assert_called_once()

    def test_seed_reads_settings_and_pulse_rate(self):
        stub = make_stub()
        stub.shell.treatment.settings_values.return_value = {
            "max_pressure": 50, "max_left": 10, "max_right": 10,
            "pulse_rate": 2.5, "duration": 12,
        }
        stub.shell.treatment.selected_protocol.return_value = 2
        KneeSpa._seed_modern_run_inputs(stub)
        assert stub.protocol_value == "2"
        assert stub.current_pulse_rate == 2.5
        assert stub.current_use_pulse_setting is True
        assert stub._prev_settings["pulse_rate"] == 2.5

    def test_seed_zero_pulse_rate_disables_pulse(self):
        stub = make_stub()
        stub.shell.treatment.settings_values.return_value = {"pulse_rate": 0}
        KneeSpa._seed_modern_run_inputs(stub)
        assert stub.current_pulse_rate is None
        assert stub.current_use_pulse_setting is False

    def test_pause_calls_worker_and_sets_state(self):
        stub = make_stub()
        stub.protocol_running = True
        stub._paused_at = None
        stub.protocol = ProtocolController(stub)
        KneeSpa._on_treatment_pause(stub)
        stub.worker.pause.assert_called_once()
        stub.shell.treatment.set_run_state.assert_called_with(running=True, paused=True)

    def test_resume_calls_worker_and_sets_state(self):
        stub = make_stub()
        stub.protocol_running = True
        stub._paused_at = 1000.0
        stub.protocol_start_time = 900.0
        stub.protocol = ProtocolController(stub)
        KneeSpa._on_treatment_resume(stub)
        stub.worker.resume.assert_called_once()
        assert stub._paused_at is None
        stub.shell.treatment.set_run_state.assert_called_with(running=True, paused=False)

    def test_estop_runs_stop_chain_and_resets_ui(self):
        """E-stop drives the controllers' chain (GPIO + X + reset); the state
        machine closes via the worker's finished(False), so the handler only
        forces the Treatment visuals to a stopped state."""
        stub = make_stub()
        stub.protocol = ProtocolController(stub)
        KneeSpa._on_estop(stub)
        stub.stop_actuators.assert_called_once()
        assert stub._paused_at is None
        stub.shell.treatment.set_run_state.assert_called_with(running=False, paused=False)
        stub.shell.treatment.set_phase.assert_called_with("stopped")


# ----- settings / mark-as-default -----
class TestSettings:
    def test_setting_max_left_forced_negative(self):
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = True
        stub._prev_settings = {}
        KneeSpa._on_setting_changed(stub, "max_left", 15)
        stub.worker.request_live_angle.assert_called_once_with("left", 15)

    def test_setting_max_right_routes_live_request(self):
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = True
        stub._prev_settings = {}
        KneeSpa._on_setting_changed(stub, "max_right", 12)
        stub.worker.request_live_angle.assert_called_once_with("right", 12)

    def test_setting_pressure_routes_live_request(self):
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = True
        stub._prev_settings = {}
        KneeSpa._on_setting_changed(stub, "max_pressure", 70)
        stub.worker.request_live_pressure.assert_called_once_with(70)

    def test_setting_pulse_rate_sets_use_pulse(self):
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = True
        stub._prev_settings = {}
        KneeSpa._on_setting_changed(stub, "pulse_rate", 0)
        stub.worker.request_live_pulse_rate.assert_called_once_with(0)

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

    def test_setting_change_without_worker_is_safe(self):
        """Slider moves while no protocol worker exists (pre-run, or after a
        stop tore the worker down): the change is recorded for the next run
        and nothing dereferences the missing worker."""
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = True
        stub._prev_settings = {}
        stub.worker = None
        KneeSpa._on_setting_changed(stub, "max_pressure", 70)
        assert stub._prev_settings["max_pressure"] == 70

    def test_pulse_rate_change_without_worker_tracks_state(self):
        """The pulse on/off + cadence snapshot feeds the NEXT start's
        seeding, so it must update even with no live worker."""
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = True
        stub._prev_settings = {}
        stub.worker = None
        KneeSpa._on_setting_changed(stub, "pulse_rate", 3)
        assert stub.current_use_pulse_setting is True
        assert stub.current_pulse_rate == 3

    def test_cancelled_change_rolls_back_slider(self):
        stub = make_stub()
        stub._confirm_mid_protocol_change.return_value = False
        stub._prev_settings = {"max_pressure": 40}
        KneeSpa._on_setting_changed(stub, "max_pressure", 70)
        stub.shell.treatment.set_settings.assert_called_once_with({"max_pressure": 40})

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
        stub.config.save_protocol_defaults.assert_called_once_with(
            80, 20, 18, 5, 30, motor_speeds=stub.shell.treatment.settings_values()
        )


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

    def test_empty_ticket_is_rejected_at_controller_boundary(self) -> None:
        stub = make_stub()
        stub._send_support_email = MagicMock()
        KneeSpa._on_submit_ticket(stub, {})
        stub._send_support_email.assert_not_called()
        assert stub.shell.support.set_delivery_state.call_args.args[0] == "invalid"

    def test_assistance_reads_current_user(self):
        stub = make_stub()
        stub.current_user = {"username": "Dr", "email": "d@x", "status": "admin"}
        KneeSpa.handle_assistance_request(stub)
        assert stub.username == "Dr"
        assert stub.user_email == "d@x"
        stub.email_admin.assert_called_once()


# ----- live telemetry (medical-device "telemetry updates live") -----
class TestTelemetry:
    def test_protocol_timer_keeps_one_second_interval_and_countdown_callback(self) -> None:
        """Exercise timer configuration without constructing the hardware window."""
        owner = QObject()
        owner.update_protocol_time = MagicMock()
        KneeSpa.setup_timers(owner)
        assert owner.protocol_timer.parent() is owner
        assert owner.protocol_timer.interval() == 1000
        assert not owner.protocol_timer.isActive()
        owner.protocol_timer.timeout.emit()
        owner.update_protocol_time.assert_called_once_with()

    def test_status_emit_drives_live_status_and_safety(self):
        """Arduino status feeds the Treatment live readouts AND still reaches
        the SafetyMonitor (the safety path must never be starved by the UI)."""
        stub = make_stub()
        # CMarks: degrees -> position. pos_c=150 sits halfway between the
        # 0deg(100) and 10deg(200) marks, so the angle approximates to 5.0.
        stub.config.CMarks = {"0.0": 100, "10.0": 200, "20.0": 300}
        KneeSpa.status_emit(stub, 500, 0, 150, 42)
        stub.shell.treatment.set_pressure.assert_called_once_with(42)
        stub.shell.treatment.set_angle.assert_called_once_with(pytest.approx(5.0))
        stub.safety.on_status.assert_called_once_with(500, 0, 150, 42)


# ----- controller presentation -----
class TestPresentation:
    @pytest.mark.parametrize("text,phase", [
        ("Pulsing at target pressure", "pulsing"),
        ("Oscillating limb", "oscillating"),
        ("Moving to lateral angle", "positioning"),
        ("Protocol complete", "complete"),
        ("Protocol stopped", "stopped"),
        ("Protocol Started", "ramping"),
        ("Preparing: centering and zeroing resting pressure", "starting"),
    ])
    def test_status_maps_to_phase(self, text, phase):
        stub = make_stub()
        ProtocolController(stub).update_status_label(text)
        stub.shell.treatment.set_phase.assert_called_with(phase)
        stub.treatment_panel.set_phase.assert_called_once_with(text.upper())

    def test_status_ignores_unknown_phase_but_keeps_banner_text(self):
        stub = make_stub()
        ProtocolController(stub).update_status_label("some unrelated message")
        stub.shell.treatment.set_phase.assert_not_called()
        stub.treatment_panel.set_phase.assert_called_once_with("SOME UNRELATED MESSAGE")

    @pytest.mark.parametrize("state,running,busy", [
        ("running", True, False), ("idle", False, False),
        ("starting", True, True), ("fault", False, True),
    ])
    def test_state_drives_view_directly(self, state, running, busy):
        stub = make_stub()
        stub.reset_in_progress = False
        ProtocolController(stub).set_state(state)
        stub.shell.treatment.set_run_state.assert_called_once_with(
            running=running, paused=False
        )
        stub.shell.treatment.set_busy.assert_called_once_with(busy)
