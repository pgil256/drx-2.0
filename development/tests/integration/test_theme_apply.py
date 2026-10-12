"""Integration smoke test: apply_theme() on a headless (offscreen) QApplication.

conftest.py forces QT_QPA_PLATFORM=offscreen, so this runs without a display.
Verifies the global stylesheet installs cleanly and themed widgets construct.
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def app(qt_app):
    return qt_app


def test_apply_theme_installs_resolved_stylesheet(app):
    from ui.theme import apply_theme

    info = apply_theme(app)

    assert isinstance(info, dict)
    assert isinstance(info["font_families"], list)
    assert isinstance(info["plex_loaded"], bool)

    sheet = app.styleSheet()
    assert sheet, "apply_theme installed an empty stylesheet"
    assert "var(" not in sheet, "stylesheet contains unresolved var() refs"
    assert "#176b9a" in sheet


def test_load_fonts_is_safe_and_repeatable(app):
    from ui.theme.qss import load_fonts

    first = load_fonts()
    second = load_fonts()
    assert isinstance(first, list)
    assert isinstance(second, list)  # never raises even if fonts/ is empty


def test_themed_widgets_construct_and_polish(app):
    """Build one of each base control with variant props and ensure they polish
    against the installed stylesheet without raising."""
    from PyQt5.QtWidgets import (
        QCheckBox,
        QFrame,
        QLabel,
        QLineEdit,
        QPushButton,
        QSlider,
    )
    from PyQt5.QtCore import Qt

    from ui.theme import apply_theme

    apply_theme(app)

    for variant in ("primary", "success", "danger", "destructive", "secondary", "ghost"):
        btn = QPushButton(variant)
        btn.setProperty("variant", variant)
        btn.ensurePolished()
        assert btn.property("variant") == variant

    big = QPushButton("START")
    big.setProperty("variant", "success")
    big.setProperty("size", "lg")
    big.ensurePolished()

    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 80)
    slider.setValue(40)
    slider.ensurePolished()

    QLineEdit("1234").ensurePolished()
    QCheckBox("Use Pulse").ensurePolished()

    card = QFrame()
    card.setProperty("dsCard", "true")
    header = QLabel("Treatment Monitor", card)
    header.setProperty("dsCardHeader", "true")
    card.ensurePolished()
    header.ensurePolished()


def test_focus_rings_are_marked_for_keyboard_focus_only(app):
    """A tap gives a button focus too; only Tab or a shortcut may light the ring."""
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QFocusEvent
    from PyQt5.QtWidgets import QApplication, QPushButton
    from ui.theme import apply_theme

    apply_theme(app)
    apply_theme(app)  # repeated application must not stack filters
    button = QPushButton("Done")

    def focus(kind, reason):
        QApplication.sendEvent(button, QFocusEvent(kind, reason))
        return bool(button.property("keyboardFocus"))

    try:
        assert focus(QEvent.FocusIn, Qt.MouseFocusReason) is False
        assert focus(QEvent.FocusIn, Qt.OtherFocusReason) is False
        assert focus(QEvent.FocusIn, Qt.TabFocusReason) is True
        assert focus(QEvent.FocusOut, Qt.MouseFocusReason) is False
        assert focus(QEvent.FocusIn, Qt.BacktabFocusReason) is True
        assert focus(QEvent.FocusIn, Qt.MouseFocusReason) is False
    finally:
        button.deleteLater()


def test_no_button_rule_draws_a_ring_on_plain_focus():
    """Every button :focus rule in the theme and the widgets is keyboard-gated."""
    import re
    from pathlib import Path

    from ui.theme import focus

    root = Path(focus.__file__).resolve().parents[1]
    offenders = []
    for path in list(root.rglob("*.py")) + list(root.rglob("*.qss")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if (re.search(r"(QPushButton|QToolButton|QSlider|#\w+)[^{]*:focus", line)
                    and "keyboardFocus" not in line and "QComboBox" not in line):
                offenders.append("%s:%d" % (path.name, number))
    assert offenders == []
