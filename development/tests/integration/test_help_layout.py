"""Help references fit the device display and remain reachable with overflow."""

from typing import Tuple

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QApplication, QLabel
from pytestqt.qtbot import QtBot

from ui.app_shell import AppShell


pytestmark = pytest.mark.integration


@pytest.mark.parametrize("size", [(1366, 768), (1360, 768), (1352, 756)])
@pytest.mark.parametrize("section", [0, 1])
def test_help_reference_fits_without_clipping(
    themed_app: QApplication, qtbot: QtBot, size: Tuple[int, int], section: int,
) -> None:
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.setFixedSize(*size)
    shell.navigate("support")
    shell.show()
    screen = shell.support
    qtbot.mouseClick(screen._section_buttons[section], Qt.LeftButton)
    qtbot.wait(10)
    scroll = screen._sections.currentWidget()
    assert screen._sections.currentIndex() == section
    assert scroll.verticalScrollBar().maximum() == 0
    assert scroll.horizontalScrollBar().maximum() == 0

    for index, button in enumerate(screen._section_buttons):
        assert button.isChecked() == (index == section)
        assert button.height() >= 48
    labels = scroll.widget().findChildren(QLabel)
    assert labels
    if section == 1:
        assert any("Read device status." in label.text() for label in labels)
        assert any("Measurements" in label.text() for label in labels)
    for label in labels:
        needed = (label.heightForWidth(label.width()) if label.hasHeightForWidth()
                  else label.minimumSizeHint().height())
        assert label.height() >= needed, label.text()
        bounds = label.rect().translated(label.mapTo(scroll.viewport(), QPoint()))
        assert scroll.viewport().rect().contains(bounds), label.text()


@pytest.mark.parametrize("section", [0, 1])
def test_help_overflow_can_reveal_every_reference(
    themed_app: QApplication, qtbot: QtBot, section: int,
) -> None:
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.setFixedSize(1360, 768)
    shell.navigate("support")
    shell.show()
    qtbot.mouseClick(shell.support._section_buttons[section], Qt.LeftButton)
    scroll = shell.support._sections.currentWidget()
    scroll.setFixedHeight(180)
    qtbot.wait(10)
    assert scroll.verticalScrollBar().maximum() > 0
    for label in scroll.widget().findChildren(QLabel):
        scroll.ensureWidgetVisible(label, 0, 0)
        bounds = label.rect().translated(label.mapTo(scroll.viewport(), QPoint()))
        assert scroll.viewport().rect().contains(bounds), label.text()
    assert all(button.isVisible() for button in shell.support._section_buttons)
