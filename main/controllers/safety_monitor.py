# controllers/safety_monitor.py
"""Pi-side safety supervision, extracted from the KneeSpa window.

Consumes device status and firmware fault messages; owns the decision
to stop, alert, and reset. Pure behavior over a window reference so it
is testable with a stub window.
"""
from config.constants import (
    AXIAL_MAX,
    PRESSURE_MAX,
    HORIZONTAL_MIN,
    HORIZONTAL_MAX,
    LATERAL_MIN,
    LATERAL_MAX,
)


class SafetyMonitor:
    def __init__(self, window):
        self.window = window

    def on_status(self, position_a, position_b, steps, pressure):
        """Handle status updates from Arduino with safety checks."""
        window = self.window
        success = True  # Track if processing was successful

        # Feed the always-visible banner with MEASURED pressure (the rest
        # of the UI shows commanded values)
        window.treatment_panel.update_pressure(pressure)

        if window.initial_setup_complete:
            try:
                # Check various safety conditions
                if position_a > AXIAL_MAX or (
                    window.initial_setup_complete and pressure > PRESSURE_MAX
                ):
                    self.trigger_safety_stop("Axial/pressure limit exceeded")
                    success = False

                # Check horizontal position (B actuator)
                if position_b < HORIZONTAL_MIN or position_b > HORIZONTAL_MAX:
                    self.trigger_safety_stop("Horizontal position limit exceeded")
                    success = False

                # Check lateral position (C actuator)
                if steps < LATERAL_MIN or steps > LATERAL_MAX:
                    self.trigger_safety_stop("Lateral position limit exceeded")
                    success = False

            except Exception as e:
                print(f"Error in status monitoring: {str(e)}")
                window.stop_actuators()
                window.initial_setup_complete = False
                window.reset_arduino()
                window._show_safety_alert(
                    f"Emergency stop: Error monitoring system status\n{str(e)}"
                )
                success = False

        return success

    def trigger_safety_stop(self, reason):
        """Pi-side limit breach: stop, alert persistently, reset."""
        window = self.window
        window._show_safety_alert(f"Emergency stop triggered: {reason}")
        window.treatment_panel.set_fault(reason)
        window.set_protocol_state("fault")
        if window.worker is not None:
            window.worker.stop()
        window.initial_setup_complete = False
        window.reset_arduino()

    def on_firmware_error(self, message):
        """Firmware ERROR:/BUSY lines. These are safety events (pressure
        limit, stop button, heartbeat loss, sensor faults) that used to be
        logged as 'unrecognized data' and never reached the operator."""
        window = self.window
        print(f"FIRMWARE ERROR: {message}")
        window.logger.error(f"Firmware error: {message}")

        if message == "BUSY":
            # A command was refused because a move is running; transient
            return

        # The firmware has already stopped itself and begun releasing
        # traction; align the application state with that.
        if window.protocol_running and window.worker:
            try:
                window.worker.is_running = False
            except Exception as e:
                print(f"Error flagging worker stop: {e}")
        window.treatment_panel.set_fault(message)
        window.set_protocol_state("fault")
        window._show_safety_alert(f"DEVICE SAFETY STOP: {message}")

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
        """Serial link declared lost by the transport watchdog."""
        window = self.window
        print("Arduino connection lost")
        window.logger.error("Arduino connection lost")
        # Stop the protocol state machine; the firmware's own heartbeat
        # timeout has already stopped motion and released traction on its
        # side within ~3 seconds of losing us.
        if window.protocol_running and window.worker:
            try:
                window.worker.is_running = False
            except Exception as e:
                print(f"Error flagging worker stop: {e}")
        was_treating = window.protocol_running
        window.treatment_panel.set_fault("CONNECTION LOST")
        window.set_protocol_state("fault")
        if was_treating:
            window._show_safety_alert(
                "CONNECTION LOST during treatment. The device stops and "
                "releases traction on its own within 3 seconds. Verify the "
                "patient, then reconnect."
            )
        window.reset_arduino()
