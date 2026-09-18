"""Cancellable controller operations completed by typed evidence and its ack."""

import math
import threading
import time
from typing import Callable, Optional, Tuple

from PyQt5.QtCore import Qt

from helpers.firmware_protocol import HX711_PROTOCOL_DRIVER


class OperationCancelled(RuntimeError):
    """The owner cancelled this operation; no continuation may write."""


class OperationRejected(RuntimeError):
    """A controller rejection or latched fault must not cause automatic retry."""


class BaselineError(OperationRejected):
    """A failed baseline requires deliberate operator recovery."""


class FirmwareCompatibilityError(OperationRejected):
    """Unknown live calibration semantics must never be guessed."""


class ControllerOperations:
    """Own reply state for one worker, without updating widgets from serial callbacks.

    The sender must serialize cancellation with enqueueing. V2 additionally
    requires the matching command handle; legacy DONE is usable only after the
    expected typed reply. Call close on every exit path.
    """

    def __init__(self, arduino: object, send: Callable, check_cancelled: Callable) -> None:
        self.arduino = arduino
        self.send = send
        self.check_cancelled = check_cancelled
        self._lock = threading.RLock()
        self._event = threading.Event()
        self._expected: Optional[Tuple] = None
        self._command = ""
        self._matched = False
        self._started = False
        self._error: Optional[str] = None
        self.actual: Optional[float] = None
        self._connections = (
            (arduino.motion_done, self._motion),
            (arduino.calibration_result, self._calibration),
            (arduino.zeros_emit, self._zeros),
            (arduino.ready_to_go_emit, self._ready),
            (arduino.done_emit, self._done),
            (arduino.command_rejected, self._rejected),
            (arduino.fault_emit, self._fault),
            (arduino.error_emit, self._error_reply),
            (arduino.connection_lost, self._disconnected),
        )
        for signal, callback in self._connections:
            signal.connect(callback, Qt.DirectConnection)

    def close(self) -> None:
        with self._lock:
            self._expected = None
        for signal, callback in self._connections:
            try:
                signal.disconnect(callback)
            except (TypeError, RuntimeError):
                pass

    def _motion(self, kind: str, target: float, actual: float) -> None:
        with self._lock:
            expected = self._expected
            if not expected or expected[0] != "motion":
                return
            _, wanted_kind, wanted_target, low, high = expected
            if (kind == wanted_kind and math.isclose(target, wanted_target, abs_tol=1e-6)
                    and math.isfinite(actual) and low <= actual <= high):
                self._matched = True
                self.actual = actual

    def _calibration(self, result: dict) -> None:
        with self._lock:
            expected = self._expected
            if not expected or expected[0] not in ("tare", "set"):
                return
            if result.get("operation") != expected[0]:
                return
            status = result.get("status")
            if status in ("rejected", "cancelled"):
                self._error = "Pressure baseline/calibration: " + result.get("reason", status)
                self._event.set()
            elif status == "started":
                self._started = True
            elif status == "ok" and (expected[0] == "set" or self._started):
                factor = result.get("factor")
                if (isinstance(factor, (float, int)) and math.isfinite(factor)
                        and math.isclose(factor, expected[1], rel_tol=1e-6, abs_tol=1e-6)):
                    self._matched = True
                else:
                    self._error = "Calibration reply does not match the configured factor"
                    self._event.set()

    def _zeros(self, axial: int, horizontal: int) -> None:
        with self._lock:
            if self._expected == ("zeros", axial, horizontal):
                self._matched = True

    def _ready(self) -> None:
        with self._lock:
            if self._expected == ("ready",):
                self._event.set()

    def _done(self) -> None:
        with self._lock:
            if self._matched:
                self._event.set()

    def _rejected(self, result: dict) -> None:
        with self._lock:
            if self._expected and self._command.startswith(result["command"]):
                self._error = "{} rejected: {}".format(self._command, result["reason"])
                self._event.set()

    def _fault(self, result: dict) -> None:
        with self._lock:
            if self._expected:
                self._error = "Controller fault: " + result["reason"]
                self._event.set()

    def _disconnected(self) -> None:
        self._fault({"reason": "DISCONNECTED"})

    def _error_reply(self, reason: str) -> None:
        self._fault({"reason": reason})

    def perform(self, command: str, expected: Tuple, timeout: float) -> Optional[float]:
        """Arm before sending, validate evidence, then consume its trailing DONE."""
        self.check_cancelled()
        with self._lock:
            self._expected, self._command = expected, command
            self._matched = self._started = False
            self._error = None
            self.actual = None
            self._event.clear()
        try:
            handle = self.send(command)
            if not handle:
                raise OperationRejected("Could not queue " + command)
            deadline = time.monotonic() + timeout
            while True:
                self.check_cancelled()
                with self._lock:
                    if self._error:
                        raise OperationRejected(self._error)
                    if self._event.is_set():
                        if expected == ("ready",) or not self.arduino.protocol_v2:
                            return self.actual
                        if handle.completed.is_set() and handle.result == "DONE":
                            return self.actual
                if (self.arduino.protocol_v2 and handle.completed.is_set()
                        and handle.result not in ("DONE", "OK")):
                    raise OperationRejected(f"{command}: {handle.result} {handle.reason}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for confirmed " + command)
                # A typed reply for a different v2 command can set _event;
                # never spin on it or accept it without this handle's ack.
                time.sleep(min(0.02, remaining))
        finally:
            with self._lock:
                self._expected = None

    def require_firmware(self, timeout: float = 3.0) -> None:
        self.check_cancelled()
        if self.arduino.firmware_driver != HX711_PROTOCOL_DRIVER:
            if not self.send("T"):
                raise FirmwareCompatibilityError("Cannot request controller identity")
        deadline = time.monotonic() + timeout
        while self.arduino.firmware_driver != HX711_PROTOCOL_DRIVER:
            self.check_cancelled()
            if time.monotonic() >= deadline:
                raise FirmwareCompatibilityError("Controller requires DRX-HX711-NB2 firmware")
            time.sleep(0.02)

    def baseline(self, config: object, retract: bool = False) -> None:
        """Zero supported resting weight only after the owning workflow stops motion."""
        self.arduino.baseline_valid = False
        try:
            if retract:
                if not self.send("X"):
                    raise BaselineError("Cannot stop pressure control before axial home")
                home = float(config.AMarks.get("0.0", config.AMarks.get("0")))
                self.perform("I120", ("motion", "I", home, max(0, home - 25),
                                       min(4095, home + 25)), 60.0)
            self.perform("L1|BASELINE", ("tare", float(config.calibration)), 10.0)
            # The owner serializes this final update with cancellation too.
            self.check_cancelled()
        except OperationCancelled:
            raise
        except Exception as exc:
            raise BaselineError(str(exc)) from exc
