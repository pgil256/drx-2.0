from PyQt5.QtCore import QRunnable, QObject, pyqtSignal, pyqtSlot
import time

# Define the signals this worker can emit
class ResetWorkerSignals(QObject):
    finished = pyqtSignal(bool) # True for success, False for failure
    error = pyqtSignal(str)

class ResetWorker(QRunnable):
    """
    Worker thread to handle the multi-step Arduino reset sequence
    asynchronously using polling for command completion status.
    """
    # Add main_window parameter to accept the KneeSpa instance
    def __init__(self, arduino_instance, config_instance, main_window):
        super().__init__()
        print("ResetWorker: Initializing reset worker thread")
        self.signals = ResetWorkerSignals()
        self.arduino = arduino_instance
        self.config = config_instance
        # Store the reference to the main KneeSpa instance
        self.main_window = main_window # Reference to access I2Cstatus
        print("ResetWorker: Initialization complete")

    def _wait_for_done(self, timeout=10.0, operation_name="operation"):
        """
        Waits for main_window.I2Cstatus to become 1 or timeout using thread-safe event.
        Resets the flag via main_window reference before returning.
        NOTE: Runs in the worker thread.
        """
        print(f"Worker waiting for '{operation_name}' completion (max {timeout}s)...")

        # Use thread-safe event if available, otherwise fall back to polling
        if hasattr(self.main_window, 'I2Cstatus_event'):
            # Thread-safe wait using event
            if self.main_window.I2Cstatus_event.wait(timeout=timeout):
                print(f"Worker detected '{operation_name}' completed (event signaled).")
                self.main_window.I2Cstatus_event.clear()  # Reset event for next use
                self.main_window.I2Cstatus = 0  # Reset flag for compatibility
                return True
            else:
                print(f"Worker timeout waiting for '{operation_name}' completion.")
                self.main_window.I2Cstatus = 0  # Ensure flag is reset on timeout
                return False
        else:
            # Fallback to polling if event not available (backward compatibility)
            start_wait = time.time()
            while self.main_window.I2Cstatus == 0 and time.time() - start_wait < timeout:
                time.sleep(0.05)  # Short sleep in worker thread

            if self.main_window.I2Cstatus == 1:
                print(f"Worker detected '{operation_name}' completed (polling).")
                self.main_window.I2Cstatus = 0
                return True
            else:
                print(f"Worker timeout waiting for '{operation_name}' completion.")
                self.main_window.I2Cstatus = 0
                return False
            
    def _try_command_with_retry(self, command, operation_name="operation", timeout=30.0):
        """
        Send a command and wait for completion. If it fails, try resetting DTR and retry once.
        Returns True if successful on either try, False if both attempts fail.
        """
        # First attempt
        print(f"Attempting '{operation_name}' with command: {command}")
        self.main_window.I2Cstatus = 0  # Reset flag BEFORE sending command
        if hasattr(self.main_window, 'I2Cstatus_event'):
            self.main_window.I2Cstatus_event.clear()  # Clear event before sending command
        if not self.arduino.send(command):
            print(f"Failed to send command for {operation_name}")
            
            # Try DTR reset
            print("Resetting Arduino via DTR and retrying...")
            if hasattr(self.arduino, "reset_dtr") and callable(self.arduino.reset_dtr):
                self.arduino.reset_dtr()
                time.sleep(3)  # Wait for Arduino to initialize after reset
                
                # Second attempt after DTR reset
                print(f"Retrying '{operation_name}' after DTR reset")
                self.main_window.I2Cstatus = 0  # Reset flag again
                if not self.arduino.send(command):
                    print(f"Failed to send command for {operation_name} after DTR reset")
                    return False
            else:
                print("DTR reset method not available")
                return False
        
        # Wait for completion
        if not self._wait_for_done(timeout=timeout, operation_name=operation_name):
            print(f"Timeout waiting for {operation_name} completion")
            
            # Try DTR reset if we haven't already
            if not hasattr(self.arduino, "reset_dtr") or not callable(self.arduino.reset_dtr):
                return False
                
            print("Resetting Arduino via DTR due to timeout and retrying...")
            self.arduino.reset_dtr()
            time.sleep(3)  # Wait for Arduino to initialize after reset
            
            # Retry the command after DTR reset
            print(f"Retrying '{operation_name}' after timeout and DTR reset")
            self.main_window.I2Cstatus = 0  # Reset flag again
            if not self.arduino.send(command):
                print(f"Failed to send command for {operation_name} after DTR reset and timeout")
                return False
                
            # Wait for completion again
            return self._wait_for_done(timeout=timeout, operation_name=f"{operation_name} (retry)")
            
        return True  # First attempt was successful

    @pyqtSlot()
    def run(self):
        """Execute the reset sequence steps."""
        print("=" * 60)
        print("ResetWorker: Starting full reset sequence")
        print("=" * 60)

        # Safety check: Ensure no protocol is running
        if hasattr(self.main_window, 'worker') and self.main_window.worker:
            if hasattr(self.main_window.worker, 'is_running') and self.main_window.worker.is_running:
                print("ResetWorker: ERROR - Protocol is still running! Aborting reset.")
                self.signals.error.emit("Cannot reset while protocol is running")
                self.signals.finished.emit(False)
                return

        success = True
        start_time = time.time()
        try:
            # --- Step 1: Send 'Y' (Reset Command) ---
            print("ResetWorker: [STEP 1/6] Sending 'Y' (Reset Command)")
            if not self.arduino.send("Y"): 
                # Try DTR reset and retry
                print("Failed to send 'Y', trying DTR reset...")
                if hasattr(self.arduino, "reset_dtr") and callable(self.arduino.reset_dtr):
                    self.arduino.reset_dtr()
                    time.sleep(3)  # Wait for Arduino to initialize
                    if not self.arduino.send("Y"):
                        raise RuntimeError("Failed to send Y even after DTR reset")
                else:
                    raise RuntimeError("Failed to send Y and DTR reset not available")
                    
            # Assuming 'Y' doesn't send 'DONE', use a fixed delay. Adjust if needed.
            print("ResetWorker: Fixed delay after 'Y'...")
            time.sleep(5)
            print("ResetWorker: [STEP 1/6] Complete")

            # --- Step 2: Send Zero Mark ('L5') ---
            print("ResetWorker: [STEP 2/6] Sending zero mark ('L5')")
            zero_cmd = "L5{:3} {:3}".format(self.config.AMarks["0.0"], self.config.BMarks["0.0"])
            if not self._try_command_with_retry(zero_cmd, "Zero Mark", 30.0):
                raise TimeoutError("Failed to complete Zero Mark setup even after retry")
            print("ResetWorker: [STEP 2/6] Complete")

            # --- Step 3: Reset Actuator C ('I14') ---
            print("ResetWorker: [STEP 3/6] Resetting Actuator C ('I14')")
            pos_c = self.config.CMarks["{:.1f}".format(0)]
            cmd_c = f"I14{pos_c}"
            if not self._try_command_with_retry(cmd_c, "Actuator C Reset", 30.0):
                raise TimeoutError("Failed to reset Actuator C even after retry")
            print("ResetWorker: [STEP 3/6] Complete")

            # --- Step 4: Reset Actuator B ('A13') ---
            print("ResetWorker: [STEP 4/6] Resetting Actuator B ('A13')")
            cmd_b = f"A13{3}" # Equivalent inches for -10 degrees
            if not self._try_command_with_retry(cmd_b, "Actuator B Reset", 30.0):
                raise TimeoutError("Failed to reset Actuator B even after retry")
            print("ResetWorker: [STEP 4/6] Complete")

            # --- Step 5: Reset Actuator A ('I12') ---
            print("ResetWorker: [STEP 5/6] Resetting Actuator A ('I12')")
            cmd_a = f"I12{0}"
            if not self._try_command_with_retry(cmd_a, "Actuator A Reset", 60.0):
                raise TimeoutError("Failed to reset Actuator A even after retry")
            print("ResetWorker: [STEP 5/6] Complete")

            # --- Step 6: Send Calibration ('L0') ---
            print("ResetWorker: [STEP 6/6] Sending Calibration ('L0')")
            calib_cmd = f"L0{self.config.calibration}"
            if not self._try_command_with_retry(calib_cmd, "Calibration", 30.0):
                raise TimeoutError("Failed to complete calibration even after retry")
            print("ResetWorker: [STEP 6/6] Complete")

            elapsed_time = time.time() - start_time
            print("=" * 60)
            print(f"ResetWorker: Reset sequence completed successfully in {elapsed_time:.1f} seconds")
            print("=" * 60)

        except Exception as e:
            elapsed_time = time.time() - start_time
            error_msg = f"Error during reset sequence in worker: {e}"
            print("=" * 60)
            print(f"ResetWorker: ERROR - Reset sequence failed after {elapsed_time:.1f} seconds")
            print(f"ResetWorker: Error details: {error_msg}")
            print("=" * 60)
            # Try one last DTR reset to ensure system is in a clean state
            if hasattr(self.arduino, "reset_dtr") and callable(self.arduino.reset_dtr):
                try:
                    print("Performing final DTR reset to clean up after error...")
                    self.arduino.reset_dtr()
                except Exception as reset_err:
                    print(f"Final DTR reset also failed: {reset_err}")
                    
            self.signals.error.emit(str(e)) # Emit error signal
            success = False
        finally:
            # Emit finished signal regardless of success/failure
            result_msg = "SUCCESS" if success else "FAILURE"
            print(f"ResetWorker: Finished with result: {result_msg}")
            self.signals.finished.emit(success)