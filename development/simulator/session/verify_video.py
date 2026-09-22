"""Exercise the real VLC decoder and video controls in the desktop simulator."""

import sys
from typing import Generator

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

from simulator.session.verify import GuiVerification


class VideoVerification(GuiVerification):
    """Require advancing clocks, rendered frames, and decoded narration."""

    def select_video(self, index: int) -> None:
        """Scroll to and tap a real library row, including below the fold."""
        listing = self.window.shell.video_modal._video_list
        item = listing.item(index)
        listing.scrollToItem(item)
        QApplication.processEvents()
        rect = listing.visualItemRect(item)
        assert listing.viewport().rect().contains(rect.center())
        QTest.mouseClick(listing.viewport(), Qt.LeftButton, pos=rect.center())

    def _steps(self) -> Generator[tuple, None, None]:
        import vlc

        window, shell = self.window, self.window.shell
        yield self.wait("device ready", lambda: window.initial_setup_complete
                        and not window.reset_in_progress)
        for dialog in QApplication.topLevelWidgets():
            if isinstance(dialog, QMessageBox) and dialog.isVisible():
                self.click(dialog.button(QMessageBox.Ok))
        self.click(shell.nav_rail._video)
        modal = shell.video_modal
        yield self.wait("video modal open", modal.isVisible)
        engine = modal._engine
        assert engine.available, "Install python-vlc and native VLC before verifying playback"
        assert engine.count() == 9, "Expected three demo clips and six Blahnik videos"
        assert isinstance(vlc.libvlc_get_version(), bytes), "Verification requires real libVLC"
        assert modal._pages.currentWidget() is modal._library_page
        assert modal._video_list.count() == engine.count()
        assert not modal._playing and not modal._poll.isActive()
        self.save("video-library")
        self.select_video(7)
        yield self.wait("select a later video from the list", lambda:
                        engine.index() == 7 and engine.playback_state() == "playing")
        self.click(modal._library_btn)
        yield self.wait("All videos stops playback and shows the list", lambda:
                        modal._pages.currentWidget() is modal._library_page
                        and not modal._playing and not modal._poll.isActive())
        self.select_video(0)

        for index in range(engine.count()):
            def playing() -> bool:
                position = engine.position()
                return (engine.index() == index and engine.playback_state() == "playing"
                        and position is not None and position[0] > 1 and position[1] > 1)

            yield self.wait(f"clip {index + 1} clock advances", playing, 20)
            player = engine._player
            stats = vlc.MediaStats()
            media = player.get_media()
            has_audio = player.audio_get_track_count() > 0
            try:
                yield self.wait(f"clip {index + 1} renders video and audio", lambda:
                                bool(media.get_stats(stats)) and stats.displayed_pictures > 0
                                and (not has_audio or (stats.decoded_audio > 0
                                                       and stats.played_abuffers > 0)), 15)
            finally:
                media.release()
            self.results.append({
                "clip": index + 1, "title": engine.titles()[index],
                "position": engine.position(), "has_audio": has_audio,
                "displayed_pictures": stats.displayed_pictures,
                "decoded_audio": stats.decoded_audio, "played_abuffers": stats.played_abuffers,
            })
            snapshot = self.directory / f"video-clip-{index + 1}.png"
            assert player.video_take_snapshot(0, str(snapshot), 0, 0) == 0
            yield self.wait(f"clip {index + 1} frame saved", snapshot.is_file)
            assert player.has_vout() > 0
            if sys.platform == "win32":
                assert player.get_hwnd() == int(modal._surface.winId())
            assert modal._elapsed.text() != "0:00" and modal._progress_fraction > 0
            self.save(f"video-clip-{index + 1}-controls")

            self.click(modal._small_play)
            yield self.wait(f"clip {index + 1} pauses", lambda:
                            engine.playback_state() == "paused" and not modal._playing)
            paused_at = engine.position()[0]
            self.click(modal._small_play)
            yield self.wait(f"clip {index + 1} resumes", lambda:
                            engine.playback_state() == "playing"
                            and engine.position()[0] > paused_at + 0.5)
            if index < engine.count() - 1:
                # Decode the real end of each clip without waiting through the
                # entire instructional video. No VLC state or timer is mocked.
                player.set_time(max(0, player.get_length() - 1200))
                yield self.wait(f"clip {index + 1} advances automatically", lambda:
                                engine.index() == index + 1, 15)

        self.click(modal._prev_btn)
        yield self.wait("previous clip plays", lambda: engine.index() == engine.count() - 2
                        and engine.playback_state() == "playing")
        self.click(modal._next_btn)
        yield self.wait("next clip plays", lambda: engine.index() == engine.count() - 1
                        and engine.playback_state() == "playing")
        self.click(modal._fs_btn)
        yield self.wait("fullscreen playback", lambda: modal._fullscreen
                        and engine.playback_state() == "playing")
        self.click(modal._fs_btn)
        engine._player.set_time(max(0, engine._player.get_length() - 1200))
        yield self.wait("last clip ends at the library", lambda:
                        modal._pages.currentWidget() is modal._library_page
                        and not modal._playing and not modal._poll.isActive(), 15)
        self.select_video(4)
        yield self.wait("select another video after playlist completion", lambda:
                        engine.index() == 4 and engine.playback_state() == "playing")
        self.click(self.named(modal, "Close video"))
        yield self.wait("close stops playback and resets playlist", lambda:
                        modal.isHidden() and not modal._poll.isActive() and not modal._playing
                        and engine.index() == 0 and engine.playback_state() != "playing")
        self.click(shell.nav_rail._video)
        assert modal._pages.currentWidget() is modal._library_page and not modal._playing
        self.select_video(0)
        yield self.wait("reopen plays first clip", lambda:
                        engine.index() == 0 and engine.playback_state() == "playing"
                        and engine.position() is not None and engine.position()[0] > 0.5)
        self.click(self.named(modal, "Close video"))
