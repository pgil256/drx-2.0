"""Cancellable controller operations completed by typed evidence and its ack."""

import json
import math
import threading
import time
from typing import Callable, Optional, Tuple
from uuid import uuid4

from PyQt5.QtCore import Qt

from helpers.firmware_protocol import HOME_RELEASE_CAPABILITY, HX711_PROTOCOL_DRIVER
from helpers.logging import setup_logger


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

    TARE_TIMEOUT = 32.0
    RELEASE_TIMEOUT = 62.0
    RETRY_SETTLE_SECONDS = 2.0

    def __init__(self, arduino: object, send: Callable, check_cancelled: Callable) -> None:
        self.arduino = arduino
        self.send = send
        self.check_cancelled = check_cancelled
        self.logger = setup_logger(component="ControllerOperations")
        self._lock = threading.RLock()
        self._event = threading.Event()
        self._expected: Optional[Tuple] = None
        self._command = ""
        self._matched = False
        self._started = False
        self._error: Optional[str] = None
        self._blocked_error: Optional[str] = None
        self._reason: Optional[str] = None
        self.release_evidence: Optional[dict] = None
        self.new_offset: Optional[int] = None
        self.actual: Optional[float] = None
        self._connections = (
            (arduino.motion_done, self._motion),
            (arduino.home_release_result, self._release),
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
                self._reason = result.get("reason", status)
                self._error = "Pressure baseline/calibration: " + result.get("reason", status)
                self._event.set()
            elif status == "started":
                self._started = True
            elif status == "ok" and (expected[0] == "set" or self._started):
                factor = result.get("factor")
                if (isinstance(factor, (float, int)) and math.isfinite(factor)
                        and math.isclose(factor, expected[1], rel_tol=1e-6, abs_tol=1e-6)):
                    self._matched = True
                    if expected[0] == "tare":
                        self.new_offset = result["offset"]
                else:
                    self._error = "Calibration reply does not match the configured factor"
                    self._event.set()

    def _release(self, result: dict) -> None:
        with self._lock:
            expected = self._expected
            if not expected or expected[0] != "release" or result["token"] != expected[1]:
                return
            _, token, home, factor = expected
            if (result["target"] != home or abs(result["actual"] - home) > 25
                    or not math.isclose(result["factor"], factor, rel_tol=1e-6, abs_tol=1e-6)):
                self._error = "Final retraction confirmation did not match home/calibration"
            else:
                self.release_evidence = dict(result)
                self._matched = True
                self.logger.info("Final retraction confirmed stopped: %s", json.dumps({
                    "token": token, "configured_home": home, "actual_home": result["actual"],
                    "pre_zero_pressure_lb": result["pressure_lb"],
                    "old_offset": result["offset"], "factor": result["factor"],
                }, sort_keys=True))
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
            self._blocked_error = "Controller fault: " + result["reason"]
            self._event.set()

    def _disconnected(self) -> None:
        self._fault({"reason": "DISCONNECTED"})

    def _error_reply(self, reason: str) -> None:
        if reason == "BUSY" and self._expected is None:
            return  # Pulse start can legitimately be deferred by the worker.
        self._fault({"reason": reason})

    def perform(self, command: str, expected: Tuple, timeout: float) -> Optional[float]:
        """Arm before sending, validate evidence, then consume its trailing DONE."""
        self._check()
        with self._lock:
            self._expected, self._command = expected, command
            self._matched = self._started = False
            self._error = None
            self._reason = None
            self.new_offset = None
            self.actual = None
            self._event.clear()
        try:
            handle = self.send(command)
            if not handle:
                raise OperationRejected("Could not queue " + command)
            deadline = time.monotonic() + timeout
            while True:
                self._check()
                with self._lock:
                    if self._error:
                        raise OperationRejected(self._error)
                    if self._event.is_set():
                        if (expected == ("ready",) or expected[0] == "release"
                                or not self.arduino.protocol_v2):
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

    def _check(self) -> None:
        self.check_cancelled()
        if self._blocked_error:
            raise OperationRejected(self._blocked_error)

    def require_firmware(self, timeout: float = 3.0, home_release: bool = False) -> None:
        self._check()

        def compatible() -> bool:
            return (self.arduino.firmware_driver == HX711_PROTOCOL_DRIVER
                    and (not home_release or HOME_RELEASE_CAPABILITY in
                         self.arduino.firmware_capabilities))
        if not compatible():
            if not self.send("T"):
                raise FirmwareCompatibilityError("Cannot request controller identity")
        deadline = time.monotonic() + timeout
        while not compatible():
            self._check()
            if time.monotonic() >= deadline:
                raise FirmwareCompatibilityError(
                    "Controller update required: install matching DRX-HX711-NB2 firmware"
                    + (" with HOME_RELEASE_V1 before treatment" if home_release else ""))
            time.sleep(0.02)

    def baseline(self, config: object, retract: bool = False,
                 final_release: bool = False) -> None:
        """Zero supported resting weight only after the owning workflow stops motion."""
        self.arduino.baseline_valid = False
        try:
            factor = float(config.calibration)
            token = uuid4().hex[:12] if final_release else None
            if final_release:
                self.require_firmware(home_release=True)
            if retract or final_release:
                self._check()
                if not self.send("X"):
                    raise BaselineError("Cannot stop pressure control before axial home")
                home = float(config.AMarks.get("0.0", config.AMarks.get("0")))
                if final_release:
                    self.perform("R|" + token, ("release", token, home, factor),
                                 self.RELEASE_TIMEOUT)
                else:
                    self.perform("I120", ("motion", "I", home, max(0, home - 25),
                                           min(4095, home + 25)), 60.0)
            for attempt in range(2):
                try:
                    command = "L1|HOME|" + token if final_release else "L1|BASELINE"
                    self.perform(command, ("tare", factor), self.TARE_TIMEOUT)
                    break
                except OperationRejected:
                    self._check()
                    if self._reason != "UNSTABLE" or attempt == 1:
                        raise
                    deadline = time.monotonic() + self.RETRY_SETTLE_SECONDS
                    while time.monotonic() < deadline:
                        self._check()
                        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            # The owner serializes this final update with cancellation too.
            self._check()
            if final_release:
                self.logger.info("Final pressure zero accepted: %s", json.dumps({
                    "token": token, "pre_zero_pressure_lb": self.release_evidence["pressure_lb"],
                    "old_offset": self.release_evidence["offset"], "new_offset": self.new_offset,
                    "actual_home": self.release_evidence["actual"], "factor": factor,
                }, sort_keys=True))
        except OperationCancelled:
            raise
        except Exception as exc:
            raise BaselineError(str(exc)) from exc
