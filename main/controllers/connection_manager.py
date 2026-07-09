# controllers/connection_manager.py
"""Arduino connection lifecycle, extracted from the KneeSpa window.

Owns setup, verification, the reset sequence orchestration, and the
calibration/zero-mark pushes that follow a (re)connect. Connection
state (arduino, thread, reset_in_progress, initial_setup_complete)
stays on the window; this module owns the transitions.
"""
import time

from PyQt5.QtCore import QTimer, QThread
from PyQt5.QtWidgets import QApplication

from helpers.arduino import Arduino
from helpers.reset_worker import ResetWorker
from config.constants import ARDUINO_SETTINGS, BUTTON_STYLES


class ConnectionManager:
    def __init__(self, window):
        self.window = window

    def setup_arduino(self, auto_reset=True):
        """Setup Arduino interface."""
        window = self.window
        try:
            # Never overwrite a live transport/QThread pair. Reconnects used
            # to leak the old Qt event loop and could abort with
            # "QThread: Destroyed while thread is still running".
            if getattr(window, "arduino", None) is not None or getattr(
                window, "thread", None
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

            window.thread = QThread()  # no parent!
            print("Thread instance created for Arduino")

            # 2 - Connect Worker's Signals to Form method slots to post data
            print("Connecting Arduino signals to corresponding slots")
            window.arduino.done_emit.connect(self.set_done)

            # 3 - Move the Worker object to the Thread object
            print("Moving Arduino object to thread")
            window.arduino.moveToThread(window.thread)

            # 4 - Connect Worker Signals to the Thread slots
            print("Connecting Arduino finished signal to thread quit")
            window.arduino.finished.connect(window.thread.quit)
            window.arduino.ready_to_go_emit.connect(self.ready_to_go)
            window.arduino.buffer_warning.connect(window.handle_buffer_warning)

            # 5 - Connect Thread started signal to Worker operational slot method
            print("Connecting thread started signal to Arduino run method")
            window.thread.started.connect(window.arduino.run)

            # Additional Arduino signal connections
            print("Connecting Arduino position, status, and pressure signals")
            window.arduino.position_emit.connect(window.read_position)
            window.arduino.status_emit.connect(window.status_emit)
            window.arduino.connection_lost.connect(window.handle_connection_lost)
            window.arduino.connection_failed.connect(window.handle_connection_failed)
            window.arduino.error_emit.connect(window.handle_firmware_error)
            window.arduino.released_emit.connect(window.handle_pressure_released)
            window.arduino.zeros_emit.connect(window.handle_zeros_echo)

            # 6 - Start the thread
            print("Starting Arduino thread")
            window.thread.start()
            print("Thread started for Arduino")

            # Wait for "Ready to Go" signal with timeout
            print("Waiting for Arduino connection readiness")
            connection_ready = False
            start_time = time.time()
            timeout = ARDUINO_SETTINGS["CONNECTION_TIMEOUT_S"]
            while time.time() - start_time < timeout:
                if window.arduino.connection_ready_event.is_set():
                    connection_ready = True
                    break
                QApplication.processEvents()
                time.sleep(0.1)

            if connection_ready:
                print("Arduino initialized successfully")

                print("Arduino connection verified by readiness event")
                if auto_reset:
                    QTimer.singleShot(0, self.reset_arduino)
            else:
                window.loading_spinner.hide()

                print("Arduino initialization timed out")

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

            # Send calibration commands after reconnection
            self.send_zero_mark()
            time.sleep(1)
            self.send_calibration()

            return True
        else:
            print("Failed to restore Arduino connection.")
            window._show_timed_error(
                "Unable to establish reliable connection to Arduino. Please check connections and try again."
            )
            return False

    def teardown_arduino(self, drain_timeout=0.0):
        """Stop both transport layers and release their references safely."""
        window = self.window
        drained = True
        arduino = getattr(window, "arduino", None)
        thread = getattr(window, "thread", None)

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
        window.thread = None
        return drained


    def reset_arduino(self, event=None):
        """Reset Arduino and reinitialize actuators using ResetWorker."""
        window = self.window
        print("Reset Arduino requested...")

        # Check if reset is already in progress to avoid multiple overlapping resets
        if window.reset_in_progress:
            print("Reset already in progress, ignoring duplicate request")
            return

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
        window.start_button.setEnabled(False)
        QApplication.processEvents() # Ensure spinner is visible

        # Create and configure the worker, passing 'self'
        reset_worker = ResetWorker(window.arduino, window.config, window)

        # Connect signals from the worker to slots in this main class
        reset_worker.signals.finished.connect(self._on_reset_finished)
        reset_worker.signals.error.connect(self._on_reset_error)

        # Run the worker in the thread pool
        print("Starting ResetWorker in threadpool")
        window.threadpool.start(reset_worker)
        window.reset_setup_readings()

    def _on_reset_finished(self, success):
        """Slot called when ResetWorker finishes."""
        window = self.window
        print(f"Reset sequence finished signal received. Success: {success}")

        # Clear the reset in progress flag
        window.reset_in_progress = False

        if success:
            if window.initial_setup_complete == False:
                window.reset_extra_button_clicked()
            window.loading_spinner.hide() # Hide spinner when done
            window.start_button.setText("Start")
            window.start_button.setStyleSheet(BUTTON_STYLES["START"])
            window.start_button.setEnabled(True)  # Re-enable start button
            window._show_timed_error(
                "Arduino reset and actuators reinitialized."
            )
            window.initial_setup_complete = True
            window.protocol_stop_requested = False
            if hasattr(window, "set_protocol_state"):
                window.set_protocol_state("idle")
            print("Reset sequence completed successfully via worker.")
        else:
            window.start_button.setEnabled(True)  # Re-enable start button even on failure
            if hasattr(window, "set_protocol_state"):
                window.set_protocol_state("fault")
            window._show_timed_error(
             "Reset sequence failed. Check logs and Arduino connection."
             )

    def _on_reset_error(self, error_message):
        """Slot called if ResetWorker emits an error signal."""
        window = self.window
        print(f"Reset error signal received: {error_message}")
        # Ensure spinner hides even if finished signal doesn't fire (though finally should handle it)
        window.loading_spinner.hide()
        # Make sure to clear the reset_in_progress flag in case of error too
        window.reset_in_progress = False
        window.start_button.setEnabled(True)  # Re-enable start button on error
        if hasattr(window, "set_protocol_state"):
            window.set_protocol_state("fault")
        window._show_timed_error(
         f"Could not complete reset sequence:\n{error_message}"
        )

    def send_zero_mark(self):
        window = self.window
        print("send_zero_mark")
        a_zero = window.config.AMarks.get("0.0", window.config.AMarks.get("0", 0))
        b_zero = window.config.BMarks.get("0.0", window.config.BMarks.get("0", 0))
        # Delimited form: the legacy fixed-width format truncated any
        # 4-digit zero mark (1900 became 190); the reset worker was
        # already fixed but this copy still sent the legacy format
        window.arduino.send(f"L5|{a_zero}|{b_zero}")

    def send_calibration(self):
        window = self.window
        print("send_calibration")
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
        """Set the I2C status to ready."""
        window = self.window
        print("Setting I2C status to ready")
        window.I2Cstatus = 1
        window.I2Cstatus_event.set()  # Signal the thread-safe event  


    def handle_connection_failed(self, message):
        """Handle failure to connect to Arduino."""
        window = self.window
        print(message)
        window._show_timed_error(message)


