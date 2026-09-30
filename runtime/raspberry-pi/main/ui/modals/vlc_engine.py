"""VLC playback engine and ALSA audio helpers for :class:`VideoModal`.

``_VlcEngine`` wraps a libVLC media player that renders into a native Qt
surface and plays every ``.mp4`` in the videos directory in sorted filename
order. The module-level helpers discover the Pi's direct ALSA outputs and
persist the operator's volume preference. VLC is optional: when the binding or
its native runtime is missing the engine reports ``available = False`` and the
modal falls back to its static frame.
"""

import os
import shutil
import subprocess
import sys
from numbers import Real
from typing import List, Optional

from PyQt5.QtWidgets import QWidget

from config.constants import UI_PATHS

try:  # VLC is optional — absent on dev boxes / headless CI (mocked in tests).
    import vlc
except Exception as exc:  # pragma: no cover - exercised only where vlc is missing
    print(f"VideoModal: VLC unavailable: {exc!r}")
    vlc = None

_DEFAULT_VOLUME = 100
# Keep the original clip filenames so existing devices retain their playback order.
_VIDEO_TITLES = {
    "1": "Regenerative Medicine Explained",
    "2": "Stem Cell Research and Innovation",
    "3": "How KneeSpa Works",
}


def _real_number(value: object) -> Optional[float]:
    """Return a VLC numeric result as a float, or ``None`` when unavailable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Real):
        return float(value)
    # Some older python-vlc/ctypes combinations expose c_long values instead
    # of plain Python ints. Do not broadly call float(value): MagicMock and
    # other sentinel objects can misleadingly coerce to a number.
    raw = getattr(value, "value", None)
    if isinstance(raw, Real) and not isinstance(raw, bool):
        return float(raw)
    return None


def _audio_config_dir() -> str:
    configured = os.environ.get("KNEESPA_AUDIO_CONFIG_DIR")
    if configured:
        return os.path.expanduser(configured)
    root = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(root, "kneespa")


def _read_audio_preference(name: str) -> str:
    try:
        with open(os.path.join(_audio_config_dir(), name), "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _write_audio_preference(name: str, value: object) -> None:
    try:
        folder = _audio_config_dir()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(f"{value}\n")
        os.replace(temporary, path)
    except OSError as exc:
        print(f"VideoModal: unable to save audio preference {name}: {exc!r}")


def _discover_alsa_devices() -> List[str]:
    """Return the direct ALSA devices used by the successful Pi sound test."""
    if not sys.platform.startswith("linux") or shutil.which("aplay") is None:
        return []
    try:
        result = subprocess.run(
            ["aplay", "-L"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return list(dict.fromkeys(
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("sysdefault:")
    ))


def _friendly_audio_device(device: str) -> str:
    lowered = device.lower()
    if "headphone" in lowered:
        return "Headphones / Speakers"
    if "vc4hdmi0" in lowered:
        return "HDMI 1"
    if "vc4hdmi1" in lowered:
        return "HDMI 2"
    if "vc4hdmi" in lowered or "hdmi" in lowered:
        return "HDMI"
    card = device.split("CARD=", 1)[-1]
    return card.replace("_", " ")


class _VlcEngine:
    """Thin VLC wrapper that renders into a host surface widget.

    Every public method is a no-op when VLC or the clip is unavailable, so the
    modal degrades gracefully instead of raising. All VLC calls are guarded —
    in tests ``vlc`` is a MagicMock, so ``position()`` returns ``None`` (the
    mock's getters are not real numbers) and play/pause are harmless.
    """

    def __init__(
        self,
        surface: QWidget,
        audio_device: str = "",
        volume: int = _DEFAULT_VOLUME,
    ) -> None:
        self._surface = surface
        self._instance = None
        self._player = None
        self._playlist = self._discover_playlist()
        self._index = 0
        self._audio_device = audio_device
        self._volume = max(0, min(100, int(volume)))
        self._muted = self._volume == 0
        self._audio_attempts = 0
        self._audio_ready = False
        self.available = vlc is not None and bool(self._playlist)

    @staticmethod
    def _discover_playlist():
        """All .mp4 paths in the videos directory, in sorted filename order.

        ``UI_PATHS["VIDEOS"]`` is the directory; a single-file path (the
        pre-playlist config shape) still works via the dirname fallback.
        """
        try:
            configured = UI_PATHS.get("VIDEOS")
            if not configured:
                return []
            folder = configured if os.path.isdir(configured) else os.path.dirname(configured)
            if os.path.isdir(folder):
                return [
                    os.path.join(folder, f)
                    for f in sorted(os.listdir(folder), key=str.casefold)
                    if f.lower().endswith(".mp4") and os.path.isfile(os.path.join(folder, f))
                ]
        except Exception:
            pass
        return []

    def count(self):
        return len(self._playlist)

    def index(self):
        return self._index

    def titles(self) -> List[str]:
        """Return readable clip names in their playback order."""
        names = [os.path.splitext(os.path.basename(path))[0] for path in self._playlist]
        return [
            _VIDEO_TITLES.get(
                name, f"Demo video {name}" if name.isdigit() else name.replace("_", " ")
            )
            for name in names
        ]

    def audio_device(self) -> str:
        return self._audio_device

    def _ensure_player(self):
        if self._player is not None or not self.available:
            return self._player
        try:
            options = ["--no-xlib", "--quiet"]
            if sys.platform.startswith("linux") and self._audio_device:
                # Match the successful direct-output diagnostic exactly:
                # bypass PipeWire/Pulse routing and address ALSA by name.
                options.extend([
                    "--aout=alsa",
                    f"--alsa-audio-device={self._audio_device}",
                ])
                print(f"VideoModal: forcing ALSA output {self._audio_device}")
            self._instance = vlc.Instance(options)
            self._player = self._instance.media_player_new()
            self._embed()
            try:
                # Don't let VLC grab mouse/keyboard input for the embedded
                # window — on X11 that grab can leave the surrounding Qt UI
                # (including the close button) unresponsive during playback.
                self._player.video_set_mouse_input(False)
                self._player.video_set_key_input(False)
            except Exception:
                pass
            self._load(self._index)
        except Exception as exc:
            print(f"VideoModal: VLC init failed, degrading to poster: {exc!r}")
            self._player = None
            self.available = False
        return self._player

    def _load(self, index):
        path = self._playlist[index]
        print(f"VideoModal: loading clip {index + 1}/{len(self._playlist)}: {path}")
        media = self._instance.media_new(path)
        self._player.set_media(media)
        media.release()
        self._audio_attempts = 0
        self._audio_ready = False

    def set_track(self, index):
        """Select playlist entry ``index`` (does not start playback).

        Returns True when the track is selected; the caller decides whether
        to ``play()``. If the player already exists the current clip is
        stopped and the new media loaded; otherwise the index simply becomes
        the one ``_ensure_player`` loads on first play.
        """
        if not self.available or not 0 <= index < len(self._playlist):
            return False
        self._index = index
        if self._player is not None:
            try:
                self._player.stop()
                self._load(index)
            except Exception:
                return False
        return True

    def ended(self):
        """True once the current clip has played to the end."""
        return self.playback_state() == "ended"

    def playback_state(self) -> str:
        """Return a stable lowercase VLC state name, or ``unknown``."""
        if self._player is None or vlc is None:
            return "unknown"
        try:
            state = self._player.get_state()
            for name in (
                "Opening",
                "Buffering",
                "Playing",
                "Paused",
                "Stopped",
                "Ended",
                "Error",
            ):
                if state == getattr(vlc.State, name, object()):
                    return name.lower()
        except Exception:
            pass
        return "unknown"

    def _embed(self):
        if os.environ.get("KNEESPA_VIDEO_NO_EMBED") == "1":
            # Diagnostic escape hatch: let VLC open its own top-level window
            # so embedding problems can be separated from playback problems.
            print("VideoModal: KNEESPA_VIDEO_NO_EMBED=1 — VLC opens its own window")
            return
        handle = int(self._surface.winId())
        print(f"VideoModal: embedding VLC into winId=0x{handle:x} ({sys.platform})")
        if sys.platform.startswith("linux"):
            self._player.set_xwindow(handle)
        elif sys.platform == "win32":
            self._player.set_hwnd(handle)
        elif sys.platform == "darwin":
            self._player.set_nsobject(handle)

    def play(self):
        player = self._ensure_player()
        if player is None:
            return False
        try:
            result = player.play()
            if _real_number(result) == -1:
                return False
            # LibVLC may not have an active audio stream until play() is
            # called. Apply now and retry from the poll once state=Playing.
            self.ensure_audio()
            return True
        except Exception as exc:
            print(f"VideoModal: play() failed: {exc!r}")
            return False

    def pause(self):
        if self._player is not None:
            try:
                # Explicit pause avoids libvlc_media_player_pause()'s toggle
                # semantics getting out of sync with the Qt button state.
                self._player.set_pause(1)
            except Exception:
                try:
                    self._player.pause()
                except Exception:
                    pass

    def set_audio_device(self, device: str) -> None:
        """Rebuild VLC so a new direct ALSA output is used on the next play."""
        if device == self._audio_device:
            return
        self.release()
        self._audio_device = device
        self._audio_attempts = 0
        self._audio_ready = False

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))
        self._audio_ready = False
        if self._player is not None:
            try:
                self._player.audio_set_volume(self._volume)
            except Exception:
                pass

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._audio_ready = False
        if self._player is not None:
            try:
                self._player.audio_set_mute(self._muted)
            except Exception:
                pass

    def ensure_audio(self) -> None:
        """Unmute and restore nominal VLC volume once audio output exists."""
        if self._player is None or self._audio_ready or self._audio_attempts >= 20:
            return
        self._audio_attempts += 1
        try:
            desired_mute = self._muted or self._volume == 0
            self._player.audio_set_mute(desired_mute)
            self._player.audio_set_volume(self._volume)
            muted = _real_number(self._player.audio_get_mute())
            volume = _real_number(self._player.audio_get_volume())
            # Mute can report -1 until the stream is active. Keep retrying in
            # that case; only a confirmed unmuted stream completes setup.
            self._audio_ready = bool(
                volume is not None
                and int(volume) == self._volume
                and muted == float(desired_mute)
            )
            if self._audio_attempts == 20 and not self._audio_ready:
                print(
                    "VideoModal: VLC audio output did not become ready "
                    f"(mute={muted!r}, volume={volume!r})"
                )
        except Exception as exc:
            if self._audio_attempts == 20:
                print(f"VideoModal: unable to enable VLC audio: {exc!r}")

    def stop(self):
        # Unconditional — a paused player is not "playing" but still holds media.
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass

    def position(self):
        """Return ``(elapsed_s, total_s)`` floats, or ``None`` when unknown."""
        if self._player is None:
            return None
        try:
            length = _real_number(self._player.get_length())
            current = _real_number(self._player.get_time())

            if length is None or length <= 0:
                media = self._player.get_media()
                if media is not None:
                    length = _real_number(media.get_duration())

            # Some VLC outputs advance relative position while get_time()
            # remains zero. Use whichever clock has made more progress.
            relative = _real_number(self._player.get_position())
            if length is not None and length > 0 and relative is not None:
                if 0.0 <= relative <= 1.0:
                    relative_time = relative * length
                    current = max(current or 0.0, relative_time)

            if length is not None and length > 0 and current is not None and current >= 0:
                return current / 1000.0, length / 1000.0
        except Exception:
            pass
        return None

    def release(self):
        try:
            self.stop()
            if self._player is not None:
                media = self._player.get_media()
                if media:
                    media.release()
                self._player.release()
            if self._instance is not None:
                self._instance.release()
        except Exception:
            pass
        finally:
            self._player = None
            self._instance = None
