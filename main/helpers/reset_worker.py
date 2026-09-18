"""Ordered reset with per-worker replies, cancellation, and resting baseline."""
import threading
import time
from typing import Optional

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

try:
    from main.config.constants import DEFAULT_HORIZONTAL_POSITION
except ModuleNotFoundError:
    from config.constants import DEFAULT_HORIZONTAL_POSITION
from helpers.controller_operations import (
    ControllerOperations, OperationCancelled, OperationRejected,
)
from helpers.conversions import horizontal_degrees_to_position, lateral_degrees_to_position
from helpers.logging import setup_logger


class ResetWorkerSignals(QObject):
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)


class ResetWorker(QRunnable):
    """Replay a failed sequence once; baseline/rejection/cancellation never retry."""

    def __init__(self, arduino_instance: object, config_instance: object,
                 main_window: object) -> None:
        super().__init__()
        self.signals = ResetWorkerSignals()
        self.arduino = arduino_instance
        self.config = config_instance
        self.main_window = main_window
        self.logger = setup_logger(component="ResetWorker")
        self._cancelled = threading.Event()
        self._command_lock = threading.RLock()
        self.completed = threading.Event()
        self.step_times = []

    def cancel(self) -> None:
        with self._command_lock:
            self._cancelled.set()
            self.arduino.baseline_valid = False

    def _check_cancelled(self) -> None:
        if (self._cancelled.is_set()
                or getattr(self.main_window, "_closing", False) is True
                or getattr(self.main_window, "_physical_stop_active", False) is True):
            raise OperationCancelled("Reset cancelled")

    def _send(self, command: str) -> object:
        with self._command_lock:
            self._check_cancelled()
            return self.arduino.send_tracked(command)

    def _sequence(self, operations: ControllerOperations) -> None:
        operations.perform("Y", ("ready",), 10.0)
        operations.require_firmware()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            self._check_cancelled()
            time.sleep(0.02)
        a_zero = int(self.config.AMarks.get("0.0", self.config.AMarks.get("0", 0)))
        b_zero = int(self.config.BMarks.get("0.0", self.config.BMarks.get("0", 0)))
        pos_c, _ = lateral_degrees_to_position(self.config.CMarks, 0)
        pos_b = horizontal_degrees_to_position(self.config.BMarks, DEFAULT_HORIZONTAL_POSITION)
        if any(not 0 <= value <= 4095 for value in (a_zero, b_zero, pos_c, pos_b)):
            raise OperationRejected("Configured reset position exceeds controller feedback range")
        operations.perform(f"L5|{a_zero}|{b_zero}", ("zeros", a_zero, b_zero), 10.0)
        for command, kind, target, tolerance, timeout in (
            (f"K{pos_c}", "K", pos_c, 100, 30.0),
            (f"I13{pos_b}", "I", pos_b, 25, 30.0),
            ("I120", "I", a_zero, 25, 60.0),
        ):
            operations.perform(command, ("motion", kind, target, max(0, target - tolerance),
                                         min(4095, target + tolerance)), timeout)
        if not self.config.scale_calibrated:
            raise OperationRejected("A valid scale calibration is required before pressure zero")
        factor = float(self.config.calibration)
        operations.perform(f"L0{factor}", ("set", factor), 10.0)
        operations.baseline(self.config)

    @pyqtSlot()
    def run(self) -> None:
        success = False
        operations: Optional[ControllerOperations] = None
        try:
            self._check_cancelled()
            worker = getattr(self.main_window, "worker", None)
            if worker is not None and worker.is_running:
                raise OperationRejected("Cannot reset while a treatment worker is running")
            operations = ControllerOperations(self.arduino, self._send, self._check_cancelled)
            for attempt in range(2):
                try:
                    self._sequence(operations)
                    with self._command_lock:
                        self._check_cancelled()
                        self.arduino.baseline_valid = True
                        success = True
                    break
                except (OperationCancelled, OperationRejected):
                    raise
                except TimeoutError:
                    if attempt:
                        raise
                    # The Pi UART has no wired DTR reset. A fresh Y replays all
                    # initialization; never resume a single failed axis step.
                    self.logger.warning("Reset timed out; replaying complete initialization once")
        except OperationCancelled:
            self.logger.info("Reset cancelled")
        except Exception as exc:
            self.logger.exception("Reset failed")
            if not self._cancelled.is_set():
                self.arduino.send("X")
                self.signals.error.emit(str(exc))
        finally:
            if operations is not None:
                operations.close()
            self.completed.set()
            self.signals.finished.emit(success and not self._cancelled.is_set())
