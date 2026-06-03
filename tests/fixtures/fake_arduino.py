"""
FakeArduino: A pty-based Arduino simulator for integration testing.

Creates a virtual serial port pair. The Arduino class connects to one end,
and FakeArduino reads/writes the other. Simulates command responses,
gradual position movement, and pressure changes.
"""
import os
import time
import threading
import select
from typing import Optional, List

try:
    import pty
    PTY_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    pty = None
    PTY_AVAILABLE = False


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
        self.high_frequency_status: bool = False

        # Configurable behavior
        self.movement_speed: float = 5000.0  # units per second (fast for tests)
        self.pressure_rate: float = 50.0     # lbs per second (fast for tests)

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

                # Process complete commands (newline-terminated)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    cmd = line.decode(errors="replace").strip()
                    if cmd:
                        self.commands_received.append(cmd)
                        self._process_command(cmd)

                # Simulate gradual movement
                now = time.time()
                dt = now - last_movement_time
                last_movement_time = now
                self._update_movement(dt)
                self._update_pressure(dt)

                # High-frequency status updates
                if self.high_frequency_status and now - last_hf_status_time >= 0.1:
                    self._send_status()
                    last_hf_status_time = now

            except Exception as e:
                if self._running:
                    print(f"FakeArduino error: {e}")
                break

    def _process_command(self, cmd: str):
        """Handle an incoming command string."""
        if self._delay_ms > 0:
            time.sleep(self._delay_ms / 1000.0)

        if len(cmd) == 0:
            return

        cmd_type = cmd[0]

        if cmd_type == 'T':
            self._write("OK\n")

        elif cmd_type == 'Q':
            pass  # Status acknowledgment

        elif cmd_type == 'S':
            self._send_status()

        elif cmd_type == 'H':
            if len(cmd) > 2 and cmd[1:3] == "F1":
                self.high_frequency_status = True
                self._send_status()
                self._write("DONE\n")
            elif len(cmd) > 2 and cmd[1:3] == "F0":
                self.high_frequency_status = False
                self._write("DONE\n")

        elif cmd_type == 'P':
            target = float(cmd[1:]) if len(cmd) > 1 else 0
            self._target_pressure = target
            self.measure_pressure = True
            self._send_status()

        elif cmd_type == 'I':
            actuator_id = cmd[1:3]
            position = int(cmd[3:]) if len(cmd) > 3 else 0
            if actuator_id == "12":
                self._target_position_a = position
            elif actuator_id == "13":
                self._target_position_b = position
            elif actuator_id == "14":
                self._target_position_c = position
            self.b_running = True

        elif cmd_type == 'K':
            position = int(cmd[1:]) if len(cmd) > 1 else 0
            self._target_position_c = position
            self.b_running = True

        elif cmd_type == 'A':
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
            self.b_running = True

        elif cmd_type == 'J':
            if len(cmd) > 1 and cmd[1] == 'S':
                self.jerking = False
            else:
                self.jerking = True

        elif cmd_type == 'X':
            self.b_running = False
            self.measure_pressure = False
            self.jerking = False
            self._target_position_a = None
            self._target_position_b = None
            self._target_position_c = None
            self._target_pressure = None
            self._write("DONE\n")

        elif cmd_type == 'Y':
            self._write("Reset|\n")
            self._write("DONE\n")

        elif cmd_type == 'G':
            actuator_id = cmd[1:3]
            pos = {
                "12": self.position_a,
                "13": self.position_b,
                "14": self.position_c,
            }.get(actuator_id, 0)
            self._write(f"P|{pos}\n")
            self._write("DONE\n")

        elif cmd_type == 'L':
            stage = cmd[1] if len(cmd) > 1 else '0'
            if stage == '4':
                self._write(f"weight|{self.pressure}\n")
            elif stage == '5':
                self._write("DONE\n")
            elif stage == '6':
                self._send_status()
            else:
                self._write("DONE\n")

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
                self._send_status()
            elif current < target:
                setattr(self, attr, current + step)
            else:
                setattr(self, attr, current - step)

    def _update_pressure(self, dt: float):
        """Gradually ramp pressure toward target."""
        if self._target_pressure is None:
            return

        step = self.pressure_rate * dt
        diff = self._target_pressure - self.pressure

        if abs(diff) <= step:
            self.pressure = self._target_pressure
            self._target_pressure = None
            self.measure_pressure = False
            self._send_status()
        elif diff > 0:
            self.pressure += step
        else:
            self.pressure -= step

    def _send_status(self):
        """Send status in the real Arduino format."""
        if self._corrupt_next:
            self._corrupt_next = False
            self._write("STATUS_START|GARBAGE|STATUS_END\n")
            return

        self._write(
            f"STATUS_START|S|{self.position_a}|{self.position_b}"
            f"|{self.position_c}|{self.pressure:.1f}|STATUS_END\n"
        )

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
