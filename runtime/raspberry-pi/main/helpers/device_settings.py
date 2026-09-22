"""Read and adjust the Pi's system audio and supported backlight controls."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple


class DeviceSettings:
    """Use existing OS interfaces without sudo or shell command construction."""

    def __init__(self, backlights: Path = Path("/sys/class/backlight")) -> None:
        self.backlights = backlights
        self._audio = None
        self._backlight = None

    @staticmethod
    def _run(args: List[str]) -> str:
        return subprocess.run(
            args, check=True, capture_output=True, text=True, timeout=3,
        ).stdout

    @staticmethod
    def _percent(text: str) -> int:
        values = re.findall(r"(\d+)%", text)
        if not values:
            raise ValueError("The audio device did not report a volume.")
        return min(100, max(0, round(sum(map(int, values)) / len(values))))

    def read(self, key: str) -> Tuple[Optional[int], str]:
        """Return the real setting, or explain why it cannot be controlled."""
        if key not in ("volume", "brightness"):
            raise ValueError("Unknown device setting.")
        if sys.platform != "linux":
            return None, "Available on the Raspberry Pi with supported hardware."
        if key == "volume":
            # PulseAudio owns system audio on desktop images. ALSA is the
            # fallback on images without a running PulseAudio server.
            candidates = []
            if shutil.which("pactl"):
                candidates.append(("pactl",))
            if shutil.which("amixer"):
                candidates.extend(("amixer", name) for name in ("Master", "PCM", "Speaker"))
            for candidate in candidates:
                try:
                    value = self._read_audio(candidate)
                    self._audio = candidate
                    return value, "Adjusts the system's default audio output."
                except (OSError, ValueError, subprocess.SubprocessError):
                    continue
            self._audio = None
            return None, "No controllable audio output found. Check the system audio configuration."
        self._backlight = None
        for path in sorted(self.backlights.glob("*")):
            maximum = int((path / "max_brightness").read_text().strip())
            if maximum <= 0:
                continue
            brightness = path / "brightness"
            if not os.access(brightness, os.W_OK) and not shutil.which("brightnessctl"):
                continue
            self._backlight = path
            value = round(int(brightness.read_text().strip()) * 100 / maximum)
            return value, "Minimum 10% keeps the display visible."
        return None, (
            "No adjustable backlight found. Use the display's physical brightness controls."
        )

    def _read_audio(self, audio: tuple) -> int:
        if audio[0] == "pactl":
            text = self._run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
            muted = "yes" in self._run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]).lower()
        else:
            text = self._run(["amixer", "sget", audio[1]])
            muted = "[off]" in text and "[on]" not in text
        return 0 if muted else self._percent(text)

    def write(self, key: str, value: int) -> Tuple[Optional[int], str]:
        """Apply a validated setting, then read it back before reporting success."""
        if key not in ("volume", "brightness") or type(value) is not int:
            raise ValueError("Invalid device setting.")
        if not (10 if key == "brightness" else 0) <= value <= 100:
            raise ValueError("Device setting is outside its allowed range.")
        if sys.platform != "linux":
            raise ValueError("System controls are available on the Raspberry Pi.")
        if key == "volume":
            if self._audio is None:
                raise ValueError("Refresh device settings to find an audio output.")
            if self._audio[0] == "pactl":
                self._run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"])
                self._run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
            else:
                self._run(["amixer", "sset", self._audio[1], f"{value}%", "unmute"])
            return self._read_audio(self._audio), "System volume updated."
        if self._backlight is None:
            raise ValueError("Refresh device settings to find a supported backlight.")
        path = self._backlight
        maximum = int((path / "max_brightness").read_text().strip())
        if maximum <= 0:
            raise ValueError("The display reported an invalid brightness range.")
        if os.access(path / "brightness", os.W_OK):
            (path / "brightness").write_text(str(max(1, round(value * maximum / 100))))
        else:
            self._run(["brightnessctl", "--device", path.name, "set", f"{value}%"])
        actual = round(int((path / "brightness").read_text().strip()) * 100 / maximum)
        return actual, "Brightness updated."
