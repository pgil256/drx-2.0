"""Touch controls for editing the settings displayed on the treatment screen.

An in-shell DSDialog sheet over a dimmed Treatment page: one row per setting
(label with its allowed range, − / slider / + and the value), Stop at the left
of the footer while a treatment runs and Done at the right. Tapping the scrim
closes the sheet like Done; every change has already been requested.
"""

from typing import Optional, Sequence

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.screens.content import PROTOCOLS
from ui.theme import control_icon
from ui.widgets.common import hline
from ui.widgets.ds import DSButton, DSDialog, DSSlider
from ui.widgets.ds._common import mono_font, resolve, sans_font

EDITOR_SIZE = (1000, 708)


def _range_hint(low: float, high: float, unit: str) -> str:
    return f"{low:g}–{high:g}{unit}"


class TreatmentEditorDialog(DSDialog):
    """Apply edits through the controller while keeping Stop directly accessible."""

    setting_changed = pyqtSignal(str, float)
    estop_requested = pyqtSignal()

    def __init__(self, specs: Sequence[tuple], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, title="Edit treatment", dismiss_on_scrim=True)
        self._selected = 1
        self._running = False
        self._editable = True
        self.resize(*EDITOR_SIZE)
        layout = self.body_layout
        layout.setContentsMargins(28, 14, 28, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(16)
        self._protocol_label = QLabel()
        self._protocol_label.setFont(sans_font(size="--text-md", weight=600))
        self._protocol_label.setStyleSheet(f"color: {resolve('--text-strong')};")
        header.addWidget(self._protocol_label)
        header.addStretch(1)
        self._hint = QLabel("Changes apply to the current treatment settings.")
        self._hint.setFont(sans_font(size="--text-sm"))
        self._hint.setStyleSheet(f"color: {resolve('--text-muted')};")
        header.addWidget(self._hint)
        layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self._settings = {}
        for index, (key, label, value, low, high, step, unit) in enumerate(specs):
            slider = DSSlider(label=label, value=value, minimum=low, maximum=high,
                              step=step, unit=unit, with_steps=True, label_width=170,
                              hint=_range_hint(low, high, unit))
            slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            slider.layout().setContentsMargins(0, 6, 0, 6)
            slider.layout().setSpacing(20)
            slider._label.setFont(sans_font(size="--text-md", weight=600))
            slider._value_label.setFont(mono_font(size="--text-lg", weight=600))
            for button in (slider._left_btn, slider._right_btn):
                button.setFixedSize(64, 64)
            slider.set_accessible_label(label)
            slider._slider.setTracking(False)
            slider._slider.setMinimumHeight(64)
            slider._value_label.setFixedWidth(112)
            slider.valueChanged.connect(lambda v, k=key: self.setting_changed.emit(k, v))
            self._settings[key] = slider
            rows.addWidget(slider, 1)
            if index < len(specs) - 1:
                rows.addWidget(hline())
        self._scroll.setWidget(content)
        for widget in (self._scroll, self._scroll.viewport(), content):
            widget.setAutoFillBackground(False)
        layout.addWidget(self._scroll, 1)
        self._settings["motor_speed"].setAccessibleDescription(
            "One output percentage for axial, lateral, and pulsation movement."
        )

        white = resolve("--white")
        self.stop_button = DSButton("STOP", variant="danger", size="md",
                                    icon=control_icon("stop", white, 20))
        self.stop_button.setAutoDefault(False)
        self.stop_button.setMinimumWidth(220)
        self.stop_button.clicked.connect(self._stop)
        self.stop_button.hide()
        self.add_action(self.stop_button)
        self.add_action_stretch(1)
        self.done_button = DSButton("Done", variant="primary", size="md")
        self.done_button.setMinimumWidth(180)
        self.done_button.setAutoDefault(False)
        self.done_button.clicked.connect(self.accept)
        self.add_action(self.done_button)
        self.select_protocol(1)

    def _stop(self) -> None:
        self.reject()
        self.estop_requested.emit()

    def select_protocol(self, number: int) -> None:
        """Reflect a selection without emitting another controller request."""
        self._selected = number
        self._protocol_label.setText(f"{number} · {PROTOCOLS[number - 1]['title']}")
        self.set_run_state(self._running, self._editable)

    def set_run_state(self, running: bool, editable: bool) -> None:
        """Keep protocol, duration and motor speed fixed throughout an active run."""
        self._running = running
        self._editable = editable
        for key, slider in self._settings.items():
            relevant = (
                (key != "max_left" or self._selected in (2, 4))
                and (key != "max_right" or self._selected in (3, 4))
            )
            slider.setEnabled(
                editable and relevant and (not running or key not in ("duration", "motor_speed"))
            )
        self.stop_button.setVisible(running)
        self._hint.setText(
            "Protocol, duration and motor speed are locked during treatment."
            if running else "Changes apply to the current treatment settings."
        )
