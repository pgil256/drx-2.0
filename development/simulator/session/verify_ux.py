"""Scripted operator workflows through the real GUI and simulated hardware.

These are repeatable software sessions, not human participants or physical tests.
Use the normal controllers, clocks, PIN gates, outbox, and local cloud adapter.
"""

import json
import time
from pathlib import Path
from typing import Callable, Iterator

from PyQt5.QtCore import QPoint, Qt, QTimer
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

from simulator.session.verify import GuiVerification


class UxVerification(GuiVerification):
    """Observe patient preparation, review, recovery and secondary workflows."""

    def note(self, label: str, **observations: object) -> None:
        self.results.append({"check": label, "sim_time": self.state["sim_time"],
                             "wall_time": time.time(),
                             "observations": observations})
        print("VERIFY passed:", label, flush=True)

    def enter_pin(self, parent: object, pin: str) -> None:
        for digit in pin:
            self.click(self.named(parent, digit))

    def dismiss_messages(self) -> None:
        for dialog in QApplication.topLevelWidgets():
            if isinstance(dialog, QMessageBox) and dialog.isVisible():
                button = dialog.button(QMessageBox.Ok)
                if button is not None:
                    self.click(button)

    def after(self, seconds: float) -> Callable[[], bool]:
        deadline = time.monotonic() + seconds
        return lambda: time.monotonic() >= deadline

    def assert_contained(self, widget: object, root: object) -> None:
        assert widget.isVisible(), f"Hidden control: {widget.objectName()}"
        ancestor = widget.parentWidget()
        while ancestor is not None:
            bounds = widget.rect().translated(widget.mapTo(ancestor, QPoint()))
            assert ancestor.rect().contains(bounds), (
                type(widget).__name__, bounds, type(ancestor).__name__, ancestor.rect()
            )
            if ancestor is root:
                break
            ancestor = ancestor.parentWidget()

    def capture_layout(self, name: str) -> None:
        """Capture each actual controller-driven state at both target resolutions."""
        w, shell = self.window, self.window.shell
        for width in (1360, 1366):
            w.setFixedSize(width, 768)
            QApplication.processEvents()
            if shell.treatment.isVisible() and not shell.patient_modal.isVisible():
                view = shell.treatment
                assert view._estop_btn.isEnabled() and view._estop_btn.height() >= 72
                for button in (view._start_btn, view._pause_btn, view._estop_btn):
                    self.assert_contained(button, shell)
                stop = view._estop_btn
                hit = w.childAt(stop.mapTo(w, stop.rect().center()))
                assert hit is stop or stop.isAncestorOf(hit), "Stop covered by an overlay"
                for control in view._settings.values():
                    if control.isVisible():
                        for button in (control._left_btn, control._right_btn):
                            self.assert_contained(button, shell)
                            assert button.width() >= 48 and button.height() >= 48
                self.assert_contained(view._patient_label, shell)
                self.assert_contained(view._readiness, shell)
            self.save(f"ux-{name}-{width}")
        self.note(name + " layout", resolutions=["1360x768", "1366x768"])

    def review(self, start: bool, expected_protocol: int) -> None:
        """Inspect and dismiss the real modal without bypassing preflight."""
        from ui.modals.treatment_review import TreatmentReviewDialog

        errors = []

        def respond() -> None:
            dialog = next((d for d in QApplication.topLevelWidgets()
                           if isinstance(d, TreatmentReviewDialog) and d.isVisible()), None)
            try:
                assert dialog is not None, "Review dialog did not appear"
                rows = dict(dialog._rows)
                assert ("Left angle" in rows) == (expected_protocol in (2, 4))
                assert ("Right angle" in rows) == (expected_protocol in (3, 4))
                assert rows["Duration"] == "5 min"
                assert rows["Pressure limit"] == "20 lbs"
                assert "Simulator test patient" in dialog._patient.text()
                for button in (dialog.back_button, dialog.start_button):
                    self.assert_contained(button, dialog)
                    assert button.height() >= 48
                dialog.grab().save(str(self.directory / f"ux-review-{expected_protocol}.png"))
                self.note(f"protocol {expected_protocol} review",
                          parameters=rows, action="Start" if start else "Back")
                self.click(dialog.start_button if start else dialog.back_button)
            except Exception as exc:
                errors.append(exc)
                if dialog is not None:
                    dialog.reject()

        QTimer.singleShot(300, respond)
        self.click(self.window.shell.treatment._start_btn)
        if errors:
            raise errors[0]

    def pending_records(self) -> list:
        from config.constants import DATA_PATHS

        path = self.directory / "device/raspberry-pi/data"
        pending = Path(DATA_PATHS["PENDING_UPLOADS"])
        assert pending.is_relative_to(path), "Outbox escaped the synthetic session"
        return json.loads(pending.read_text()) if pending.exists() else []

    def _steps(self) -> Iterator[tuple]:
        w, shell = self.window, self.window.shell
        yield self.wait("cold initialization and baseline", lambda: w.initial_setup_complete
                        and w.arduino.baseline_valid and not w.reset_in_progress)
        self.dismiss_messages()
        self.click(shell.nav_rail._buttons["setup"])
        yield self.wait("Setup login gate", lambda: shell.login_modal.isVisible())
        self.enter_pin(shell.login_modal, "5678")
        yield self.wait("operator returns to Setup", lambda: shell.setup.isVisible()
                        and bool(w.current_user))
        assert not w._is_admin()
        self.capture_layout("operator-setup")

        # A target edit must remain pending while real sensor packets keep arriving.
        row = shell.setup._rows["pressure"]
        self.click(row.motion_buttons[2])
        target = row.slider.value()
        assert target > 0
        yield self.wait("target edit observed over telemetry", self.after(1.5))
        assert row.slider.value() == target
        assert abs(self.state["pose"]["force_lb"]) < 1
        assert shell.setup._pos["pressure"]._value.text() != f"{target:g} lbs"
        self.note("pressure edit does not command movement", target=target,
                  measured=shell.setup._pos["pressure"]._value.text())
        self.capture_layout("pending-target")

        # A routine operator cannot enroll the separate service PIN.
        self.click(shell.setup._calibration)
        from ui.modals.service_pin_dialog import ServicePinDialog
        yield self.wait("technician PIN gate", lambda: any(
            isinstance(d, ServicePinDialog) and d.isVisible()
            for d in QApplication.topLevelWidgets()))
        gate = next(d for d in QApplication.topLevelWidgets()
                    if isinstance(d, ServicePinDialog) and d.isVisible())
        assert not gate.keypad.isEnabled()
        assert "administrator" in gate.message.text().lower()
        self.click(self.named(gate, "Cancel"))
        self.note("operator cannot provision service access")

        self.click(shell.nav_rail._buttons["protocols"])
        view = shell.treatment
        self.click(view._patient_button)
        self.enter_pin(shell.patient_modal, "0000")
        yield self.wait("unknown patient PIN reported", lambda: not w._patient_lookup_pending
                        and "dashboard" not in shell.patient_modal._status.text()
                        and "Looking" not in shell.patient_modal._status.text())
        assert w.cloud_patient is None
        self.capture_layout("unknown-patient")
        self.enter_pin(shell.patient_modal, "2468")
        yield self.wait("synthetic patient linked", lambda: bool(w.cloud_patient)
                        and not shell.patient_modal.isVisible())
        self.click(view._patient_button)
        assert w.cloud_patient is None
        self.click(shell.patient_modal._manual)
        assert "will not upload" in view._patient_detail.text()
        self.note("change and cancel clear prior patient identity")
        self.click(view._patient_button)
        self.enter_pin(shell.patient_modal, "2468")
        yield self.wait("patient relinked", lambda: bool(w.cloud_patient)
                        and not shell.patient_modal.isVisible())

        for number in (1, 2, 3, 4):
            self.click(view._proto_buttons[number])
            assert view._phase_badge._label.text() == "Not started"
            self.capture_layout(f"protocol-{number}-preparation")
            self.click(view._settings_tabs[1])
            self.capture_layout(f"protocol-{number}-speeds")
            self.click(view._settings_tabs[0])
            self.review(False, number)
            yield self.wait(f"protocol {number} review cancel leaves idle", self.after(0.5))
            assert w.protocol_state == "idle" and not self.state["moving"]
            assert not w.protocol_running

        # Short linked run to exercise the real record/outbox path on operator Stop.
        self.click(view._proto_buttons[1])
        self.review(True, 1)
        yield self.wait("linked treatment active", lambda: w.protocol_state == "running")
        self.capture_layout("starting")
        yield self.wait("linked treatment reaches load", lambda: self.state["pulsing"]
                        and self.state["pose"]["force_lb"] > 15, 60)
        assert not view._settings["duration"].isEnabled()
        assert not view._patient_button.isEnabled()
        assert view._pressure_stat._value != "—"
        assert view._limit_stat._value == "20"
        self.capture_layout("running")
        self.click(shell.nav_rail._buttons["help"])
        assert shell.treatment.isVisible()
        self.dismiss_messages()
        self.note("active treatment blocks nonessential navigation")
        self.click(view._pause_btn)
        yield self.wait("paused protocol stops pulse", lambda: not self.state["pulsing"])
        assert view._start_btn.text() == "RESUME"
        self.capture_layout("paused")
        self.click(view._start_btn)
        yield self.wait("resume restores pulse", lambda: self.state["pulsing"])
        self.bridge.request("fault", {"name": "side_effect_failure", "value": True})
        self.note("Stop activated", simulator_force_lb=self.state["pose"]["force_lb"])
        self.click(view._estop_btn)
        yield self.wait("Stop enters recovery", lambda: w.reset_in_progress
                        or w.protocol_state == "stopping")
        self.capture_layout("recovering")
        assert not view._next_button.isEnabled()
        yield self.wait("Stop releases and rehomes", lambda: w.protocol_state == "idle"
                        and w.initial_setup_complete and w.arduino.baseline_valid
                        and not w.reset_in_progress, 60)
        yield self.wait("failed upload retained", lambda: bool(self.pending_records())
                        and "Upload" in view._cloud_status.text())
        records = self.pending_records()
        assert len(records) == 1
        self.note("operator stop outcome survives upload failure", outcome=view._outcome,
                  record_status=view._cloud_status.text(), queued_records=len(records))
        assert view._outcome == "stopped"
        assert view._device_label == "Ready"
        self.capture_layout("stopped-upload-pending")
        self.bridge.request("fault", {"name": "side_effect_failure", "value": False})
        self.click(view._retry_button)
        yield self.wait("record retry succeeds respecting backoff", lambda:
                        not self.pending_records() and "synced" in view._cloud_status.text(), 50)
        self.click(view._next_button)
        assert shell.patient_modal.isVisible() and w.cloud_patient is None
        assert view._outcome is None
        self.capture_layout("next-patient-choice")
        self.click(shell.patient_modal._manual)
        yield from self._secondary_steps()
        yield from self._service_steps()

    def _secondary_steps(self) -> Iterator[tuple]:
        shell = self.window.shell
        self.click(shell.nav_rail._buttons["help"])
        for index, name in enumerate(("protocols", "controls-safety")):
            self.click(shell.help._section_buttons[index])
            self.capture_layout("help-" + name)
            scroll = shell.help._sections.currentWidget()
            assert scroll.verticalScrollBar().maximum() == 0
            assert scroll.horizontalScrollBar().maximum() == 0
        self.click(shell.nav_rail._buttons["support"])
        support = shell.support
        from ui.screens.support import _FailureItem
        item = support.findChildren(_FailureItem)[0]
        self.click(item._header)
        assert item._question in support._selected_issue.text()
        self.capture_layout("support-selected-issue")
        # Local simulation boundary captures both actions; no email leaves the PC.
        self.bridge.request("fault", {"name": "side_effect_failure", "value": True})
        self.click(support._send_buttons[1])
        yield self.wait("support failure visible", lambda:
                        "failure" in support._delivery_status.text().lower())
        self.dismiss_messages()
        self.capture_layout("support-failure")
        self.bridge.request("fault", {"name": "side_effect_failure", "value": False})
        self.click(support._send_buttons[1])
        yield self.wait("support retry captured locally", lambda:
                        "Captured" in support._delivery_status.text())
        self.dismiss_messages()
        self.capture_layout("support-sent")

    def _service_steps(self) -> Iterator[tuple]:
        shell = self.window.shell
        self.click(shell.top_bar._avatar)
        self.click(shell.profile._logout)
        self.click(shell.nav_rail._buttons["setup"])
        self.enter_pin(shell.login_modal, "1234")
        yield self.wait("administrator returns to Setup", lambda: shell.setup.isVisible()
                        and self.window._is_admin())
        self.click(shell.setup._calibration)
        from ui.modals.service_pin_dialog import ServicePinDialog
        from ui.modals.hardware_service_dialog import HardwareServiceDialog
        gate = next(d for d in QApplication.topLevelWidgets()
                    if isinstance(d, ServicePinDialog) and d.isVisible())
        for _ in range(2):
            self.enter_pin(gate, "135790")
        yield self.wait("separate PIN opens technician service", lambda: any(
            isinstance(d, HardwareServiceDialog) and d.isVisible()
            for d in QApplication.topLevelWidgets()))
        dialog = next(d for d in QApplication.topLevelWidgets()
                      if isinstance(d, HardwareServiceDialog) and d.isVisible())
        for index in range(dialog.steps.count()):
            item = dialog.steps.item(index)
            QTest.mouseClick(dialog.steps.viewport(), Qt.LeftButton,
                             pos=dialog.steps.visualItemRect(item).center())
            QApplication.processEvents()
            assert dialog.steps.currentRow() == index
            self.assert_contained(dialog.close_button, dialog)
            stop = self.named(dialog, "STOP")
            assert stop.isEnabled()
            self.assert_contained(stop, dialog)
            dialog.grab().save(str(self.directory / f"ux-service-{index}.png"))
        self.note("technician service pages retain Stop and Close", pages=dialog.steps.count())
        self.click(dialog.close_button)
        yield self.wait("service closes without calibration edits", lambda: not any(
            isinstance(d, HardwareServiceDialog) and d.isVisible()
            for d in QApplication.topLevelWidgets()))


class UxStopVerification(UxVerification):
    """Exercise distinct urgent controls during simulated motion and recovery."""

    def _steps(self) -> Iterator[tuple]:
        w, shell = self.window, self.window.shell
        yield self.wait("cold initialization and baseline", lambda: w.initial_setup_complete
                        and w.arduino.baseline_valid and not w.reset_in_progress)
        self.dismiss_messages()
        self.click(shell.nav_rail._buttons["setup"])
        self.enter_pin(shell.login_modal, "5678")
        yield self.wait("Setup authenticated", lambda: shell.setup.isVisible())
        self.click(shell.nav_rail._buttons["protocols"])
        view = shell.treatment
        self.click(view._patient_button)
        self.enter_pin(shell.patient_modal, "2468")
        yield self.wait("patient linked", lambda: bool(w.cloud_patient)
                        and not shell.patient_modal.isVisible())
        # Delayed real serial replies leave preparation observable without
        # replacing its worker, state transitions or timeout configuration.
        self.bridge.request("fault", {"name": "delay_ms", "value": 1000})
        self.review(True, 1)
        yield self.wait("preparation in progress", lambda: w.protocol_state == "starting", 5)
        assert view._phase_badge._label.text() == "Preparing"
        self.capture_layout("starting-stop-access")
        self.note("Stop during preparation activated")
        self.click(view._estop_btn)
        self.bridge.request("fault", {"name": "delay_ms", "value": 0})
        yield self.wait("preparation cancelled and recovery begins", lambda: w.reset_in_progress,
                        40)
        self.capture_layout("reset-stop-access")
        self.note("Stop during reset activated")
        self.click(view._estop_btn)
        yield self.wait("repeated Stop returns to readiness", lambda: w.protocol_state == "idle"
                        and w.initial_setup_complete and not w.reset_in_progress
                        and w.arduino.baseline_valid, 60)
        self.dismiss_messages()
        self.click(shell.nav_rail._buttons["setup"])
        pressure = shell.setup._rows["pressure"]
        yield self.wait("pressure controls reenabled", lambda:
                        pressure.motion_buttons[-1].isEnabled())
        pressure.slider.set_value(20)
        self.click(pressure.motion_buttons[-1])
        yield self.wait("static loaded hold", lambda: not self.state["moving"]
                        and self.state["pose"]["force_lb"] > 18)
        # Inject a documented notice at the wire boundary; no direct UI signal.
        self.bridge.request("fault", {"name": "pressure_notice", "value": True})
        yield self.wait("pressure advisory parsed and shown", lambda:
                        getattr(w, "_pressure_notice", None) is not None)
        notice = w._pressure_notice
        self.click(notice.details_button)
        assert "2150" in notice.details.text()
        notice.grab().save(str(self.directory / "ux-pressure-notice-details.png"))
        self.click(notice.dismiss_button)
        yield self.wait("dismiss closes advisory", lambda: w._pressure_notice is None)
        assert self.state["pose"]["force_lb"] > 18
        assert w.protocol_state == "idle" and not w.reset_in_progress
        self.note("dismissal preserves loaded hold")
        self.bridge.request("fault", {"name": "pressure_notice", "value": True})
        yield self.wait("second advisory visible", lambda: w._pressure_notice is not None)
        self.note("Pressure-notice Stop activated")
        self.click(w._pressure_notice.stop_button)
        yield self.wait("advisory Stop inhibits recovery", lambda: w.protocol_state == "fault"
                        and w._no_automatic_recovery and not self.state["moving"])
        yield self.wait("no automatic homing after advisory Stop", self.after(3))
        assert not w.reset_in_progress and self.state["pose"]["force_lb"] > 18
        self.capture_layout("notice-stop-no-home")
        yield from self._reset()
        self.dismiss_messages()

        # A sustained jam produces the emulator's real motor-stall warning.
        # The idle positioning banner has its own urgent-stop outcome route.
        lateral = shell.setup._rows["lateral"]
        yield self.wait("lateral controls reenabled", lambda:
                        lateral.motion_buttons[-1].isEnabled())
        self.bridge.request("fault", {"name": "jam_c", "value": True})
        lateral.slider.set_value(10)
        self.click(lateral.motion_buttons[-1])
        yield self.wait("positioning warning banner", lambda: w.treatment_panel.isVisible(), 30)
        self.dismiss_messages()
        self.note("Banner Stop activated")
        self.click(w.treatment_panel.stop_button)
        self.bridge.request("fault", {"name": "jam_c", "value": False})
        yield self.wait("banner Stop reaches recovery", lambda: w.protocol_state == "stopping"
                        or w.reset_in_progress)
        yield self.wait("banner recovery completes", lambda: w.protocol_state == "idle"
                        and not w.reset_in_progress and w.arduino.baseline_valid, 60)
        self.dismiss_messages()

        leg = shell.setup._rows["leg_length"]
        yield self.wait("leg controls available", lambda: leg.motion_buttons[3].isEnabled())
        self.click(leg.motion_buttons[3])
        yield self.wait("leg moving", lambda: self.state["pose"]["fit_inches"] > 0.1)
        self.click(leg.safety_buttons[0])
        yield self.wait("leg Stop clears direction outputs", lambda:
                        self.state["gpio"].get("27") == 0
                        and self.state["gpio"].get("22") == 0)
        assert shell.setup._pos["leg_length"]._caption.text() == "Estimated"
        self.note("leg Stop preserves explicit open-loop labeling")
