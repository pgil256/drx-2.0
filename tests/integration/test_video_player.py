# tests/integration/test_video_player.py
"""Integration tests for VideoPlayer play-state UI updates (offscreen, via qtbot).

``vlc`` and the multimedia modules are mocked by ``conftest.py``, so the media
player is a ``MagicMock`` whose ``is_playing()`` return value can be scripted.
These tests drive ``update_ui()`` across play-state transitions and assert it
runs without raising and reflects the new state on the control buttons.

Regression guard for the ``self.is_playing`` AttributeError that used to live in
``update_ui()`` -- the attribute never existed (play state is kept in
``self.video_state["is_playing"]``), and the error was silently swallowed by a
broad ``try/except`` so the control buttons stopped updating without any crash.

All tests run under ``QT_QPA_PLATFORM=offscreen`` (set in conftest).
"""
import pytest

from ui.dialogs.video_player import VideoPlayer


@pytest.mark.integration
class TestVideoPlayerUpdateUi:
    """update_ui() reacts to VLC play-state transitions without raising."""

    def test_transition_to_playing_updates_state_and_buttons(self, qtbot):
        """A stopped->playing transition flips state and the control buttons."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        # Play button is only enabled when videos exist; ensure that holds.
        player.config["video_list"] = ["1.mp4"]
        player.video_state["is_playing"] = False
        player.resources["media_player"].is_playing.return_value = True
        # Seed the buttons opposite to the expected post-transition state so the
        # old swallowed-AttributeError behaviour (buttons left untouched) fails.
        player.play_button.setEnabled(True)
        player.pause_button.setEnabled(False)

        player.update_ui()  # must not raise

        assert player.video_state["is_playing"] is True
        assert player.play_button.isEnabled() is False
        assert player.pause_button.isEnabled() is True
        player.safe_cleanup()

    def test_transition_to_stopped_updates_state_and_buttons(self, qtbot):
        """A playing->stopped transition re-enables play and disables pause."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        player.config["video_list"] = ["1.mp4"]
        player.video_state["is_playing"] = True
        player.resources["media_player"].is_playing.return_value = False
        player.play_button.setEnabled(False)
        player.pause_button.setEnabled(True)

        player.update_ui()  # must not raise

        assert player.video_state["is_playing"] is False
        assert player.play_button.isEnabled() is True
        assert player.pause_button.isEnabled() is False
        player.safe_cleanup()

    def test_play_button_stays_disabled_without_videos(self, qtbot):
        """With no videos loaded, play stays disabled even when stopped."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        player.config["video_list"] = []
        player.video_state["is_playing"] = False
        player.resources["media_player"].is_playing.return_value = False
        player.play_button.setEnabled(True)

        player.update_ui()  # must not raise

        assert player.play_button.isEnabled() is False
        player.safe_cleanup()

    def test_no_media_player_disables_buttons(self, qtbot):
        """When the media player is gone, both buttons are disabled (no raise)."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        player.resources["media_player"] = None
        player.play_button.setEnabled(True)
        player.pause_button.setEnabled(True)

        player.update_ui()  # must not raise

        assert player.play_button.isEnabled() is False
        assert player.pause_button.isEnabled() is False
        player.safe_cleanup()
