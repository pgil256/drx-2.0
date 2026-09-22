"""POSIX virtual-serial adapter for the shared controller test model."""
import os
import select
import threading
import time

from simulator.controller.serial_model import (
    ControllerModel, MAX_PRESSURE_LBS, PRESSURE_WARNING_LBS,
)

try:
    import pty
    import tty
    PTY_AVAILABLE = True
except ImportError:
    pty = None
    PTY_AVAILABLE = False


class FakeArduino(ControllerModel):
    """Connect the shared controller model to a POSIX pseudo-terminal."""

    @property
    def port(self) -> str:
        """The virtual serial port path for the Arduino class to connect to."""
        return self._slave_path


    def start(self):
        """Create pty pair and start command processing thread."""
        if not PTY_AVAILABLE:
            raise RuntimeError("FakeArduino requires POSIX pty/termios support")
        self._master_fd, self._slave_fd = pty.openpty()
        # Configure the serial endpoint before the worker can write replies.
        # Changing terminal modes while reading can flush queued response bytes.
        tty.setraw(self._slave_fd)
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


    def _write(self, data: str):
        """Write data to the master side of the pty."""
        if self._master_fd is not None and not self._disconnected:
            try:
                os.write(self._master_fd, data.encode())
            except OSError:
                pass


    def simulate_disconnect(self):
        """Close the pty to simulate a serial disconnect."""
        self._disconnected = True
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
