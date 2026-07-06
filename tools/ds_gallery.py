"""Design-system gallery — renders every DS component in its states.

Run on a display to eyeball the components, or headless to snapshot them:

    python tools/ds_gallery.py                     # windowed
    QT_QPA_PLATFORM=offscreen python tools/ds_gallery.py --screenshot out.png

Phase 1 verification aid for the KneeSpa DRx modernization.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main"))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ui.theme import apply_theme, resolve  # noqa: E402
from ui.widgets.ds import (  # noqa: E402
    DSBadge,
    DSButton,
    DSCard,
    DSKeypad,
    DSNavRailButton,
    DSProtocolButton,
    DSSlider,
    DSStatReadout,
)


def section(title):
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 10)
    lay.setSpacing(10)
    head = QLabel(title)
    head.setStyleSheet(
        f"color: {resolve('--gray-600')}; font-size: 13px; font-weight: 700;"
        " letter-spacing: 1px;"
    )
    lay.addWidget(head)
    return box, lay


def hrow(widgets, spacing=10, align_left=True):
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w)
    if align_left:
        lay.addStretch(1)
    return row


def build():
    root = QWidget()
    # Scope the page wash to root ONLY — a selector-less `background:` would
    # cascade onto descendant widgets (overriding button fills, etc.).
    root.setObjectName("dsGalleryRoot")
    root.setStyleSheet(f"#dsGalleryRoot {{ background: {resolve('--surface-page')}; }}")
    grid = QVBoxLayout(root)
    grid.setContentsMargins(28, 28, 28, 28)
    grid.setSpacing(22)

    title = QLabel("KneeSpa DRx — Design System (Phase 1)")
    title.setStyleSheet(f"color: {resolve('--ink-900')}; font-size: 28px; font-weight: 700;")
    grid.addWidget(title)

    # Buttons: variant × size, plus disabled
    box, lay = section("BUTTON — variant × size")
    for variant in ("primary", "success", "danger", "secondary", "ghost"):
        lay.addWidget(hrow(
            [DSButton(f"{variant} {s}", variant=variant, size=s) for s in ("sm", "md", "lg")]
        ))
    dis = [DSButton(f"{v} disabled", variant=v) for v in ("primary", "secondary", "danger")]
    for b in dis:
        b.setEnabled(False)
    lay.addWidget(hrow(dis))
    grid.addWidget(box)

    # Badges
    box, lay = section("BADGE — tones (with dot)")
    lay.addWidget(hrow(
        [DSBadge(t.title(), tone=t, dot=True) for t in
         ("neutral", "info", "success", "danger", "warning", "cyan")]
    ))
    lay.addWidget(hrow(
        [DSBadge(t.title(), tone=t) for t in ("success", "danger", "cyan")]
    ))
    grid.addWidget(box)

    # Sliders
    box, lay = section("SLIDER — labeled float ranges")
    lay.addWidget(DSSlider("Max Pressure", value=50, minimum=10, maximum=80, unit=" lbs"))
    lay.addWidget(DSSlider("Max Angle L", value=10, minimum=0, maximum=20, step=2.5, unit="°"))
    lay.addWidget(DSSlider("Pulse Rate", value=2, minimum=0, maximum=5, step=0.2, unit="/sec"))
    grid.addWidget(box)

    # ProtocolButtons (exclusive group)
    box, lay = section("PROTOCOL BUTTON — picker (1 selected, 1 disabled)")
    group = QButtonGroup(box)
    group.setExclusive(True)
    tiles = []
    for n, name in ((1, "Axial"), (2, "Left"), (3, "Right"), (4, "Oscillate")):
        t = DSProtocolButton(n, name)
        group.addButton(t)
        tiles.append(t)
    tiles[0].setChecked(True)
    tiles[3].setEnabled(False)
    lay.addWidget(hrow(tiles))
    grid.addWidget(box)

    # StatReadouts
    box, lay = section("STAT READOUT — live values")
    lay.addWidget(hrow([
        DSStatReadout("12:00", label="Time Left", tone="default", size="sm"),
        DSStatReadout("45", unit="lbs", label="Pressure", tone="warning", size="sm"),
        DSStatReadout("-12°", label="Lateral Angle", tone="cyan", size="sm"),
        DSStatReadout("80", unit="lbs", label="Max", tone="danger", size="md"),
    ]))
    grid.addWidget(box)

    # NavRail (dark strip)
    box, lay = section("NAV RAIL BUTTON — dark rail (Setup active)")
    rail = QFrame()
    rail.setStyleSheet(f"background: {resolve('--ink-900')};")
    rlay = QHBoxLayout(rail)
    rlay.setContentsMargins(0, 0, 0, 0)
    rlay.setSpacing(0)
    nav_group = QButtonGroup(rail)
    for i, lbl in enumerate(("Home", "Setup", "Protocols", "Help", "Support")):
        nb = DSNavRailButton(lbl)
        nav_group.addButton(nb)
        if lbl == "Setup":
            nb.setChecked(True)
        rlay.addWidget(nb)
    rlay.addStretch(1)
    lay.addWidget(rail)
    grid.addWidget(box)

    # Card + Keypad side by side
    box, lay = section("CARD (dark header + Badge) & KEYPAD")
    rowwrap = QHBoxLayout()
    card = DSCard("Treatment Monitor", header_right=DSBadge("Holding…", tone="success", dot=True))
    card.add_widget(DSStatReadout("32", unit="lbs", label="Pressure", tone="success", size="lg"))
    body_copy = QLabel("Plain body copy added to the card inherits the design's ink-700 text color (not black).")
    body_copy.setWordWrap(True)
    card.add_widget(body_copy)
    card.add_widget(DSSlider("Max Pressure", value=50, minimum=10, maximum=80, unit=" lbs"))
    card.setMinimumWidth(420)
    rowwrap.addWidget(card)
    kp = DSKeypad(length=4, label="Enter User PIN")
    kp.set_value("12")
    rowwrap.addWidget(kp)
    rowwrap.addStretch(1)
    lay.addLayout(rowwrap)
    grid.addWidget(box)

    grid.addStretch(1)
    return root


def main():
    parser = argparse.ArgumentParser(description="KneeSpa DRx design-system gallery")
    parser.add_argument("--screenshot", metavar="PATH", help="Render to PNG and exit")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    root = build()

    if args.screenshot:
        root.setFixedWidth(1180)
        # Show (offscreen = no real window) so every nested widget runs through
        # the full polish/layout pipeline before we grab — otherwise app-stylesheet
        # rules (e.g. button fills) aren't applied to deeply nested children.
        root.show()
        app.processEvents()
        root.adjustSize()
        app.processEvents()
        pix = root.grab()
        pix.save(args.screenshot)
        print(f"Saved {args.screenshot} ({pix.width()}x{pix.height()})")
        return

    root.resize(1180, 980)
    root.setWindowTitle("KneeSpa DRx — DS Gallery")
    root.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
