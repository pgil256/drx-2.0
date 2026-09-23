# controllers/protocol_controller.py
"""Protocol lifecycle, extracted from the KneeSpa window.

Owns the idle/starting/running/stopping/fault state machine and the
start/stop/completion flow. State attributes (protocol_state,
protocol_running, worker, timers) stay on the window: many widgets and
other controllers read them; this module owns the transitions.
"""
import time
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
from typing import Dict, Optional

import RPi.GPIO as GPIO
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox

from helpers import protocols
from helpers.cloud_contract import end_settings
from helpers.treatment_session import TreatmentSession
from controllers.machine_sign_in_controller import authorize
from ui.modals.treatment_review import TreatmentReviewDialog

try:
    from main.config.constants import DATA_PATHS, EMERGENCYSTOP
except ModuleNotFoundError:
    from config.constants import DATA_PATHS, EMERGENCYSTOP


class ProtocolController:
    # Bound on waiting for the post-stop P0 release to unload the patient
    # before the recovery reset runs. The reset's 'Y' reboots the MCU (which
    # aborts an in-flight pressure move) and the homing sequence retracts the
    # axial actuator LAST, so resetting 1 s after stop left the limb under
    # load for the whole homing sequence.
    RELEASE_WAIT_S = 20.0
    RELEASE_DONE_LBS = 5.0  # mirrors firmware PRESSURE_RELEASE_LBS
    _RELEASE_POLL_MS = 250

    def __init__(self, window):
        self.window = window
        self._session: Optional[TreatmentSession] = None
        self._prepared = False

    def set_state(self, state):
        """Single source of truth for the protocol lifecycle.

        Drives the Start/Stop button, the treatment banner, and navigation
        gating together so they can no longer desync (the button text used
        to be the de-facto state and could show "Stop" with nothing
        running, or vice versa).
        """
        window = self.window
        previous = window.protocol_state
        if state == "fault":
            self.latch_session_outcome("fault")
            self.finalize_session()
        print(f"Protocol state: {window.protocol_state} -> {state}")
        window.protocol_state = state
        window.protocol_running = state in ("starting", "running", "stopping")

        if state == "idle":
            self._set_run_state(False)
            self.set_busy(window.reset_in_progress is True)
            window.treatment_panel.set_idle()
        elif state == "starting":
            self._set_run_state(True)
            self.set_busy(True)
        elif state == "running":
            self._set_run_state(True)
            self.set_busy(False)
        elif state == "stopping":
            self.set_busy(True)
            window.treatment_panel.set_stopping()
        elif state == "fault":
            self._set_run_state(False)
            # A fault is not treatment-ready. Recovery reset is the only path
            # back to idle.
            self.set_busy(True)
        # Videos may stay open while treatment runs (the player has its own
        # STOP). A stop, fault or finish closes it so the operator sees the
        # Treatment page and any recovery prompts.
        try:
            if state in ("starting", "running"):
                window.shell.close_nonessential_overlays(keep_video=True)
            elif state == "stopping":
                window.shell.close_nonessential_overlays()
            elif previous in ("starting", "running", "stopping"):
                window.shell.close_video()
        except Exception:
            pass
        refresh = getattr(window, "_refresh_device_presentation", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                # A display failure must not interrupt the lifecycle's safety work.
                window.logger.exception("Could not refresh device presentation")

    def _set_run_state(self, running: bool) -> None:
        """Present an unpaused lifecycle transition without delaying safety work."""
        try:
            self.window.shell.treatment.set_run_state(running=running, paused=False)
        except Exception:
            pass

    def set_busy(self, busy: bool) -> None:
        """Gate treatment controls during transitions and connection/reset work."""
        try:
            self.window.shell.treatment.set_busy(busy)
        except Exception:
            pass

    def confirm_leave_treatment(self, source_page: str, destination_page: str) -> bool:
        """Warn before leaving the Treatment screen during an active protocol.

        The protocol continues to own the hardware after navigation. Returning
        ``False`` lets the operator cancel the navigation from the warning.
        """
        window = self.window
        active = window.protocol_state in ("starting", "running", "stopping")
        leaving_treatment = source_page == "protocols" and destination_page != source_page
        if not active or not leaving_treatment:
            return True

        result = QMessageBox.warning(
            window,
            "Caution",
            (
                "Caution: An active treatment protocol is in progress. Leaving the "
                "Treatment screen does not stop the protocol; it will continue to run.\n\n"
                "Press OK to leave the screen, or Cancel to stay and monitor treatment."
            ),
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return result == QMessageBox.Ok

    def block_active_treatment_exit(self) -> bool:
        """Block logout or application exit while a protocol owns the hardware."""
        window = self.window
        if window.protocol_state in ("starting", "running", "stopping"):
            window._show_timed_error(
                "Treatment in progress - press STOP before logging out or exiting."
            )
            return True
        return False

    def block_video_overlay(self) -> bool:
        """Videos stay available during treatment, but not while it is stopping."""
        window = self.window
        if window.protocol_state == "stopping":
            window._show_timed_error(
                "Treatment is stopping - videos are available again once it has stopped."
            )
            return True
        return False

    def block_nonessential_overlay(self) -> bool:
        """Keep nonessential overlays closed while a protocol is active."""
        window = self.window
        if window.protocol_state in ("starting", "running", "stopping"):
            window._show_timed_error(
                "Treatment in progress - return after the protocol has stopped."
            )
            return True
        return False

    def panel_stop_requested(self):
        """Emergency stop pressed on the always-visible treatment banner."""
        print("Panel EMERGENCY STOP pressed")
        self.emergency_stop_clicked(None)


    def confirm_start(self):
        """Summarize the treatment parameters and require confirmation.

        Starting traction on a patient used to be a single unguarded
        touch event.
        """
        window = self.window
        try:
            protocol = int(window.protocol_value)
            if protocol not in (1, 2, 3, 4):
                return False
            settings = dict(window.shell.treatment.settings_values())
            settings["duration"] = int(window._duration_minutes())
        except Exception as e:
            print(f"Error reading protocol parameters for confirmation: {e}")
            return False

        patient = getattr(window, "cloud_patient", None)
        if patient:
            name = (patient.get("display_name") or patient.get("external_ref")
                    or patient["patient_id"])
            patient_summary = f"Patient: {name}"
        else:
            patient_summary = "No cloud patient linked. This treatment will not upload."
        return TreatmentReviewDialog.confirm(window, protocol, settings, patient_summary)


    def start_or_stop(self) -> None:
        """Toggle the lifecycle and finish the existing start-phase presentation."""
        self._toggle_start_stop()
        if self.window.protocol_state == "running":
            try:
                self.window.shell.treatment.set_phase("ramping")
            except Exception:
                pass

    def _toggle_start_stop(self) -> None:
        """Start or stop the protocol with debouncing to prevent multiple rapid clicks."""
        window = self.window
        print("Toggling protocol start/stop")
        if window.protocol_state == "idle" and not authorize(
                window, "treatment", self.start_or_stop):
            return

        # Prevent rapid clicking by disabling the button during operation
        self.set_busy(True)

        try:
            if window.protocol_state == "fault":
                window._show_timed_error(
                    "Recover/reset the device before starting another treatment."
                )
                self.set_state("fault")
                return
            if window.protocol_state == "idle":
                if not self.confirm_start():
                    self.set_state(window.protocol_state)
                    return
                # confirm_start ran a nested event loop: a firmware fault or
                # a reset may have arrived while the dialog was up. Re-check
                # before arming, or the "starting" transition would override
                # the fault and run on a device the monitor just flagged.
                if (
                    window.protocol_state != "idle"
                    or window.reset_in_progress is True
                ):
                    window._show_timed_error(
                        "Device state changed while confirming; treatment not started."
                    )
                    self.set_state(window.protocol_state)
                    return
                self.set_state("starting")
                connected = window.ensure_arduino_connection()
                # Reconnection also pumps Qt events. A fault, stop or reset
                # received there invalidates the confirmed start request.
                if (
                    window.protocol_state != "starting"
                    or window.reset_in_progress is True
                ):
                    if window.protocol_state == "starting":
                        self.set_state("idle")
                    window._show_timed_error(
                        "Device state changed while connecting; treatment not started."
                    )
                    return
                if not connected:
                    window._show_timed_error(
                        "Arduino connection is not ready. Check connections and try again."
                    )
                    self.set_state("idle")
                    return
                if not self.start_protocol():
                    if window.protocol_state == "starting":
                        self.set_state("idle")
                    return
                # Dispatch is not preparation completion. The worker's prepared
                # signal owns the running transition and treatment clock.
            else:
                self._set_run_state(True)
                self.stop_protocol()
        except Exception as e:
            print(f"Error during protocol operation: {e}")
            window.logger.exception("Protocol start/stop transition failed")
            if window.protocol_state in ("fault", "stopping"):
                # A nested event may already have started fault/stop recovery.
                # Keep both its state and its worker reference intact.
                self.set_state(window.protocol_state)
            else:
                window.worker = None
                window.protocol_timer.stop()
                window.protocol_start_time = None
                window.protocol_stop_requested = False
                self.set_state("idle")
            window._show_timed_error(f"Could not complete treatment operation: {e}")


    def start_protocol(self):
        """Start protocol execution."""
        window = self.window
        if not authorize(window, "treatment", self.start_protocol):
            return False
        if getattr(window, "_patient_lookup_pending", False) is True:
            window._show_timed_error(
                "Wait for patient lookup or choose treatment without a patient."
            )
            return False
        if (getattr(window, "_calibration_active", False) is True
                or getattr(window, "_device_maintenance_active", False) is True):
            window._show_timed_error("Finish device service before starting treatment.")
            return False
        if (window.protocol_state not in ("idle", "starting")
                or getattr(window, "initial_setup_complete", False) is not True
                or any(getattr(window, flag, False) is True for flag in (
                    "_closing", "_physical_stop_active", "_no_automatic_recovery",
                    "reset_in_progress", "actuator_command_in_progress",
                ))):
            window._show_timed_error("Finish recovery/reset and movement before starting treatment.")
            return False
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
            protocol = str(window.protocol_value)
            if protocol not in ["1", "2", "3", "4"]:
                raise ValueError(f"Invalid protocol number: {protocol}")

            # Keep these live reads after confirmation and connection checks.
            duration = 12  # Default to 12 minutes
            try:
                duration = int(window._duration_minutes())
            except Exception as e:
                print(f"Error getting time value: {e}, using default 5 minutes")

            if duration == 0:
                duration = 12  # Ensure we have a valid duration

            print(f"Protocol duration: {duration} minutes")
            max_pressure = int(window.shell.treatment.settings_values().get("max_pressure", 50))
            max_left_from_slider = int(window.shell.treatment.settings_values().get("max_left", 10))
            max_right_from_slider = int(
                window.shell.treatment.settings_values().get("max_right", 10)
            )

            # The worker expects max_left to be negative
            max_left_for_worker = -abs(max_left_from_slider)
            max_right_for_worker = abs(max_right_from_slider)

            use_pulse = window.current_use_pulse_setting # Use the tracked state
            # Pulse cadence from the modern Settings slider (None on the
            # legacy UI). Only acts on flag-gated J<ms> firmware; otherwise
            # the worker falls back to bare J (see helpers.protocols).
            pulse_rate = getattr(window, "current_pulse_rate", None)

            # Preparation belongs to the cancellable worker. Its typed centering
            # and baseline replies precede both pressure and the treatment clock.
            self._prepared = False
            window.protocol_duration = duration * 60  # Convert to seconds
            window.protocol_start_time = None

            window.mid_protocol_warning_shown = False
            window.protocol_stop_requested = False
            self._set_run_state(True)

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
                motor_speeds=window.shell.treatment.settings_values(),
            )

            patient = deepcopy(window.cloud_patient)
            session = TreatmentSession(
                patient_id=str(patient["patient_id"]) if patient else None,
                protocol_number=int(protocol), planned_duration_s=duration * 60,
            )
            # Bind callbacks to this session; queued signals from a retired
            # worker must never finish/reset or relabel a newer treatment.
            window.worker.signals.finished.connect(
                partial(self.protocol_completed, session=session)
            )
            window.worker.signals.progress.connect(partial(self._session_progress, session=session))
            window.worker.signals.motor_speed_failed.connect(window._show_timed_error)
            window.worker.signals.prepared.connect(partial(self._on_prepared, session=session))
            window.worker.signals.operation_failed.connect(
                partial(self._on_operation_failed, session=session)
            )
            window.worker.signals.baseline_changed.connect(window.on_baseline_changed)
            window.protocol_running = True
            # Freeze the association before dispatch, and invalidate any lookup
            # that could arrive after this treatment has already ended.
            window._patient_lookup_id += 1
            window._treatment_patient = patient
            window.mid_protocol_warning_shown = False

            self.set_state("starting")

            # Always-visible treatment banner: live values arrive via
            # status_emit; the countdown via update_protocol_time
            window.treatment_panel.set_running(max_pressure, duration * 60)

            # Finish UI/signal setup before dispatch: a fast worker may emit
            # progress or finish as soon as the thread pool starts it.
            self._set_phase_from_text("Preparing treatment")
            window.shell.treatment.set_progress(0, duration * 60)
            self._session = session
            try:
                window.threadpool.start(window.worker)
            except Exception:
                self._session = None  # Dispatch failed: no treatment was started.
                window._treatment_patient = None
                window.protocol_timer.stop()
                window.protocol_start_time = None
                window.protocol_running = False
                window.worker = None
                raise
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


    def _on_prepared(self, wall_time: float, clock_time: float,
                     session: TreatmentSession) -> None:
        window = self.window
        if (session is not self._session or session.finalized or window._closing
                or window.protocol_stop_requested or window.protocol_state == "fault"):
            return
        self._prepared = True
        session.started_at = datetime.fromtimestamp(wall_time, timezone.utc)
        session.started_clock = clock_time
        window.protocol_start_time = wall_time
        self.set_state("running")
        window.protocol_timer.start()

    def _on_operation_failed(self, reason: str, session: TreatmentSession) -> None:
        if session is not self._session or self.window._closing:
            return
        if self.window.reset_in_progress:
            return  # A late result from cancelled treatment cannot cancel explicit recovery.
        if (self.window.protocol_state == "fault"
                and self.window._no_automatic_recovery):
            return  # The firmware fault already owns the operator-facing result.
        self.window.safety.on_controller_fault({"reason": reason})

    def stop_without_recovery(self, reason: str, fault: bool = False) -> None:
        """Stop outputs and cancel producers without any automatic movement."""
        window = self.window
        window._no_automatic_recovery = True
        window.protocol_stop_requested = True
        self.latch_session_outcome("fault" if fault else "stopped")
        arduino = window.arduino
        if arduino is not None:
            arduino.send("X")
        window.connection.cancel_reset()
        if window.worker:
            # The explicit stop here owns output cleanup; stop() must not issue P0.
            window.worker.cancel(firmware_stopped=True)
        if arduino is not None:
            arduino.send("X")
            arduino.send("HF1")
            arduino.baseline_valid = False
        window._release_leg_gpio()
        window.protocol_timer.stop()
        window.initial_setup_complete = False
        self.set_state("fault")
        window.shell.setup.set_reset_enabled(not window.reset_in_progress)
        window.on_baseline_changed(False)
        if fault:
            window.treatment_panel.set_fault(reason)
        self.finalize_session()

    def stop_protocol(self):
        """Stop protocol sequence."""
        window = self.window
        print("Stopping protocol")
        window.protocol_stop_requested = True
        self.latch_session_outcome("stopped")
        # Cancel the producer before X clears queued work. Waiting until phase
        # 2 allowed the worker to enqueue fresh motion after the stop command.
        if window.worker:
            window.worker.cancel()
        window.stop_actuators()
        self.finalize_session()
        self.set_state("stopping")
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
        if window.worker:
            window.worker.stop()
        # Continue to phase 3 after another 0.5 seconds
        QTimer.singleShot(500, self._stop_phase3)

    def _stop_phase3(self):
        """Phase 3 of stop protocol - recovery reset once the load has cleared."""
        # Keep the explicit stopping state until either the worker reports a
        # user-requested completion or reset recovery finishes.
        self._reset_after_release(time.time())

    def _reset_after_release(self, started):
        """Run the recovery reset once the P0 release has unloaded the patient,
        or after RELEASE_WAIT_S. ``last_measured_pressure`` is fed by the
        firmware's status frames (kneespa.status_emit); None means no telemetry
        has ever arrived (dev launcher / link never up), so there is nothing to
        wait for."""
        window = self.window
        if getattr(window, "_no_automatic_recovery", False) is True:
            return
        if getattr(window, "_closing", False) is True:
            return
        if getattr(window, "_physical_stop_active", False) is True:
            return  # Physical stops require an explicit operator recovery.
        pressure = getattr(window, "last_measured_pressure", None)
        released = (
            pressure is None
            or (isinstance(pressure, (int, float)) and pressure < self.RELEASE_DONE_LBS)
        )
        waited = time.time() - started
        if released or waited >= self.RELEASE_WAIT_S:
            if not released:
                window.logger.warning(
                    "Release did not clear within %.0fs (pressure=%s); resetting anyway",
                    waited, pressure,
                )
            window.reset_arduino()
            return
        QTimer.singleShot(
            self._RELEASE_POLL_MS, lambda: self._reset_after_release(started)
        )


    def protocol_completed(self, success=True, session: Optional[TreatmentSession] = None):
        """Handle protocol completion."""
        window = self.window
        if getattr(window, "_closing", False) is True:
            return
        if session is not None and session is not self._session:
            return
        if self._session is not None:
            # A fault/stop may already have finalized the cloud record. That
            # must not suppress this worker's pressure-release cleanup.
            if self._session.completion_handled:
                return
            self._session.completion_handled = True
        print(f"Protocol completed; success={success}")
        user_stopped = bool(getattr(window, "protocol_stop_requested", False))
        safety_fault_active = getattr(window, "protocol_state", "") == "fault"
        outcome = self._completion_outcome(success, user_stopped, safety_fault_active)
        self.latch_session_outcome(outcome)
        captured_settings = self._capture_end_settings()
        window.protocol_timer.stop()
        # The UI pause anchor must not outlive the run (PAUSE was permanently
        # inert after a run that ended while paused)
        window._paused_at = None

        self.finalize_session(captured_settings)

        if window.reset_in_progress:
            return  # The explicit recovery now owns controls/readiness.

        try:
            self._set_phase_from_text(
                "Protocol complete" if success else "Protocol stopped"
            )
        except Exception as e:
            print(f"Error updating status label: {e}")
        window.mid_protocol_warning_shown = False
        if safety_fault_active:
            # Preserve an existing command/device fault. A later worker
            # completion must neither clear it nor stack another notice.
            self.set_state("fault")
        elif user_stopped:
            # The staged stop still owes the patient a recovery reset. Keep
            # Start/navigation gated until _on_reset_finished confirms it,
            # even if a successful completion was queued just before STOP.
            self.set_state("stopping")
        elif success:
            self.set_state("idle")
        else:
            self.set_state("fault")
            window.initial_setup_complete = False
            window.shell.setup.set_reset_enabled(True)
        if not user_stopped:
            window.protocol_stop_requested = False

    def _upload_treatment(self, success, user_stopped, safety_fault_active):
        self.latch_session_outcome(
            self._completion_outcome(success, user_stopped, safety_fault_active)
        )
        self.finalize_session()

    @staticmethod
    def _completion_outcome(success: bool, user_stopped: bool, safety_fault_active: bool) -> str:
        if safety_fault_active:
            return "fault"
        if user_stopped:
            return "stopped"
        return "completed" if success else "fault"

    def latch_session_outcome(self, outcome: str) -> None:
        """Latch only in-memory timing/reason before any cancel/reset cleanup."""
        if self._session is not None:
            if not self._prepared:
                self._session.actual_duration_s = 0
            self._session.latch(outcome)

    def _capture_end_settings(self) -> Optional[Dict[str, float]]:
        try:
            return end_settings(self.window.shell.treatment.settings_values())
        except Exception:
            self.window.logger.exception("Could not snapshot ending treatment settings")
            return None

    def finalize_session(self, settings: Optional[Dict[str, float]] = None) -> None:
        """Capture once, then delegate all disk/network work to the cloud executor."""
        session = self._session
        if session is None or session.finalized or session.outcome is None:
            return
        window = self.window
        try:
            if settings is None:
                settings = end_settings(window.shell.treatment.settings_values())
            record = session.finish(settings)
            client = getattr(window, "cloud_client", None)
            if record is not None and client is not None:
                client.post_treatment_async(record, pending_path=DATA_PATHS["PENDING_UPLOADS"])
        except Exception:
            # Recording must never interrupt motion/stop handling. Keep the
            # session context for diagnosis and show the failed save explicitly.
            window.logger.exception("Could not capture treatment record")
            try:
                window.shell.treatment.set_cloud_status(
                    "Treatment record needs attention; contact support"
                )
                window._cloud_bridge.upload_failed.emit(
                    "The treatment record could not be saved for upload. Contact support.", False
                )
            except Exception:
                window.logger.error("Could not display the treatment recording failure")
        try:
            window.shell.treatment.set_outcome(session.outcome, session.elapsed())
        except Exception:
            window.logger.exception("Could not display treatment outcome")
        sign_in = getattr(window, "machine_sign_in", None)
        if sign_in is not None:
            try:
                sign_in.treatment_finished()
            except Exception:
                window.logger.error("Could not finish sign-out presentation after treatment")

    def _session_progress(self, text: str, session: TreatmentSession) -> None:
        if session is self._session and not session.finalized:
            self.update_status_label(text)

    def update_protocol_time(self):
        """Update the protocol timer display."""
        window = self.window
        if not window.protocol_start_time:
            return

        elapsed_time = int(time.time() - window.protocol_start_time)
        remaining_time = max(0, window.protocol_duration - elapsed_time)

        # Always-visible banner countdown (not gated on any dialog)
        window.treatment_panel.update_remaining(remaining_time)

        if remaining_time == 0:
            window.protocol_timer.stop()
            window.protocol_start_time = None

    def _reset_after_failure(self, session: Optional[TreatmentSession] = None) -> None:
        """Do not let a queued worker failure reset a physical emergency stop."""
        if getattr(self.window, "_no_automatic_recovery", False) is True:
            return
        if session is not None:
            if session is not self._session or session.reset_requested:
                return
            # Workers emit finished(False) BEFORE reset_needed. Completing the
            # record must not swallow that recovery request for the same run.
            if session.finalized and session.outcome != "fault":
                return
            session.reset_requested = True
        self.latch_session_outcome("fault")
        self.finalize_session()
        if getattr(self.window, "_physical_stop_active", False) is not True:
            self.window.reset_arduino()


    def emergency_stop_clicked(self, event, outcome: str = "fault"):
        """Handle emergency stop button press."""
        window = self.window
        print("Emergency stop triggered")
        # Mark this as an intentional stop before any firmware responses can
        # arrive. Command rejections from the follow-up pressure-release
        # cleanup must not be mislabeled as a new physical device fault.
        window.protocol_stop_requested = True
        self.latch_session_outcome(outcome)
        # The banner's EMERGENCY STOP reaches here directly (not via the
        # Treatment screen's _on_estop), so clear the UI pause anchor here
        # too -- it used to survive an e-stop taken while paused, after
        # which PAUSE did nothing for every later treatment.
        window._paused_at = None
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
        if window.worker:
            window.worker.cancel()
        # arduino.send never blocks or reconnects; 'X' jumps the tx queue
        # and stop_actuators alarms the operator if the link is down.
        window.stop_actuators()
        self.finalize_session()
        # UI state changes come after both independent stop mechanisms so a
        # broken widget can never delay either safety action. The raw stop
        # flag above is already sufficient to classify an immediate reply.
        if hasattr(window, "protocol_state"):
            try:
                self.set_state("stopping")
            except Exception as e:
                print(f"Could not update emergency-stop UI state: {e}")
        # Use QTimer instead of sleep to avoid blocking UI
        QTimer.singleShot(1000, self._emergency_stop_phase2)

    def _emergency_stop_phase2(self):
        """Phase 2 of emergency stop after 1 second delay."""
        window = self.window
        if getattr(window, "_no_automatic_recovery", False) is True:
            return
        if getattr(window, "_closing", False) is True:
            return
        if window.worker:
            window.worker.stop()
        # Continue to phase 3 after another second
        QTimer.singleShot(1000, self._emergency_stop_phase3)

    def _emergency_stop_phase3(self):
        """Phase 3: release the hardware stop line, then run the recovery
        reset (the reset sequence homes actuators, which needs the machine
        powered)."""
        if getattr(self.window, "_no_automatic_recovery", False) is True:
            return
        if getattr(self.window, "_closing", False) is True:
            return
        try:
            GPIO.output(EMERGENCYSTOP, GPIO.HIGH)
        except Exception as e:
            print(f"Could not release EMERGENCYSTOP GPIO: {e}")
        # Same release-then-reset ordering as the staged stop
        self._reset_after_release(time.time())


    def update_status_label(self, text):
        """Mirror worker phase messages on the persistent status label
        and the treatment banner."""
        window = self.window
        clean = str(text).lstrip(">")
        try:
            self._set_phase_from_text(clean)
        except Exception as e:
            print(f"Error updating status label: {e}")
        window.treatment_panel.set_phase(clean.upper())

    def _set_phase_from_text(self, text: str) -> None:
        """Map legacy progress text in precedence order; retain unknown phases."""
        lowered = str(text).lower()
        if "prepar" in lowered:
            phase = "starting"
        elif "pulsing" in lowered:
            phase = "pulsing"
        elif "oscillat" in lowered:
            phase = "oscillating"
        elif "moving to" in lowered:
            phase = "positioning"
        elif "complete" in lowered:
            phase = "complete"
        elif "stopped" in lowered:
            phase = "stopped"
        elif "started" in lowered or "pressure" in lowered:
            phase = "ramping"
        else:
            return
        try:
            self.window.shell.treatment.set_phase(phase)
        except Exception:
            pass

    def pause(self) -> None:
        """Pause the worker and countdown, then present the paused controls."""
        window = self.window
        if window.worker and window.protocol_running and not window._paused_at:
            window.worker.pause()
            if self._session is not None:
                self._session.pause()
            window._paused_at = time.time()
            if window.protocol_timer.isActive():
                window.protocol_timer.stop()
            try:
                window.shell.treatment.set_run_state(running=True, paused=True)
                window.shell.treatment.set_phase("paused")
            except Exception:
                pass

    def resume(self) -> None:
        """Resume the worker, excluding paused time from the UI countdown."""
        window = self.window
        if window.worker and window.protocol_running and window._paused_at:
            window.worker.resume()
            if self._session is not None:
                self._session.resume()
            if window.protocol_start_time is not None:
                window.protocol_start_time += time.time() - window._paused_at
            window._paused_at = None
            window.protocol_timer.start(1000)
            try:
                window.shell.treatment.set_run_state(running=True, paused=False)
                window.shell.treatment.set_phase(
                    "pulsing" if window.current_use_pulse_setting else "holding"
                )
            except Exception:
                pass

    def stop_from_view(self) -> None:
        """Run the screen STOP chain, then present its stopped controls."""
        window = self.window
        self.emergency_stop_clicked(None, outcome="stopped")
        window._paused_at = None
        if window.protocol_timer.isActive():
            window.protocol_timer.stop()
        try:
            window.shell.treatment.set_run_state(running=False, paused=False)
            window.shell.treatment.set_phase("stopped")
        except Exception:
            pass
