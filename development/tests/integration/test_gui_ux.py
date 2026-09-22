"""Operator-visible contracts for the GUI improvement plan."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtWidgets import QAbstractButton, QScrollArea, QScroller

from kneespa import KneeSpa
from ui.app_shell import AppShell
from ui.measurements import calibrated_reading
from ui.modals.treatment_review import TreatmentReviewDialog
from ui.presentation import device_presentation
from ui.theme.qss import resolve
from ui.widgets.ds.badge import TONES as BADGE_TONES

pytestmark = pytest.mark.integration


@pytest.fixture
def shell(themed_app, qtbot):
    window = AppShell()
    qtbot.addWidget(window)
    window.set_user("Review operator")
    window.set_device_status("Ready", "Review settings and positioning.", True)
    window.resize(1366, 768)
    window.show()
    return window


def test_pending_target_survives_sensor_updates_and_commands_are_not_measurements(shell):
    setup = shell.setup
    setup.set_position("lateral", 5)
    setup._rows["lateral"].slider._increment()
    target = setup.row_value("lateral")
    setup.set_measured_position("lateral", 2.2)
    assert setup.row_value("lateral") == target
    assert setup._pos["lateral"]._value.text() == "2.2°"
    setup._rows["lateral"].slider._increment()
    assert setup._pos["lateral"]._value.text() == "2.2°"
    setup.set_arduino_connected(False)
    assert setup._pos["lateral"]._value.text() == "—"
    assert setup.row_value("lateral") == target + 2.5


def test_real_telemetry_binding_never_replaces_a_target(shell):
    shell.setup.set_position("pressure", 40)
    shell.setup.set_position("lateral", 10)
    config = SimpleNamespace(
        AMarks={"0": 0, "4": 4000}, BMarks={"-25": 0, "5": 3000},
        CMarks={"-20": 500, "20": 2500}, marks_valid=True,
        axial_service_calibrated=True, a_factor=6000,
    )
    window = SimpleNamespace(
        shell=shell, config=config, safety=SimpleNamespace(on_status=Mock()),
        arduino=SimpleNamespace(connected=True),
        _measurement=SimpleNamespace(caption=lambda connected: "Pressure live"),
    )
    KneeSpa.status_emit(window, 1200, 1500, 1750, 23.4)
    assert shell.setup.row_value("pressure") == 40
    assert shell.setup.row_value("lateral") == 10
    assert shell.setup._pos["axial"]._value.text() == "1.2 in"
    assert shell.setup._pos["horizontal"]._value.text() == "-10°"
    assert shell.setup._pos["lateral"]._value.text() == "5°"
    window.safety.on_status.assert_called_once_with(1200, 1500, 1750, 23.4)


def test_missing_or_stale_pressure_is_never_green_zero(shell):
    view = shell.treatment
    view.set_pressure(42)
    view.set_pressure_state("Pressure live")
    assert view._pressure_stat._value == "42.0"
    for caption in ("Pressure stale", "Pressure unavailable", "Waiting for controller"):
        view.set_pressure_state(caption)
        assert view._pressure_stat._value == "—"
        assert view._pressure_stat._tone == "default"
    view.set_progress(12 * 60, 12 * 60)
    assert view._time_stat._tone == "default"


def test_pressure_display_ages_even_if_diagnostics_keep_arriving(shell):
    import time
    from helpers.measurement_state import MeasurementState

    state = MeasurementState()
    state.receive({"valid": True, "age_ms": 0})
    state.baseline_valid = True
    shell.treatment.set_pressure(42)
    window = SimpleNamespace(
        shell=shell, _measurement=state, _measurement_fault=None,
        arduino=SimpleNamespace(connected=True), _status_received_at=time.monotonic() - 3,
    )
    KneeSpa._refresh_pressure_state(window)
    assert shell.treatment._pressure_stat._value == "—"
    assert shell.treatment._pressure_caption == "Pressure stale"
    assert shell.setup._pos["pressure"]._value.text() == "—"


def test_connection_warning_remains_visible_during_active_treatment(shell):
    view = shell.treatment
    view.set_run_state(True, False)
    view.set_device_status("Controller offline", "Commands may not reach the device.", False)
    assert "may not reach" in view._readiness.text()
    assert not view._readiness.isHidden()
    assert view._estop_btn.isEnabled()


@pytest.mark.parametrize("outcome,expected", [
    (None, "Not started"), ("completed", "Protocol Complete"),
    ("stopped", "Protocol Stopped"), ("fault", "Not started"),
])
def test_ready_clears_recovery_phase_without_losing_outcome(shell, outcome, expected):
    view = shell.treatment
    if outcome is not None:
        view.set_outcome(outcome, 60)
    view.set_device_status("Resetting", "Homing in progress", False)
    assert view._phase_badge._label.text() == "Stopping / recovering"
    view.set_device_status("Ready", "Review settings before starting", True)
    assert view._phase_badge._label.text() == expected
    assert view._outcome == outcome
    assert view._readiness.isHidden()


def test_target_stepper_changes_target_without_moving_device(shell, qtbot):
    # Setup targets change only through the − / + stepper; the position track
    # beneath each row is an indicator and never takes input.
    shell.navigate("setup")
    row = shell.setup._rows["pressure"]
    control = row.slider
    control.set_value(0)
    go = Mock()
    shell.setup.go_requested.connect(go)
    qtbot.mouseClick(control._right_btn, Qt.LeftButton)
    assert control.value() > 0
    assert row.track._target == control.value()
    assert row.track.testAttribute(Qt.WA_TransparentForMouseEvents)
    go.assert_not_called()


def test_motor_speed_touch_drag_commits_only_on_release(shell, qtbot):
    shell.navigate("protocols")
    view = shell.treatment
    view.open_treatment_editor()
    control = view._settings["motor_speed"]
    track = control._slider
    before = control.value()
    edits = Mock()
    control.valueChanged.connect(edits)
    end = QPoint(track.width() - 12, 4)
    qtbot.mousePress(track, Qt.LeftButton, pos=end)
    assert control.value() == before
    edits.assert_not_called()
    qtbot.mouseRelease(track, Qt.LeftButton, pos=end)
    assert control.value() == control._max
    edits.assert_called_once_with(control._max)


def test_angles_follow_protocol_without_losing_saved_values(shell):
    view = shell.treatment
    view.set_settings({"max_left": 12, "max_right": 15})
    for protocol, left, right in ((1, False, False), (2, True, False),
                                  (3, False, True), (4, True, True)):
        view.select_protocol(protocol)
        assert view._summary_rows["max_left"].isHidden() is not left
        assert view._summary_rows["max_right"].isHidden() is not right
        assert view._settings["max_left"].isEnabled() is left
        assert view._settings["max_right"].isEnabled() is right
    assert view.settings_values()["max_left"] == 12
    assert view.settings_values()["max_right"] == 15


def test_login_returns_to_setup_and_active_run_guards_video(shell):
    shell.logout()
    shell._on_nav("setup")
    shell.login_succeeded("Operator")
    assert shell._current == "setup"
    shell.set_nav_guard(lambda: True)
    shell.show_video()
    shell.show_login()
    assert shell.video_modal.isHidden()
    assert shell.login_modal.isHidden()


@pytest.mark.parametrize("width", [1360, 1366])
@pytest.mark.parametrize("page,protocol,state", [
    ("setup", 1, "ready"), ("protocols", 1, "ready"), ("protocols", 4, "ready"),
    ("protocols", 4, "running"), ("protocols", 4, "starting"),
    ("protocols", 4, "paused"), ("protocols", 4, "stopping"),
    ("protocols", 4, "resetting"), ("protocols", 4, "fault"),
    ("protocols", 4, "completed"),
])
def test_controls_fit_the_device_and_stop_remains_reachable(
    shell, themed_app, width, page, protocol, state,
):
    shell.setFixedSize(width, 768)
    shell.navigate(page)
    shell.treatment.select_protocol(protocol)
    shell.treatment.set_patient(
        "Alexandria Elizabeth Montgomery-Wellington de la Cruz Example Patient"
    )
    shell.treatment.set_cloud_status(
        "Upload failed: record retained; authentication required before retrying."
    )
    themed_app.processEvents()
    original_stop = shell.treatment._estop_btn.geometry()
    shell.treatment.set_run_state(
        state in ("running", "starting", "paused", "stopping"), state == "paused",
    )
    shell.treatment.set_busy(state in ("starting", "stopping", "resetting", "fault"))
    if state in ("completed", "fault"):
        shell.treatment.set_outcome(state, 720 if state == "completed" else 180)
    if page == "setup":
        shell.setup.set_measured_position(
            "pressure", None, "Controller fault — last reading stale",
        )
    themed_app.processEvents()
    screen = shell.setup if page == "setup" else shell.treatment
    for button in screen.findChildren(QAbstractButton):
        if not button.isVisibleTo(screen):
            continue
        point = button.mapTo(shell, QPoint(0, 0))
        assert point.x() >= 0 and point.y() >= 0, button.text()
        assert point.x() + button.width() <= width, button.text()
        assert point.y() + button.height() <= 768, button.text()
        assert button.width() >= 48 and button.height() >= 48, button.text()
        ancestor = button.parentWidget()
        while ancestor is not None and ancestor is not shell:
            origin = button.mapTo(ancestor, QPoint(0, 0))
            bounds = button.rect().translated(origin)
            assert ancestor.rect().contains(bounds), (
                button.text(), ancestor.objectName(), bounds, ancestor.rect()
            )
            ancestor = ancestor.parentWidget()
    stop = screen._estop_btn
    assert stop.isEnabled() and stop.height() >= 72
    if page == "protocols":
        assert stop.geometry() == original_stop
        activated = Mock()
        shell.treatment.estop_requested.connect(activated)
        stop.click()
        activated.assert_called_once_with()


@pytest.mark.parametrize("section", [0, 1, 2])
def test_reference_pages_accept_drag_scroll_without_sending_a_request(shell, qtbot, section):
    from ui.screens.support import _FailureItem

    shell.navigate("support")
    screen = shell.support
    screen._select_section(section)
    for item in screen.findChildren(_FailureItem):
        item._toggle()
    qtbot.wait(1)
    scroll = screen._sections.currentWidget()
    scroll.setFixedHeight(250)
    qtbot.wait(1)
    assert scroll.verticalScrollBar().maximum() > 0
    assert QScroller.grabbedGesture(scroll.viewport()) != 0
    sent = Mock()
    shell.support.submit_ticket_requested.connect(sent)
    scroller = QScroller.scroller(scroll.viewport())
    scroller.handleInput(QScroller.InputPress, QPointF(200, 350), 0)
    scroller.handleInput(QScroller.InputMove, QPointF(200, 260), 100)
    scroller.handleInput(QScroller.InputMove, QPointF(200, 140), 200)
    scroller.handleInput(QScroller.InputRelease, QPointF(200, 140), 250)
    qtbot.waitUntil(lambda: scroll.verticalScrollBar().value() > 0)
    scroller.stop()
    sent.assert_not_called()


def test_review_shows_only_applicable_angles_and_defaults_to_back(shell, qtbot):
    settings = shell.treatment.settings_values()
    dialog = TreatmentReviewDialog(2, settings, "Patient: Example", shell)
    qtbot.addWidget(dialog)
    assert ("Left angle", "10°") in dialog._rows
    assert all(label != "Right angle" for label, _ in dialog._rows)
    assert not dialog.start_button.autoDefault()
    dialog.show()
    dialog.back_button.click()
    assert dialog.result() == dialog.Rejected


@pytest.mark.parametrize("marks,raw,expected", [
    ({"0": 0, "4": 4000}, 1200, 1.2),
    ({"-20": 2500, "20": 500}, 1000, 10),
    ({"0": 0, "4": 4000}, 5000, None),
    ({"0": 0, "2": 4000, "4": 2000}, 1000, None),
    ({}, 0, None), ({"0": 0, "4": 4000}, float("nan"), None),
])
def test_display_conversion_never_fabricates_an_endpoint(marks, raw, expected):
    assert calibrated_reading(raw, marks) == expected


@pytest.mark.parametrize("changed", [
    {"connected": False}, {"protocol_state": "fault"}, {"resetting": True},
    {"initialized": False}, {"calibrated": False}, {"physical_stop": True},
])
def test_idle_or_connected_does_not_alone_mean_ready(changed):
    state = dict(connected=True, protocol_state="idle", resetting=False,
                 initialized=True, calibrated=True, physical_stop=False)
    assert device_presentation(**state).can_start
    state.update(changed)
    assert not device_presentation(**state).can_start


def test_action_text_and_control_edges_have_measurable_contrast():
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                  for v in channels]
        return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))

    def contrast(foreground, background):
        dark, light = sorted((luminance(resolve(foreground)), luminance(resolve(background))))
        return (light + .05) / (dark + .05)

    for token in ("--color-primary", "--color-primary-hover", "--color-primary-active",
                  "--color-success", "--color-success-hover", "--color-danger",
                  "--color-danger-hover"):
        assert contrast("--white", token) >= 4.5, token
    for background in ("--white", "--gray-200", "--gray-300", "--blue-050", "--blue-100"):
        assert contrast("--ink-800", background) >= 4.5, background
    assert contrast("--gray-600", "--gray-300") >= 4.5  # disabled text stays readable
    for name, (background, foreground) in BADGE_TONES.items():
        assert contrast(foreground, background) >= 4.5, name
    for background in ("--white", "--gray-200"):
        assert contrast("--border-control", background) >= 3
    assert contrast("--color-primary", "--white") >= 3  # indicator / focus / slider ring
