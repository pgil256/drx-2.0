"""Integration tests for the DS widget library (offscreen Qt).

Verifies each component constructs/polishes against the themed app and that the
interactive ones (Slider float mapping, Keypad entry, ProtocolButton/NavRail
toggles, Button variant/size) behave. conftest forces QT_QPA_PLATFORM=offscreen.
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def app():
    from PyQt5.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    from ui.theme import apply_theme

    apply_theme(application)
    return application


def test_all_components_construct_and_polish(app):
    from ui.widgets.ds import (
        DSBadge,
        DSButton,
        DSCard,
        DSKeypad,
        DSNavRailButton,
        DSProtocolButton,
        DSSlider,
        DSStatReadout,
    )

    widgets = []
    for variant in ("primary", "success", "danger", "secondary", "ghost"):
        for size in ("sm", "md", "lg"):
            widgets.append(DSButton(variant, variant=variant, size=size))
    for tone in ("neutral", "info", "success", "danger", "warning", "cyan"):
        widgets.append(DSBadge(tone, tone=tone, dot=True))
    for tone in ("default", "cyan", "success", "warning", "danger"):
        for size in ("sm", "md", "lg"):
            widgets.append(DSStatReadout("42", unit="lbs", label=tone, tone=tone, size=size))
    widgets.append(DSSlider("P", value=50, minimum=10, maximum=80, unit=" lbs"))
    widgets.append(DSProtocolButton(1, "Axial"))
    widgets.append(DSNavRailButton("Setup"))
    widgets.append(DSKeypad(length=4))
    card = DSCard("Title", header_right=DSBadge("Ready", tone="warning", dot=True))
    card.add_widget(DSStatReadout("1", label="x"))
    widgets.append(card)

    for w in widgets:
        w.ensurePolished()
    # 15 buttons + 6 badges + 15 readouts + slider + protocol + nav + keypad + card
    assert len(widgets) == 15 + 6 + 15 + 5


def test_button_variant_and_size_switch(app):
    from ui.widgets.ds import DSButton

    b = DSButton("x", variant="primary", size="md")
    assert b.property("variant") == "primary"
    assert b.property("dsSize") == "md"  # not "size" — that collides with QWidget.size
    b.set_variant("danger")
    b.set_size("lg")
    assert b.variant() == "danger"
    assert b.size_variant() == "lg"
    assert b.property("variant") == "danger"
    assert b.property("dsSize") == "lg"
    # invalid values fall back
    b.set_variant("nonsense")
    assert b.variant() == "primary"


def test_slider_float_mapping_and_clamp(app):
    from ui.widgets.ds import DSSlider

    s = DSSlider(value=0, minimum=-20, maximum=20, step=2.5, unit="°")
    s.set_value(2.5)
    assert s.value() == 2.5
    s.set_value(999)  # clamps to max
    assert s.value() == 20
    s.set_value(-999)  # clamps to min
    assert s.value() == -20


def test_slider_emits_float_on_user_change(app):
    from PyQt5.QtWidgets import QSlider

    from ui.widgets.ds import DSSlider

    s = DSSlider(value=10, minimum=0, maximum=80, step=5, unit=" lbs")
    seen = []
    s.valueChanged.connect(seen.append)
    inner = s.findChild(QSlider)
    inner.setValue(inner.value() + 2)  # simulate a user drag of 2 ticks = +10
    assert seen and isinstance(seen[-1], float)
    assert seen[-1] == 20.0


def test_keypad_entry_submit_clear_back(app):
    from PyQt5.QtWidgets import QPushButton

    from ui.widgets.ds import DSKeypad

    kp = DSKeypad(length=4)
    changes, submits = [], []
    kp.valueChanged.connect(changes.append)
    kp.submitted.connect(submits.append)

    from ui.widgets.ds.keypad import BACKSPACE

    keys = {b.text(): b for b in kp.findChildren(QPushButton)}
    for d in "123":
        keys[d].click()
    assert kp.value() == "123"
    assert submits == []  # not yet full
    keys[BACKSPACE].click()  # backspace
    assert kp.value() == "12"
    keys["3"].click()
    keys["4"].click()
    assert kp.value() == "1234"
    assert submits == ["1234"]  # fired exactly once at length
    keys["5"].click()  # ignored past length
    assert kp.value() == "1234"
    keys["Clear"].click()
    assert kp.value() == ""
    assert changes  # got change events throughout


def test_protocol_and_nav_toggle(app):
    from PyQt5.QtWidgets import QGraphicsOpacityEffect

    from ui.widgets.ds import DSNavRailButton, DSProtocolButton

    p = DSProtocolButton(2, "Left")
    assert p.isCheckable() and not p.isChecked()
    p.setChecked(True)
    assert p.isChecked()
    # Disabled dims the whole tile to 0.5 opacity (not just the text color).
    p.setEnabled(False)
    p.ensurePolished()
    assert isinstance(p.graphicsEffect(), QGraphicsOpacityEffect)
    assert p.graphicsEffect().opacity() == 0.5
    p.setEnabled(True)
    p.ensurePolished()
    assert p.graphicsEffect() is None

    n = DSNavRailButton("Setup")
    assert n.isCheckable()
    n.setChecked(True)
    assert n.isChecked()


def test_stat_readout_empty_label_renders_no_caption(app):
    from PyQt5.QtWidgets import QLabel

    from ui.widgets.ds import DSStatReadout

    with_label = DSStatReadout("1", label="Pressure")
    empty_label = DSStatReadout("1", label="")
    none_label = DSStatReadout("1")
    assert len(with_label.findChildren(QLabel)) == 2  # value + caption
    assert len(empty_label.findChildren(QLabel)) == 1  # value only
    assert len(none_label.findChildren(QLabel)) == 1
