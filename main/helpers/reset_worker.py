from PyQt5.QtCore import QRunnable, QObject, pyqtSignal, pyqtSlot
import time
from helpers.logging import (
    debug, debug_timing, debug_error, debug_state_change
)

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
        debug("Initializing reset worker thread", component="ResetWorker", level="INFO")
        self.signals = ResetWorkerSignals()
        self.arduino = arduino_instance
        self.config = config_instance
        # Store the reference to the main KneeSpa instance
        self.main_window = main_window # Reference to access I2Cstatus
        self.step_times = []  # Track time for each step
        debug("ResetWorker initialization complete", component="ResetWorker")

    def _wait_for_done(self, timeout=10.0, operation_name="operation"):
        """
        Waits for main_window.I2Cstatus to become 1 or timeout using thread-safe event.
        Resets the flag via main_window reference before returning.
        NOTE: Runs in the worker thread.
        """
        start_time = time.time()
        debug(f"Waiting for '{operation_name}' completion", component="ResetWorker",
              timeout=timeout, method="event" if hasattr(self.main_window, 'I2Cstatus_event') else "polling")

        # Use thread-safe event if available, otherwise fall back to polling
        if hasattr(self.main_window, 'I2Cstatus_event'):
            # Thread-safe wait using event
            if self.main_window.I2Cstatus_event.wait(timeout=timeout):
                debug_timing(f"'{operation_name}' completed via event",
                           start_time=start_time, component="ResetWorker")
                self.main_window.I2Cstatus_event.clear()  # Reset event for next use
                self.main_window.I2Cstatus = 0  # Reset flag for compatibility
                debug_state_change("ResetWorker.I2Cstatus", 1, 0, f"{operation_name} completed")
                return True
            else:
                debug(f"Timeout waiting for '{operation_name}'", component="ResetWorker",
                     level="WARNING", elapsed=f"{time.time()-start_time:.1f}s")
                self.main_window.I2Cstatus = 0  # Ensure flag is reset on timeout
                return False
        else:
            # Fallback to polling if event not available (backward compatibility)
            poll_count = 0
            while self.main_window.I2Cstatus == 0 and time.time() - start_time < timeout:
                time.sleep(0.05)  # Short sleep in worker thread
                poll_count += 1

            if self.main_window.I2Cstatus == 1:
                debug_timing(f"'{operation_name}' completed via polling",
                           start_time=start_time, component="ResetWorker",
                           poll_count=poll_count)
                debug_state_change("ResetWorker.I2Cstatus", 1, 0, f"{operation_name} completed")
                self.main_window.I2Cstatus = 0
                return True
            else:
                debug(f"Timeout waiting for '{operation_name}'", component="ResetWorker",
                     level="WARNING", elapsed=f"{time.time()-start_time:.1f}s", poll_count=poll_count)
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
        debug("="*60, component="ResetWorker", level="INFO")
        debug("Starting full Arduino reset sequence (6 steps)", component="ResetWorker", level="INFO")
        debug("="*60, component="ResetWorker", level="INFO")

        # Safety check: Ensure no protocol is running
        if hasattr(self.main_window, 'worker') and self.main_window.worker:
            if hasattr(self.main_window.worker, 'is_running') and self.main_window.worker.is_running:
                debug("ERROR - Protocol is still running! Aborting reset",
                     component="ResetWorker", level="ERROR")
                self.signals.error.emit("Cannot reset while protocol is running")
                self.signals.finished.emit(False)
                return

        success = True
        sequence_start = time.time()
        try:
            # --- Step 1: Send 'Y' (Reset Command) ---
            step_start = time.time()
            debug("[STEP 1/6] Sending 'Y' (Reset Command)", component="ResetWorker", level="INFO")
            if not self.arduino.send("Y"):
                # Try DTR reset and retry
                debug("Failed to send 'Y', trying DTR reset...", component="ResetWorker", level="WARNING")
                if hasattr(self.arduino, "reset_dtr") and callable(self.arduino.reset_dtr):
                    self.arduino.reset_dtr()
                    time.sleep(3)  # Wait for Arduino to initialize
                    if not self.arduino.send("Y"):
                        raise RuntimeError("Failed to send Y even after DTR reset")
                else:
                    raise RuntimeError("Failed to send Y and DTR reset not available")

            # Assuming 'Y' doesn't send 'DONE', use a fixed delay. Adjust if needed.
            debug("Fixed 5s delay after 'Y' command", component="ResetWorker")
            time.sleep(5)
            debug_timing("[STEP 1/6] Reset command complete", start_time=step_start, component="ResetWorker")
            self.step_times.append(("Reset Command", time.time() - step_start))

            # --- Step 2: Send Zero Mark ('L5') ---
            step_start = time.time()
            debug("[STEP 2/6] Sending zero mark ('L5')", component="ResetWorker", level="INFO")
            a_zero = self.config.AMarks.get("0.0", self.config.AMarks.get("0", 0))
            b_zero = self.config.BMarks.get("0.0", self.config.BMarks.get("0", 0))
            zero_cmd = "L5{:3} {:3}".format(a_zero, b_zero)
            if not self._try_command_with_retry(zero_cmd, "Zero Mark", 30.0):
                raise TimeoutError("Failed to complete Zero Mark setup even after retry")
            debug_timing("[STEP 2/6] Zero mark complete", start_time=step_start, component="ResetWorker")
            self.step_times.append(("Zero Mark", time.time() - step_start))

            # --- Step 3: Reset Actuator C ('I14') ---
            step_start = time.time()
            debug("[STEP 3/6] Resetting Actuator C ('I14')", component="ResetWorker", level="INFO")
            pos_c = self.config.CMarks["{:.1f}".format(0)]
            cmd_c = f"I14{pos_c}"
            debug(f"Actuator C command: {cmd_c}", component="ResetWorker", position=pos_c)
            if not self._try_command_with_retry(cmd_c, "Actuator C Reset", 30.0):
                raise TimeoutError("Failed to reset Actuator C even after retry")
            debug_timing("[STEP 3/6] Actuator C reset complete", start_time=step_start, component="ResetWorker")
            self.step_times.append(("Actuator C", time.time() - step_start))

            # --- Step 4: Reset Actuator B ('A13') ---
            step_start = time.time()
            debug("[STEP 4/6] Resetting Actuator B ('A13')", component="ResetWorker", level="INFO")
            cmd_b = f"A13{3}" # Equivalent inches for -10 degrees
            debug(f"Actuator B command: {cmd_b}", component="ResetWorker", inches=3)
            if not self._try_command_with_retry(cmd_b, "Actuator B Reset", 30.0):
                raise TimeoutError("Failed to reset Actuator B even after retry")
            debug_timing("[STEP 4/6] Actuator B reset complete", start_time=step_start, component="ResetWorker")
            self.step_times.append(("Actuator B", time.time() - step_start))

            # --- Step 5: Reset Actuator A ('I12') ---
            step_start = time.time()
            debug("[STEP 5/6] Resetting Actuator A ('I12')", component="ResetWorker", level="INFO")
            cmd_a = f"I12{0}"
            debug(f"Actuator A command: {cmd_a}", component="ResetWorker", position=0)
            if not self._try_command_with_retry(cmd_a, "Actuator A Reset", 60.0):
                raise TimeoutError("Failed to reset Actuator A even after retry")
            debug_timing("[STEP 5/6] Actuator A reset complete", start_time=step_start, component="ResetWorker")
            self.step_times.append(("Actuator A", time.time() - step_start))

            # --- Step 6: Send Calibration ('L0') ---
            step_start = time.time()
            debug("[STEP 6/6] Sending Calibration ('L0')", component="ResetWorker", level="INFO")
            calib_cmd = f"L0{self.config.calibration}"
            debug(f"Calibration command: {calib_cmd}", component="ResetWorker")
            if not self._try_command_with_retry(calib_cmd, "Calibration", 30.0):
                raise TimeoutError("Failed to complete calibration even after retry")
            debug_timing("[STEP 6/6] Calibration complete", start_time=step_start, component="ResetWorker")
            self.step_times.append(("Calibration", time.time() - step_start))

            # Log summary of all step times
            debug("="*60, component="ResetWorker", level="INFO")
            for step_name, step_time in self.step_times:
                debug(f"Step timing: {step_name} = {step_time:.1f}s", component="ResetWorker")
            debug_timing("RESET SEQUENCE COMPLETED SUCCESSFULLY", start_time=sequence_start, component="ResetWorker")
            debug("="*60, component="ResetWorker", level="INFO")

        except Exception as e:
            elapsed_time = time.time() - sequence_start
            debug("="*60, component="ResetWorker", level="ERROR")
            debug_error(f"Reset sequence FAILED after {elapsed_time:.1f}s",
                       exception=e, component="ResetWorker")

            # Log step timing up to failure
            if self.step_times:
                debug("Completed steps before failure:", component="ResetWorker", level="ERROR")
                for step_name, step_time in self.step_times:
                    debug(f"  {step_name}: {step_time:.1f}s", component="ResetWorker")

            debug("="*60, component="ResetWorker", level="ERROR")

            # Try one last DTR reset to ensure system is in a clean state
            if hasattr(self.arduino, "reset_dtr") and callable(self.arduino.reset_dtr):
                try:
                    debug("Performing final DTR reset to clean up after error...",
                         component="ResetWorker", level="WARNING")
                    self.arduino.reset_dtr()
                    debug("Final DTR reset completed", component="ResetWorker")
                except Exception as reset_err:
                    debug_error("Final DTR reset also failed", exception=reset_err,
                              component="ResetWorker")

            self.signals.error.emit(str(e)) # Emit error signal
            success = False
        finally:
            # Emit finished signal regardless of success/failure
            result_msg = "SUCCESS" if success else "FAILURE"
            debug(f"ResetWorker finished with result: {result_msg}",
                 component="ResetWorker", level="INFO" if success else "ERROR")
            self.signals.finished.emit(success)
