"""HelpScreen — protocol reference.

Mirrors `HelpScreen` in `bundle.jsx`: a "Preset Protocols" card with a 2×2 grid
of protocol explainers, then "Treatment Controls" and "Safety" cards. Static
reference content; no signals.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ui.theme import GLYPH
from ui.widgets.ds import DSBadge, DSCard
from ui.widgets.ds._common import mono_font, resolve, sans_font

from .content import HELP_CONTROLS, HELP_PROTOCOLS

_PAD = 20
_GAP = 16


def _number_circle(n):
    lbl = QLabel(str(n))
    lbl.setFixedSize(36, 36)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setFont(mono_font(size="--text-md", weight=600))
    lbl.setStyleSheet(
        f"background: {resolve('--color-primary')}; color: #ffffff;"
        " border-radius: 18px;"
    )
    return lbl


class _ProtocolHelpPanel(QFrame):
    def __init__(self, p, parent=None):
        super().__init__(parent)
        self.setObjectName("ProtoHelp")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#ProtoHelp {{ background: {resolve('--gray-050')};"
            f" border: 1px solid {resolve('--gray-300')};"
            f" border-radius: {resolve('--radius-md')}; }}"
            f" #ProtoHelp QLabel {{ background: transparent; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(_number_circle(p["n"]), 0, Qt.AlignTop)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(p["title"])
        title.setFont(sans_font(size="--text-base", weight=700))
        title.setStyleSheet(f"color: {resolve('--ink-900')};")
        summary = QLabel(p["summary"])
        summary.setFont(sans_font(size="--text-xs"))
        summary.setStyleSheet(f"color: {resolve('--gray-600')};")
        summary.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(summary)
        head.addLayout(title_box, 1)
        lay.addLayout(head)
        lay.addSpacing(2)

        bullet = GLYPH["bullet"]
        cyan = resolve("--brand-cyan")
        for name, desc in p["phases"]:
            row = QLabel(
                f"<span style='color:{cyan}'>{bullet}</span> "
                f"<b style='color:{resolve('--ink-800')}'>{name}</b> "
                f"<span style='color:{resolve('--ink-700')}'>— {desc}</span>"
            )
            row.setTextFormat(Qt.RichText)
            row.setWordWrap(True)
            row.setFont(sans_font(size="--text-sm"))
            lay.addWidget(row)
        lay.addStretch(1)


class HelpScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HelpScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#HelpScreen {{ background: {resolve('--surface-page')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        lay.setSpacing(_GAP)

        # Preset Protocols — 2×2 grid.
        presets = DSCard("Preset Protocols", header_right=DSBadge("v2.3", tone="cyan"),
                         padded=False)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setSpacing(14)
        for i, p in enumerate(HELP_PROTOCOLS):
            grid.addWidget(_ProtocolHelpPanel(p), i // 2, i % 2)
        for c in (0, 1):
            grid.setColumnStretch(c, 1)
        for r in (0, 1):
            grid.setRowStretch(r, 1)
        presets.add_widget(grid_host)
        lay.addWidget(presets, 1)

        # Treatment Controls + Safety row.
        bottom = QHBoxLayout()
        bottom.setSpacing(_GAP)
        bottom.addWidget(self._controls_card(), 3)
        bottom.addWidget(self._safety_card(), 2)
        lay.addLayout(bottom, 0)

    def _controls_card(self):
        card = DSCard("Treatment Controls", padded=False)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(9)
        for i, (key, desc) in enumerate(HELP_CONTROLS):
            cell = QLabel(
                f"<b style='color:{resolve('--ink-900')}'>{key}</b> "
                f"<span style='color:{resolve('--ink-700')}'>— {desc}</span>"
            )
            cell.setTextFormat(Qt.RichText)
            cell.setWordWrap(True)
            cell.setFont(sans_font(size="--text-xs"))
            grid.addWidget(cell, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        card.add_widget(host)
        return card

    def _safety_card(self):
        card = DSCard("Safety", padded=False)
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(16)
        limits = QLabel(
            "<ul style='margin:0; -qt-list-indent:1;'>"
            "<li>Pressure max — <b>80 lbs</b></li>"
            "<li>Axial range — <b>0–4 in</b></li>"
            "<li>Lateral range — <b>±20°</b></li>"
            "<li>Horizontal — <b>−25° to +5°</b></li>"
            "</ul>"
        )
        limits.setTextFormat(Qt.RichText)
        limits.setFont(sans_font(size="--text-xs"))
        limits.setStyleSheet(f"color: {resolve('--ink-700')};")
        note = QLabel(
            f"<b style='color:{resolve('--red-500')}'>{GLYPH['estop']} Emergency Stop</b> "
            "halts all actuators and returns the device to a safe state."
        )
        note.setTextFormat(Qt.RichText)
        note.setWordWrap(True)
        note.setFont(sans_font(size="--text-xs"))
        note.setStyleSheet(f"color: {resolve('--ink-700')};")
        row.addWidget(limits, 1)
        row.addWidget(note, 1)
        card.add_widget(host)
        return card
