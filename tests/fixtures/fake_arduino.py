"""
FakeArduino: A pty-based Arduino simulator for integration testing.

Creates a virtual serial port pair. The Arduino class connects to one end,
and FakeArduino reads/writes the other. Simulates command responses,
gradual position movement, and pressure changes.

Behavior mirrors main/motor/motor.ino:
- Completed position moves and pressure ramps emit "DONE".
- Commands are processed at most once per MIN_COMMAND_INTERVAL (200 ms);
  'Q' acks and 'X' (emergency stop) bypass the limiter.
- After each status frame, further frames are suppressed until the host
  acknowledges with 'Q' or STATUS_TIMEOUT (2 s) elapses.
- High-frequency status runs at 1 Hz (HIGH_FREQ_INTERVAL), idle status
  every 5 s (LOOP_STATUS_DELAY); status keeps flowing during pulsing.
- 'Y' replies "Reset|", reboots (state reset + boot delay), then announces
  "Ready to Go" -- it never replies DONE.
- P/I/K/A reply "BUSY" while a move is running (bRunning).
- FIT commands remain active until their timer ends, emit DONE on physical
  completion, and reply BUSY to conflicting FIT commands.
- L5 zero marks accept the delimited form (L5|a|b) and echo "ZEROS|a|b".
- Pressure above 80 lbs during a ramp emits
  "ERROR: Pressure limit exceeded" and stops everything.
- Protocol v2 frames ("#<seq>:<CMD>*<XX>") are verified and acked with
  the sequence echoed (DONE|<seq>, BUSY|<seq>, OK|<seq>, ERR|<seq>|...);
  status frames then carry a trailing "*<XX>" checksum.
Timing constants are attributes so individual tests may tighten them.
"""
import os
import time
import threading
import select
from collections import deque
from typing import Optional, List

try:
    import pty
    PTY_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    pty = None
    PTY_AVAILABLE = False

MAX_PRESSURE_LBS = 80.0


class FakeArduino:
    """Simulates Arduino firmware behavior over a virtual serial port."""

    def __init__(self):
        # State mirrors real Arduino globals
        self.position_a: int = 0
        self.position_b: int = 0
        self.position_c: int = 1200  # center
        self.pressure: float = 0.0
        self.jerking: bool = False
        self.b_running: bool = False
        self.measure_pressure: bool = False
        self.fit_moving: bool = False
        self.high_frequency_status: bool = False
        self.status_acknowledged: bool = True
        self.host_v2: bool = False
        self._current_seq = None  # seq of command being processed
        self._active_seq = None   # seq of motion/pressure command in flight
        self._active_fit_seq = None
        self._fit_end_time = 0.0

        # Configurable behavior (defaults mirror motor.ino timing)
        self.movement_speed: float = 5000.0  # units per second (fast for tests)
        self.pressure_rate: float = 50.0     # lbs per second (fast for tests)
        self.hf_interval: float = 1.0        # HIGH_FREQ_INTERVAL (1000 ms)
        self.idle_status_interval: float = 5.0  # LOOP_STATUS_DELAY (5000 ms)
        self.min_command_interval: float = 0.2  # MIN_COMMAND_INTERVAL (200 ms)
        self.status_timeout: float = 2.0     # STATUS_TIMEOUT (2000 ms)
        self.boot_delay: float = 0.3         # 'Y' reset boot time

        # Fault injection state
        self._stalled_actuator: Optional[str] = None
        self._delay_ms: int = 0
        self._corrupt_next: bool = False
        self._disconnected: bool = False

        # Internal state
        self._master_fd: Optional[int] = None
        self._slave_fd: Optional[int] = None
        self._slave_path: Optional[str] = None
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._pending_commands = deque()
        self._last_command_time: float = 0.0
        self._last_status_time: float = 0.0

        # Movement targets
        self._target_position_a: Optional[int] = None
        self._target_position_b: Optional[int] = None
        self._target_position_c: Optional[int] = None
        self._target_pressure: Optional[float] = None

        # Track commands received (for assertions)
        self.commands_received: List[str] = []

    @property
    def port(self) -> str:
        """The virtual serial port path for the Arduino class to connect to."""
        return self._slave_path

    def start(self):
        """Create pty pair and start command processing thread."""
        if not PTY_AVAILABLE:
            raise RuntimeError("FakeArduino requires POSIX pty/termios support")
        self._master_fd, self._slave_fd = pty.openpty()
        self._slave_path = os.ttyname(self._slave_fd)
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop processing and close pty."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._slave_fd is not None:
            try:
                os.close(self._slave_fd)
            except OSError:
                pass
            self._slave_fd = None

    def _run_loop(self):
        """Main loop: read commands, update state, send responses."""
        buffer = b""
        last_movement_time = time.time()
        last_hf_status_time = time.time()
        last_idle_status_time = time.time()

        while self._running and self._master_fd is not None:
            try:
                # Check for incoming data
                ready, _, _ = select.select([self._master_fd], [], [], 0.01)
                if ready:
                    try:
                        data = os.read(self._master_fd, 1024)
                        if data:
                            buffer += data
                    except OSError:
                        break

                # Queue complete commands (newline-terminated)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    cmd = line.decode(errors="replace").strip()
                    if cmd:
                        self.commands_received.append(cmd)
                        self._pending_commands.append(cmd)

                # Process at most one command per MIN_COMMAND_INTERVAL,
                # like the firmware's rate limiter. 'Q' acks and 'X'
                # (emergency stop) bypass the limiter, as on the device.
                now = time.time()
                while self._pending_commands and self._is_priority(
                    self._pending_commands[0]
                ):
                    self._process_command(self._pending_commands.popleft())
                if self._pending_commands and (
                    now - self._last_command_time >= self.min_command_interval
                ):
                    self._last_command_time = now
                    self._process_command(self._pending_commands.popleft())

                # Simulate gradual movement
                now = time.time()
                dt = now - last_movement_time
                last_movement_time = now
                self._update_movement(dt)
                self._update_pressure(dt)
                self._update_fit(now)

                # High-frequency status updates
                if self.high_frequency_status:
                    if now - last_hf_status_time >= self.hf_interval:
                        if self._send_status():
                            last_hf_status_time = now
                # Idle status (firmware LOOP_STATUS_DELAY path)
                elif not self.b_running and not self.measure_pressure and not self.fit_moving:
                    if now - last_idle_status_time >= self.idle_status_interval:
                        if self._send_status():
                            last_idle_status_time = now

            except Exception as e:
                if self._running:
                    print(f"FakeArduino error: {e}")
                break

    def _reboot(self):
        """Mirror firmware resetFunc(): drop all activity, re-init state."""
        self.b_running = False
        self.measure_pressure = False
        self.fit_moving = False
        self.jerking = False
        self.status_acknowledged = True
        self.high_frequency_status = False
        self.host_v2 = False
        self._current_seq = None
        self._active_seq = None
        self._active_fit_seq = None
        self._fit_end_time = 0.0
        self._target_position_a = None
        self._target_position_b = None
        self._target_position_c = None
        self._target_pressure = None
        self._pending_commands.clear()
        time.sleep(self.boot_delay)
        self._write("\n")
        self._write("Ready to Go\n")

    @staticmethod
    def _xor(payload: str) -> int:
        value = 0
        for byte in payload.encode():
            value ^= byte
        return value

    def _ack(self, token: str, seq=None):
        if seq is not None:
            self._write(f"{token}|{seq}\n")
        else:
            self._write(f"{token}\n")

    @staticmethod
    def _is_priority(raw: str) -> bool:
        """Q acks and X (framed or not) bypass the rate limiter."""
        if not raw:
            return False
        if raw[0] in ("Q", "X"):
            return True
        if raw[0] == "#":
            inner = raw.partition(":")[2]
            return inner[:1] in ("Q", "X")
        return False

    def _unframe(self, raw: str):
        """Return (inner_cmd, seq); (None, None) after a checksum reject."""
        if not raw.startswith("#"):
            return raw, None
        self.host_v2 = True
        try:
            body, star, checksum_hex = raw[1:].rpartition("*")
            if not star:
                raise ValueError("no checksum")
            seq_str, _, inner = body.partition(":")
            seq = int(seq_str)
            if int(checksum_hex, 16) != self._xor(body):
                self._write(f"ERR|{seq}|Checksum mismatch\n")
                return None, None
            return inner, seq
        except (ValueError, TypeError):
            self._write("ERROR: Malformed frame\n")
            return None, None

    def _process_command(self, raw: str):
        """Handle an incoming command string."""
        if self._delay_ms > 0:
            time.sleep(self._delay_ms / 1000.0)

        cmd, seq = self._unframe(raw)
        if cmd is None or len(cmd) == 0:
            return
        self._current_seq = seq

        cmd_type = cmd[0]

        if cmd_type == 'T':
            self._ack("OK", self._current_seq)

        elif cmd_type == 'Q':
            self.status_acknowledged = True

        elif cmd_type == 'S':
            self._send_status()

        elif cmd_type == 'H':
            if len(cmd) > 2 and cmd[1:3] == "F1":
                self.high_frequency_status = True
                self.status_acknowledged = True  # firmware resets the flag
                self._send_status()
                self._ack("DONE", self._current_seq)
            elif len(cmd) > 2 and cmd[1:3] == "F0":
                self.high_frequency_status = False
                self._ack("DONE", self._current_seq)

        elif cmd_type == 'P':
            if self.b_running:
                self._ack("BUSY", self._current_seq)
                return
            target = float(cmd[1:]) if len(cmd) > 1 else 0
            self._target_pressure = target
            self.measure_pressure = True
            self._active_seq = self._current_seq
            self._send_status()

        elif cmd_type == 'I':
            if self.b_running:
                self._ack("BUSY", self._current_seq)
                return
            actuator_id = cmd[1:3]
            position = int(cmd[3:]) if len(cmd) > 3 else 0
            if actuator_id == "12":
                self._target_position_a = position
            elif actuator_id == "13":
                self._target_position_b = position
            elif actuator_id == "14":
                self._target_position_c = position
            self._active_seq = self._current_seq
            self.b_running = True

        elif cmd_type == 'K':
            if self.b_running:
                self._ack("BUSY", self._current_seq)
                return
            position = int(cmd[1:]) if len(cmd) > 1 else 0
            self._target_position_c = position
            self._active_seq = self._current_seq
            self.b_running = True

        elif cmd_type == 'A':
            if self.b_running:
                self._ack("BUSY", self._current_seq)
                return
            actuator_id = cmd[1:3]
            inches = float(cmd[3:]) if len(cmd) > 3 else 0
            fullinch = {"12": 430, "13": 620, "14": 1880}.get(actuator_id, 430)
            position = int(fullinch * inches)
            if actuator_id == "12":
                self._target_position_a = position
            elif actuator_id == "13":
                self._target_position_b = position
            elif actuator_id == "14":
                self._target_position_c = position
            self._active_seq = self._current_seq
            self.b_running = True

        elif cmd_type == 'J':
            # Status keeps flowing during pulsing (the firmware's old
            # noStatus suppression blinded the pressure ceiling check)
            if len(cmd) > 1 and cmd[1] == 'S':
                self.jerking = False
                self._ack("DONE", self._current_seq)
            else:
                self.jerking = True
                self._ack("DONE", self._current_seq)

        elif cmd_type == 'F':
            direction = cmd[1:2]
            if direction == "0":
                self.fit_moving = False
                self._fit_end_time = 0.0
                self._active_fit_seq = None
                self._ack("DONE", self._current_seq)
            elif self.fit_moving:
                self._ack("BUSY", self._current_seq)
            elif direction in ("+", "-", "F", "R"):
                self.fit_moving = True
                self._active_fit_seq = self._current_seq
                # Shortened for tests while preserving slow/fast ordering.
                self._fit_end_time = time.time() + (
                    0.05 if direction in ("+", "-") else 0.2
                )
            else:
                if self._current_seq is not None:
                    self._write(f"ERR|{self._current_seq}|Invalid F direction\n")
                else:
                    self._write("ERROR: Invalid F direction\n")

        elif cmd_type == 'X':
            self.b_running = False
            self.measure_pressure = False
            self.jerking = False
            self.fit_moving = False
            self._fit_end_time = 0.0
            self._active_fit_seq = None
            self._target_position_a = None
            self._target_position_b = None
            self._target_position_c = None
            self._target_pressure = None
            self._active_seq = None
            self._ack("DONE", self._current_seq)

        elif cmd_type == 'Y':
            self._write("Reset|\n")
            self._reboot()  # no DONE: firmware resets before it could reply

        elif cmd_type == 'G':
            actuator_id = cmd[1:3]
            pos = {
                "12": self.position_a,
                "13": self.position_b,
                "14": self.position_c,
            }.get(actuator_id, 0)
            self._write(f"P|{pos}\n")
            self._ack("DONE", self._current_seq)

        elif cmd_type == 'L':
            stage = cmd[1] if len(cmd) > 1 else '0'
            if stage == '4':
                self._write(f"weight|{self.pressure}\n")
            elif stage == '5':
                if len(cmd) > 2 and cmd[2] == '|':
                    parts = cmd.split('|')
                    a_zero = int(parts[1]) if len(parts) > 1 else 0
                    b_zero = int(parts[2]) if len(parts) > 2 else 0
                else:
                    # Legacy fixed-width parse (truncates 4-digit values)
                    a_zero = int(cmd[2:5]) if cmd[2:5].strip() else 0
                    b_zero = int(cmd[5:9]) if cmd[5:9].strip() else 0
                self._write(f"ZEROS|{a_zero}|{b_zero}\n")
                self._ack("DONE", self._current_seq)
            elif stage == '6':
                self._write(
                    f"A|{self.position_a}|{self.position_b}"
                    f"|{self.position_c}|{self.pressure:.1f}\n"
                )
            else:
                self._ack("DONE", self._current_seq)

    def _update_movement(self, dt: float):
        """Gradually move actuators toward their targets."""
        step = int(self.movement_speed * dt)
        if step < 1:
            step = 1

        for attr, target_attr in [
            ("position_a", "_target_position_a"),
            ("position_b", "_target_position_b"),
            ("position_c", "_target_position_c"),
        ]:
            target = getattr(self, target_attr)
            if target is None:
                continue

            # Check stall
            actuator_letter = attr[-1]
            if self._stalled_actuator == actuator_letter:
                continue

            current = getattr(self, attr)
            if abs(current - target) <= step:
                setattr(self, attr, target)
                setattr(self, target_attr, None)
                if not any([
                    self._target_position_a,
                    self._target_position_b,
                    self._target_position_c,
                ]):
                    self.b_running = False
                # Firmware: sendStatus() then "DONE" on completion
                self._send_status()
                self._ack("DONE", self._active_seq)
                self._active_seq = None
            elif current < target:
                setattr(self, attr, current + step)
            else:
                setattr(self, attr, current - step)

    def _update_pressure(self, dt: float):
        """Gradually ramp pressure toward target."""
        if self._target_pressure is None:
            return

        # Firmware safety: over-limit during a ramp -> ERROR + stop
        if self.measure_pressure and self.pressure > MAX_PRESSURE_LBS:
            self._write("ERROR: Pressure limit exceeded\n")
            self.b_running = False
            self.measure_pressure = False
            self.jerking = False
            self._target_pressure = None
            return

        step = self.pressure_rate * dt
        diff = self._target_pressure - self.pressure

        if abs(diff) <= step:
            self.pressure = self._target_pressure
            self._target_pressure = None
            self.measure_pressure = False
            # Firmware: sendStatus() then "DONE" when pressure reached
            self._send_status()
            self._ack("DONE", self._active_seq)
            self._active_seq = None
        elif diff > 0:
            self.pressure += step
        else:
            self.pressure -= step

    def _update_fit(self, now: float):
        if not self.fit_moving or now < self._fit_end_time:
            return
        self.fit_moving = False
        self._fit_end_time = 0.0
        self._ack("DONE", self._active_fit_seq)
        self._active_fit_seq = None

    def _send_status(self) -> bool:
        """Send status in the real Arduino format.

        Returns False (suppressed) while the previous status is
        unacknowledged and STATUS_TIMEOUT has not passed,
        mirroring the firmware's sendStatus() gate.
        """
        now = time.time()
        if not self.status_acknowledged and (
            now - self._last_status_time < self.status_timeout
        ):
            return False

        if self._corrupt_next:
            self._corrupt_next = False
            self._write("STATUS_START|GARBAGE|STATUS_END\n")
        else:
            frame = (
                f"STATUS_START|S|{self.position_a}|{self.position_b}"
                f"|{self.position_c}|{self.pressure:.1f}|STATUS_END"
            )
            if self.host_v2:
                frame += f"*{self._xor(frame):02X}"
            self._write(frame + "\n")
        self.status_acknowledged = False
        self._last_status_time = now
        return True

    def _write(self, data: str):
        """Write data to the master side of the pty."""
        if self._master_fd is not None and not self._disconnected:
            try:
                os.write(self._master_fd, data.encode())
            except OSError:
                pass

    # --- Fault injection methods ---

    def simulate_disconnect(self):
        """Close the pty to simulate a serial disconnect."""
        self._disconnected = True
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

    def simulate_stall(self, actuator: str):
        """Stop position updates for an actuator ('a', 'b', or 'c')."""
        self._stalled_actuator = actuator

    def clear_stall(self):
        """Resume normal movement."""
        self._stalled_actuator = None

    def simulate_pressure_overshoot(self, amount: float):
        """Add overshoot to current pressure."""
        self.pressure += amount

    def delay_responses(self, ms: int):
        """Add artificial delay before responding to commands."""
        self._delay_ms = ms

    def corrupt_status(self):
        """Make the next status response malformed."""
        self._corrupt_next = True

    def wait_for_command(self, prefix: str, timeout: float = 5.0) -> bool:
        """Wait until a command starting with `prefix` has been received."""
        start = time.time()
        while time.time() - start < timeout:
            if any(c.startswith(prefix) for c in self.commands_received):
                return True
            time.sleep(0.05)
        return False

    def get_last_command(self, prefix: str) -> Optional[str]:
        """Get the most recent command starting with prefix."""
        for cmd in reversed(self.commands_received):
            if cmd.startswith(prefix):
                return cmd
        return None

    def clear_commands(self):
        """Clear the command history."""
        self.commands_received.clear()
