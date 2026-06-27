"""DSCard — white surface panel with an optional dark header bar.

Mirrors `Card`: rounded white surface (--radius-lg), soft shadow (--shadow-md),
optional dark header (title left, `header_right` widget right), and a body whose
padding follows `padded`. Screens add content via `add_widget` / `body_layout`.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ._common import drop_shadow, px, resolve, sans_font


class DSCard(QFrame):
    def __init__(self, title=None, header_right=None, padded=True, parent=None):
        super().__init__(parent)
        self.setObjectName("DSCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        radius = resolve("--radius-lg")
        # Mirror the DS Card's `color: var(--text-body)` on the outer div: give
        # descendant labels the body text color so screen copy added without an
        # explicit color inherits ink-700 (not Qt's default near-black). Labels
        # with their own color (header title, StatReadout, etc.) override this.
        self.setStyleSheet(
            f"#DSCard {{ background: {resolve('--surface-card')}; border-radius: {radius}; }}"
            f"#DSCard QLabel {{ color: {resolve('--text-body')}; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = None
        self._title_label = None
        if title is not None:
            self._header = QFrame(self)
            self._header.setObjectName("DSCardHeader")
            self._header.setAttribute(Qt.WA_StyledBackground, True)
            self._header.setStyleSheet(
                f"#DSCardHeader {{ background: {resolve('--surface-dark')};"
                f" border-top-left-radius: {radius}; border-top-right-radius: {radius}; }}"
            )
            hbox = QHBoxLayout(self._header)
            hbox.setContentsMargins(20, 12, 20, 12)
            hbox.setSpacing(8)
            self._title_label = QLabel(title, self._header)
            self._title_label.setFont(sans_font(size="--text-base", weight=600))
            self._title_label.setStyleSheet(
                f"color: {resolve('--text-on-dark')}; background: transparent;"
            )
            hbox.addWidget(self._title_label)
            hbox.addStretch(1)
            self._header_box = hbox
            if header_right is not None:
                self.set_header_right(header_right)
            outer.addWidget(self._header)

        self.body = QWidget(self)
        self.body.setAttribute(Qt.WA_StyledBackground, True)
        self.body.setStyleSheet("background: transparent;")
        self.body_layout = QVBoxLayout(self.body)
        pad = px("--space-6") if padded else 0
        self.body_layout.setContentsMargins(pad, pad, pad, pad)
        outer.addWidget(self.body, 1)

        drop_shadow(self, blur=24, dy=4, alpha=38)  # --shadow-md

    def set_header_right(self, widget):
        if self._header is None:
            return
        widget.setParent(self._header)
        self._header_box.addWidget(widget)

    def add_widget(self, widget, stretch=0):
        self.body_layout.addWidget(widget, stretch)

    def add_layout(self, layout, stretch=0):
        self.body_layout.addLayout(layout, stretch)
