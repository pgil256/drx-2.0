# controllers/safety_monitor.py
"""Pi-side safety supervision, extracted from the KneeSpa window.

Consumes device status and firmware notices. Safety notices are advisory:
only the dedicated emergency-stop path is allowed to interrupt operation.
Pure behavior over a window reference so it is testable with a stub window.
"""
from config.constants import (
    AXIAL_MAX,
    PRESSURE_WARNING_MAX,
    HORIZONTAL_MIN,
    HORIZONTAL_MAX,
    LATERAL_MIN,
    LATERAL_MAX,
)


COMMAND_REJECTION_MESSAGES = {
    "A value out of range",
    "Checksum mismatch",
    "Command too long",
    "Invalid A value",
    "Invalid F direction",
    "Invalid I value",
    "Invalid K value",
    "Invalid P value",
    "Invalid device",
    "Malformed frame",
    "Position read failed",
}

# Firmware revisions before advisory WARNING: frames reported these expected
# startup/reset heuristics as ERROR:. Treat both wire formats consistently so
# deploying the Pi-side update does not depend on reflashing the MCU first.
LEGACY_ADVISORY_MESSAGES = {
    "Heartbeat lost",
    "Host heartbeat lost",
    "Motor stalled",
}

# Status telemetry can briefly land a few counts (or a fraction of a pound)
# outside a boundary while the device settles. Confirm small excursions across
# several frames; gross excursions bypass debounce.
LIMIT_CONFIRMATION_SAMPLES = 3
LIMIT_IMMEDIATE_MARGINS = {
    "axial": 100,
    "pressure": 5,
    "horizontal": 75,
    "lateral": 75,
}

# Settle tolerance (encoder counts) around a legal position limit. A commanded
# move to a calibrated endpoint -- e.g. the -20 deg lateral mark, which IS
# LATERAL_MIN -- legitimately settles a few counts past it, and that used to be
# confirmed as a breach after three frames (312 lateral / 211 horizontal false
# warnings in the bench unit's logs). ~0.5 deg horizontal, ~1 deg lateral.
LIMIT_SETTLE_TOLERANCE = 50

# Static fallback envelope per axis, and the calibrated mark table that is the
# real authority when present (it is exactly the range the host can command:
# the degree limits map through these tables).
STATIC_POSITION_BOUNDS = {
    "horizontal": (HORIZONTAL_MIN, HORIZONTAL_MAX),
    "lateral": (LATERAL_MIN, LATERAL_MAX),
}
POSITION_TABLES = {"horizontal": "BMarks", "lateral": "CMarks"}


class SafetyMonitor:
    def __init__(self, window):
        self.window = window
        self._limit_samples = {
            "axial": 0,
            "pressure": 0,
            "horizontal": 0,
            "lateral": 0,
        }
        self._warned_limits = set()

    @staticmethod
    def _table_bounds(table):
        """(min, max) encoder position of a calibrated mark table, or None
        when the table is missing/unusable (fewer than two numeric marks)."""
        try:
            values = [int(v) for v in table.values()]
        except (AttributeError, TypeError, ValueError):
            return None
        if len(values) < 2:
            return None
        return min(values), max(values)

    def _position_bounds(self, name):
        """Legal (lo, hi) encoder band for an axis, widened by the settle
        tolerance. Calibrated tables win over the static constants, which were
        written in an older position convention."""
        lo, hi = STATIC_POSITION_BOUNDS[name]
        config = getattr(self.window, "config", None)
        table = getattr(config, POSITION_TABLES[name], None) if config is not None else None
        bounds = self._table_bounds(table) if table is not None else None
        if bounds is not None:
            lo, hi = bounds
        return lo - LIMIT_SETTLE_TOLERANCE, hi + LIMIT_SETTLE_TOLERANCE

    def _limit_confirmed(
        self,
        name: str,
        breached: bool,
        excursion: float,
    ) -> bool:
        """Confirm a borderline limit across frames; pass gross breaches now."""
        if not breached:
            self._limit_samples[name] = 0
            self._warned_limits.discard(name)
            return False

        if name in self._warned_limits:
            return False

        self._limit_samples[name] += 1
        confirmed = (
            excursion >= LIMIT_IMMEDIATE_MARGINS[name]
            or self._limit_samples[name] >= LIMIT_CONFIRMATION_SAMPLES
        )
        if confirmed:
            self._warned_limits.add(name)
        return confirmed

    def _clear_limit_samples(self) -> None:
        """Forget telemetry debounce counts after presenting a warning."""
        for name in self._limit_samples:
            self._limit_samples[name] = 0

    def _present_warning(self, reason: str) -> None:
        """Show an advisory warning without changing device/protocol state."""
        window = self.window
        window.logger.warning("Device safety warning: %s", reason)
        window.treatment_panel.set_warning(reason)
        window._show_safety_alert(
            f"DEVICE SAFETY WARNING: {reason}",
            warning=True,
        )

    def on_status(self, position_a, position_b, steps, pressure):
        """Handle status updates from Arduino with safety checks."""
        window = self.window
        # Feed the always-visible banner with MEASURED pressure (the rest
        # of the UI shows commanded values)
        window.treatment_panel.update_pressure(pressure)

        if window.initial_setup_complete:
            try:
                confirmed_breaches = []
                if self._limit_confirmed(
                    "axial",
                    position_a > AXIAL_MAX,
                    max(0, position_a - AXIAL_MAX),
                ):
                    confirmed_breaches.append(
                        f"Axial position limit exceeded "
                        f"({position_a} > {AXIAL_MAX})"
                    )

                pressure_breached = pressure > PRESSURE_WARNING_MAX
                if self._limit_confirmed(
                    "pressure",
                    pressure_breached,
                    max(0, pressure - PRESSURE_WARNING_MAX),
                ):
                    confirmed_breaches.append(
                        f"Pressure warning threshold exceeded "
                        f"({pressure} > {PRESSURE_WARNING_MAX} lbs)"
                    )

                # Check horizontal position (B actuator)
                h_lo, h_hi = self._position_bounds("horizontal")
                horizontal_excursion = max(h_lo - position_b, position_b - h_hi, 0)
                if self._limit_confirmed(
                    "horizontal",
                    horizontal_excursion > 0,
                    horizontal_excursion,
                ):
                    confirmed_breaches.append(
                        "Horizontal position limit exceeded "
                        f"({position_b} outside {h_lo}-{h_hi})"
                    )

                # Check lateral position (C actuator)
                l_lo, l_hi = self._position_bounds("lateral")
                lateral_excursion = max(l_lo - steps, steps - l_hi, 0)
                if self._limit_confirmed(
                    "lateral",
                    lateral_excursion > 0,
                    lateral_excursion,
                ):
                    confirmed_breaches.append(
                        "Lateral position limit exceeded "
                        f"({steps} outside {l_lo}-{l_hi})"
                    )

                if confirmed_breaches:
                    self._present_warning("; ".join(confirmed_breaches))
                    self._clear_limit_samples()

            except Exception as e:
                window.logger.exception("Error monitoring system status")
                self._present_warning(
                    f"Error monitoring system status: {str(e)}"
                )

        return True

    def trigger_safety_stop(self, reason):
        """Compatibility entry point: present a warning without stopping."""
        self._present_warning(reason)

    def on_firmware_error(self, message):
        """Handle firmware faults and command rejections.

        Safety notices are advisory and never change protocol/device state.
        Parser/validation errors describe a command the firmware refused and
        retain their separate command-failure handling.
        """
        window = self.window
        print(f"FIRMWARE ERROR: {message}")

        if message == "BUSY":
            # A command was refused because a move is running; transient
            window.logger.warning("Firmware busy: %s", message)
            return

        if message in LEGACY_ADVISORY_MESSAGES:
            self.on_firmware_warning(message)
            return

        if message in COMMAND_REJECTION_MESSAGES:
            stopping = (
                getattr(window, "protocol_stop_requested", False)
                or getattr(window, "protocol_state", "") == "stopping"
            )
            if stopping:
                # Emergency stop deliberately queues X followed by P0 to
                # unload traction. Some deployed firmware revisions can
                # reject that cleanup command as "Invalid P value". The stop
                # is already in progress, so logging is sufficient and avoids
                # a second, false DEVICE SAFETY WARNING popup.
                window.logger.warning(
                    "Ignoring command rejection during intentional stop: %s",
                    message,
                )
                return

            # Outside a stop, a rejected command still matters: halt the
            # treatment state machine, but identify it as a command failure
            # rather than a device safety trip.
            window.stop_actuators()
            if window.protocol_running and window.worker:
                try:
                    window.worker.is_running = False
                except Exception as e:
                    print(f"Error flagging worker stop: {e}")
            fault = f"COMMAND REJECTED: {message}"
            window.treatment_panel.set_fault(fault)
            window.set_protocol_state("fault")
            window._show_timed_error(
                f"The device rejected a command: {message}. Reset before continuing."
            )
            return

        self._present_warning(message)

    def on_firmware_warning(self, message: str) -> None:
        """Handle advisory firmware notices without startup alert noise.

        Homing/reset is already supervised by ``ResetWorker`` with explicit
        completion timeouts. Firmware heartbeat and progress heuristics can
        legitimately fire while that sequence is still establishing the
        device state, so keep those notices in the log and let the reset result
        provide the single operator-facing outcome. Once setup is complete,
        warnings remain visible normally.
        """
        window = self.window
        initializing = (
            not getattr(window, "initial_setup_complete", False)
            or getattr(window, "reset_in_progress", False)
        )
        if initializing and not getattr(window, "protocol_running", False):
            window.logger.warning(
                "Firmware warning during initialization (not shown): %s",
                message,
            )
            return

        self._present_warning(message)

    def on_pressure_released(self):
        """Firmware completed its autonomous post-fault pressure release."""
        print("Firmware reports traction released")
        self.window.logger.info("Firmware reports traction released")

    def on_zeros_echo(self, a_zero, b_zero):
        """Verify the zero marks the firmware applied match the config."""
        window = self.window
        try:
            expected_a = int(
                window.config.AMarks.get("0.0", window.config.AMarks.get("0", 0))
            )
            expected_b = int(
                window.config.BMarks.get("0.0", window.config.BMarks.get("0", 0))
            )
            if (a_zero, b_zero) != (expected_a, expected_b):
                msg = (
                    f"Zero-mark mismatch: firmware applied A={a_zero} B={b_zero}, "
                    f"config has A={expected_a} B={expected_b}"
                )
                print(msg)
                window.logger.error(msg)
                window._show_timed_error(msg)
            else:
                print(f"Zero marks verified: A={a_zero} B={b_zero}")
        except Exception as e:
            print(f"Error verifying zero marks: {e}")

    def on_connection_lost(self):
        """Present connection loss as an advisory warning."""
        window = self.window
        print("Arduino connection lost")
        self._present_warning(
            "CONNECTION LOST. Use the physical emergency stop if motion "
            "must be interrupted."
        )
