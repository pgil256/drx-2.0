"""Touch controls for guided horizontal and lateral actuator calibration."""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from helpers.calibration import CalibrationDraft
from ui.widgets.ds import DSButton
from ui.widgets.ds._common import resolve, sans_font

try:
    from main.config.constants import CALIBRATION_AXES
except ModuleNotFoundError:  # Direct script entry point
    from config.constants import CALIBRATION_AXES


class CalibrationDialog(QDialog):
    """Edit a draft; the controller owns all device access and persistence."""

    jog_requested = pyqtSignal(int)
    capture_requested = pyqtSignal()
    move_requested = pyqtSignal()
    anchor_requested = pyqtSignal(str)
    factor_requested = pyqtSignal()
    save_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    leaving = pyqtSignal()
    axis_changed = pyqtSignal()

    def __init__(self, draft: CalibrationDraft, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.draft = draft
        self._closed = False
        self.setWindowTitle("Calibrate Actuators")
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(1080, 704)
        self.setFont(sans_font(size="--text-base"))
        self.setStyleSheet(
            f"QDialog {{ background: {resolve('--surface-page')}; }}"
            "QComboBox { min-height: 48px; padding: 0 8px; }"
            "QDoubleSpinBox, QSpinBox { min-height: 48px; padding: 0 8px; }"
            "QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 34px; }"
            "QTabBar::tab { padding: 12px 20px; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        title = QLabel("Calibrate Actuators")
        title.setFont(sans_font(size="--text-xl", weight=700))
        root.addWidget(title)
        guide = QLabel(
            "Use with the device unloaded. Jog to a physically measured angle, then record it. "
            "Choosing an angle does not move the actuator."
        )
        guide.setWordWrap(True)
        root.addWidget(guide)
        header = QHBoxLayout()
        self.axis = QComboBox()
        for key, spec in CALIBRATION_AXES.items():
            self.axis.addItem(spec["label"], key)
        header.addWidget(self.axis)
        self.live = QLabel("Waiting for live positions…")
        header.addWidget(self.live, 1)
        root.addLayout(header)
        jog = QHBoxLayout()
        self.jog_buttons = []
        for step in (-200, -50, 50, 200):
            button = DSButton(f"{step:+d} counts", variant="secondary")
            button.clicked.connect(
                lambda _checked=False, delta=step: self.jog_requested.emit(delta)
            )
            self.jog_buttons.append(button)
            jog.addWidget(button)
            if step == -50:
                self.stop_button = DSButton("STOP", variant="danger")
                self.stop_button.clicked.connect(self.stop_requested)
                jog.addWidget(self.stop_button)
        root.addLayout(jog)
        self.tabs = QTabWidget()
        self._build_angles()
        self._build_factor()
        root.addWidget(self.tabs, 1)
        self.message = QLabel("Waiting for fresh, steady position readings.")
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(48)
        root.addWidget(self.message)
        footer = QHBoxLayout()
        self.close_button = DSButton("Close", variant="ghost")
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.close_button)
        footer.addStretch()
        self.save_button = DSButton("Save calibration", variant="success")
        self.save_button.clicked.connect(self.save_requested)
        footer.addWidget(self.save_button)
        root.addLayout(footer)
        self.axis.currentIndexChanged.connect(self._change_axis)
        # Enter while editing a number must not activate a default jog button.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self._change_axis()
        self.set_available(False, False)

    def _build_angles(self) -> None:
        page = QWidget()
        row = QHBoxLayout(page)
        editor = QVBoxLayout()
        label = QLabel("Measured angle")
        editor.addWidget(label)
        self.angle = QDoubleSpinBox()
        self.angle.setDecimals(1)
        self.angle.setSuffix("°")
        editor.addWidget(self._number_control(self.angle))
        self.capture_button = DSButton("Record current position")
        self.capture_button.clicked.connect(self.capture_requested)
        editor.addWidget(self.capture_button)
        tip = QLabel(
            "Measure each angle with a gauge. Record both endpoints and intermediate angles."
        )
        tip.setWordWrap(True)
        tip.setMaximumWidth(290)
        editor.addWidget(tip)
        editor.addStretch()
        self.move_button = DSButton("Go to selected mark", variant="secondary")
        self.move_button.clicked.connect(self.move_requested)
        editor.addWidget(self.move_button)
        self.remove_button = DSButton("Remove selected mark", variant="ghost")
        self.remove_button.clicked.connect(self._remove_mark)
        editor.addWidget(self.remove_button)
        row.addLayout(editor, 1)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Angle", "Position (counts)", "Source"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._select_mark)
        row.addWidget(self.table, 2)
        self.tabs.addTab(page, "Angle marks")

    def _build_factor(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        description = QLabel(
            "Record two actuator positions and measure the travel between them in inches. "
            "This calculates the distance factor; angle movements use the angle marks."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        anchors = QHBoxLayout()
        self.anchor_buttons = []
        for name in ("start", "end"):
            button = DSButton(f"Record {name} position", variant="secondary")
            button.clicked.connect(lambda _checked=False, n=name: self.anchor_requested.emit(n))
            self.anchor_buttons.append(button)
            anchors.addWidget(button)
        layout.addLayout(anchors)
        self.anchors_label = QLabel("Start: —    End: —")
        layout.addWidget(self.anchors_label)
        form = QFormLayout()
        self.distance = QDoubleSpinBox()
        self.distance.setRange(0.01, 20.0)
        self.distance.setDecimals(2)
        self.distance.setSingleStep(0.1)
        self.distance.setValue(1.0)
        self.distance.setSuffix(" in")
        form.addRow("Measured travel", self._number_control(self.distance))
        self.factor = QSpinBox()
        self.factor.setRange(1, 1000000)
        form.addRow("Distance factor", self._number_control(self.factor))
        layout.addLayout(form)
        self.calculate_button = DSButton("Calculate factor", variant="secondary")
        self.calculate_button.clicked.connect(self.factor_requested)
        layout.addWidget(self.calculate_button)
        self.apply_factor_button = DSButton("Use this factor")
        self.apply_factor_button.clicked.connect(self._apply_factor)
        layout.addWidget(self.apply_factor_button)
        layout.addStretch()
        self.tabs.addTab(page, "Distance factor")

    @staticmethod
    def _number_control(spin: QWidget) -> QWidget:
        """Give numeric entry full-size touch buttons without moving the device."""
        host = QWidget()
        host.setFixedHeight(56)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        spin.setButtonSymbols(QSpinBox.NoButtons)
        for label, slot in (("−", spin.stepDown), ("+", spin.stepUp)):
            button = DSButton(label, variant="secondary")
            button.setFixedSize(56, 56)
            button.setStyleSheet("padding: 0; font-size: 24px;")
            button.setAutoRepeat(True)
            button.setAutoRepeatDelay(500)
            button.setAutoRepeatInterval(150)
            button.clicked.connect(slot)
            layout.addWidget(button)
            if label == "−":
                layout.addWidget(spin, 1)
        return host

    def current_axis(self) -> str:
        """Return the selected actuator key."""
        return self.axis.currentData()

    def _change_axis(self) -> None:
        spec = CALIBRATION_AXES[self.current_axis()]
        self.angle.setRange(*spec["angle_limits"])
        self.angle.setSingleStep(spec["angle_step"])
        self.angle.setValue(0)
        self.factor.setValue(self.draft.factors[self.current_axis()])
        self.refresh_table()
        self.axis_changed.emit()

    def refresh_table(self) -> None:
        """Show saved and newly recorded values without claiming they were verified."""
        axis = self.current_axis()
        entries = sorted(self.draft.marks[axis].items(), key=lambda pair: float(pair[0]))
        self.table.setRowCount(len(entries))
        for row, (angle, position) in enumerate(entries):
            source = "Recorded" if angle in self.draft.recorded[axis] else "Existing"
            for column, value in enumerate((f"{angle}°", str(position), source)):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, angle)
                self.table.setItem(row, column, item)
        self.save_button.setEnabled(self.draft.dirty)

    def selected_mark(self) -> Optional[str]:
        """Return the selected angle key, if any."""
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item is not None else None

    def _select_mark(self) -> None:
        key = self.selected_mark()
        if key is not None:
            self.angle.setValue(float(key))

    def _remove_mark(self) -> None:
        key = self.selected_mark()
        if key is not None:
            self.draft.marks[self.current_axis()].pop(key)
            self.draft.recorded[self.current_axis()].discard(key)
            self.refresh_table()

    def _apply_factor(self) -> None:
        self.draft.factors[self.current_axis()] = self.factor.value()
        self.save_button.setEnabled(self.draft.dirty)
        self.show_message("Factor added to the draft. Select Save calibration to keep it.")

    def set_available(self, ready: bool, moving: bool) -> None:
        """Keep STOP/Close reachable while all motion and capture controls are locked."""
        for widget in self.jog_buttons + self.anchor_buttons + [
            self.capture_button, self.move_button,
        ]:
            widget.setEnabled(ready and not moving)
        self.axis.setEnabled(not moving)
        self.tabs.setEnabled(not moving)
        self.save_button.setEnabled(self.draft.dirty and not moving)

    def show_message(self, message: str, error: bool = False) -> None:
        """Present persistent feedback below the editor."""
        self.message.setText(message)
        self.message.setStyleSheet("color: #b42318;" if error else "")

    def reject(self) -> None:
        """Stop an outstanding move before offering to discard unsaved edits."""
        if self._closed:
            return
        self.leaving.emit()
        if self.draft.dirty:
            choice = QMessageBox.question(
                self, "Unsaved calibration", "Discard the unsaved calibration changes?",
                QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if choice != QMessageBox.Discard:
                return
        self.done(QDialog.Rejected)

    def done(self, result: int) -> None:
        """Mark the dialog closed before emitting finished and releasing its owner."""
        self._closed = True
        super().done(result)
