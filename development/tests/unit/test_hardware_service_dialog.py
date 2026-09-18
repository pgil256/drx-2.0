"""Service wizard safeguards and visibility of incomplete hardware checks."""

from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QMessageBox

from ui.modals.hardware_service_dialog import HardwareServiceDialog
from ui.theme import load_fonts


@pytest.fixture
def service_dialog(qtbot):
    load_fonts()
    draft = SimpleNamespace(
        marks={
            "axial": {"0.0": 0, "4.0": 4000},
            "horizontal": {"-25.0": 0, "5.0": 2000},
            "lateral": {"-20.0": 500, "20.0": 2400},
        },
        factors={"axial": 6000, "horizontal": 1900, "lateral": 1900},
        scale=1.0,
        recorded={"axial": {"0.0"}, "horizontal": set(), "lateral": set()},
        changes=lambda: [],
    )
    dialog = HardwareServiceDialog(draft)
    qtbot.addWidget(dialog, before_close_func=lambda widget: setattr(widget, "_closed", True))
    yield dialog
    dialog._closed = True


@pytest.mark.unit
class TestHardwareServiceDialog:
    def test_begin_requires_all_preparation_confirmations(self, service_dialog):
        dialog = service_dialog
        actions = []
        dialog.action_requested.connect(lambda *args: actions.append(args))
        assert not dialog.begin_button.isEnabled()
        for check in dialog.preflight_checks[:-1]:
            check.setChecked(True)
        assert not dialog.begin_button.isEnabled()
        dialog.preflight_checks[-1].setChecked(True)
        dialog.begin_button.click()
        assert actions == [("begin", None)]

    def test_each_movement_requires_fresh_confirmation(self, service_dialog, monkeypatch):
        dialog = service_dialog
        dialog.set_available(True, False)
        actions = []
        confirmations = []
        decisions = iter((QMessageBox.No, QMessageBox.Yes, QMessageBox.No))

        def confirm(*args):
            confirmations.append(args)
            return next(decisions)

        monkeypatch.setattr(QMessageBox, "question", confirm)
        dialog.action_requested.connect(lambda *args: actions.append(args))
        dialog.steps.setCurrentRow(2)
        jog = next(button for button in dialog._actions if button.text() == "Jog +50")
        jog.click()
        jog.click()
        dialog.steps.setCurrentRow(5)
        extend = next(button for button in dialog._actions if button.text() == "Brief extend")
        extend.click()
        assert len(confirmations) == 3
        assert actions == [("jog", 50)]
        assert all("no patient" in args[2] for args in confirmations)

    def test_selected_mark_move_requires_confirmation(self, service_dialog, monkeypatch):
        dialog = service_dialog
        dialog.set_available(True, False)
        dialog.steps.setCurrentRow(2)
        dialog._tables["axial"].selectRow(1)
        actions = []
        dialog.action_requested.connect(lambda *args: actions.append(args))
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
        dialog._selected_mark_action("axial", "goto")
        assert not actions
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
        dialog._selected_mark_action("axial", "goto")
        assert actions == [("goto", "4.0")]

    def test_busy_keeps_stop_and_close_available(self, service_dialog):
        dialog = service_dialog
        dialog.set_available(True, True)
        assert dialog.stop_button.isEnabled()
        assert dialog.close_button.isEnabled()
        assert not dialog.steps.isEnabled()
        assert not dialog.next_button.isEnabled()
        assert not any(button.isEnabled() for button in dialog._actions)

    def test_aborted_session_still_records_observations_and_exports(self, service_dialog):
        dialog = service_dialog
        dialog.set_available(False, False, aborted=True)
        assert all(button.isEnabled() for button in dialog._result_buttons)
        assert dialog.export_button.isEnabled()
        assert dialog.steps.isEnabled()
        assert not any(button.isEnabled() for button in dialog._actions
                       if button not in dialog._stationary_actions)
        assert all(button.isEnabled() for button in dialog._stationary_actions)
        assert not dialog.begin_button.isEnabled()
        assert not dialog.save_button.isEnabled()
        dialog.draft.changes = lambda: [("scale", "1", "2")]
        dialog.steps.setCurrentRow(8)
        assert dialog.save_button.isEnabled()

    def test_review_does_not_infer_pass_from_staged_changes(self, service_dialog):
        dialog = service_dialog
        dialog.draft.changes = lambda: [("a_factor", "1900", "2000")]
        dialog.set_available(True, False)
        dialog.refresh_draft()
        assert not dialog.save_button.isEnabled()
        dialog.set_result("axial", "fail", "Unexpected direction")
        dialog.set_result("loadcell", "skip", "No force reference available")
        dialog.steps.setCurrentRow(8)
        assert dialog.save_button.isEnabled()
        statuses = [dialog.results_table.item(row, 1).text() for row in range(8)]
        assert statuses.count("Incomplete") == 6
        assert "Observed failure" in statuses
        assert "Skipped / not tested" in statuses
        assert dialog.changes_table.item(0, 2).text() == "2000"

    def test_close_stops_before_discard_question_even_if_cancelled(self, service_dialog,
                                                                 monkeypatch):
        dialog = service_dialog
        dialog.draft.changes = lambda: [("a_factor", "1900", "2000")]
        events = []
        dialog.leaving.connect(lambda: events.append("stop"))

        def confirm(*args):
            events.append("confirm")
            return QMessageBox.No

        monkeypatch.setattr(QMessageBox, "question", confirm)
        dialog.reject()
        assert events == ["stop", "confirm"]
        assert not dialog._closed

    def test_tables_distinguish_existing_and_observed_points(self, service_dialog):
        table = service_dialog._tables["axial"]
        assert table.item(0, 2).text() == "Recorded this session"
        assert table.item(1, 2).text() == "Existing / unverified"

    def test_bench_observations_start_untested_and_remain_individual(self, service_dialog):
        dialog = service_dialog
        assert all(dialog.bench_review_table.item(row, 1).text() == "Not tested"
                   for row in range(7))
        dialog.set_bench_result("pressure_accuracy", "skip", "No reference gauge")
        dialog.set_bench_result("mechanical", "pass", "Cable and mounting inspection")
        assert dialog.bench_review_table.item(1, 1).text() == "Skipped / not tested"
        assert dialog.bench_review_table.item(6, 1).text() == "Observed pass"
        assert dialog.bench_review_table.item(0, 1).text() == "Not tested"

    def test_content_fits_kiosk_and_remains_scrollable(self, service_dialog, qtbot):
        dialog = service_dialog
        dialog.show()
        qtbot.wait(20)
        assert dialog.width() == 1080
        assert dialog.height() == 700
        for index in range(dialog.pages.count()):
            dialog.steps.setCurrentRow(index)
            qtbot.wait(5)
            page = dialog.pages.widget(index)
            assert page.horizontalScrollBar().maximum() == 0, index
        assert dialog.stop_button.geometry().height() >= 44
        assert dialog.close_button.isVisible()
