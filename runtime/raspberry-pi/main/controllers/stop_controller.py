"""One owner for every way the device stops (checklist A2).

Each stop kind's behaviour used to live where it was triggered: the operator
STOP and the on-screen emergency stop in ProtocolController, the physical
button and command rejections in SafetyMonitor, the shutdown stop in
KneeSpa.cleanup. Their bodies now live here, unchanged, behind
``StopController.stop(kind)``. The old entry points delegate to it.

``POLICIES`` states what each kind does: the commands it sends, how traction
is released, how the device recovers, the flags it sets and the screen state
it leaves. ``development/tests/unit/test_stop_controller.py`` runs every kind
and checks it against this table, so the table cannot drift from the code.
Where two paths of one kind behave differently today, the table records both
(``fault`` and ``fault/command``) instead of merging them.
"""

import time
from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

from PyQt5.QtCore import QTimer

from helpers.stop_commands import RELEASE_SEQUENCE, STOP_ALL, TELEMETRY_ON

OPERATOR = "operator"   # the treatment STOP (ProtocolController.stop_protocol)
ESTOP = "estop"         # the on-screen EMERGENCY STOP (screen, banner, Setup)
PHYSICAL = "physical"   # the device's own stop button
FAULT = "fault"         # a latched controller fault: stop, no automatic movement
SHUTDOWN = "shutdown"   # the app is closing


@dataclass(frozen=True)
class StopPolicy:
    """What one kind of stop does, as checked by the table-driven tests."""

    commands: Tuple[str, ...]        # sent when the stop begins, in order
    hardware_line: bool              # drives EMERGENCYSTOP low before anything else
    release: str                     # how traction comes off
    recovery: str                    # how the device gets back to ready
    outcome: str                     # the session outcome it latches
    flags: Mapping[str, object]      # DeviceState fields it sets when it begins
    screen: str                      # the protocol state it leaves when it begins


POLICIES: Dict[str, StopPolicy] = {
    OPERATOR: StopPolicy(
        commands=(STOP_ALL,), hardware_line=False,
        release="after 0.5 s the worker's stop() sends X, P0, HF0; P0 alone if it did not",
        recovery="operator re-home prompt once the load clears (S2)",
        outcome="stopped", flags={}, screen="stopping",
    ),
    ESTOP: StopPolicy(
        commands=(STOP_ALL,), hardware_line=True,
        release="after 1 s, as the operator stop; the stop line goes high after 2 s",
        recovery="operator re-home prompt once the load clears (S2)",
        outcome="fault", flags={}, screen="stopping",
    ),
    PHYSICAL: StopPolicy(
        commands=(), hardware_line=False,
        release="the firmware's own release; queued commands are dropped",
        recovery="Reset in Setup",
        outcome="fault",
        flags={"physical_stop_active": True, "no_automatic_recovery": True,
               "initial_setup_complete": False},
        screen="fault",
    ),
    FAULT: StopPolicy(
        commands=(STOP_ALL, STOP_ALL, TELEMETRY_ON), hardware_line=False,
        release="none: no automatic movement",
        recovery="Reset in Setup",
        outcome="fault",
        flags={"no_automatic_recovery": True, "initial_setup_complete": False},
        screen="fault",
    ),
    FAULT + "/command": StopPolicy(
        commands=(STOP_ALL,), hardware_line=False,
        release="none: no automatic movement",
        recovery="Reset in Setup",
        outcome="fault",
        flags={"no_automatic_recovery": True, "initial_setup_complete": False},
        screen="fault",
    ),
    SHUTDOWN: StopPolicy(
        commands=RELEASE_SEQUENCE, hardware_line=False,
        release="P0 at shutdown; after a physical stop, queued commands are dropped instead",
        recovery="none: the app is closing",
        outcome="fault", flags={"no_automatic_recovery": True}, screen="unchanged",
    ),
}


def stops_for(window) -> "StopController":
    """The window's StopController (the protocol controller's), or a new one.

    Stateless apart from the window, so a new instance behaves the same; this
    keeps window stubs without a protocol controller working.
    """
    protocol = getattr(window, "protocol", None)
    stops = getattr(protocol, "stops", None)
    return stops if isinstance(stops, StopController) else StopController(window, protocol)


class StopController:
    """Runs every kind of stop. State stays on the window and its DeviceState."""

    # Bound on waiting for the post-stop P0 release to unload the patient
    # before the operator is asked to re-home. The reset's 'Y' reboots the
    # MCU (which aborts an in-flight pressure move) and the homing sequence
    # retracts the axial actuator LAST, so resetting 1 s after stop left the
    # limb under load for the whole homing sequence.
    RELEASE_WAIT_S = 20.0
    RELEASE_DONE_LBS = 5.0  # mirrors firmware PRESSURE_RELEASE_LBS
    _RELEASE_POLL_MS = 250

    def __init__(self, window, protocol=None) -> None:
        self.window = window
        self._protocol = protocol

    @property
    def protocol(self):
        """The protocol controller that owns sessions and the lifecycle state."""
        if self._protocol is not None:
            return self._protocol
        return getattr(self.window, "protocol", None)

    @staticmethod
    def policy(kind: str) -> StopPolicy:
        return POLICIES[kind]

    def stop(self, kind: str, **options) -> None:
        """Run one kind of stop; ``options`` are that kind's arguments."""
        handlers = {
            OPERATOR: self._operator_stop,
        }
        handlers[kind](**options)

    # ----- moved methods follow -----

    def _operator_stop(self):
        """Stop protocol sequence."""
        window = self.window
        window.logger.info("Stopping protocol")
        window.protocol_stop_requested = True
        self.protocol.latch_session_outcome("stopped")
        # Cancel the producer before X clears queued work. Waiting until phase
        # 2 allowed the worker to enqueue fresh motion after the stop command.
        if window.worker:
            window.worker.cancel()
        window.stop_actuators()
        self.protocol.finalize_session()
        self.protocol.set_state("stopping")
        window.mid_protocol_warning_shown = False
        # Use QTimer to avoid blocking UI
        QTimer.singleShot(500, self._stop_phase2)

    def _stop_phase2(self):
        """Phase 2 of stop protocol after 0.5 second delay."""
        window = self.window
        if getattr(window, "_no_automatic_recovery", False) is True:
            return
        if getattr(window, "_closing", False) is True:
            return
        self._release_after_stop()
        # Continue to phase 3 after another 0.5 seconds
        QTimer.singleShot(500, self._stop_phase3)

    def _release_after_stop(self):
        """Release traction for an operator STOP or on-screen emergency stop.

        The treatment worker's stop() normally sends X, P0 and HF0. When there
        is no worker (pressure applied from the Setup screen), or a finished
        worker declines because an earlier physical stop marked it, P0 used
        to be skipped: the load stayed on until the recovery reset re-homed
        the axial actuator, up to RELEASE_WAIT_S later. Fault stops never
        reach here (stop_without_recovery sets _no_automatic_recovery).
        """
        window = self.window
        worker = window.worker
        if worker is not None and worker.stop() is not False:
            return
        if getattr(window, "_physical_stop_active", False) is True:
            # The firmware's own release owns the load; X would abort it.
            return
        arduino = getattr(window, "arduino", None)
        if arduino is None or not arduino.send("P0"):
            window.logger.error("Pressure release (P0) could not be sent after stop")
            return
        window.logger.info("Pressure release command sent")

    def _stop_phase3(self):
        """Phase 3 of stop protocol - ask to re-home once the load has cleared."""
        # Keep the explicit stopping state until the release finishes; the
        # device then waits for the operator's re-home.
        self._reset_after_release(time.time())

    def _reset_after_release(self, started):
        """Ask the operator to re-home once the P0 release has unloaded the
        patient, or after RELEASE_WAIT_S. ``last_measured_pressure`` is fed by
        the firmware's status frames (kneespa.status_emit); None means no
        telemetry has ever arrived (dev launcher / link never up), so there is
        nothing to wait for."""
        window = self.window
        if getattr(window, "_no_automatic_recovery", False) is True:
            return
        if getattr(window, "_closing", False) is True:
            return
        if getattr(window, "_physical_stop_active", False) is True:
            return  # Physical stops require an explicit operator recovery.
        if getattr(window, "reset_in_progress", False) is True:
            # A reset this Stop cancelled may still be winding down. Wait for
            # it so the prompt is not lost.
            QTimer.singleShot(
                self._RELEASE_POLL_MS, lambda: self._reset_after_release(started)
            )
            return
        pressure = getattr(window, "last_measured_pressure", None)
        released = (
            pressure is None
            or (isinstance(pressure, (int, float)) and pressure < self.RELEASE_DONE_LBS)
        )
        waited = time.time() - started
        if released or waited >= self.RELEASE_WAIT_S:
            if not released:
                window.logger.warning(
                    "Release did not clear within %.0fs (pressure=%s)", waited, pressure,
                )
            self._require_operator_rehome(released)
            return
        QTimer.singleShot(
            self._RELEASE_POLL_MS, lambda: self._reset_after_release(started)
        )

    def _require_operator_rehome(self, load_cleared):
        """Leave the released device un-homed until the operator asks.

        Homing used to start on its own once the release finished, unlike
        the physical stop, which waits for the operator. The device now waits
        in "Recovery required" until the operator taps Re-home in the prompt
        or Reset in Setup. Nothing happens when time passes.
        """
        window = self.window
        if window.protocol_state == "idle":
            return  # An operator reset finished during the release wait.
        window.logger.info("Release finished; waiting for the operator to re-home")
        window.initial_setup_complete = False
        self.protocol.set_state("fault")
        window.disable_actuator_controls()
        window.shell.setup.set_reset_enabled(True)
        window.treatment_panel.set_idle()
        window._show_rehome_prompt(load_cleared)
