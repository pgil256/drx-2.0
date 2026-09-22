"""Touch controls for editing the settings displayed on the treatment screen."""

from typing import Optional, Sequence

from PyQt5.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QShowEvent
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.screens.content import PROTOCOLS
from ui.widgets.common import hline
from ui.widgets.ds import DSButton, DSSlider
from ui.widgets.ds._common import mono_font, resolve, sans_font


class TreatmentEditorDialog(QDialog):
    """Apply edits through the controller while keeping Stop directly accessible."""

    setting_changed = pyqtSignal(str, float)
    estop_requested = pyqtSignal()

    def __init__(self, specs: Sequence[tuple], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._selected = 1
        self._running = False
        self._editable = True
        self.setWindowTitle("Edit treatment")
        self.setObjectName("TreatmentEditorDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#TreatmentEditorDialog {{ background: {resolve('--surface-card')}; }}"
            f"#TreatmentEditorDialog QLabel {{ color: {resolve('--text-body')}; }}"
        )
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(1000, 708)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(12)
        header = QVBoxLayout()
        header.setSpacing(4)
        heading = QHBoxLayout()
        title = QLabel("Edit treatment")
        title.setFont(sans_font(size=28, weight=600))
        heading.addWidget(title)
        heading.addStretch(1)
        self._protocol_label = QLabel()
        self._protocol_label.setFont(sans_font(size=18, weight=600))
        heading.addWidget(self._protocol_label)
        header.addLayout(heading)
        self._hint = QLabel("Changes apply to the current treatment settings.")
        self._hint.setFont(sans_font(size=16))
        header.addWidget(self._hint)
        layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self._settings = {}
        for index, (key, label, value, low, high, step, unit) in enumerate(specs):
            slider = DSSlider(label=label, value=value, minimum=low, maximum=high,
                              step=step, unit=unit, with_steps=True, label_width=160)
            slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            slider.layout().setContentsMargins(0, 10, 0, 10)
            slider.layout().setSpacing(20)
            slider._label.setFont(sans_font(size=20, weight=600))
            slider._value_label.setFont(mono_font(size=24, weight=600))
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

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.stop_button = DSButton("Stop", variant="danger", size="lg", full_width=True)
        self.stop_button.setAutoDefault(False)
        self.stop_button.clicked.connect(self._stop)
        self.stop_button.hide()
        actions.addWidget(self.stop_button)
        actions.addStretch(1)
        self.done_button = DSButton("Done", variant="primary", size="lg")
        self.done_button.setFixedWidth(180)
        self.done_button.setAutoDefault(False)
        self.done_button.clicked.connect(self.accept)
        actions.addWidget(self.done_button)
        layout.addLayout(actions)
        self.select_protocol(1)

    def showEvent(self, event: QShowEvent) -> None:
        """Fit and center the popup over the main GUI each time it opens."""
        super().showEvent(event)
        self._fit_over_gui()
        # Recheck once the window manager has supplied the native frame size.
        QTimer.singleShot(0, self._fit_over_gui)

    def _fit_over_gui(self) -> None:
        """Keep the entire window frame inside the GUI with a 20 px inset."""
        if not self.isVisible():
            return
        parent = self.parentWidget()
        if parent is None:
            bounds = self.screen().availableGeometry()
        else:
            window = parent.window()
            bounds = window.rect().translated(window.mapToGlobal(QPoint()))
        frame = self.frameGeometry()
        frame_width = frame.width() - self.width()
        frame_height = frame.height() - self.height()
        self.setFixedSize(
            max(1, min(1000, bounds.width() - 40 - frame_width)),
            max(1, min(708, bounds.height() - 40 - frame_height)),
        )
        frame = self.frameGeometry()
        frame.moveCenter(bounds.center())
        self.move(frame.topLeft())

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
