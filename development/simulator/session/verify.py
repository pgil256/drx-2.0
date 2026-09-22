"""Opt-in acceptance driver using actual widgets, serial replies, and physical state.

Run with the native Windows Qt platform (the offscreen plugin can hang on dialogs).
No production readiness, authentication, durations, or worker logic are replaced.
"""
import json
import time
import traceback
from pathlib import Path
from typing import Callable

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QAbstractButton, QApplication, QMessageBox


class GuiVerification:
    """Advance a bounded operator script while the normal Qt loop keeps running."""

    def __init__(self, window: object, bridge: object, directory: Path, mode: str) -> None:
        self.window, self.bridge, self.directory, self.mode = window, bridge, directory, mode
        self.passed = False
        self.results = []
        self.state = {}
        self._wait = None
        self._busy = False
        self._script = self._steps()
        self.timer = QTimer(window)
        self.timer.timeout.connect(self._advance)
        self.timer.start(250)

    def click(self, button: QAbstractButton) -> None:
        assert button.isEnabled() and button.isVisible(), (
            f"Control unavailable: {button.accessibleName() or button.text()}"
        )
        QTest.mouseClick(button, Qt.LeftButton)

    def named(self, parent: object, name: str) -> QAbstractButton:
        found = [b for b in parent.findChildren(QAbstractButton)
                 if name in (b.accessibleName(), b.text()) and b.isVisible()]
        assert len(found) == 1, f"Expected one visible control {name!r}; found {len(found)}"
        return found[0]

    def wait(self, label: str, predicate: Callable[[], bool], seconds: float = 30) -> tuple:
        print("VERIFY waiting:", label, flush=True)
        return label, predicate, time.monotonic() + seconds

    def save(self, name: str) -> None:
        self.window.grab().save(str(self.directory / (name + ".png")))

    def _advance(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self.state = self.bridge.request("state")
            if self._wait:
                label, predicate, deadline = self._wait
                if not predicate():
                    if time.monotonic() > deadline:
                        raise AssertionError("Timed out: " + label)
                    return
                self.results.append({"check": label, "sim_time": self.state["sim_time"]})
                print("VERIFY passed:", label, flush=True)
                self._wait = None
            self._wait = next(self._script)
        except StopIteration:
            self.passed = True
            self._finish()
        except Exception:
            self.results.append({"error": traceback.format_exc(), "state": self.state})
            traceback.print_exc()
            self._finish()
        finally:
            self._busy = False

    def _finish(self) -> None:
        self.timer.stop()
        self.save("verification-final")
        (self.directory / "verification.json").write_text(json.dumps({
            "passed": self.passed, "mode": self.mode, "results": self.results,
        }, indent=2), encoding="utf-8")
        QTimer.singleShot(100, self.window.close)

    def _steps(self):
        w, shell = self.window, self.window.shell
        yield self.wait("cold initialization and baseline", lambda: w.initial_setup_complete
                        and w.arduino.baseline_valid and not w.reset_in_progress)
        checkpoint = self.directory / "restart-checkpoint.json"
        if checkpoint.exists():
            previous = json.loads(checkpoint.read_text())
            assert self.state["session_id"] == previous["session_id"]
            assert self.state["sim_time"] > previous["sim_time"]
            self.results = previous["results"] + self.results
            self.results.append({"check": "GUI restart retained the same backend and profile"})
            return
        # Dismiss the real reset confirmation, then log in using the actual keypad.
        for dialog in QApplication.topLevelWidgets():
            if isinstance(dialog, QMessageBox) and dialog.isVisible():
                self.click(dialog.button(QMessageBox.Ok))
        self.click(shell.nav_rail._buttons["setup"])
        yield self.wait("login gate", lambda: shell.login_modal.isVisible())
        for digit in "1234":
            self.click(self.named(shell.login_modal, digit))
        yield self.wait("authenticated setup", lambda: bool(shell._username)
                        and shell.setup.isVisible())
        if self.mode == "restart":
            yield from self._restart()
            return
        for axis, target, pose_key, tolerance in (
            ("lateral", 10, "lateral_degrees", 0.1),
            ("horizontal", -5, "horizontal_degrees", 0.1),
            ("axial", 0.5, "axial_inches", 0.03),
        ):
            row = shell.setup._rows[axis]
            yield self.wait(axis + " controls ready", lambda row=row:
                            row.motion_buttons[-1].isEnabled())
            row.slider.set_value(target)
            self.click(row.motion_buttons[-1])
            yield self.wait(axis + " physical target", lambda key=pose_key, target=target,
                            tol=tolerance: abs(self.state["pose"][key] - target) < tol
                            and not self.state["moving"])
        self.save("setup-three-axes")
        leg = shell.setup._rows["leg_length"]
        yield self.wait("FIT controls ready", lambda: leg.motion_buttons[3].isEnabled())
        self.click(leg.motion_buttons[3])
        yield self.wait("bounded FIT motion and GPIO release", lambda:
                        self.state["pose"]["fit_inches"] > 2.9
                        and self.state["gpio"].get("27") == 0
                        and self.state["gpio"].get("22") == 0)
        for target in (1.25, 1.75):
            yield self.wait("FIT target control ready", lambda:
                            leg.motion_buttons[-1].isEnabled() and not w.leg.active)
            before_pose = self.state["pose"]["fit_inches"]
            direction = 1 if target > w.leg.position else -1
            leg.slider.set_value(target)
            self.click(leg.motion_buttons[-1])
            yield self.wait(f"FIT Go completes estimated {target:g} inches", lambda target=target:
                            not w.leg.active and w.leg.position == target
                            and self.state["gpio"].get("27") == 0
                            and self.state["gpio"].get("22") == 0)
            # FIT has no position sensor: serial/GPIO timing affects actual travel.
            # Verify physical direction and bounds, and record the estimation error
            # instead of treating command completion as measured target accuracy.
            pose = self.state["pose"]["fit_inches"]
            assert 0 <= pose <= 6 and (pose - before_pose) * direction > 0.1
            assert leg.readout._caption.text() == "Estimated"
            self.results.append({"check": "FIT target remains explicitly estimated",
                                 "estimate_inches": target, "physical_inches": pose,
                                 "error_inches": pose - target})
        self.save("setup-leg-target")
        yield self.wait("reset control ready", lambda: shell.setup._reset_btn.isEnabled())
        self.click(shell.setup._reset_btn)
        yield self.wait("reset after positioning", lambda: w.reset_in_progress)
        yield self.wait("resting baseline restored", lambda: w.initial_setup_complete
                        and not w.reset_in_progress and self.state["pose"]["axial_inches"] < 0.01)
        if self.mode == "smoke":
            return
        if self.mode == "faults":
            yield from self._fault_steps()
            return
        if self.mode == "live":
            yield from self._live_steps()
            return
        self.click(shell.nav_rail._buttons["protocols"])
        treatment = shell.treatment
        numbers = (int(self.mode[-1]),) if self.mode.startswith("protocol-") else (1, 2, 3, 4)
        for number in numbers:
            yield self.wait("treatment ready", lambda: treatment._start_btn.isEnabled())
            self.click(treatment._proto_buttons[number])
            # Set through real slider buttons so the normal setting signals run.
            for key, target in (("duration", 5), ("max_pressure", 20), ("pulse_rate", 2)):
                slider = treatment._settings[key]
                while slider.value() > target:
                    self.click(slider._left_btn)
                while slider.value() < target:
                    self.click(slider._right_btn)

            def confirm() -> None:
                from ui.modals.treatment_review import TreatmentReviewDialog
                for dialog in QApplication.topLevelWidgets():
                    if isinstance(dialog, TreatmentReviewDialog) and dialog.isVisible():
                        self.click(dialog.start_button)
                        return
                raise AssertionError("Treatment review did not open")

            QTimer.singleShot(300, confirm)
            self.click(treatment._start_btn)
            yield self.wait(f"protocol {number} running", lambda: w.protocol_state == "running")
            yield self.wait(f"protocol {number} reaches load and pulse", lambda:
                            self.state["pulsing"] and self.state["pose"]["force_lb"] > 15, 60)
            self.save(f"protocol-{number}-running")
            if number in (2, 3):
                sign = -1 if number == 2 else 1
                assert self.state["pose"]["lateral_degrees"] * sign > 5
            if number == 4:
                yield self.wait("oscillation reaches right", lambda:
                                self.state["pose"]["lateral_degrees"] > 5, 40)
                yield self.wait("oscillation returns left", lambda:
                                self.state["pose"]["lateral_degrees"] < -5, 40)
            yield self.wait(f"protocol {number} completes and rezeros", lambda:
                            w.protocol_state == "idle" and w.arduino.baseline_valid
                            and self.state["pose"]["axial_inches"] < 0.01, 360)
            assert w.worker is None or w.worker._run_success
            self.save(f"protocol-{number}-complete")

    def _reset(self):
        setup = self.window.shell.setup
        for dialog in QApplication.topLevelWidgets():
            if isinstance(dialog, QMessageBox) and dialog.isVisible():
                self.click(dialog.button(QMessageBox.Ok))
        yield self.wait("recovery reset available", lambda: setup._reset_btn.isEnabled())
        self.click(setup._reset_btn)
        yield self.wait("recovery begins", lambda: self.window.reset_in_progress)
        yield self.wait("recovery restores readiness", lambda: self.window.initial_setup_complete
                        and not self.window.reset_in_progress and self.window.arduino.baseline_valid)

    def _live_steps(self):
        w, shell = self.window, self.window.shell
        self.click(shell.nav_rail._buttons["protocols"])
        treatment = shell.treatment
        yield self.wait("live test ready", lambda: treatment._start_btn.isEnabled())
        self.click(treatment._proto_buttons[2])
        slider = treatment._settings["max_pressure"]
        while slider.value() > 20:
            self.click(slider._left_btn)

        def confirm() -> None:
            from ui.modals.treatment_review import TreatmentReviewDialog
            dialog = next(d for d in QApplication.topLevelWidgets()
                          if isinstance(d, TreatmentReviewDialog) and d.isVisible())
            self.click(dialog.start_button)

        QTimer.singleShot(300, confirm)
        self.click(treatment._start_btn)
        yield self.wait("live test pulsing", lambda: self.state["pulsing"], 60)
        self.click(treatment._pause_btn)
        yield self.wait("pause stops pulsing", lambda: not self.state["pulsing"])
        self.click(treatment._start_btn)
        yield self.wait("resume restores pulsing", lambda: self.state["pulsing"])
        self.click(treatment._adjust_button)
        def confirm_live_edit() -> None:
            dialog = next(d for d in QApplication.topLevelWidgets()
                          if isinstance(d, QMessageBox) and d.windowTitle() == "Caution")
            self.click(dialog.button(QMessageBox.Ok))

        QTimer.singleShot(300, confirm_live_edit)
        for _ in range(5):
            self.click(slider._right_btn)
        yield self.wait("live pressure change reaches hardware", lambda:
                        self.state["targets"]["pressure_lb"] == 25 and self.state["pulsing"]
                        and self.state["pose"]["force_lb"] > 22, 40)
        angle = treatment._settings["max_left"]
        for _ in range(5):
            self.click(angle._right_btn)
        yield self.wait("live angle reaches hardware", lambda:
                        self.state["pose"]["lateral_degrees"] < -14 and self.state["pulsing"], 40)
        pulse = treatment._settings["pulse_rate"]
        while pulse.value() > 0:
            self.click(pulse._left_btn)
        yield self.wait("live pulse off", lambda: not self.state["pulsing"])
        self.save("live-adjustments")
        self.click(treatment._estop_btn)
        yield self.wait("GUI Stop enters recovery", lambda: w.protocol_state == "stopping"
                        or w.reset_in_progress)
        yield self.wait("GUI Stop releases homes and rezeros", lambda:
                        w.protocol_state == "idle" and w.initial_setup_complete
                        and w.arduino.baseline_valid and not w.reset_in_progress
                        and self.state["pose"]["axial_inches"] < 0.01, 60)

    def _fault_steps(self):
        w, setup = self.window, self.window.shell.setup
        for name in ("identity_mismatch", "tare_failure"):
            yield self.wait("reset available", lambda: setup._reset_btn.isEnabled())
            self.bridge.request("fault", {"name": name, "value": True})
            self.click(setup._reset_btn)
            yield self.wait(name + " reset begins", lambda: w.reset_in_progress)
            yield self.wait(name + " blocks readiness", lambda:
                            not w.reset_in_progress and not w.initial_setup_complete, 30)
            self.bridge.request("fault", {"name": name, "value": False})
            yield from self._reset()

        lateral = setup._rows["lateral"]
        for name in ("jam_c", "freeze_c"):
            yield self.wait("lateral controls ready", lambda: lateral.motion_buttons[-1].isEnabled())
            self.bridge.request("fault", {"name": name, "value": True})
            lateral.slider.set_value(10)
            self.click(lateral.motion_buttons[-1])
            start = time.monotonic()
            yield self.wait(name + " motion observed", lambda: time.monotonic() - start > 2)
            assert self.state["sensors"]["c"] == 1688
            if name == "jam_c":
                assert self.state["pose"]["lateral_degrees"] == 0
            else:
                assert self.state["pose"]["lateral_degrees"] > 5
            self.click(lateral.safety_buttons[0])
            yield self.wait("GUI Stop stops axis", lambda: not self.state["moving"])
            self.bridge.request("fault", {"name": name, "value": False})
            yield from self._reset()

        pressure = setup._rows["pressure"]
        for name in ("pressure_stale", "pressure_bias", "physical_stop"):
            yield self.wait("pressure controls ready", lambda: pressure.motion_buttons[-1].isEnabled())
            pressure.slider.set_value(20)
            self.click(pressure.motion_buttons[-1])
            yield self.wait("static loaded hold", lambda: not self.state["moving"]
                            and self.state["pose"]["force_lb"] > 18)
            self.bridge.request("fault", {"name": name,
                                          "value": 40 if name == "pressure_bias" else True})
            yield self.wait(name + " reaches GUI fault state", lambda: w.protocol_state == "fault")
            if name == "physical_stop":
                yield self.wait("autonomous physical release", lambda:
                                self.state["pose"]["force_lb"] < 5)
            self.save(name)
            self.bridge.request("fault", {"name": name,
                                          "value": 0 if name == "pressure_bias" else False})
            yield from self._reset()

        self.bridge.request("fault", {"name": "disconnect", "value": 3})
        yield self.wait("serial disconnect reaches GUI", lambda: not w.arduino.connected)
        disconnected = time.monotonic()
        yield self.wait("link fault has elapsed", lambda: time.monotonic() - disconnected > 3)
        # The current production app reports disconnects but does not reconnect
        # its ended reader automatically. Exercise its explicit Restart action.
        yield from self._restart()

    def _restart(self):
        self.click(self.window.shell.top_bar._avatar)
        yield self.wait("profile screen visible", lambda: self.window.shell.profile.isVisible())
        checkpoint = {"session_id": self.state["session_id"], "sim_time": self.state["sim_time"],
                      "results": self.results}
        (self.directory / "restart-checkpoint.json").write_text(json.dumps(checkpoint))
        self.click(self.window.shell.profile._restart)
        yield self.wait("restart exits current GUI", lambda: False, 30)
