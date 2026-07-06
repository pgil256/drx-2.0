# tests/unit/test_press_feedback.py
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel

from ui.widgets.press_feedback import install_press_feedback


@pytest.mark.unit
class TestPressFeedback:
    def test_press_dims_and_release_restores(self, qtbot):
        label = QLabel("nav")
        qtbot.addWidget(label)
        label.show()
        feedback = install_press_feedback(label)
        assert label.graphicsEffect() is None

        qtbot.mousePress(label, Qt.LeftButton)
        assert label.graphicsEffect() is not None
        assert label.graphicsEffect().opacity() == 0.5

        qtbot.mouseRelease(label, Qt.LeftButton)
        assert label.graphicsEffect() is None

    def test_handlers_still_run(self, qtbot):
        label = QLabel("nav")
        qtbot.addWidget(label)
        label.show()
        calls = []
        label.mousePressEvent = lambda event: calls.append(1)
        feedback = install_press_feedback(label)

        qtbot.mousePress(label, Qt.LeftButton)
        assert calls == [1]  # the filter never consumes the event
        qtbot.mouseRelease(label, Qt.LeftButton)

    def test_none_widgets_skipped(self, qtbot):
        label = QLabel("nav")
        qtbot.addWidget(label)
        label.show()
        feedback = install_press_feedback(None, label, None)
        qtbot.mousePress(label, Qt.LeftButton)
        assert label.graphicsEffect() is not None
        qtbot.mouseRelease(label, Qt.LeftButton)
