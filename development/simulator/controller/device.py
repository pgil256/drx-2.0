"""Interactive controller emulator coupled to a synthetic mechanism.

The serial vocabulary is shared with the legacy test double. This controller
adds real-time plant/sensor state and explicit preparation/stop behavior. It is
identified as an emulator; native-sketch testing is a separate fidelity level.
"""
import math
from typing import List, Optional, Tuple

from simulator.controller.serial_model import ControllerModel
from simulator.core.plant import Plant


class SimulatedController(ControllerModel):
    """Single-thread-owned deterministic model driven by the session service."""

    def __init__(self, seed: int = 1, profile: Optional[dict] = None) -> None:
        super().__init__()
        self.plant = Plant(seed, profile)
        self.time_s = 1.0
        self._last_command_time = -1.0
        self._last_status_time = -10.0
        self._last_periodic_status = -10.0
        self._boot_until = 0.0
        self._tare_until = 0.0
        self._tare_seq = None
        self._output: List[Tuple[float, str]] = []
        self.reply_delay_ms = 0
        self.events: List[dict] = []
        self.calibrated = False
        self.fault: Optional[str] = None
        self.stop_pressed = False
        self.releasing = False
        self._release_started = 0.0
        self.pressure_guard = False
        self.pressure_target = 0.0
        self.pressure_limit = 0.0
        self._pressure_started = 0.0
        self._pressure_direction = 0
        self._pressure_ceiling = 100.0
        self._pulse_interval = 0.5
        self._pulse_phase = 0.0
        self._pulse_direction = -1
        self._motion_started = 0.0
        self._motion_warning = False
        self._fit_direction = 0
        self._last_host_time = self.time_s
        self._heartbeat_warning = False
        self._factor = self.plant.profile["scale_factor"]
        self._b_zero = 1900
        self.motor_speeds = {"axial_speed": 50, "lateral_speed": 50, "pulse_speed": 50}
        self._sync_sensors()

    def _write(self, data: str) -> None:
        self._output.append((self.time_s + self.reply_delay_ms / 1000.0, data))

    def replies(self) -> List[str]:
        """Take ready serial replies without delaying the model's clock."""
        ready = [text for due, text in self._output if due <= self.time_s]
        self._output = [(due, text) for due, text in self._output if due > self.time_s]
        return ready

    def receive(self, raw: str) -> None:
        """Enqueue one complete wire command, bounding malformed input."""
        raw = raw.strip()
        if not raw or self._boot_until:
            return
        if len(raw) > 256 or len(self._pending_commands) >= 128:
            self._write("ERROR: Command buffer full\n")
            return
        self.commands_received.append(raw)
        self._last_host_time = self.time_s
        self.commands_received[:] = self.commands_received[-2000:]
        self._pending_commands.append(raw)

    def _sync_sensors(self) -> None:
        self.position_a, self.position_b, self.position_c = (
            int(self.plant.sensor[axis]) for axis in "abc"
        )
        ratio = abs(self.plant.profile["scale_factor"] / self._factor)
        self.pressure = self.plant.reported_force * ratio

    def _stop(self) -> None:
        self.plant.velocity = dict.fromkeys("abc", 0.0)
        self.plant.fit_velocity = 0.0
        self.b_running = self.measure_pressure = self.jerking = self.fit_moving = False
        self.pressure_guard = False
        self._active_seq = self._active_fit_seq = None
        self._target_position_a = self._target_position_b = self._target_position_c = None
        self._target_pressure = None
        if self._tare_until:
            self._write("CALIBRATION|TARE|CANCELLED|STOP\n")
            self._tare_until = 0.0
            self.calibrated = False

    def _trip(self, reason: str) -> None:
        if self.fault:
            return
        self.fault = reason
        self.calibrated = False
        self._stop()
        self._write(f"FAULT|{reason}|{self.pressure_target:.2f}|{self.pressure:.2f}\n")

    def set_fault(self, name: str, value: object) -> None:
        """Apply a fixture fault independently of the application's serial link."""
        allowed = {"jam_a", "jam_b", "jam_c", "freeze_a", "freeze_b", "freeze_c",
                   "pressure_stale", "pressure_bias", "tare_failure", "identity_mismatch",
                   "physical_stop", "delay_ms", "corrupt_status"}
        if name not in allowed:
            raise ValueError("Unknown fault: " + name)
        if name in ("pressure_bias", "delay_ms"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Fault value must be numeric")
            if not math.isfinite(value) or not -150 <= value <= 5000:
                raise ValueError("Fault value outside allowed range")
            if name == "delay_ms" and value < 0:
                raise ValueError("Delay cannot be negative")
        elif not isinstance(value, bool):
            raise ValueError("Fault value must be boolean")
        self.events.append({"time": self.time_s, "fault": name, "value": value})
        if name == "physical_stop":
            pressed = bool(value)
            if pressed and not self.stop_pressed:
                active = self.b_running or self.measure_pressure or self.jerking or self.fit_moving
                self._stop()
                if active or self.pressure > 5:
                    self.releasing = True
                    self._release_started = self.time_s
                    self._write("ERROR: Stop button pressed\n")
            self.stop_pressed = pressed
        elif name == "delay_ms":
            self.reply_delay_ms = int(value)
        elif name == "corrupt_status":
            self._corrupt_next = value
        else:
            self.plant.faults[name] = value

    def _reject(self, command: str, reason: str) -> None:
        self._write(f"COMMAND_REJECTED|{command}|{reason}\n")

    def _identity(self) -> None:
        driver = "UNKNOWN" if self.plant.faults.get("identity_mismatch") else "DRX-HX711-NB2"
        self._write(f"FIRMWARE|simulator-v1|{driver}\n")

    def _diagnostics(self) -> None:
        raw = int(self.plant.raw_force * self.plant.profile["scale_factor"])
        offset = int(self.plant.tare_force * self.plant.profile["scale_factor"])
        age = int(self.plant.sensor_age * 1000)
        ready = int(not self.plant.faults.get("pressure_stale"))
        self._write(f"DIAG|HX711|{raw}|{offset}|{self._factor:g}|{self.pressure:.3f}|"
                    f"{age}|10|0|{ready}\n")

    def _reboot(self) -> None:
        self._stop()
        self.fault = None
        self.releasing = False
        self.calibrated = False
        self._pending_commands.clear()
        self._boot_until = self.time_s + 0.3
        self.high_frequency_status = False
        self.status_acknowledged = True

    def _process_command(self, raw: str) -> None:
        command, seq = self._unframe(raw)
        if not command:
            return
        self._current_seq = seq
        kind = command[0]
        moving = kind in "PIKA" or (kind == "J" and command != "JS")
        moving = moving or (kind == "F" and command != "F0")
        if moving and self.fault:
            self._reject(kind, "FAULT_LATCHED")
            return
        if moving and self.stop_pressed and command != "P0":
            self._reject(kind, "STOP_ENGAGED")
            return
        if moving and self._tare_until:
            self._reject(kind, "TARE_BUSY")
            return
        try:
            if kind == "T":
                self._ack("OK", seq)
                self._identity()
                self._diagnostics()
            elif kind == "D":
                self._write(f"DIAG|HARDWARE|1|1|1|{int(self.stop_pressed)}|"
                            f"{int(self.fit_moving)}\n")
                if seq is not None:
                    self._ack("OK", seq)
            elif kind == "X":
                self.releasing = False
                self._stop()
                self._ack("DONE", seq)
            elif kind == "P":
                self._pressure_command(command, seq)
            elif kind in "IKA":
                if self.measure_pressure or self.jerking or self.releasing:
                    self._ack("BUSY", seq)
                    return
                if kind in "IA" and command[1:3] not in ("12", "13", "14"):
                    raise ValueError("Invalid actuator")
                number = float(command[1:] if kind == "K" else command[3:])
                if not math.isfinite(number) or not 0 <= number <= (12 if kind == "A" else 4095):
                    raise ValueError("Invalid movement target")
                super()._process_command(raw)
                self._current_seq = seq
                if self.b_running:
                    self._active_seq = seq
                    self._motion_started = self.time_s
                    self._motion_warning = False
            elif kind == "L":
                self._calibration_command(command, seq)
            elif kind == "J":
                if command == "JS":
                    if self.jerking:
                        self.plant.velocity["a"] = 0
                    self.jerking = False
                    self._ack("DONE", seq)
                elif not self.calibrated:
                    self._reject("J", "TARE_REQUIRED")
                elif not self.pressure_guard or self.pressure_target <= 0:
                    self._reject("J", "PRESSURE_TARGET_REQUIRED")
                elif self.b_running or self.measure_pressure or self.releasing:
                    self._ack("BUSY", seq)
                else:
                    if command[1:].isdigit() and 100 <= int(command[1:]) <= 5000:
                        self._pulse_interval = int(command[1:]) / 1000
                    self.jerking = True
                    self._pulse_phase = self.time_s
                    self._pulse_direction = -1
                    self._ack("DONE", seq)
            elif kind == "F":
                self._fit_command(command, seq)
            elif kind == "V":
                values = [int(value) for value in command[1:].split(",")]
                if len(values) != 3 or any(not 50 <= value <= 100 for value in values):
                    raise ValueError("Invalid V speeds")
                if self.measure_pressure or self.jerking or self.releasing:
                    self._ack("BUSY", seq)
                else:
                    self.motor_speeds = dict(zip(self.motor_speeds, values))
                    if seq is None:
                        self._write("SPEED|" + "|".join(map(str, values)) + "\n")
                    else:
                        self._ack("OK", seq)
            else:
                # Keep the original framing so all inherited acks retain their sequence.
                delay, self._delay_ms = self._delay_ms, 0
                try:
                    super()._process_command(raw)
                finally:
                    self._delay_ms = delay
        except (ValueError, OverflowError, IndexError) as exc:
            if seq is None:
                self._write(f"ERROR: {exc}\n")
            else:
                self._write(f"ERR|{seq}|{exc}\n")

    def _pressure_command(self, command: str, seq: Optional[int]) -> None:
        if not self.calibrated:
            self._reject("P", "TARE_REQUIRED")
            return
        if self.b_running or self.jerking or self.releasing:
            self._ack("BUSY", seq)
            return
        parts = command[1:].split("|")
        target = float(parts[0])
        limit = float(parts[1]) if len(parts) == 2 else target
        if len(parts) > 2 or not 0 <= target <= limit <= 80:
            self._trip("PRESSURE_TARGET_INVALID")
            return
        if self.plant.sensor_age > 0.5:
            self._trip("PRESSURE_SENSOR_TIMEOUT")
            return
        if self.pressure_guard and target == self.pressure_target and limit == self.pressure_limit:
            if not self.measure_pressure:
                self._pressure_done(seq)
            return
        self.pressure_target, self.pressure_limit = target, limit
        self._pressure_ceiling = max(self.pressure, limit) + 10
        self._pressure_direction = 1 if self.pressure < target else -1
        self._target_pressure = target
        self.pressure_guard = self.measure_pressure = True
        self._pressure_started = self.time_s
        self._active_seq = seq
        if target <= self.pressure <= target + 2:
            self._pressure_done(seq)

    def _calibration_command(self, command: str, seq: Optional[int]) -> None:
        stage = command[1:2]
        if stage in ("0", "1", "5") and (self.b_running or self.measure_pressure
                or self.jerking or self.fit_moving or self.pressure_guard or self._tare_until):
            self._reject(command[:2], "MOTION_ACTIVE")
            return
        if stage == "0":
            factor = float(command[2:])
            if not math.isfinite(factor) or not 1 <= abs(factor) <= 100000000:
                self._reject("L0", "INVALID_FACTOR")
                return
            self._factor = factor
            self.calibrated = False
            self._write(f"CALIBRATION|SET|{factor:g}\n")
            self._ack("DONE", seq)
        elif stage == "1":
            self.calibrated = False
            if command != "L1|BASELINE":
                self._write("CALIBRATION|TARE|REJECTED|BASELINE_REQUEST_REQUIRED\n")
                return
            self._write("CALIBRATION|TARE|STARTED\n")
            self._tare_until = self.time_s + 0.8
            self._tare_seq = seq
        elif stage == "5":
            _, a_zero, b_zero = command.split("|")
            a_zero, b_zero = int(a_zero), int(b_zero)
            if not 0 <= a_zero <= 4095 or not 0 <= b_zero <= 4095:
                raise ValueError("Invalid L5 zero marks")
            self._a_zero, self._b_zero = a_zero, b_zero
            self._write(f"ZEROS|{a_zero}|{b_zero}\n")
            self._ack("DONE", seq)
        elif stage == "4":
            self._write(f"weight|{self.pressure:.2f}\n")
            self._diagnostics()
        elif stage == "6":
            self._send_status()

    def _fit_command(self, command: str, seq: Optional[int]) -> None:
        direction = command[1:]
        if direction == "0":
            self.fit_moving = False
            self.plant.fit_velocity = 0
            self._active_fit_seq = None
            self._ack("DONE", seq)
        elif self.fit_moving:
            self._ack("BUSY", seq)
        elif direction in ("+", "-", "F", "R"):
            self.fit_moving = True
            self._fit_end_time = self.time_s + (0.5 if direction in ("+", "-") else 6)
            self._active_fit_seq = seq
            sign = 1 if direction in ("+", "F") else -1
            self._fit_direction = sign
        else:
            raise ValueError("Invalid F direction")

    def _pressure_done(self, seq: Optional[int]) -> None:
        self.measure_pressure = False
        self._target_pressure = None
        self.plant.velocity["a"] = 0
        self._pressure_ceiling = self.pressure_limit + 10
        self._write(f"MOTION_DONE|P|{self.pressure_target:.2f}|{self.pressure:.2f}\n")
        self._ack("DONE", seq)

    def _send_status(self) -> bool:
        if not self.status_acknowledged and self.time_s - self._last_status_time < 2:
            return False
        frame = (f"STATUS_START|S|{self.position_a}|{self.position_b}|{self.position_c}|"
                 f"{self.pressure:.2f}|STATUS_END")
        if self.host_v2:
            checksum = self._xor(frame) ^ (1 if self._corrupt_next else 0)
            frame += f"*{checksum:02X}"
        elif self._corrupt_next:
            frame = "STATUS_START|GARBAGE|STATUS_END"
        self._corrupt_next = False
        self._write(frame + "\n")
        self.status_acknowledged = False
        self._last_status_time = self.time_s
        return True

    def tick(self, dt: float = 0.01) -> None:
        """Advance controller and physical state independently of the renderer."""
        self.time_s += dt
        if self._boot_until:
            self.plant.step(dt)
            self._sync_sensors()
            if self.time_s >= self._boot_until:
                self._boot_until = 0
                self._write("Ready to Go\n")
                self._identity()
                self._diagnostics()
            return
        for raw in list(self._pending_commands):
            if self._is_priority(raw):
                self._pending_commands.remove(raw)
                self._process_command(raw)
        if self._pending_commands and self.time_s - self._last_command_time >= 0.2:
            self._process_command(self._pending_commands.popleft())
            self._last_command_time = self.time_s
        if self._boot_until:
            return
        self._drive_motors(dt)
        self.plant.step(dt)
        self._sync_sensors()
        active = self.b_running or self.measure_pressure or self.jerking or self.fit_moving
        if active and self.time_s - self._last_host_time > 10:
            if not self._heartbeat_warning:
                self._write("WARNING: Host heartbeat lost\n")
                self._heartbeat_warning = True
        else:
            self._heartbeat_warning = False
        if (self.calibrated or self.pressure_guard) and self.pressure > 100:
            self._trip("PRESSURE_LIMIT")
        if self.pressure_guard:
            if self.plant.sensor_age > 0.5:
                self._trip("PRESSURE_SENSOR_TIMEOUT")
            elif self.pressure > self._pressure_ceiling:
                self._trip("PRESSURE_LIMIT")
            elif self.measure_pressure and self.time_s - self._pressure_started > 90:
                self._trip("PRESSURE_MOVE_TIMEOUT")
        if self._tare_until and self.time_s >= self._tare_until:
            self._tare_until = 0
            if self.plant.faults.get("tare_failure") or self.plant.sensor_age > 0.5:
                self._write("CALIBRATION|TARE|REJECTED|SENSOR_TIMEOUT\n")
            else:
                self.plant.tare_force = self.plant.raw_force
                self.calibrated = True
                offset = int(self.plant.tare_force * self.plant.profile["scale_factor"])
                self._write(f"CALIBRATION|TARE|OK|{offset}|{self._factor:g}\n")
                self._ack("DONE", self._tare_seq)
        interval = self.hf_interval if self.high_frequency_status else self.idle_status_interval
        if self.time_s - self._last_periodic_status >= interval:
            self._send_status()
            self._diagnostics()
            self._last_periodic_status = self.time_s

    def _drive_motors(self, dt: float) -> None:
        for axis in "abc":
            target = getattr(self, "_target_position_" + axis)
            if target is None:
                continue
            difference = target - self.plant.sensor[axis]
            speed = self.plant.profile["axis_speed_counts_s"][axis]
            if axis in "ac":
                key = "axial_speed" if axis == "a" else "lateral_speed"
                speed *= self.motor_speeds[key] / 50
            if abs(difference) <= 1:
                self.plant.velocity[axis] = 0
                setattr(self, "_target_position_" + axis, None)
                self.b_running = False
                self._write(f"MOTION_DONE|{self._motion_kind}|{target}|"
                            f"{int(self.plant.sensor[axis])}\n")
                self._ack("DONE", self._active_seq)
                self._active_seq = None
                self._send_status()
            else:
                self.plant.velocity[axis] = math.copysign(min(speed, abs(difference) / dt),
                                                        difference)
                if not self._motion_warning and self.time_s - self._motion_started >= 20:
                    self._write("WARNING: Motor stalled\n")
                    self._motion_warning = True
        if self.releasing:
            released = self.plant.sensor_age < 2 and self.pressure < 5
            if released or self.plant.sensor["a"] <= self._a_zero:
                self.releasing = False
                self.plant.velocity["a"] = 0
                self._write("RELEASED\n" if released else "ERROR: Release incomplete\n")
            elif self.time_s - self._release_started > 15:
                self.releasing = False
                self.plant.velocity["a"] = 0
                self._write("ERROR: Release incomplete\n")
            else:
                self.plant.velocity["a"] = -215
        elif self.measure_pressure:
            diff = self.pressure_target - self.pressure
            reached = ((self._pressure_direction > 0 and diff <= 0)
                       or (self._pressure_direction < 0 and diff >= -2))
            if reached:
                self._pressure_done(self._active_seq)
            else:
                speed = 215 * (self.motor_speeds["axial_speed"] / 50
                               if self.pressure_target > 0 else 1)
                self.plant.velocity["a"] = math.copysign(min(speed, max(4, abs(diff) * 15)), diff)
        elif self.jerking:
            if self.time_s - self._pulse_phase >= self._pulse_interval:
                self._pulse_direction *= -1
                self._pulse_phase = self.time_s
            direction = self._pulse_direction
            if self.pressure >= self.pressure_target and direction > 0:
                direction = 0
            if self.pressure <= max(0, self.pressure_target - 2) and direction < 0:
                direction = 0
            self.plant.velocity["a"] = direction * 80 * self.motor_speeds["pulse_speed"] / 50
        if self.fit_moving and self.time_s >= self._fit_end_time:
            self.fit_moving = False
            self.plant.fit_velocity = 0
            self._ack("DONE", self._active_fit_seq)
            self._active_fit_seq = None
        if self.fit_moving:
            gpio = self.plant.gpio
            allowed = True
            if self.plant.profile.get("fit_drive") == "combined-firmware-and-pi":
                # Synthetic wiring hypothesis: both controllers permit one motor.
                # Record both outputs; do not add their travel together.
                pi_direction = gpio.get(27, 0) - gpio.get(22, 0)
                allowed = gpio.get(17) == 1 and pi_direction == self._fit_direction
            self.plant.fit_velocity = (self._fit_direction
                                      * self.plant.profile["fit_speed_inches_s"] if allowed else 0)

    def snapshot(self) -> dict:
        """Publish physical and reported state without giving the viewer control logic."""
        return {
            "sim_time": round(self.time_s, 4), "backend": "emulated", "pose": self.plant.pose(),
            "sensors": {"a": self.position_a, "b": self.position_b, "c": self.position_c,
                        "pressure_lb": self.pressure, "age_ms": self.plant.sensor_age * 1000},
            "targets": {"a": self._target_position_a, "b": self._target_position_b,
                        "c": self._target_position_c, "pressure_lb": self.pressure_target},
            "pulsing": self.jerking, "stop_pressed": self.stop_pressed,
            "releasing": self.releasing, "fault": self.fault, "calibrated": self.calibrated,
            "faults": dict(self.plant.faults), "gpio": dict(self.plant.gpio),
            "profile": self.plant.profile["id"], "moving": self.b_running or self.measure_pressure,
        }
