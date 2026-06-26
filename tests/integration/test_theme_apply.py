"""Integration smoke test: apply_theme() on a headless (offscreen) QApplication.

conftest.py forces QT_QPA_PLATFORM=offscreen, so this runs without a display.
Verifies the global stylesheet installs cleanly and themed widgets construct.
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def app():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_apply_theme_installs_resolved_stylesheet(app):
    from ui.theme import apply_theme

    info = apply_theme(app)

    assert isinstance(info, dict)
    assert isinstance(info["font_families"], list)
    assert isinstance(info["plex_loaded"], bool)

    sheet = app.styleSheet()
    assert sheet, "apply_theme installed an empty stylesheet"
    assert "var(" not in sheet, "stylesheet contains unresolved var() refs"
    assert "#3498db" in sheet


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

    for variant in ("primary", "success", "danger", "secondary", "ghost"):
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
