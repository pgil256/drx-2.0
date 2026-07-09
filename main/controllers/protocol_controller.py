# controllers/protocol_controller.py
"""Protocol lifecycle, extracted from the KneeSpa window.

Owns the idle/starting/running/stopping/fault state machine and the
start/stop/completion flow. State attributes (protocol_state,
protocol_running, worker, timers) stay on the window: many widgets and
other controllers read them; this module owns the transitions.
"""
import time

import RPi.GPIO as GPIO
from PyQt5 import QtWidgets
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox

from helpers import protocols
from config.constants import BUTTON_STYLES, EMERGENCYSTOP


class ProtocolController:
    def __init__(self, window):
        self.window = window

    def set_state(self, state):
        """Single source of truth for the protocol lifecycle.

        Drives the Start/Stop button, the treatment banner, and navigation
        gating together so they can no longer desync (the button text used
        to be the de-facto state and could show "Stop" with nothing
        running, or vice versa).
        """
        window = self.window
        print(f"Protocol state: {window.protocol_state} -> {state}")
        window.protocol_state = state
        window.protocol_running = state in ("starting", "running", "stopping")

        start_button = window.ui.start_button
        if state == "idle":
            start_button.setText("Start")
            start_button.setStyleSheet(BUTTON_STYLES["START"])
            start_button.setEnabled(True)
            window.treatment_panel.set_idle()
        elif state == "starting":
            start_button.setText("Stop")
            start_button.setStyleSheet(BUTTON_STYLES["STOP"])
            start_button.setEnabled(False)
        elif state == "running":
            start_button.setText("Stop")
            start_button.setStyleSheet(BUTTON_STYLES["STOP"])
            start_button.setEnabled(True)
        elif state == "stopping":
            start_button.setEnabled(False)
            window.treatment_panel.set_stopping()
        elif state == "fault":
            start_button.setText("Start")
            start_button.setStyleSheet(BUTTON_STYLES["START"])
            # A fault is not treatment-ready. Recovery reset is the only path
            # back to idle, and the red banner remains visible until then.
            start_button.setEnabled(False)

    def block_nav(self):
        """Navigation away from the treatment screen is blocked while a
        protocol is active; the setup page's jog controls would conflict
        with the running protocol."""
        window = self.window
        if window.protocol_state in ("starting", "running", "stopping"):
            window._show_timed_error(
                "Treatment in progress - press STOP before leaving this screen."
            )
            return True
        return False

    def panel_stop_requested(self):
        """STOP pressed on the always-visible treatment banner."""
        window = self.window
        print("Panel STOP pressed")
        if window.protocol_state in ("starting", "running"):
            self.stop_protocol()
        else:
            # Fault/idle state: make sure the machine is stopped anyway
            window.stop_actuators()
            if window.protocol_state == "idle":
                window.treatment_panel.set_idle()


    def confirm_start(self):
        """Summarize the treatment parameters and require confirmation.

        Starting traction on a patient used to be a single unguarded
        touch event.
        """
        window = self.window
        try:
            protocol = window.protocol_number_field.text() if window.protocol_number_field else "?"
            max_pressure = window.max_pressure_edit.value() if window.max_pressure_edit else "?"
            max_left = window.max_left_edit.value() if window.max_left_edit else "?"
            max_right = window.max_right_edit.value() if window.max_right_edit else "?"
            duration = int(window.time_edit.value()) if window.time_edit else 12
            pulse = "on" if window.current_use_pulse_setting else "off"
        except Exception as e:
            print(f"Error reading protocol parameters for confirmation: {e}")
            return False

        summary = (
            f"Protocol {protocol}\n"
            f"Max pressure: {max_pressure} lbs\n"
            f"Lateral range: {max_left}° left / {max_right}° right\n"
            f"Duration: {duration} min\n"
            f"Pulse: {pulse}\n\n"
            "Confirm the patient is positioned and start treatment?"
        )
        reply = QMessageBox.question(
            window,
            "Start treatment?",
            summary,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes


    def start_or_stop(self):
        """Start or stop the protocol with debouncing to prevent multiple rapid clicks."""
        window = self.window
        print("Toggling protocol start/stop")

        start_button = window.ui.start_button
        # Prevent rapid clicking by disabling the button during operation
        start_button.setEnabled(False)

        try:
            if window.protocol_state == "fault":
                window._show_timed_error(
                    "Recover/reset the device before starting another treatment."
                )
                self.set_state("fault")
                return
            if window.protocol_state == "idle":
                if not self.confirm_start():
                    start_button.setEnabled(True)
                    return
                self.set_state("starting")
                if not window.ensure_arduino_connection():
                    window._show_timed_error(
                        "Arduino connection is not ready. Check connections and try again."
                    )
                    self.set_state("idle")
                    return
                if not self.start_protocol():
                    self.set_state("idle")
                    return
                self.set_state("running")
            else:
                start_button.setText("Stop")
                start_button.setStyleSheet(BUTTON_STYLES["STOP"])
                self.stop_protocol()
        except Exception as e:
            print(f"Error during protocol operation: {e}")
            window.logger.exception("Protocol start/stop transition failed")
            window.worker = None
            window.protocol_timer.stop()
            window.protocol_start_time = None
            window.protocol_stop_requested = False
            self.set_state("idle")
            window._show_timed_error(f"Could not start treatment: {e}")


    def start_protocol(self):
        """Start protocol execution."""
        window = self.window
        if not window.current_user:
            print("Access denied: User not logged in")
            window._show_timed_error("Please login to proceed")
            return False

        if not window.config.calibrated:
            # Treating a patient on generated default geometry or a
            # default scale factor is never acceptable
            window._warn_uncalibrated()
            return False

        try:
            # Validate protocol number
            protocol = window.protocol_number_field.text()
            if protocol not in ["1", "2", "3", "4"]:
                raise ValueError(f"Invalid protocol number: {protocol}")

            # Get duration in minutes from time_edit
            duration = 12  # Default to 12 minutes
            if hasattr(window, "time_edit") and window.time_edit is not None:
                try:
                    duration = int(window.time_edit.value())
                except Exception as e:
                    print(f"Error getting time value: {e}, using default 5 minutes")

            if duration == 0:
                duration = 12  # Ensure we have a valid duration

            print(f"Protocol duration: {duration} minutes")
            window.protocol_duration = duration * 60  # Convert to seconds
            window.protocol_start_time = time.time()

            # Update timer dialog if visible
            if hasattr(window, "timer_dialog") and window.timer_dialog and window.timer_dialog.isVisible():
                window.timer_dialog.initialize_protocol_time(
                    window.protocol_start_time, window.protocol_duration
                )
                window.protocol_timer.start(1000)  # Update every second

            max_pressure = int(window.max_pressure_edit.value()) if window.max_pressure_edit else 50
            max_left_from_slider = int(window.max_left_edit.value()) if window.max_left_edit else 10
            max_right_from_slider = int(window.max_right_edit.value()) if window.max_right_edit else 10

            # The worker expects max_left to be negative
            max_left_for_worker = -abs(max_left_from_slider)
            max_right_for_worker = abs(max_right_from_slider)

            use_pulse = window.current_use_pulse_setting # Use the tracked state
            # Pulse cadence from the modern Settings slider (None on the
            # legacy UI). Only acts on flag-gated J<ms> firmware; otherwise
            # the worker falls back to bare J (see helpers.protocols).
            pulse_rate = getattr(window, "current_pulse_rate", None)

            if window.ui.forward_button_protocol_image:
                window.ui.forward_button_protocol_image.setEnabled(False)
            else:
                print("Warning: Could not find forward_button_protocol_image to disable it.")

            if window.ui.backward_button_protocol_image:
                window.ui.backward_button_protocol_image.setEnabled(False)
            else:
                print("Warning: Could not find backward_button_protocol_image to disable it.")

            window.ui.reset_arduino_main_button.setEnabled(False)
            window.increase_time.setEnabled(False)
            window.decrease_time.setEnabled(False)

            window.mid_protocol_warning_shown = False
            window.protocol_stop_requested = False
            # Seed rollback values before starting: the mid-protocol
            # change dialog's Cancel path restores _prev_* -- they were
            # never initialized, so the first Cancel raised TypeError and
            # silently left the unconfirmed value applied
            window._prev_pressure = max_pressure
            window._prev_left = max_left_from_slider
            window._prev_right = max_right_from_slider

            # Update UI
            window.ui.start_button.setText("Stop")
            window.ui.start_button.setStyleSheet(BUTTON_STYLES["STOP"])

            window.set_to_c_distance(0)

            # Create and start protocol
            window.worker = protocols.Protocols(
                window.config.a_factor,
                protocol,
                max_pressure,
                max_left_for_worker,
                max_right_for_worker,
                duration,
                use_pulse,  # Just the boolean flag
                ser=window.arduino,
                config=window.config,
                pulse_rate=pulse_rate,
            )

            # Connect signals
            window.worker.signals.finished.connect(self.protocol_completed)
            # Safety recovery after a failed pulse phase (emitted by
            # protocols 2/3); was never connected to anything before
            window.worker.signals.reset_needed.connect(window.reset_arduino)

            # Connect pressure dialog regardless of visibility
            # We'll connect it now so it's ready when the checkbox is checked
            if hasattr(window, "pressure_dialog") and window.pressure_dialog:
                # Disconnect any existing connections to avoid duplicate signals
                try:
                    window.worker.signals.pressure_emit.disconnect(window.pressure_dialog.update_pressure)
                except Exception:
                    pass  # Ignore if not previously connected

                # Connect the pressure signal to the dialog's update method
                window.worker.signals.pressure_emit.connect(window.pressure_dialog.update_pressure)
                print("MAIN APP: Connected worker.signals.pressure_emit to pressure_dialog.update_pressure")

                # Also connect the Arduino's status directly as a backup connection
                if hasattr(window, "arduino") and window.arduino and hasattr(window.arduino, "status_emit"):
                    try:
                        window.arduino.status_emit.disconnect(window.pressure_dialog.update_pressure)
                    except Exception:
                        pass  # Ignore if not previously connected

                    # Create a direct connection from Arduino to pressure dialog
                    window.arduino.status_emit.connect(
                        lambda pos_a, pos_b, pos_c, pressure: window.pressure_dialog.update_pressure(pressure)
                    )
                    print("MAIN APP: Connected arduino.status_emit directly to pressure_dialog.update_pressure")

            window.protocol_running = True
            window.mid_protocol_warning_shown = False

            window.start_button.setEnabled(True)

            # Always-visible treatment banner: live values arrive via
            # status_emit; the countdown via update_protocol_time
            window.treatment_panel.set_running(max_pressure, duration * 60)

            # Start protocol execution
            window.threadpool.start(window.worker)

            # Start timers
            window.protocol_timer.start()
            QApplication.processEvents()

            # Live phase text: the label used to read "Protocol Started"
            # for the whole session because worker progress was never
            # connected to anything
            window.ui.status_label.setText("Protocol Started")
            window.worker.signals.progress.connect(self.update_status_label)
            return True

        except ValueError as e:
            print(f"Invalid parameter: {str(e)}")
            window._show_timed_error(f"Invalid Parameters: {str(e)}")
            return False
        except Exception as e:
            print(f"Failed to start protocol: {str(e)}")
            import traceback
            traceback.print_exc()  # Print full stack trace
            window._show_timed_error(f"Protocol Error: {str(e)}")
            return False


    def stop_protocol(self):
        """Stop protocol sequence."""
        window = self.window
        print("Stopping protocol")
        window.protocol_stop_requested = True
        self.set_state("stopping")
        window.stop_actuators()
        window.mid_protocol_warning_shown = False
        # Use QTimer to avoid blocking UI
        QTimer.singleShot(500, self._stop_phase2)

    def _stop_phase2(self):
        """Phase 2 of stop protocol after 0.5 second delay."""
        window = self.window
        if window.worker:
            window.worker.stop()
        # Continue to phase 3 after another 0.5 seconds
        QTimer.singleShot(500, self._stop_phase3)

    def _stop_phase3(self):
        """Phase 3 of stop protocol - final cleanup."""
        window = self.window
        # Keep the explicit stopping state until either the worker reports a
        # user-requested completion or reset recovery finishes.
        window.reset_arduino()


    def protocol_completed(self, success=True):
        """Handle protocol completion."""
        window = self.window
        print(f"Protocol completed; success={success}")
        window.protocol_timer.stop()

        if window.worker:
            window.worker.stop()

        # Update UI
        window.ui.show_timer_button.setChecked(False)
        window.ui.show_pressure_button.setChecked(False)
        # window.ui.use_pulse_button.setChecked(False)
        window.ui.use_pulse_button.setEnabled(True)
        window.ui.forward_button_protocol_image.setEnabled(True)
        window.ui.backward_button_protocol_image.setEnabled(True)
        window.ui.reset_arduino_main_button.setEnabled(True)
        window.increase_time.setEnabled(True)
        window.decrease_time.setEnabled(True)

        # (optional) be sure the dialogs disappear
        window.timer_dialog.hide()
        window.pressure_dialog.hide()
        try:
            window.ui.status_label.setText(
                "Protocol complete" if success else "Protocol stopped"
            )
        except Exception as e:
            print(f"Error updating status label: {e}")
        user_stopped = bool(getattr(window, "protocol_stop_requested", False))
        window.mid_protocol_warning_shown = False
        if success:
            self.set_state("idle")
        elif user_stopped:
            # The staged stop still owes the patient a recovery reset. Keep
            # Start/navigation gated until _on_reset_finished confirms it.
            self.set_state("stopping")
        else:
            self.set_state("fault")
            window._show_safety_alert(
                "Protocol did not complete normally. Traction has been "
                "released; verify the patient before continuing."
            )
        if not user_stopped:
            window.protocol_stop_requested = False


    def update_protocol_time(self):
        """Update the protocol timer display."""
        window = self.window
        if not window.protocol_start_time:
            return

        elapsed_time = int(time.time() - window.protocol_start_time)
        remaining_time = max(0, window.protocol_duration - elapsed_time)

        # Always-visible banner countdown (not gated on any dialog)
        window.treatment_panel.update_remaining(remaining_time)

        if window.timer_dialog.isVisible():
            window.timer_dialog.update_time(remaining_time)

        if remaining_time == 0:
            window.protocol_timer.stop()
            window.protocol_start_time = None


    def emergency_stop_clicked(self, event):
        """Handle emergency stop button press."""
        window = self.window
        print("Emergency stop triggered")
        # Assert the hardware EMERGENCYSTOP line FIRST - it does not depend
        # on the serial link being alive. setup_gpio() parks the pin HIGH
        # (run-permitted) at boot, so LOW is the asserted/stop state; it was
        # configured but never driven before. Released again when the
        # recovery reset begins (phase 3), which needs a live machine to
        # home. Polarity is inferred from the boot default - Phase E
        # hardware measurement must confirm before this ships to a device.
        try:
            GPIO.output(EMERGENCYSTOP, GPIO.LOW)
        except Exception as e:
            print(f"Could not assert EMERGENCYSTOP GPIO: {e}")
        # arduino.send never blocks or reconnects; 'X' jumps the tx queue
        # and stop_actuators alarms the operator if the link is down.
        window.stop_actuators()
        # Use QTimer instead of sleep to avoid blocking UI
        QTimer.singleShot(1000, self._emergency_stop_phase2)

    def _emergency_stop_phase2(self):
        """Phase 2 of emergency stop after 1 second delay."""
        window = self.window
        if window.worker:
            window.worker.stop()
        # Continue to phase 3 after another second
        QTimer.singleShot(1000, self._emergency_stop_phase3)

    def _emergency_stop_phase3(self):
        """Phase 3: release the hardware stop line, then run the recovery
        reset (the reset sequence homes actuators, which needs the machine
        powered)."""
        window = self.window
        try:
            GPIO.output(EMERGENCYSTOP, GPIO.HIGH)
        except Exception as e:
            print(f"Could not release EMERGENCYSTOP GPIO: {e}")
        window.reset_arduino()


    def update_status_label(self, text):
        """Mirror worker phase messages on the persistent status label
        and the treatment banner."""
        window = self.window
        clean = str(text).lstrip(">")
        try:
            window.ui.status_label.setText(clean)
        except Exception as e:
            print(f"Error updating status label: {e}")
        window.treatment_panel.set_phase(clean.upper())


