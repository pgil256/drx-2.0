"""Physical-touch end-to-end runner for a KneeSpa device.

This tool launches the real application as a child process and drives the
1366x768 touchscreen with operating-system mouse events. It never calls Qt
slots or reaches into the application process, so every action exercises the
same button path as an operator touch.

Examples:
    python tools/e2e_touchscreen.py --setup --yes-move-hardware
    python tools/e2e_touchscreen.py --actuators axial lateral --yes-move-hardware
    python tools/e2e_touchscreen.py --protocols 1 2 3 --yes-move-hardware
    python tools/e2e_touchscreen.py --video
    python tools/e2e_touchscreen.py --all --yes-move-hardware

On Linux/Raspberry Pi, install ``xdotool`` (and optionally ``scrot`` for
screenshots). PyAutoGUI is also supported as a fallback. Windows uses native
mouse events and needs no click dependency.
"""

import argparse
import ctypes
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


BASE_WIDTH = 1366
BASE_HEIGHT = 768
WINDOW_TITLE = "KneeSpa Control Interface"
ALL_ACTUATORS = ("axial", "lateral", "horizontal", "leg-length")

# Coordinates are centers in the fixed device viewport. They are scaled to the
# actual screen/client size at runtime, so the 1360x768 Pi panel works too.
POINTS: Dict[str, Tuple[int, int]] = {
    "home_login": (742, 718),
    "nav_setup": (60, 279),
    "nav_protocols": (60, 391),
    "nav_video": (60, 728),
    "avatar": (1312, 48),
    "profile_exit": (743, 601),
    "protocol_start": (306, 653),
    "panel_stop": (1270, 38),
    "video_play": (683, 360),
    "video_pause": (415, 593),
    "video_next": (469, 593),
    "video_close": (1009, 130),
}

KEYPAD: Dict[str, Tuple[int, int]] = {
    "1": (580, 342),
    "2": (684, 342),
    "3": (787, 342),
    "4": (580, 428),
    "5": (684, 428),
    "6": (787, 428),
    "7": (580, 514),
    "8": (684, 514),
    "9": (787, 514),
    "0": (684, 600),
}

SETUP_ROW_Y: Dict[str, int] = {
    "axial": 217,
    "lateral": 304,
    "horizontal": 391,
    "leg-length": 478,
}

SETUP_X = {"reverse": 381, "forward": 433, "reset": 537, "stop": 936}
PROTOCOL_X = {1: 1010, 2: 1098, 3: 1186}


class E2EError(RuntimeError):
    """A test step could not be completed or verified."""


@dataclass(frozen=True)
class Rect:
    """Screen rectangle in absolute pixels."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


class RunLog:
    """Thread-safe timestamped combined app/action log."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, source: str, message: str) -> None:
        stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        clean = str(message).rstrip("\r\n")
        line = f"[{stamp}] [{source}] {clean}"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        print(line, flush=True)


class OutputMonitor:
    """Capture child output and let steps wait for observable app events."""

    def __init__(self, log: RunLog) -> None:
        self.log = log
        self._condition = threading.Condition()
        self._lines: List[str] = []
        self._closed = False

    def feed(self, line: str) -> None:
        with self._condition:
            self._lines.append(line.rstrip("\r\n"))
            self._condition.notify_all()
        self.log.write("APP", line)

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def mark(self) -> int:
        with self._condition:
            return len(self._lines)

    def wait_for(
        self,
        expected: Sequence[str],
        after: int,
        timeout: float,
        failures: Sequence[str] = (),
    ) -> str:
        """Return the first line containing an expected token after ``after``."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                for line in self._lines[after:]:
                    if any(token in line for token in failures):
                        raise E2EError(f"Application reported failure: {line}")
                    if any(token in line for token in expected):
                        return line
                if self._closed:
                    raise E2EError(
                        "Application exited while waiting for: " + ", ".join(expected)
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise E2EError(
                        f"Timed out after {timeout:.0f}s waiting for: "
                        + ", ".join(expected)
                    )
                self._condition.wait(min(remaining, 0.5))


class ClickDriver:
    """Physical mouse-event backend with optional screenshot support."""

    def __init__(self, backend: str, log: RunLog) -> None:
        self.log = log
        self._pyautogui = None
        if platform.system() == "Windows":
            self._enable_windows_dpi_awareness()
        self.backend = self._select_backend(backend)
        self.width, self.height = self._screen_size()
        self.viewport = Rect(0, 0, self.width, self.height)
        self.log.write(
            "E2E", f"Click backend={self.backend}; screen={self.width}x{self.height}"
        )

    @staticmethod
    def _enable_windows_dpi_awareness() -> None:
        """Keep Win32 mouse/window coordinates in physical pixels.

        Without this, a 150% desktop scale reports a 1366x768 Qt client as
        roughly 910x512 while ``SetCursorPos`` still consumes physical pixels.
        """
        user32 = ctypes.windll.user32
        try:
            # Per-monitor-aware v2 on current Windows releases.
            enabled = user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            if not enabled:
                user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            try:
                user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass

    def _select_backend(self, requested: str) -> str:
        if requested != "auto":
            self._ensure_backend(requested)
            return requested
        if platform.system() == "Windows":
            return "windows"
        if shutil.which("xdotool"):
            return "xdotool"
        try:
            import pyautogui  # type: ignore

            self._pyautogui = pyautogui
            return "pyautogui"
        except (ImportError, KeyError):
            raise E2EError(
                "No physical-click backend found. Install xdotool on the Pi "
                "or PyAutoGUI, then rerun."
            )

    def _ensure_backend(self, backend: str) -> None:
        if backend == "windows" and platform.system() != "Windows":
            raise E2EError("The windows click backend is only available on Windows")
        if backend == "xdotool" and not shutil.which("xdotool"):
            raise E2EError("xdotool was requested but is not installed")
        if backend == "pyautogui":
            try:
                import pyautogui  # type: ignore

                self._pyautogui = pyautogui
            except (ImportError, KeyError) as exc:
                raise E2EError(f"PyAutoGUI is unavailable: {exc}") from exc

    def _screen_size(self) -> Tuple[int, int]:
        if self.backend == "windows":
            user32 = ctypes.windll.user32
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        if self.backend == "xdotool":
            output = subprocess.check_output(
                ["xdotool", "getdisplaygeometry"], text=True
            ).strip()
            width, height = output.split()
            return int(width), int(height)
        size = self._pyautogui.size()
        return int(size.width), int(size.height)

    def set_viewport(self, viewport: Rect) -> None:
        self.viewport = viewport
        self.log.write(
            "E2E",
            "Touch viewport="
            f"{viewport.left},{viewport.top} {viewport.width}x{viewport.height}",
        )

    def scaled(self, point: Tuple[int, int]) -> Tuple[int, int]:
        x, y = point
        actual_x = self.viewport.left + round(x * self.viewport.width / BASE_WIDTH)
        actual_y = self.viewport.top + round(y * self.viewport.height / BASE_HEIGHT)
        return actual_x, actual_y

    def click(
        self, point: Tuple[int, int], label: str, redact_coordinates: bool = False
    ) -> None:
        x, y = self.scaled(point)
        self.click_absolute(x, y, label, redact_coordinates)

    def click_absolute(
        self, x: int, y: int, label: str, redact_coordinates: bool = False
    ) -> None:
        location = "at [redacted]" if redact_coordinates else f"at ({x}, {y})"
        self.log.write("TOUCH", f"{label} {location}")
        if self.backend == "windows":
            user32 = ctypes.windll.user32
            user32.SetCursorPos(int(x), int(y))
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.06)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        elif self.backend == "xdotool":
            subprocess.run(
                ["xdotool", "mousemove", "--sync", str(x), str(y), "click", "1"],
                check=True,
            )
        else:
            self._pyautogui.click(x=x, y=y)

    def active_window_rect(self) -> Optional[Rect]:
        if self.backend == "windows":
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            raw = wintypes.RECT()
            if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(raw)):
                return Rect(
                    raw.left, raw.top, raw.right - raw.left, raw.bottom - raw.top
                )
            return None
        if self.backend == "xdotool":
            try:
                output = subprocess.check_output(
                    ["xdotool", "getactivewindow", "getwindowgeometry", "--shell"],
                    text=True,
                )
                values = dict(re.findall(r"^(X|Y|WIDTH|HEIGHT)=(\d+)$", output, re.M))
                return Rect(
                    int(values["X"]),
                    int(values["Y"]),
                    int(values["WIDTH"]),
                    int(values["HEIGHT"]),
                )
            except (subprocess.SubprocessError, KeyError, ValueError):
                return None
        return None

    def _windows_handles(self, process_id: Optional[int]) -> List[int]:
        """Return visible top-level windows for the launched app process."""
        user32 = ctypes.windll.user32
        matches: List[int] = []
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            if process_id is not None:
                owner_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
                if owner_pid.value != process_id:
                    return True
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if process_id is not None or WINDOW_TITLE in title.value:
                matches.append(hwnd)
            return True

        user32.EnumWindows(callback_type(callback), 0)
        return matches

    def activate_app(self, process_id: Optional[int], dialog: bool = False) -> bool:
        """Bring the launched app (or its modal dialog) above terminals."""
        if self.backend == "windows":
            handles = self._windows_handles(process_id)
            ranked: List[Tuple[int, int]] = []
            user32 = ctypes.windll.user32
            for hwnd in handles:
                raw = wintypes.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(raw)):
                    area = max(0, raw.right - raw.left) * max(0, raw.bottom - raw.top)
                    ranked.append((area, hwnd))
            if not ranked:
                return False
            ranked.sort()
            hwnd = ranked[0][1] if dialog and len(ranked) > 1 else ranked[-1][1]
            self._force_windows_foreground(hwnd)
            time.sleep(0.15)
            return True
        if self.backend == "xdotool":
            search = ["xdotool", "search", "--onlyvisible"]
            if process_id is not None:
                search.extend(["--pid", str(process_id)])
            else:
                search.extend(["--name", WINDOW_TITLE])
            try:
                window_ids = subprocess.check_output(search, text=True).split()
                ranked = []
                for window_id in window_ids:
                    output = subprocess.check_output(
                        ["xdotool", "getwindowgeometry", "--shell", window_id],
                        text=True,
                    )
                    values = dict(re.findall(r"^(WIDTH|HEIGHT)=(\d+)$", output, re.M))
                    ranked.append(
                        (int(values["WIDTH"]) * int(values["HEIGHT"]), window_id)
                    )
                ranked.sort()
                window_id = (
                    ranked[0][1] if dialog and len(ranked) > 1 else ranked[-1][1]
                )
                subprocess.run(
                    ["xdotool", "windowactivate", "--sync", window_id], check=True
                )
                time.sleep(0.15)
                return True
            except (subprocess.SubprocessError, KeyError, ValueError):
                return False
        return True

    @staticmethod
    def _force_windows_foreground(hwnd: int) -> None:
        """Activate a window even when the launching terminal owns focus."""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        foreground = user32.GetForegroundWindow()
        current_thread = kernel32.GetCurrentThreadId()
        foreground_thread = (
            user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        )
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        attached_foreground = False
        attached_target = False
        try:
            if foreground_thread and foreground_thread != current_thread:
                attached_foreground = bool(
                    user32.AttachThreadInput(current_thread, foreground_thread, True)
                )
            if target_thread and target_thread != current_thread:
                attached_target = bool(
                    user32.AttachThreadInput(current_thread, target_thread, True)
                )
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached_target:
                user32.AttachThreadInput(current_thread, target_thread, False)
            if attached_foreground:
                user32.AttachThreadInput(current_thread, foreground_thread, False)

    def find_app_viewport(self, process_id: Optional[int]) -> Optional[Rect]:
        """Find a windowed app client on Windows; fullscreen uses the screen."""
        if self.backend != "windows":
            return None
        handles = self._windows_handles(process_id)
        if not handles:
            return None
        user32 = ctypes.windll.user32
        ranked: List[Tuple[int, int]] = []
        for hwnd in handles:
            raw = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(raw)):
                area = max(0, raw.right - raw.left) * max(0, raw.bottom - raw.top)
                ranked.append((area, hwnd))
        if not ranked:
            return None
        hwnd = max(ranked)[1]
        client = wintypes.RECT()
        origin = wintypes.POINT(0, 0)
        if not user32.GetClientRect(hwnd, ctypes.byref(client)):
            return None
        if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            return None
        return Rect(origin.x, origin.y, client.right, client.bottom)

    def screenshot(self, path: Path) -> bool:
        try:
            if self.backend == "pyautogui":
                self._pyautogui.screenshot(str(path))
                return True
            if self.backend == "windows":
                from PIL import ImageGrab  # type: ignore

                ImageGrab.grab().save(str(path))
                return True
            if shutil.which("scrot"):
                subprocess.run(["scrot", str(path)], check=True)
                return True
        except (ImportError, OSError, subprocess.SubprocessError) as exc:
            self.log.write("E2E", f"Screenshot unavailable: {exc}")
        return False


class E2ERunner:
    """Orchestrate launch, login, physical touches, and event verification."""

    def __init__(self, args: argparse.Namespace, repo: Path, run_dir: Path) -> None:
        self.args = args
        self.repo = repo
        self.run_dir = run_dir
        self.log = RunLog(run_dir / "e2e.log")
        self.monitor = OutputMonitor(self.log)
        self.driver = ClickDriver(args.backend, self.log)
        self.process: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self.current_protocol = False
        self.current_actuator: Optional[str] = None
        self.results: List[Dict[str, str]] = []

    def launch(self) -> None:
        command = parse_app_command(self.args.app_command)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["KNEESPA_SERIAL_TRACE_FILE"] = str(self.run_dir / "serial.log")
        self.log.write("E2E", "Launching: " + " ".join(command))
        self.process = subprocess.Popen(
            command,
            cwd=str(self.repo),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

    def _read_output(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self.monitor.feed(line)
        finally:
            self.monitor.close()

    def wait_for_reset(self, initial: bool = False) -> None:
        if initial and self.args.skip_initial_reset:
            marker = self.monitor.mark()
            self.monitor.wait_for(
                ("KneeSpa launched",),
                after=max(0, marker - 100),
                timeout=self.args.startup_timeout,
            )
            time.sleep(self.args.action_delay)
            return
        marker = 0 if initial else self.monitor.mark()
        self.log.write("E2E", "Waiting for reset sequence to complete")
        self.monitor.wait_for(
            ("Reset sequence finished signal received. Success: True",),
            after=marker,
            timeout=self.args.reset_timeout,
            failures=(
                "Reset sequence finished signal received. Success: False",
                "Reset sequence FAILED",
            ),
        )
        # Acknowledge the visible completion dialog while it is still present.
        # ResetWorker reports before the open-loop leg-length home finishes, so
        # the remaining settle follows the click before any subsequent motion.
        click_delay = min(self.args.action_delay, self.args.reset_settle_seconds)
        time.sleep(click_delay)
        self.click_dialog_button("ok")
        time.sleep(max(0.0, self.args.reset_settle_seconds - click_delay))

    def click_dialog_button(self, kind: str) -> None:
        process_id = self.process.pid if self.process is not None else None
        self.driver.activate_app(process_id, dialog=True)
        rect = self.driver.active_window_rect()
        if rect and rect.width < self.driver.width * 0.85:
            y = rect.bottom - 36
            x = rect.right - (140 if kind == "yes" else 52)
            self.driver.click_absolute(x, y, f"dialog {kind.upper()}")
            return
        fallback = (743, 480) if kind == "yes" else (805, 480)
        self.driver.click(fallback, f"dialog {kind.upper()} (fallback)")

    def login(self) -> None:
        process_id = self.process.pid if self.process is not None else None
        self.driver.activate_app(process_id)
        marker = self.monitor.mark()
        self.driver.click(POINTS["home_login"], "Home Login")
        time.sleep(max(self.args.action_delay, 0.8))
        self.capture("login-modal")
        for index, digit in enumerate(self.args.pin, start=1):
            self.driver.click(
                KEYPAD[digit], f"PIN digit {index}/4", redact_coordinates=True
            )
            time.sleep(0.15)
        self.monitor.wait_for(
            ("Login successful",),
            after=marker,
            timeout=self.args.login_timeout,
            failures=("Login failed", "Too many failed attempts"),
        )
        time.sleep(self.args.action_delay)
        self.record_result("login", "PASS")
        self.capture("logged-in")

    def test_setup(self, actuators: Sequence[str]) -> None:
        process_id = self.process.pid if self.process is not None else None
        self.driver.activate_app(process_id)
        self.driver.click(POINTS["nav_setup"], "Setup navigation")
        time.sleep(self.args.action_delay)
        self.capture("setup-page")
        self.record_result("setup-page", "PASS")
        for actuator in actuators:
            try:
                self.test_actuator(actuator)
                self.record_result(f"actuator-{actuator}", "PASS")
            except Exception as exc:
                self.record_result(f"actuator-{actuator}", "FAIL", str(exc))
                self.safe_stop()
                raise
        self.capture("setup-complete")

    def _setup_point(self, actuator: str, action: str) -> Tuple[int, int]:
        return SETUP_X[action], SETUP_ROW_Y[actuator]

    def _wait_done(self, marker: int, label: str) -> None:
        self.monitor.wait_for(
            ("Setting I2C status to done",),
            after=marker,
            timeout=self.args.motion_timeout,
            failures=("Cannot send", "not sent. Check the Arduino connection"),
        )
        self.log.write("E2E", f"Firmware completed {label}")
        time.sleep(self.args.action_delay)

    def test_actuator(self, actuator: str) -> None:
        self.current_actuator = actuator
        self.log.write("E2E", f"Testing {actuator} actuator")
        if actuator == "leg-length":
            self._test_leg_length()
            self.current_actuator = None
            return
        for action in ("forward", "reverse", "reset"):
            marker = self.monitor.mark()
            self.driver.click(
                self._setup_point(actuator, action), f"{actuator} {action}"
            )
            self._wait_done(marker, f"{actuator} {action}")
        self.current_actuator = None

    def _test_leg_length(self) -> None:
        for direction in ("forward", "reverse"):
            self.driver.click(
                self._setup_point("leg-length", direction),
                f"leg-length {direction}",
            )
            time.sleep(self.args.leg_jog_seconds)
            marker = self.monitor.mark()
            self.driver.click(
                self._setup_point("leg-length", "stop"),
                f"leg-length stop after {direction}",
            )
            self._wait_done(marker, f"leg-length stop after {direction}")
        marker = self.monitor.mark()
        self.driver.click(self._setup_point("leg-length", "reset"), "leg-length reset")
        self._wait_done(marker, "leg-length reset")
        time.sleep(self.args.reset_settle_seconds)

    def test_protocols(self, protocols: Sequence[int]) -> None:
        process_id = self.process.pid if self.process is not None else None
        self.driver.activate_app(process_id)
        self.driver.click(POINTS["nav_protocols"], "Protocols navigation")
        time.sleep(self.args.action_delay)
        for protocol in protocols:
            try:
                self.test_protocol(protocol)
                self.record_result(f"protocol-{protocol}", "PASS")
            except Exception as exc:
                self.record_result(f"protocol-{protocol}", "FAIL", str(exc))
                self.safe_stop()
                raise

    def test_protocol(self, protocol: int) -> None:
        self.log.write("E2E", f"Testing protocol {protocol}")
        self.driver.click((PROTOCOL_X[protocol], 213), f"Select protocol {protocol}")
        time.sleep(self.args.action_delay)
        marker = self.monitor.mark()
        self.driver.click(POINTS["protocol_start"], f"Start protocol {protocol}")
        self.monitor.wait_for(
            ("Toggling protocol start/stop",), after=marker, timeout=10
        )
        time.sleep(0.5)
        self.click_dialog_button("yes")
        self.monitor.wait_for(
            (f"Running protocol {protocol}",),
            after=marker,
            timeout=self.args.motion_timeout,
            failures=(
                "Access denied",
                "DEVICE UNCALIBRATED",
                "Failed to start protocol",
                "Protocol Error",
            ),
        )
        self.current_protocol = True
        self.capture(f"protocol-{protocol}-running")
        self.log.write(
            "E2E",
            f"Observing protocol {protocol} for {self.args.protocol_observe_seconds}s",
        )
        time.sleep(self.args.protocol_observe_seconds)
        stop_marker = self.monitor.mark()
        self.driver.click(POINTS["panel_stop"], f"STOP protocol {protocol}")
        self.monitor.wait_for(("Panel STOP pressed",), after=stop_marker, timeout=10)
        self.current_protocol = False
        self.wait_for_reset(initial=False)
        self.capture(f"protocol-{protocol}-stopped")

    def test_video(self) -> None:
        process_id = self.process.pid if self.process is not None else None
        self.driver.activate_app(process_id)
        self.driver.click(POINTS["nav_video"], "Video navigation")
        time.sleep(self.args.action_delay)
        self.capture("video-open")
        marker = self.monitor.mark()
        self.driver.click(POINTS["video_play"], "Video Play")
        self.monitor.wait_for(
            ("Video play toggled: True",),
            after=marker,
            timeout=self.args.video_timeout,
            failures=("playback position stalled",),
        )
        time.sleep(self.args.video_observe_seconds)
        self.driver.click(POINTS["video_pause"], "Video Pause")
        self.monitor.wait_for(("Video play toggled: False",), after=marker, timeout=10)
        self.driver.click(POINTS["video_next"], "Video Next")
        time.sleep(self.args.action_delay)
        self.driver.click(POINTS["video_play"], "Video Play next clip")
        time.sleep(self.args.video_observe_seconds)
        self.capture("video-playing")
        self.driver.click(POINTS["video_close"], "Video Close")
        time.sleep(self.args.action_delay)
        self.record_result("video", "PASS")

    def safe_stop(self) -> None:
        """Best-effort physical STOP after a failed or interrupted movement."""
        try:
            if self.current_protocol:
                marker = self.monitor.mark()
                self.driver.click(POINTS["panel_stop"], "SAFETY STOP active protocol")
                self.current_protocol = False
                self.monitor.wait_for(("Panel STOP pressed",), marker, 10)
                self.wait_for_reset(initial=False)
            elif self.current_actuator:
                marker = self.monitor.mark()
                self.driver.click(
                    self._setup_point(self.current_actuator, "stop"),
                    f"SAFETY STOP {self.current_actuator}",
                )
                self.current_actuator = None
                self._wait_done(marker, "best-effort actuator stop")
        except Exception as exc:
            self.log.write("E2E", f"Best-effort safety stop failed: {exc}")

    def close_app(self) -> None:
        process_id = self.process.pid if self.process is not None else None
        self.driver.activate_app(process_id)
        self.driver.click(POINTS["avatar"], "Profile avatar")
        time.sleep(self.args.action_delay)
        self.driver.click(POINTS["profile_exit"], "Exit App")
        if self.process is not None:
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                raise E2EError("App did not exit within 15s after Profile > Exit App")

    def capture(self, name: str) -> None:
        if self.args.no_screenshots:
            return
        path = (
            self.run_dir / f"{len(list(self.run_dir.glob('*.png'))) + 1:02d}-{name}.png"
        )
        if self.driver.screenshot(path):
            self.log.write("E2E", f"Screenshot: {path.name}")

    def record_result(self, name: str, status: str, detail: str = "") -> None:
        result = {"name": name, "status": status, "detail": detail}
        self.results.append(result)
        suffix = f": {detail}" if detail else ""
        self.log.write("RESULT", f"{status} {name}{suffix}")

    def write_summary(self, status: str, error: str = "") -> None:
        serial_path = self.run_dir / "serial.log"
        summary = {
            "status": status,
            "error": error,
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "results": self.results,
            "terminal_log": str(self.run_dir / "e2e.log"),
            "serial_log": str(serial_path) if serial_path.exists() else None,
        }
        with (self.run_dir / "summary.json").open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
            handle.write("\n")


def parse_app_command(command: Optional[str]) -> List[str]:
    """Return an unbuffered default launch or split an explicit command."""
    if command:
        return shlex.split(command, posix=platform.system() != "Windows")
    return [sys.executable, "-u", "main/kneespa.py", "--print-logs"]


def expand_selection(args: argparse.Namespace) -> Tuple[List[str], List[int], bool]:
    """Expand --all/--setup into the concrete actuator/protocol/video work."""
    actuators: List[str] = []
    if args.all or args.setup:
        actuators.extend(ALL_ACTUATORS)
    if args.actuators:
        actuators.extend(args.actuators)
    actuators = list(dict.fromkeys(actuators))
    protocols = list(dict.fromkeys([1, 2, 3] if args.all else (args.protocols or [])))
    return actuators, protocols, bool(args.all or args.video)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive KneeSpa E2E through real physical touchscreen clicks"
    )
    tests = parser.add_argument_group("test selection")
    tests.add_argument(
        "--setup",
        action="store_true",
        help="test Setup plus axial, lateral, horizontal, and leg-length actuators",
    )
    tests.add_argument(
        "--actuators",
        nargs="+",
        choices=ALL_ACTUATORS,
        help="test only the selected Setup actuators",
    )
    tests.add_argument(
        "--protocols",
        nargs="+",
        type=int,
        choices=(1, 2, 3),
        help="test selected treatment protocols, stopping each after observation",
    )
    tests.add_argument(
        "--video", action="store_true", help="test video open/play/pause/next"
    )
    tests.add_argument(
        "--all", action="store_true", help="run Setup, protocols 1-3, and video"
    )

    parser.add_argument(
        "--pin", default="1234", help="four-digit login PIN (default: 1234)"
    )
    parser.add_argument(
        "--yes-move-hardware",
        action="store_true",
        help="required for actuator/protocol tests; confirms the machine is clear and attended",
    )
    parser.add_argument(
        "--app-command", help="override app launch command (quoted as one argument)"
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "windows", "xdotool", "pyautogui"),
        default="auto",
        help="physical click backend (default: auto)",
    )
    parser.add_argument(
        "--output-dir", default="logs/e2e", help="parent directory for run logs"
    )
    parser.add_argument(
        "--skip-initial-reset",
        action="store_true",
        help="dev-only: do not await reset dialog",
    )
    parser.add_argument(
        "--no-screenshots", action="store_true", help="do not capture step screenshots"
    )
    parser.add_argument("--startup-timeout", type=float, default=45)
    parser.add_argument("--reset-timeout", type=float, default=240)
    parser.add_argument("--reset-settle-seconds", type=float, default=7)
    parser.add_argument("--login-timeout", type=float, default=15)
    parser.add_argument("--motion-timeout", type=float, default=90)
    parser.add_argument("--protocol-observe-seconds", type=float, default=20)
    parser.add_argument("--video-observe-seconds", type=float, default=4)
    parser.add_argument("--video-timeout", type=float, default=20)
    parser.add_argument("--leg-jog-seconds", type=float, default=1.0)
    parser.add_argument("--action-delay", type=float, default=0.8)
    return parser


def validate_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    actuators: Sequence[str],
    protocols: Sequence[int],
    video: bool,
) -> None:
    if not actuators and not protocols and not video:
        parser.error(
            "select at least one of --setup, --actuators, --protocols, --video, or --all"
        )
    if not re.fullmatch(r"\d{4}", args.pin):
        parser.error("--pin must contain exactly four digits")
    if (actuators or protocols) and not args.yes_move_hardware:
        parser.error(
            "actuator/protocol tests move real hardware; clear the machine, remain at the "
            "physical STOP, and pass --yes-move-hardware"
        )
    positive = (
        "startup_timeout",
        "reset_timeout",
        "reset_settle_seconds",
        "login_timeout",
        "motion_timeout",
        "protocol_observe_seconds",
        "video_observe_seconds",
        "video_timeout",
        "leg_jog_seconds",
        "action_delay",
    )
    for name in positive:
        if getattr(args, name) < 0:
            parser.error(f"--{name.replace('_', '-')} cannot be negative")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    actuators, protocols, video = expand_selection(args)
    validate_args(parser, args, actuators, protocols, video)

    repo = Path(__file__).resolve().parents[1]
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    output_parent = Path(args.output_dir)
    if not output_parent.is_absolute():
        output_parent = repo / output_parent
    run_dir = output_parent / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)

    runner: Optional[E2ERunner] = None
    try:
        runner = E2ERunner(args, repo, run_dir)
        runner.log.write(
            "SAFETY",
            "No patient may be in the device. Keep an operator at the physical STOP.",
        )
        runner.launch()
        runner.wait_for_reset(initial=True)
        process_id = runner.process.pid if runner.process is not None else None
        runner.driver.activate_app(process_id)
        viewport = runner.driver.find_app_viewport(process_id)
        if viewport and viewport.width > 0 and viewport.height > 0:
            runner.driver.set_viewport(viewport)
        runner.login()
        if actuators:
            runner.test_setup(actuators)
        if protocols:
            runner.test_protocols(protocols)
        if video:
            runner.test_video()
        runner.close_app()
        runner.write_summary("PASS")
        runner.log.write("RESULT", f"PASS complete; artifacts: {run_dir}")
        return 0
    except KeyboardInterrupt:
        error = "Interrupted by operator"
        if runner:
            runner.log.write("RESULT", f"FAIL {error}")
            runner.safe_stop()
            runner.write_summary("FAIL", error)
        return 130
    except Exception as exc:
        error = str(exc)
        if runner:
            runner.log.write("RESULT", f"FAIL {error}")
            runner.safe_stop()
            runner.write_summary("FAIL", error)
        else:
            print(f"E2E setup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
