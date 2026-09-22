"""Protocol and control references in sections that fit the device display."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QScroller,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme import GLYPH
from ui.widgets.ds import DSButton, DSCard
from ui.widgets.ds._common import mono_font, resolve, sans_font

from .content import HELP_CONTROLS, HELP_PROTOCOLS, SAFETY_LIMITS

_PAD = 20
_GAP = 16


def _number_circle(n):
    lbl = QLabel(str(n))
    lbl.setFixedSize(48, 48)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setFont(mono_font(size="--text-md", weight=600))
    lbl.setStyleSheet(
        f"background: {resolve('--color-primary')}; color: #ffffff;"
        " border-radius: 12px;"
    )
    return lbl


class _ProtocolHelpPanel(QFrame):
    def __init__(self, p, parent=None):
        super().__init__(parent)
        self.setObjectName("ProtoHelp")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#ProtoHelp {{ background: {resolve('--surface-card')};"
            f" border: 1px solid {resolve('--gray-300')};"
            f" border-radius: {resolve('--radius-md')}; }}"
            f" #ProtoHelp QLabel {{ background: transparent; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(_number_circle(p["n"]), 0, Qt.AlignTop)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(p["title"])
        title.setWordWrap(True)
        title.setFont(sans_font(size="--text-md", weight=700))
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
            row.setFont(sans_font(size="--text-md"))
            lay.addWidget(row)
        lay.addStretch(1)


class HelpScreen(QWidget):
    def __init__(self, parent=None, section_titles=None):
        super().__init__(parent)
        self.setObjectName("HelpScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#HelpScreen {{ background: {resolve('--surface-page')}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        outer.setSpacing(_GAP)
        tabs = QHBoxLayout()
        tabs.setSpacing(_GAP)
        self._sections = QStackedWidget()
        self._section_buttons = []
        for index, title in enumerate(section_titles or ("Protocols", "Controls")):
            button = DSButton(title, variant="secondary", full_width=True)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, i=index: self._select_section(i))
            tabs.addWidget(button)
            self._section_buttons.append(button)
        outer.addLayout(tabs)
        outer.addWidget(self._sections, 1)
        lay = self._add_section()

        # The section button identifies this grid; a second header wastes reading space.
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(_GAP)
        for i, p in enumerate(HELP_PROTOCOLS):
            grid.addWidget(_ProtocolHelpPanel(p), i // 2, i % 2)
        for c in (0, 1):
            grid.setColumnStretch(c, 1)
        for r in (0, 1):
            grid.setRowStretch(r, 1)
        lay.addWidget(grid_host, 1)

        # Keep controls and safety directly accessible rather than below a tall
        # protocol grid. Each section can still scroll on a smaller viewport.
        reference = self._add_section()
        columns = QHBoxLayout()
        columns.setSpacing(_GAP)
        columns.addWidget(self._controls_card(), 3)
        columns.addWidget(self._safety_card(), 2)
        reference.addLayout(columns, 1)
        self._select_section(0)

    def _add_section(self) -> QVBoxLayout:
        """Create a width-aware scroll fallback without hiding section buttons."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        QScroller.grabGesture(scroll.viewport(), QScroller.TouchGesture)
        content = QWidget()
        content.setObjectName("HelpSection")
        content.setStyleSheet(f"#HelpSection {{ background: {resolve('--surface-page')}; }}")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_GAP)
        layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        scroll.setWidget(content)
        self._sections.addWidget(scroll)
        return layout

    def _select_section(self, index: int) -> None:
        """Keep the selected section and its visible button state in sync."""
        self._sections.setCurrentIndex(index)
        for i, button in enumerate(self._section_buttons):
            button.setChecked(i == index)
            button.set_variant("primary" if i == index else "secondary")

    def _controls_card(self):
        card = DSCard("Treatment Controls", padded=False)
        host = QWidget()
        rows = QVBoxLayout(host)
        rows.setContentsMargins(20, 10, 20, 10)
        rows.setSpacing(8)
        for i, (key, desc) in enumerate(HELP_CONTROLS):
            if i:
                divider = QFrame()
                divider.setFixedHeight(1)
                divider.setStyleSheet(f"background: {resolve('--gray-300')};")
                rows.addWidget(divider)
            text = QVBoxLayout()
            text.setSpacing(3)
            title = QLabel(key)
            title.setFont(sans_font(size="--text-md", weight=600))
            body = QLabel(desc)
            body.setWordWrap(True)
            body.setFont(sans_font(size="--text-md"))
            text.addWidget(title)
            text.addWidget(body)
            rows.addLayout(text, 1)
        card.add_widget(host)
        return card

    def _safety_card(self):
        card = DSCard("Limits and recovery", padded=False)
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(20, 16, 20, 16)
        column.setSpacing(16)
        limits = QGridLayout()
        limits.setSpacing(12)
        for i, (label, value, unit) in enumerate(SAFETY_LIMITS):
            tile = QFrame()
            tile.setObjectName("SafetyLimit")
            tile.setStyleSheet(
                f"#SafetyLimit {{ background: {resolve('--blue-050')}; border-radius: 8px; }}"
                "#SafetyLimit QLabel { background: transparent; }"
            )
            text = QVBoxLayout(tile)
            text.setContentsMargins(12, 12, 12, 12)
            caption = QLabel(label)
            caption.setFont(sans_font(size="--text-sm"))
            reading = QLabel(f"{value} {unit}")
            reading.setFont(sans_font(size="--text-lg", weight=600))
            text.addWidget(caption)
            text.addWidget(reading)
            limits.addWidget(tile, i // 2, i % 2)
        limits.setColumnStretch(0, 1)
        limits.setColumnStretch(1, 1)
        column.addLayout(limits, 1)
        heading = QLabel("Stopping and recovery")
        heading.setFont(sans_font(size="--text-md", weight=600))
        column.addWidget(heading)
        note = QLabel(
            f"<b style='color:{resolve('--red-500')}'>Stop + reset</b> "
            "stops now, then releases and homes the device. Physical emergency stop and "
            "pressure-notice Stop have separate recovery procedures. Read device status."
        )
        note.setTextFormat(Qt.RichText)
        note.setWordWrap(True)
        note.setFont(sans_font(size="--text-md"))
        note.setStyleSheet(f"color: {resolve('--ink-700')};")
        column.addWidget(note)
        card.add_widget(host)
        return card
