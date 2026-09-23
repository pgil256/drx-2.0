"""DSKeyValueList — muted label left, strong value right, 40px rows.

Replaces loose ``"Label: value"`` strings on Home, Device, Profile and the
treatment review. Controllers still write whole sentences such as
``"Cloud: Connected"`` into a row's value label; the label strips its own
prefix so existing ``setText`` callers keep working and the row reads
``Cloud ........ Connected``.

Rows created with ``status=True`` show a dot whose tone follows the value
(green connected, amber pending, red failed, grey unknown).
"""

from typing import Dict, Iterable, Optional, Sequence

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget

from ._common import resolve, sans_font

ROW_HEIGHT = 40

# Value words -> dot tone for status rows. First match wins; checked in order.
_TONE_WORDS = (
    ("danger", ("disconnected", "offline", "failed", "failure", "denied", "error",
                "unreachable", "not reachable", "fault")),
    ("warning", ("pending", "waiting", "not synchronized", "attention", "retry",
                 "checking", "disabled", "required", "stale")),
    ("neutral", ("not checked", "not configured", "not recorded", "unknown",
                 "unavailable", "never", "—", "no staff session", "not provided")),
    ("success", ("connected", "reachable", "enabled", "synchronized", "up to date",
                 "ready", "saved")),
)
_DOT_TOKENS = {
    "success": "--green-500", "warning": "--amber-500", "danger": "--red-500",
    "neutral": "--gray-400", "info": "--blue-500",
}


def status_tone(text: str) -> str:
    """Classify a status value for its dot colour (pure; used by tests too)."""
    lowered = (text or "").strip().lower()
    for tone, words in _TONE_WORDS:
        if any(word in lowered for word in words):
            return tone
    return "neutral"


class _ValueLabel(QLabel):
    """Strips ``"<prefix>: "`` so legacy sentence-style updates render as values."""

    def __init__(self, prefixes: Sequence[str], on_change=None, parent=None) -> None:
        super().__init__(parent)
        self._prefixes = tuple(p for p in prefixes if p)
        self._on_change = on_change

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        text = "" if text is None else str(text)
        for prefix in self._prefixes:
            marker = prefix + ": "
            if text.startswith(marker):
                text = text[len(marker):]
                break
        super().setText(text)
        if self._on_change is not None:
            self._on_change(text)


class DSKeyValueList(QWidget):
    def __init__(self, parent: Optional[QWidget] = None, label_width: Optional[int] = None,
                 dividers: bool = True) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(0)
        self._grid.setColumnStretch(1, 1)
        if label_width:
            self._grid.setColumnMinimumWidth(0, label_width)
        self._dividers = dividers
        self._row = 0
        self._values: Dict[str, _ValueLabel] = {}
        self._labels: Dict[str, QLabel] = {}
        self._dots: Dict[str, QFrame] = {}
        self._rules: Dict[str, QFrame] = {}
        self._cells: Dict[str, QWidget] = {}
        self._status_keys = set()

    def add_row(self, key: str, label: str, value: str = "",
                strip: Optional[Iterable[str]] = None, status: bool = False,
                selectable: bool = False) -> QLabel:
        """Add a row and return its value label (safe to ``setText`` directly)."""
        if self._row and self._dividers:
            rule = QFrame(self)
            rule.setFixedHeight(1)
            rule.setStyleSheet(f"background: {resolve('--border-divider')}; border: none;")
            self._grid.addWidget(rule, self._row, 0, 1, 2)
            self._rules[key] = rule
            self._row += 1

        # The dot shares the label cell, so lists without status rows stay flush.
        cell = QWidget(self)
        cell_row = QHBoxLayout(cell)
        cell_row.setContentsMargins(0, 0, 0, 0)
        cell_row.setSpacing(12)
        dot = QFrame(cell)
        dot.setFixedSize(10, 10)
        dot.setVisible(status)
        cell_row.addWidget(dot, 0, Qt.AlignVCenter)
        if status:
            self._status_keys.add(key)

        caption = QLabel(label, cell)
        caption.setFont(sans_font(size="--text-sm"))
        caption.setStyleSheet(f"color: {resolve('--text-muted')}; background: transparent;")
        caption.setMinimumHeight(ROW_HEIGHT)
        caption.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cell_row.addWidget(caption, 1)
        self._grid.addWidget(cell, self._row, 0)

        prefixes = [label] + list(strip or [])
        value_label = _ValueLabel(
            prefixes, (lambda text, k=key: self._retone(k, text)) if status else None, self)
        value_label.setTextFormat(Qt.PlainText)
        value_label.setWordWrap(True)
        value_label.setFont(sans_font(size="--text-base", weight=600))
        value_label.setStyleSheet(f"color: {resolve('--text-strong')}; background: transparent;")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setMinimumHeight(ROW_HEIGHT)
        value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if selectable:
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._grid.addWidget(value_label, self._row, 1)
        self._row += 1

        self._cells[key] = cell
        self._values[key] = value_label
        self._labels[key] = caption
        self._dots[key] = dot
        value_label.setText(value)
        if status:
            self._retone(key, value_label.text())
        return value_label

    def _retone(self, key: str, text: str) -> None:
        dot = self._dots.get(key)
        if dot is None:
            return
        color = resolve(_DOT_TOKENS[status_tone(text)])
        dot.setStyleSheet(f"background: {color}; border-radius: 5px;")

    def value(self, key: str) -> QLabel:
        return self._values[key]

    def set_value(self, key: str, text: str) -> None:
        self._values[key].setText(text)

    def set_row_visible(self, key: str, visible: bool) -> None:
        for widget in (self._values[key], self._cells[key], self._rules.get(key)):
            if widget is not None:
                widget.setVisible(visible)

    def keys(self):
        return list(self._values)
