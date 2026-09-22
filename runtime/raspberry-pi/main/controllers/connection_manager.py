# controllers/connection_manager.py
"""Arduino connection lifecycle, extracted from the KneeSpa window.

Owns setup, verification, the reset sequence orchestration, and the
calibration/zero-mark pushes that follow a (re)connect. Connection
state (arduino, arduino_thread, reset_in_progress, initial_setup_complete)
stays on the window; this module owns the transitions.
"""
import time
import threading

from PyQt5.QtCore import QTimer, QThread
from PyQt5.QtWidgets import QApplication

from helpers.arduino import Arduino
from helpers.reset_worker import ResetWorker
from config.constants import ARDUINO_SETTINGS, DEFAULT_HORIZONTAL_POSITION


class ConnectionManager:
    def __init__(self, window):
        self.window = window
        self.reset_worker = None

    def cancel_reset(self) -> None:
        """Cancel the producer before Stop discards its queued writes."""
        if self.reset_worker is not None:
            self.reset_worker.cancel()
        leg = getattr(self.window, "leg", None)
        if leg is not None:
            leg.cancel()

    def setup_arduino(self, auto_reset=True):
        """Setup Arduino interface."""
        window = self.window
        if getattr(window, "_closing", False) is True:
            return False
        try:
            # Never overwrite a live transport/QThread pair. Reconnects used
            # to leak the old Qt event loop and could abort with
            # "QThread: Destroyed while thread is still running".
            if getattr(window, "arduino", None) is not None or getattr(
                window, "arduino_thread", None
            ) is not None:
                if not self.teardown_arduino():
                    raise RuntimeError("Previous Arduino thread did not stop")
            print("Showing loading spinner")
            window.loading_spinner.show()
            window.disable_actuator_controls()

            print("Setting up Arduino interface")
            # 1 - create Worker and Thread inside the Form
            window.arduino = Arduino()  # no parent!
            print("Arduino instance created")

            window.arduino_thread = QThread()  # no parent!
            print("Thread instance created for Arduino")

            # 2 - Connect Worker's Signals to Form method slots to post data
            print("Connecting Arduino signals to corresponding slots")
            window.arduino.done_emit.connect(self.set_done)

            # 3 - Move the Worker object to the Thread object
            print("Moving Arduino object to thread")
            window.arduino.moveToThread(window.arduino_thread)

            # 4 - Connect Worker Signals to the Thread slots
            print("Connecting Arduino finished signal to thread quit")
            window.arduino.finished.connect(window.arduino_thread.quit)
            window.arduino.ready_to_go_emit.connect(self.ready_to_go)
            window.arduino.buffer_warning.connect(window.handle_buffer_warning)

            # 5 - Connect Thread started signal to Worker operational slot method
            print("Connecting thread started signal to Arduino run method")
            window.arduino_thread.started.connect(window.arduino.run)

            # Additional Arduino signal connections
            print("Connecting Arduino position, status, and pressure signals")
            window.arduino.position_emit.connect(window.read_position)
            window.arduino.status_emit.connect(window.status_emit)
            window.arduino.connection_lost.connect(window.handle_connection_lost)
            window.arduino.connection_failed.connect(window.handle_connection_failed)
            window.arduino.error_emit.connect(window.handle_firmware_error)
            window.arduino.warning_emit.connect(window.handle_firmware_warning)
            window.arduino.released_emit.connect(window.handle_pressure_released)
            window.arduino.zeros_emit.connect(window.handle_zeros_echo)
            window.arduino.fault_emit.connect(window.safety.on_controller_fault)
            window.arduino.command_rejected.connect(window.safety.on_command_rejected)
            window.arduino.sensor_diagnostics.connect(window.on_sensor_diagnostics)
            window.arduino.calibration_result.connect(window.on_calibration_result)
            window.arduino.pressure_warning.connect(window.on_pressure_progress_notice)

            # 6 - Start the thread
            print("Starting Arduino thread")
            window.arduino_thread.start()
            print("Thread started for Arduino")

            # Wait for "Ready to Go" signal with timeout
            print("Waiting for Arduino connection readiness")
            connection_ready = False
            start_time = time.time()
            timeout = ARDUINO_SETTINGS["CONNECTION_TIMEOUT_S"]
            while time.time() - start_time < timeout:
                if window._closing:
                    return False
                if window.arduino.connection_ready_event.is_set():
                    connection_ready = True
                    break
                QApplication.processEvents()
                time.sleep(0.1)

            if connection_ready:
                print("Arduino initialized successfully")

                print("Arduino connection verified by readiness event")
                if auto_reset:
                    QTimer.singleShot(0, self._automatic_reset)
            else:
                window.loading_spinner.hide()

                print("Arduino initialization timed out")
                if auto_reset:
                    # The transport keeps retrying in the background (its
                    # connect loop can outlast this wait). When it does come
                    # up the MCU still needs the reset / zero-mark /
                    # calibration sequence -- without this a late connect ran
                    # treatments on an un-homed, factory-calibrated device
                    # with the limit checks disabled.
                    window.arduino.connection_ready.connect(self._on_late_connect)

            return connection_ready  # Indicate success or failure

        except Exception as e:
            window.loading_spinner.hide()

            print(f"An error occurred while setting up Arduino: {e}")
            raise


    def ensure_arduino_connection(self):
        """
        Ensure Arduino connection is reliable before starting a protocol.
        Performs thorough reset and reconnection if needed.
        
        Returns:
            bool: True if connection is established or restored, False otherwise
        """
        window = self.window
        print("Verifying Arduino connection before protocol start...")

        # Check if Arduino is responsive
        if window.arduino and window.arduino.connected:
            # Send a test command to verify responsiveness
            if window.arduino.verify_connection():
                print("Arduino connection verified.")
                return True

        # If we reach here, connection needs reset
        print("Arduino connection needs reset, attempting reconnection...")

        # Forcefully disconnect current connection (disconnect() joins the
        # I/O thread itself; the long settling sleeps predate that)
        if hasattr(window, 'arduino') and window.arduino:
            self.teardown_arduino()
            time.sleep(0.5)  # Allow time for port to release

        # Reset GPIO pins to safe state
        window.setup_gpio()

        # Reinitialize Arduino connection
        connection_success = self.setup_arduino(auto_reset=False)

        if connection_success:
            print("Arduino successfully reset and reconnected.")

            self.reset_arduino()
            return False  # Initialization must complete before a new treatment starts.
        else:
            print("Failed to restore Arduino connection.")
            window._show_timed_error(
                "Unable to establish reliable connection to Arduino. Please check connections and try again."
            )
            return False

    def _on_late_connect(self):
        """The Arduino connected after setup_arduino() gave up waiting: run the
        reset sequence it would have scheduled had the connection been on time."""
        print("Arduino connected late; running the deferred reset sequence")
        QTimer.singleShot(0, self._automatic_reset)

    def _automatic_reset(self) -> None:
        """Respect a physical stop received while connection setup was pending."""
        if getattr(self.window, "_closing", False) is True:
            return
        if getattr(self.window, "_no_automatic_recovery", False) is True:
            return
        if getattr(self.window, "_physical_stop_active", False) is not True:
            self.reset_arduino()

    def teardown_arduino(self, drain_timeout=0.0):
        """Stop both transport layers and release their references safely."""
        window = self.window
        drained = True
        arduino = getattr(window, "arduino", None)
        thread = getattr(window, "arduino_thread", None)

        if arduino is not None:
            drained = arduino.disconnect(drain_timeout=drain_timeout)

        if thread is not None:
            thread.quit()
            if not thread.wait(3000):
                window.logger.error("Arduino QThread did not stop within 3 seconds")
                # Preserve the references: dropping the final QThread wrapper
                # while it is still running can abort the process.
                return False
            else:
                thread.deleteLater()

        window.arduino = None
        window.arduino_thread = None
        return drained


    def reset_arduino(self, event=None):
        """Reset Arduino and reinitialize actuators using ResetWorker."""
        window = self.window
        if getattr(window, "_firmware_update_recovery", None) == "flashing":
            window._show_timed_error("Firmware installation needs recovery. Open Device > Service "
                                     "and flash verified firmware before resetting.")
            return
        if (getattr(window, "_calibration_active", False) is True
                or getattr(window, "_device_maintenance_active", False) is True):
            window._show_timed_error("Finish device service before resetting Arduino.")
            return
        print("Reset Arduino requested...")
        if getattr(window, "_closing", False) is True:
            return

        # Check if reset is already in progress to avoid multiple overlapping resets
        if window.reset_in_progress:
            print("Reset already in progress, ignoring duplicate request")
            return

        worker = getattr(window, "worker", None)
        completed = getattr(worker, "completed", None)
        if isinstance(completed, threading.Event) and not completed.is_set():
            if worker.is_running:
                window._show_timed_error("Stop treatment before resetting Arduino.")
                return
            # Wait for the cancelled producer to detach its reply handlers before
            # allowing the operator's reset to issue any new commands.
            QTimer.singleShot(50, lambda: self.reset_arduino(event))
            return

        window._physical_stop_active = False
        window._no_automatic_recovery = False
        window.reset_in_progress = True  # Set flag to prevent overlapping resets
        window.initial_setup_complete = False

        if not hasattr(window, 'arduino') or window.arduino is None:
            print("Arduino object not ready for reset.")
            window._show_timed_error("Arduino connection not initialized.")
            window.reset_in_progress = False  # Reset flag
            return

        # Show the spinner
        print("Showing loading spinner for reset")
        window.loading_spinner.show()
        window.disable_actuator_controls()
        # Disable start button during reset to prevent crashes
        window.protocol.set_busy(True)
        QApplication.processEvents() # Ensure spinner is visible

        # Create and configure the worker, passing 'self'
        reset_worker = ResetWorker(window.arduino, window.config, window)
        self.reset_worker = reset_worker

        # Connect signals from the worker to slots in this main class
        reset_worker.signals.finished.connect(
            lambda success: self._on_reset_finished(success, reset_worker)
        )
        reset_worker.signals.error.connect(self._on_reset_error)

        # Run the worker in the thread pool
        print("Starting ResetWorker in threadpool")
        window.threadpool.start(reset_worker)
        window.reset_setup_readings()

    def _on_reset_finished(self, success, worker=None):
        """Slot called when ResetWorker finishes."""
        window = self.window
        if getattr(window, "_closing", False) is True:
            return False
        if worker is not None and worker is not self.reset_worker:
            return

        print(f"Reset sequence finished signal received. Success: {success}")
        if getattr(window, "_closing", False) is True:
            return
        if getattr(window, "_physical_stop_active", False) is True:
            success = False
        if getattr(window, "_no_automatic_recovery", False) is True:
            success = False

        # First initialization also establishes the open-loop leg reference.
        # Keep startup locked until the full retract completes; subsequent
        # Arduino resets preserve the patient's leg-length setting.
        leg = getattr(window, "leg", None)
        if success and leg is not None and leg.boot_home_pending:
            def finish_leg_home(homed: bool) -> None:
                self._on_reset_finished(homed, worker)

            if not leg.home(finish_leg_home) and self.reset_worker is worker:
                self._on_reset_finished(False, worker)
            return

        self.reset_worker = None

        # Clear the reset in progress flag
        window.reset_in_progress = False

        if success and getattr(window, "_firmware_update_recovery", None) == "reset_required":
            from pathlib import Path
            from config.paths import DEVICE_STATE_DIR
            try:
                (Path(DEVICE_STATE_DIR) / "updates/firmware-recovery.json").unlink()
                window._firmware_update_recovery = None
            except OSError:
                success = False
                window._no_automatic_recovery = True
                window._show_timed_error("Unable to clear the firmware recovery record. "
                                         "Check device storage before use.")

        if success:
            # The reset worker has verified these home targets. Rebase normal
            # jog estimates after service movement before controls are enabled.
            window.axial_flexion_position = 0
            window.horizontal_flexion_position = DEFAULT_HORIZONTAL_POSITION
            window.lateral_flexion_position = 0
            window._measurement_fault = None
            window.on_baseline_changed(True)
            window.loading_spinner.hide() # Hide spinner when done
            window._show_timed_error(
                "Arduino reset and actuators reinitialized."
            )
            window.initial_setup_complete = True
            window.protocol_stop_requested = False
            if hasattr(window, "set_protocol_state"):
                window.set_protocol_state("idle")
            window.enable_actuator_controls()
            print("Reset sequence completed successfully via worker.")
        else:
            window._release_leg_gpio()
            window.initial_setup_complete = False
            window.loading_spinner.hide()
            if hasattr(window, "set_protocol_state"):
                window.set_protocol_state("fault")
            window.shell.setup.set_reset_enabled(True)
            window._show_timed_error(
             "Reset sequence failed. Check logs and Arduino connection."
             )

    def _on_reset_error(self, error_message):
        """Slot called if ResetWorker emits an error signal."""
        window = self.window
        print(f"Reset error signal received: {error_message}")
        if getattr(window, "_closing", False) is True:
            return
        # Completion owns unlocking. Error arrives before worker cleanup finishes.
        window.initial_setup_complete = False
        window._show_timed_error(
         f"Could not complete reset sequence:\n{error_message}"
        )

    def send_zero_mark(self):
        window = self.window
        print("send_zero_mark")
        if getattr(window, "arduino", None) is None:
            window.logger.error("send_zero_mark: no Arduino transport")
            return
        a_zero = window.config.AMarks.get("0.0", window.config.AMarks.get("0", 0))
        b_zero = window.config.BMarks.get("0.0", window.config.BMarks.get("0", 0))
        # Delimited form: the legacy fixed-width format truncated any
        # 4-digit zero mark (1900 became 190); the reset worker was
        # already fixed but this copy still sent the legacy format
        window.arduino.send(f"L5|{a_zero}|{b_zero}")

    def send_calibration(self):
        window = self.window
        print("send_calibration")
        if getattr(window, "arduino", None) is None:
            # Also reached 5 s after a reset via QTimer.singleShot, by which
            # time a reconnect may have torn the transport down
            window.logger.error("send_calibration: no Arduino transport")
            return
        if not window.config.scale_calibrated:
            # Never push an implausible/default factor: the firmware
            # would happily produce raw-count "pressure" readings
            print(
                f"Refusing to send implausible scale factor "
                f"{window.config.calibration}"
            )
            window.logger.error(
                "Refusing to send implausible load-cell scale factor %s",
                window.config.calibration,
            )
            return
        window.arduino.send("L0{}".format(window.config.calibration))


    def set_done(self):
        """Set the I2C status to done."""
        window = self.window
        print("Setting I2C status to done - signal received from Arduino")
        window.I2Cstatus = 1
        window.I2Cstatus_event.set()  # Signal the thread-safe event
        window.enable_actuator_controls()

    def ready_to_go(self):
        """Firmware announced "Ready to Go" (its boot banner after a reset).

        Deliberately does NOT set ``I2Cstatus_event``. ResetWorker already
        waits for the banner on ``Arduino.ready_event`` (set on the I/O
        thread); this GUI-thread slot arrives a little later, and setting the
        DONE event here could land after the worker had cleared it for the
        NEXT step (the L5 zero mark) -- that step then returned instantly on
        the stale set, every later DONE was attributed one step early, and a
        homing step could be skipped while the reset still reported success.
        """
        print("Firmware ready (boot banner received)")


    def handle_connection_failed(self, message):
        """Handle failure to connect to Arduino."""
        window = self.window
        print(message)
        window._show_timed_error(message)

