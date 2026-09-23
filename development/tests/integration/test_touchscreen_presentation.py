"""Readable text and reachable touch controls across the operator workspace."""

from types import SimpleNamespace
from typing import Tuple

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import (
    QAbstractButton, QApplication, QDoubleSpinBox, QLabel, QScrollArea,
    QStyle, QStyleOptionSpinBox,
)
from pytestqt.qtbot import QtBot

from ui.app_shell import AppShell
from ui.modals.hardware_service_dialog import HardwareServiceDialog


pytestmark = pytest.mark.integration


@pytest.mark.parametrize("size", [(1366, 768), (1360, 768), (1352, 756)])
@pytest.mark.parametrize("page", ["home", "setup", "protocols", "device", "support", "profile"])
def test_screen_text_and_touch_targets(
    themed_app: QApplication, qtbot: QtBot, size: Tuple[int, int], page: str,
) -> None:
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.setFixedSize(*size)
    shell.set_user("Review operator", is_admin=True)
    shell.navigate(page)
    shell.show()
    qtbot.wait(10)
    screen = shell.stack.currentWidget()
    if page == "support":
        assert screen.findChild(QScrollArea).verticalScrollBar().maximum() == 0
    for label in screen.findChildren(QLabel):
        if not label.isVisibleTo(screen) or not label.text():
            continue
        # Arm's-length text stays >= 16px; only tagged captions, eyebrows and
        # units use the smaller 13-14px steps of the type scale.
        minimum = 13 if label.property("dsCaption") else 16
        assert label.font().pixelSize() >= minimum, label.text()
        needed = (label.heightForWidth(label.width()) if label.hasHeightForWidth()
                  else label.minimumSizeHint().height())
        assert label.height() >= needed, label.text()
    for button in shell.findChildren(QAbstractButton):
        if not button.isVisibleTo(shell):
            continue
        assert button.width() >= 48 and button.height() >= 48, button.text()
        ancestor = button.parentWidget()
        while ancestor is not None:
            # Scrollable references can extend past the viewport, but their
            # controls must fit in the content and remain large enough to tap.
            if isinstance(ancestor, QScrollArea):
                break
            bounds = button.rect().translated(button.mapTo(ancestor, QPoint()))
            if isinstance(ancestor.parentWidget(), QScrollArea):
                break
            assert ancestor.rect().contains(bounds), button.text()
            ancestor = ancestor.parentWidget()


@pytest.mark.parametrize("topic", range(5))
def test_support_question_text_is_a_touch_target(
    themed_app: QApplication, qtbot: QtBot,
    topic: int,
) -> None:
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.resize(1360, 768)
    shell.navigate("support")
    shell.show()
    from ui.screens.support import _FailureItem

    shell.support._select_section(2)
    shell.support._select_topic(topic)
    qtbot.wait(10)
    item = shell.support._trouble_pages.currentWidget().findChildren(_FailureItem)[0]
    qtbot.mouseClick(item._header, Qt.LeftButton, pos=item._q.geometry().center())
    assert item._body.isVisible()
    assert item._body.font().pixelSize() >= 18


def test_service_spin_buttons_have_independent_full_size_targets(
    themed_app: QApplication, qtbot: QtBot,
) -> None:
    # Use the service stylesheet on a field without starting any service session.
    # Its numeric controls must expose separate 48px up/down hit rectangles.
    draft = SimpleNamespace(
        marks={"axial": {"0": 0, "4": 4000}, "horizontal": {"-25": 0, "5": 3000},
               "lateral": {"-20": 500, "20": 2500}},
        factors={"axial": 6000, "horizontal": 6000, "lateral": 6000},
        scale=10000, changes=lambda: [],
    )
    dialog = HardwareServiceDialog(draft)
    qtbot.addWidget(dialog)
    spin = dialog.findChildren(QDoubleSpinBox)[0]
    spin.resize(260, 56)
    spin.ensurePolished()
    option = QStyleOptionSpinBox()
    spin.initStyleOption(option)
    rectangles = [spin.style().subControlRect(QStyle.CC_SpinBox, option, control, spin)
                  for control in (QStyle.SC_SpinBoxUp, QStyle.SC_SpinBoxDown)]
    assert all(rect.width() >= 48 and rect.height() >= 48 for rect in rectangles)
    assert not rectangles[0].intersects(rectangles[1])
