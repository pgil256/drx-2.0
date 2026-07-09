"""Integration tests for the Phase 2 view layer (offscreen Qt).

Covers the AppShell composition (nav switching + login gating), the per-screen
signal surfaces and state models (treatment run-state, setup jog/live-position,
support accordion), the modal overlays, and the drawn icon / glyph helpers.
conftest forces QT_QPA_PLATFORM=offscreen; no backend is involved.
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def app(themed_app):
    return themed_app


@pytest.fixture
def shell(app):
    from ui.app_shell import AppShell

    s = AppShell()
    s.resize(1366, 768)
    return s


# ----- icons / glyphs -----
def test_glyph_substitutes_are_plex_safe(app):
    from PyQt5.QtGui import QFont, QFontMetrics

    from ui.theme import GLYPH

    fm = QFontMetrics(QFont("IBM Plex Sans", 20))
    # Every glyph we ship as a label substitute must actually exist in Plex.
    for key in ("jog_rev", "jog_fwd", "jog_rev_fast", "jog_fwd_fast", "reset",
                "close", "estop", "check", "bullet", "accordion_closed", "accordion_open"):
        ch = GLYPH[key]
        assert fm.inFont(ch), f"GLYPH[{key}]={ch!r} (U+{ord(ch):04X}) tofus in IBM Plex"


def test_drawn_icons_render_non_null(app):
    from ui.theme import nav_icon, pause_icon, play_icon

    for icon in (play_icon("#fff", 24), pause_icon("#000", 24)):
        assert not icon.isNull()
        assert not icon.pixmap(24, 24).isNull()
    for name in ("home", "setup", "protocols", "help", "support", "play"):
        ic = nav_icon(name, "#29abe2", 26)
        assert not ic.pixmap(26, 26).isNull()


# ----- shell: nav + gating -----
def test_shell_builds_with_six_screens(shell):
    from ui.screens import (
        HelpScreen,
        HomeScreen,
        ProfileScreen,
        SetupScreen,
        SupportScreen,
        TreatmentScreen,
    )

    assert shell.stack.count() == 6
    assert isinstance(shell.home, HomeScreen)
    assert isinstance(shell.setup, SetupScreen)
    assert isinstance(shell.treatment, TreatmentScreen)
    assert isinstance(shell.help, HelpScreen)
    assert isinstance(shell.support, SupportScreen)
    assert isinstance(shell.profile, ProfileScreen)


def test_gated_pages_bounce_to_login_when_logged_out(shell):
    from ui.app_shell import PAGES

    shell.set_user(None)
    shell.nav_rail.navigate.emit("setup")  # gated
    assert shell.stack.currentIndex() == PAGES.index("home")
    assert not shell.login_modal.isHidden()  # login modal popped instead
    shell.login_modal.close_overlay()

    # Ungated page is always reachable.
    shell.nav_rail.navigate.emit("help")
    assert shell.stack.currentIndex() == PAGES.index("help")


def test_login_grants_access_to_gated_pages(shell):
    from ui.app_shell import PAGES

    shell.set_user("Dr. Vasquez")
    shell.nav_rail.navigate.emit("setup")
    assert shell.stack.currentIndex() == PAGES.index("setup")
    shell.nav_rail.navigate.emit("protocols")
    assert shell.stack.currentIndex() == PAGES.index("protocols")


def test_topbar_identity_toggles_with_user(shell):
    shell.set_user(None)
    assert not shell.top_bar._identity.isVisible()
    shell.set_user("Dr. Vasquez")
    # The identity block is shown and carries the name (visibility needs an
    # ancestor show; assert the model + text instead of pixel visibility).
    assert shell.top_bar._name.text() == "Dr. Vasquez"


def test_login_success_and_logout_flow(shell):
    from ui.app_shell import PAGES

    shell.set_user(None)
    shell.show_login()
    assert not shell.login_modal.isHidden()
    shell.login_succeeded("Dr. Vasquez")
    assert shell.login_modal.isHidden()
    assert shell.stack.currentIndex() == PAGES.index("protocols")
    shell.logout()
    assert shell.stack.currentIndex() == PAGES.index("home")


def test_avatar_opens_profile_and_logout_button_logs_out(shell):
    from ui.app_shell import PAGES

    # Logged out: the avatar pops the login modal, not the profile page.
    shell.set_user(None)
    shell.top_bar._avatar.click()
    assert not shell.login_modal.isHidden()
    shell.login_modal.close_overlay()

    # Logged in: the avatar navigates to the profile page (no logout).
    shell.login_succeeded("Dr. Vasquez", title="Clinician")
    fired = []
    shell.logout_requested.connect(lambda: fired.append(True))
    shell.top_bar._avatar.click()
    assert shell.stack.currentIndex() == PAGES.index("profile")
    assert not fired
    assert shell.profile._name.text() == "Dr. Vasquez"
    assert shell.profile._title.text() == "Clinician"

    # The profile Log Out button surfaces the shell's logout signal.
    shell.profile._logout.click()
    assert fired


def test_profile_add_pin_admin_only_and_exit(shell):
    # Non-admin: Add PIN hidden, Exit App present and wired.
    shell.login_succeeded("Dr. Vasquez", title="Clinician", is_admin=False)
    assert not shell.profile._add_pin.isVisibleTo(shell.profile)

    exits = []
    shell.exit_requested.connect(lambda: exits.append(True))
    shell.profile._exit.click()
    assert exits

    # Admin: Add PIN visible; clicking opens the Add PIN modal.
    shell.login_succeeded("Administrator", title="Administrator", is_admin=True)
    assert shell.profile._add_pin.isVisibleTo(shell.profile)
    shell.profile._add_pin.click()
    assert not shell.add_pin_modal.isHidden()
    shell.add_pin_modal.close_overlay()

    # Logged out again: Add PIN hides.
    shell.set_user(None)
    assert not shell.profile._add_pin.isVisibleTo(shell.profile)


def test_add_pin_modal_two_step_flow(shell):
    m = shell.add_pin_modal
    submitted = []
    shell.add_pin_submitted.connect(lambda name, pin: submitted.append((name, pin)))

    shell.show_add_pin()
    assert not m.isHidden()
    m._name.setText("Dr. New")

    # Step 1: enter — no submission yet, keypad flips to confirm.
    m._keypad.set_value("")
    m._keypad._press("4"); m._keypad._press("3"); m._keypad._press("2"); m._keypad._press("1")
    assert submitted == []
    assert m._keypad._title.text() == "Confirm New PIN"

    # Mismatched confirm restarts the flow with an error.
    for d in "9999":
        m._keypad._press(d)
    assert submitted == []
    assert "did not match" in m._error.text()
    assert m._keypad._title.text() == "Enter New PIN"

    # Matching enter + confirm emits (username, pin).
    for d in "4321" + "4321":
        m._keypad._press(d)
    assert submitted == [("Dr. New", "4321")]

    # Controller error feedback restarts entry inside the modal…
    shell.add_pin_failed("That PIN is already in use. Choose another.")
    assert "already in use" in m._error.text()
    assert not m.isHidden()
    # …and success dismisses it.
    shell.add_pin_succeeded()
    assert m.isHidden()


# ----- treatment run-state model -----
def test_treatment_run_state_button_gating(shell):
    t = shell.treatment
    t.set_run_state(running=False, paused=False)
    assert t._start_btn.isEnabled() and not t._pause_btn.isEnabled()
    assert t._start_btn.text() == "START"
    assert all(tile.isEnabled() for tile in t._proto_buttons.values())

    t.set_run_state(running=True, paused=False)
    assert not t._start_btn.isEnabled() and t._pause_btn.isEnabled()
    assert all(not tile.isEnabled() for tile in t._proto_buttons.values())

    t.set_run_state(running=True, paused=True)
    assert t._start_btn.isEnabled() and not t._pause_btn.isEnabled()
    assert t._start_btn.text() == "RESUME"


def test_treatment_start_vs_resume_signal(shell):
    t = shell.treatment
    starts, resumes = [], []
    t.start_requested.connect(lambda: starts.append(1))
    t.resume_requested.connect(lambda: resumes.append(1))

    t.set_run_state(running=False, paused=False)
    t._on_start()
    assert starts == [1] and resumes == []

    t.set_run_state(running=True, paused=True)
    t._on_start()
    assert resumes == [1]


def test_treatment_duration_slider_locks_during_run(shell):
    t = shell.treatment
    dur = t._settings["duration"]
    t.set_run_state(running=False, paused=False)
    assert dur.isEnabled()                      # editable before a run
    t.set_run_state(running=True, paused=False)
    assert not dur.isEnabled()                  # locked while running
    t.set_run_state(running=True, paused=True)
    assert not dur.isEnabled()                  # still locked while paused
    t.set_run_state(running=False, paused=False)
    assert dur.isEnabled()                      # editable again after stop


def test_treatment_protocol_select_and_settings(shell):
    t = shell.treatment
    picked, settings = [], []
    t.protocol_selected.connect(picked.append)
    t.setting_changed.connect(lambda k, v: settings.append((k, v)))

    t._proto_buttons[3].click()
    assert picked[-1] == 3
    assert "Right Lateral" in t._title.text()

    t._settings["max_pressure"].set_value(65)
    # set_value is programmatic; emulate a user change via the inner slider.
    inner = t._settings["pulse_rate"]
    inner.valueChanged.emit(3.0)
    assert ("pulse_rate", 3.0) in settings


def test_treatment_telemetry_setters(shell):
    t = shell.treatment
    t.set_phase("holding")
    assert t._phase_badge._label.text() == "Holding…"
    t.set_progress(15, 30)  # half done
    assert abs(t._progress_fraction - 0.5) < 1e-6
    assert t._timer.text() == "0:15"
    t.set_pressure(72)
    t.set_angle(-12)  # exercises the knee rotation path


# ----- setup -----
def test_setup_jog_adjusts_slider_and_updates_live(shell):
    s = shell.setup
    jogs = []
    s.jog_requested.connect(lambda k, a: jogs.append((k, a)))
    row = s._rows["axial"]
    start = row.value()
    row._on_jog("rev", -row._step)
    assert row.value() == pytest.approx(start - row._step)
    assert ("axial", "rev") in jogs
    # Live position mirrors the slider.
    assert s._pos["axial"]._value.text()  # rendered something


def test_setup_action_signals(shell):
    s = shell.setup
    seen = {"mark": 0, "reset": 0, "estop": 0}
    s.mark_default_requested.connect(lambda: seen.__setitem__("mark", 1))
    s.reset_arduino_requested.connect(lambda: seen.__setitem__("reset", 1))
    s.emergency_stop_requested.connect(lambda: seen.__setitem__("estop", 1))
    s.mark_default_requested.emit()
    s.reset_arduino_requested.emit()
    s.emergency_stop_requested.emit()
    assert seen == {"mark": 1, "reset": 1, "estop": 1}


def test_setup_arduino_badge_toggle(shell):
    s = shell.setup
    s.set_arduino_connected(False)
    assert s._arduino_badge._label.text() == "Arduino offline"
    s.set_arduino_connected(True)
    assert s._arduino_badge._label.text() == "Arduino connected"


def test_setup_stop_controls_are_never_in_motion_lock_group(shell):
    s = shell.setup
    locked = s.control_buttons()
    for row in s._rows.values():
        assert all(button not in locked for button in row.safety_buttons)
        assert all(button in locked for button in row.motion_buttons)


def test_leg_length_go_is_disabled(shell):
    row = shell.setup._rows["leg_length"]
    go = next(button for button in row.motion_buttons if button.text() == "Go")
    assert not go.isEnabled()


# ----- support -----
def test_support_accordion_and_signals(shell):
    from ui.screens.support import _FailureItem
    from ui.theme import GLYPH

    sup = shell.support
    activated, assist, ticket = [], [], []
    sup.issue_activated.connect(activated.append)
    sup.request_assistance.connect(lambda: assist.append(1))
    sup.submit_ticket_requested.connect(lambda: ticket.append(1))

    item = sup.findChild(_FailureItem)
    assert item is not None
    assert not item._body.isVisibleTo(item)
    item._toggle()
    assert item._body.isVisibleTo(item)
    assert item._indicator.text() == GLYPH["accordion_open"]
    assert activated  # issue_activated fired

    sup.request_assistance.emit()
    sup.submit_ticket_requested.emit()
    assert assist == [1] and ticket == [1]


# ----- modals -----
def test_login_modal_submit_and_close(shell):
    from PyQt5.QtWidgets import QPushButton

    pins, closes = [], []
    shell.login_modal.submitted.connect(pins.append)
    shell.login_modal.closed.connect(lambda: closes.append(1))
    shell.show_login()

    keys = {b.text(): b for b in shell.login_modal._keypad.findChildren(QPushButton)}
    for d in "1234":
        keys[d].click()
    assert pins == ["1234"]

    shell.login_modal.show_error("Invalid PIN. Please try again.")
    assert shell.login_modal._error.text()

    shell.login_modal.close_overlay()
    assert shell.login_modal.isHidden() and closes == [1]


def test_video_modal_play_toggle(shell):
    states = []
    shell.video_modal.play_toggled.connect(states.append)
    shell.show_video()
    shell.video_modal._toggle()
    shell.video_modal._toggle()
    assert states == [True, False]
    shell.video_modal.close_overlay()
    assert shell.video_modal.isHidden()


def test_video_modal_stops_playback_on_close(shell):
    m = shell.video_modal
    shell.show_video()
    m._toggle()  # play
    assert m._playing and m._poll.isActive()
    m.close_overlay()  # dismiss → playback must be reset
    assert not m._playing
    assert not m._poll.isActive()


def test_video_modal_degrades_without_vlc(app, monkeypatch):
    """No VLC → engine unavailable, but the modal still toggles + never crashes."""
    import ui.modals.video_modal as vm

    monkeypatch.setattr(vm, "vlc", None)
    modal = vm.VideoModal()
    try:
        assert modal._engine.available is False
        states = []
        modal.play_toggled.connect(states.append)
        modal._toggle()  # "play" — engine is a no-op
        # Degrades to the static frame: surface stays hidden, the poster
        # (watermark) stays visible, and no idle poll is left running.
        assert not modal._surface.isVisibleTo(modal)
        assert modal._watermark.isVisibleTo(modal)
        assert not modal._poll.isActive()
        modal._toggle()  # "pause"
        assert states == [True, False]
    finally:
        modal.cleanup()
        modal.deleteLater()


def test_video_modal_skip_next_prev(shell):
    m = shell.video_modal
    eng = m._engine
    assert eng.count() == 3  # 1.mp4 / 2.mp4 / 3.mp4 ship in media/videos
    shell.show_video()
    assert m._clip_label.text() == "1 / 3"
    m._toggle()  # play
    m._skip(+1)
    assert eng.index() == 1 and m._clip_label.text() == "2 / 3"
    assert m._playing and m._poll.isActive()  # skip keeps playing
    m._skip(-1)
    assert eng.index() == 0
    m._skip(-1)  # wraps to the last clip
    assert eng.index() == 2 and m._clip_label.text() == "3 / 3"
    m.close_overlay()
    assert m.isHidden()
    assert eng.index() == 0  # close rewinds to the first clip


def test_video_modal_advances_through_playlist_on_clip_end(shell, monkeypatch):
    m = shell.video_modal
    shell.show_video()
    m._toggle()  # play clip 1
    monkeypatch.setattr(m._engine, "ended", lambda: True)
    m._on_poll()  # clip 1 ended → clip 2 keeps playing
    assert m._engine.index() == 1
    assert m._playing and m._poll.isActive()
    m._on_poll()  # clip 2 ended → clip 3
    assert m._engine.index() == 2
    states = []
    m.play_toggled.connect(states.append)
    m._on_poll()  # last clip ended → poster restored, rewound to clip 1
    assert not m._playing and not m._poll.isActive()
    assert m._engine.index() == 0
    assert m._watermark.isVisibleTo(m)
    assert states == [False]


def test_video_modal_audio_not_disabled(app):
    """The demo clips carry narration — the VLC instance must not be created
    with --no-audio (regression guard for the legacy silent-player options)."""
    import ui.modals.video_modal as vm

    m = vm.VideoModal()
    try:
        m._toggle()  # forces _ensure_player → vlc.Instance(...)
        args = vm.vlc.Instance.call_args[0][0]
        assert "--no-audio" not in args
    finally:
        m.cleanup()
        m.deleteLater()


def test_video_modal_recovers_from_sustained_none_position(shell, monkeypatch):
    """VLC dying mid-playback (position() stuck at None) must recover to the
    poster instead of polling a dead player forever."""
    m = shell.video_modal
    shell.show_video()
    m._toggle()  # play
    assert m._playing and m._poll.isActive()

    states = []
    m.play_toggled.connect(states.append)
    monkeypatch.setattr(m._engine, "position", lambda: None)

    # First two None polls are tolerated (VLC opens media lazily)...
    m._on_poll()
    m._on_poll()
    assert m._poll.isActive()
    assert m._playing
    # ...the third trips the recovery.
    m._on_poll()
    assert not m._poll.isActive()
    assert not m._playing
    assert m._watermark.isVisibleTo(m)
    assert states == [False]


def test_video_modal_none_run_reset_by_valid_poll(shell, monkeypatch):
    """A transient None (e.g. one slow poll) must NOT trip recovery once a
    valid position resumes; the counter resets."""
    m = shell.video_modal
    shell.show_video()
    m._toggle()

    seq = [None, None, (1.0, 30.0), None]
    monkeypatch.setattr(m._engine, "position", lambda: seq.pop(0))
    m._on_poll()  # None (1)
    m._on_poll()  # None (2)
    m._on_poll()  # valid -> resets counter
    m._on_poll()  # None (1 again)
    assert m._poll.isActive()  # never reached the threshold of 3
    assert m._playing
