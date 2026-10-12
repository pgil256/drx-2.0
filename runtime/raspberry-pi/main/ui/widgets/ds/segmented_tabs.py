"""DSSegmentedTabs — one tab pattern for every sectioned page and dialog.

A white group with a 1px border holds equal-width segments; the active segment
is filled primary. Support, Troubleshooting topics, Device and the service
dialog all use it, so a "tab" looks the same everywhere.

The owner decides what a tap means: a tap emits ``tab_requested(index)`` and
leaves the highlight alone until :meth:`set_current` is called. That keeps a
gated section (Device → Service needs a PIN) from lighting up before access is
granted.

Sizes: ``md`` (56px group) and ``sm`` (52px group, smaller label) — both keep
48px segments so every tab stays a full touch target.
"""

from typing import List, Optional, Sequence

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QPushButton, QSizePolicy, QWidget

from ._common import resolve, sans_font

# size -> (segment height, group padding, label font)
_METRICS = {"md": (48, 4, "--text-base"), "sm": (48, 2, "--text-sm")}


class DSSegmentedTabs(QFrame):
    tab_requested = pyqtSignal(int)

    def __init__(self, titles: Sequence[str], size: str = "md",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DSSegmentedTabs")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        segment_h, pad, font = _METRICS.get(size, _METRICS["md"])
        self._current = -1
        self._buttons: List[QPushButton] = []

        lay = QHBoxLayout(self)
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(pad)
        for index, title in enumerate(titles):
            button = QPushButton(title.replace("&", "&&"), self)
            button.setObjectName("DSSegment")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.TabFocus)
            button.setFixedHeight(segment_h)
            button.setFont(sans_font(size=font, weight=600))
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setAccessibleName(title)
            button.clicked.connect(lambda _checked, i=index: self._on_clicked(i))
            lay.addWidget(button, 1)
            self._buttons.append(button)
        # Group padding on both sides plus its 1px border.
        self.setFixedHeight(segment_h + 2 * pad + 2)

        primary = resolve("--color-primary")
        radius = int(resolve("--radius-md").replace("px", ""))
        self.setStyleSheet(
            f"#DSSegmentedTabs {{ background: {resolve('--white')};"
            f" border: 1px solid {resolve('--border-control')};"
            f" border-radius: {radius + pad // 2}px; }}"
            f"#DSSegment {{ background: transparent; color: {resolve('--ink-700')};"
            f" border: none; border-radius: {radius - 2}px; padding: 0 12px;"
            # QSS min/max-height replace setFixedHeight's bounds; restate them.
            f" min-height: {segment_h}px; max-height: {segment_h}px; }}"
            f"#DSSegment:hover {{ background: {resolve('--gray-050')}; }}"
            f"#DSSegment:pressed {{ background: {resolve('--gray-200')}; }}"
            f"#DSSegment:checked {{ background: {primary}; color: {resolve('--white')}; }}"
            f"#DSSegment:checked:pressed {{ background: {resolve('--color-primary-active')}; }}"
            f"#DSSegment:disabled {{ color: {resolve('--gray-600')}; }}"
            f"#DSSegment[keyboardFocus=\"true\"]:focus {{"
            f" border: 2px solid {resolve('--ink-900')}; }}"
        )

    def _on_clicked(self, index: int) -> None:
        # QPushButton toggles itself on click; restore the owner's selection
        # until it confirms the change.
        self._sync()
        self.tab_requested.emit(index)

    def _sync(self) -> None:
        for i, button in enumerate(self._buttons):
            button.setChecked(i == self._current)

    def set_current(self, index: int) -> None:
        """Highlight *index* without emitting ``tab_requested``."""
        self._current = index
        self._sync()

    def current(self) -> int:
        return self._current

    def buttons(self) -> List[QPushButton]:
        return list(self._buttons)

    def set_titles(self, titles: Sequence[str]) -> None:
        for button, title in zip(self._buttons, titles):
            button.setText(title.replace("&", "&&"))
            button.setAccessibleName(title)
