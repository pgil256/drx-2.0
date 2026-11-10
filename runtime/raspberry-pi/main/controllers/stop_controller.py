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

One rule sits above the table: once the device's own stop button is active,
no later stop of any kind sends X until the operator's Reset. The firmware
releases the load by itself after the button, and an X ends that release.
"""

import time
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

import RPi.GPIO as GPIO
from PyQt5.QtCore import QTimer

from config.constants import EMERGENCYSTOP
from helpers.stop_commands import RELEASE, RELEASE_SEQUENCE, STOP_ALL, TELEMETRY_ON

OPERATOR = "operator"   # the treatment STOP (ProtocolController.stop_protocol)
ESTOP = "estop"         # the on-screen EMERGENCY STOP (screen, banner, Setup)
PHYSICAL = "physical"   # the device's own stop button
FAULT = "fault"         # a latched controller fault: stop, no automatic movement
SHUTDOWN = "shutdown"   # the app is closing
# A command the firmware rejected outside a stop (SafetyMonitor.on_firmware_error).
# A fault stop too, but it sends X once and cancels the worker only while a
# treatment runs.
COMMAND_FAULT = FAULT + "/command"


@dataclass(frozen=True)
class StopPolicy:
    """What one kind of stop does, as checked by the table-driven tests."""

    commands: Tuple[str, ...]        # sent when the stop begins, in order
    hardware_line: bool              # drives EMERGENCYSTOP low before anything else
    release: str                     # how traction comes off
    release_after_ms: Optional[int]  # when the release phase is scheduled, if it is
    recovery: str                    # how the device gets back to ready
    outcome: str                     # the session outcome it latches
    flags: Mapping[str, object]      # DeviceState fields it sets when it begins
    screen: str                      # the protocol state it leaves when it begins


POLICIES: Dict[str, StopPolicy] = {
    OPERATOR: StopPolicy(
        commands=(STOP_ALL,), hardware_line=False,
        release="after 0.5 s the worker's stop() sends X, P0, HF0; P0 alone if it did not",
        release_after_ms=500,
        recovery="operator re-home prompt once the load clears (S2)",
        outcome="stopped", flags={}, screen="stopping",
    ),
    ESTOP: StopPolicy(
        commands=(STOP_ALL,), hardware_line=True,
        release="after 1 s, as the operator stop; the stop line goes high after 2 s",
        release_after_ms=1000,
        recovery="operator re-home prompt once the load clears (S2)",
        outcome="fault", flags={}, screen="stopping",
    ),
    PHYSICAL: StopPolicy(
        commands=(), hardware_line=False,
        release="the firmware's own release; queued commands are dropped",
        release_after_ms=None,
        recovery="Reset in Setup",
        outcome="fault",
        flags={"physical_stop_active": True, "no_automatic_recovery": True,
               "initial_setup_complete": False},
        screen="fault",
    ),
    # With fault=False (a command the worker or reset reported as rejected, or
    # the pressure-progress Stop) the same stop latches "stopped" instead and
    # leaves the treatment banner alone.
    FAULT: StopPolicy(
        commands=(STOP_ALL, STOP_ALL, TELEMETRY_ON), hardware_line=False,
        release="none: no automatic movement", release_after_ms=None,
        recovery="Reset in Setup",
        outcome="fault",
        flags={"no_automatic_recovery": True, "initial_setup_complete": False},
        screen="fault",
    ),
    COMMAND_FAULT: StopPolicy(
        commands=(STOP_ALL,), hardware_line=False,
        release="none: no automatic movement", release_after_ms=None,
        recovery="Reset in Setup",
        outcome="fault",
        flags={"no_automatic_recovery": True, "initial_setup_complete": False},
        screen="fault",
    ),
    SHUTDOWN: StopPolicy(
        commands=RELEASE_SEQUENCE, hardware_line=False,
        release="P0 at shutdown; after a physical stop, queued commands are dropped instead",
        release_after_ms=None,
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
            ESTOP: self._estop_stop,
            FAULT: self._fault_stop,
            PHYSICAL: self._physical_stop,
            COMMAND_FAULT: self._command_rejected_stop,
            SHUTDOWN: self._shutdown_stop,
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
        if arduino is None or not arduino.send(RELEASE):
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

    def _estop_stop(self, outcome: str = "fault"):
        """Handle emergency stop button press."""
        window = self.window
        # Mark this as an intentional stop before any firmware responses can
        # arrive. Command rejections from the follow-up pressure-release
        # cleanup must not be mislabeled as a new physical device fault.
        window.protocol_stop_requested = True
        self.protocol.latch_session_outcome(outcome)
        # The banner's EMERGENCY STOP reaches here directly (not via the
        # Treatment screen's _on_estop), so clear the UI pause anchor here
        # too -- it used to survive an e-stop taken while paused, after
        # which PAUSE did nothing for every later treatment.
        window._paused_at = None
        # Assert the hardware EMERGENCYSTOP line FIRST - it does not depend
        # on the serial link being alive. setup_gpio() parks the pin HIGH
        # (run-permitted) at boot, so LOW is the asserted/stop state; it was
        # configured but never driven before. Released again in phase 3,
        # before the operator is asked to re-home: homing needs a live
        # machine. Polarity is inferred from the boot default - Phase E
        # hardware measurement must confirm before this ships to a device.
        try:
            GPIO.output(EMERGENCYSTOP, GPIO.LOW)
        except Exception:
            window.logger.exception("Could not assert EMERGENCYSTOP GPIO")
        # Logged only after the hardware line is asserted.
        window.logger.warning("Emergency stop triggered")
        if window.worker:
            window.worker.cancel()
        # arduino.send never blocks or reconnects; 'X' jumps the tx queue
        # and stop_actuators alarms the operator if the link is down.
        window.stop_actuators()
        self.protocol.finalize_session()
        # UI state changes come after both independent stop mechanisms so a
        # broken widget can never delay either safety action. The raw stop
        # flag above is already sufficient to classify an immediate reply.
        if hasattr(window, "protocol_state"):
            try:
                self.protocol.set_state("stopping")
            except Exception:
                window.logger.exception("Could not update emergency-stop UI state")
        # Use QTimer instead of sleep to avoid blocking UI
        QTimer.singleShot(1000, self._emergency_stop_phase2)

    def _emergency_stop_phase2(self):
        """Phase 2 of emergency stop after 1 second delay."""
        window = self.window
        if getattr(window, "_no_automatic_recovery", False) is True:
            return
        if getattr(window, "_closing", False) is True:
            return
        self._release_after_stop()
        # Continue to phase 3 after another second
        QTimer.singleShot(1000, self._emergency_stop_phase3)

    def _emergency_stop_phase3(self):
        """Phase 3: release the hardware stop line, then ask the operator to
        re-home (the reset sequence homes actuators, which needs the machine
        powered)."""
        if getattr(self.window, "_no_automatic_recovery", False) is True:
            return
        if getattr(self.window, "_closing", False) is True:
            return
        try:
            GPIO.output(EMERGENCYSTOP, GPIO.HIGH)
        except Exception:
            self.window.logger.exception("Could not release EMERGENCYSTOP GPIO")
        # Same release-then-ask ordering as the staged stop
        self._reset_after_release(time.time())

    def _fault_stop(self, reason: str, fault: bool = False) -> None:
        """Stop outputs and cancel producers without any automatic movement."""
        window = self.window
        window._no_automatic_recovery = True
        window.protocol_stop_requested = True
        self.protocol.latch_session_outcome("fault" if fault else "stopped")
        arduino = window.arduino
        # After the device's stop button the firmware has stopped every motor
        # and is releasing the load by itself; an X would end that release.
        send_stop = (arduino is not None
                     and getattr(window, "_physical_stop_active", False) is not True)
        if send_stop:
            arduino.send(STOP_ALL)
        window.connection.cancel_reset()
        if window.worker:
            # The explicit stop here owns output cleanup; stop() must not issue P0.
            window.worker.cancel(firmware_stopped=True)
        if send_stop:
            arduino.send(STOP_ALL)
        if arduino is not None:
            arduino.send(TELEMETRY_ON)
            arduino.baseline_valid = False
        window._release_leg_gpio()
        window.protocol_timer.stop()
        window.initial_setup_complete = False
        self.protocol.set_state("fault")
        window.shell.setup.set_reset_enabled(not window.reset_in_progress)
        window.on_baseline_changed(False)
        if fault:
            window.treatment_panel.set_fault(reason)
        self.protocol.finalize_session()

    def _physical_stop(self) -> None:
        """Latch the physical stop on the host while firmware releases traction."""
        window = self.window
        window._no_automatic_recovery = True
        window.connection.cancel_reset()
        window.logger.error("Physical emergency stop activated")
        already_stopped = getattr(window, "_physical_stop_active", False) is True
        protocol = self.protocol
        if protocol is not None:
            protocol.latch_session_outcome("fault")
        window._physical_stop_active = True
        window.protocol_stop_requested = True
        window.initial_setup_complete = False
        if window.worker:
            window.worker.cancel(firmware_stopped=True)
        if window.arduino:
            window.arduino.cancel_pending_commands()
        try:
            window._release_leg_gpio()
        except Exception:
            window.logger.exception("Could not release leg GPIO after physical stop")
        window._paused_at = None
        window.protocol_timer.stop()
        window.set_protocol_state("fault")
        window.disable_actuator_controls()
        window.shell.setup.set_reset_enabled(not window.reset_in_progress)
        window.treatment_panel.set_fault("PHYSICAL EMERGENCY STOP")
        if not already_stopped:
            window._show_safety_alert(
                "Physical emergency stop activated. Release the button and reset "
                "the device before starting another treatment."
            )

    def _command_rejected_stop(self, message: str) -> None:
        """Halt after the firmware rejected a command outside a stop.

        Halts the treatment state machine, but identifies it as a command
        failure rather than a device safety trip.
        """
        window = self.window
        protocol = self.protocol
        if protocol is not None:
            protocol.latch_session_outcome("fault")
        window.stop_actuators()
        window._no_automatic_recovery = True
        window.initial_setup_complete = False
        if window.protocol_running and window.worker:
            try:
                window.worker.cancel()
            except Exception:
                window.logger.exception("Error flagging worker stop")
        fault = f"COMMAND REJECTED: {message}"
        window.treatment_panel.set_fault(fault)
        window.set_protocol_state("fault")
        window._show_timed_error(
            f"The device rejected a command: {message}. Reset before continuing."
        )

    def _shutdown_stop(self) -> None:
        """Stop the device as the app closes, before resources are released.

        No automatic recovery, the session latched as "fault", producers and
        timers stopped, then X, P0 and HF0 -- or, after a physical stop, the
        queued commands dropped so X cannot abort the firmware's release.
        """
        window = self.window
        window._no_automatic_recovery = True
        self.protocol.latch_session_outcome("fault")
        window.connection.cancel_reset()
        if window.worker:
            window.worker.cancel(firmware_stopped=window._physical_stop_active)
        if getattr(window, "_calibration_active", False) is True:
            window.hardware_service.shutdown()
        for name in ("protocol_timer", "controls_enable_timer", "_cloud_retry_timer",
                     "_pressure_state_timer", "_motion_watchdog"):
            timer = getattr(window, name, None)
            if timer is not None:
                timer.stop()
        arduino = window.arduino
        if arduino is not None:
            arduino._connect_cancel.set()
            if window._physical_stop_active:
                arduino.cancel_pending_commands()
            else:
                for command in RELEASE_SEQUENCE:
                    arduino.send(command)
        window._release_leg_gpio()
        self.protocol.finalize_session()
