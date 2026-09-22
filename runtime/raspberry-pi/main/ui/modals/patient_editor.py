"""Touchscreen patient name and treatment-plan editor."""

from typing import Dict, Mapping, Optional

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea,
    QVBoxLayout, QWidget,
)

from helpers.cloud_contract import SETTING_RULES, validate_patient
from ui.modals.staff_login import open_text_keyboard
from ui.screens.content import PROTOCOLS
from ui.screens.treatment import SETTING_SPECS
from ui.widgets.ds import DSButton, DSSlider
from ui.widgets.ds._common import sans_font


class NameKeyboard(QDialog):
    """Edit a name without relying on a desktop's optional keyboard service."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Patient name")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setFixedWidth(860)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        self.text = QLineEdit()
        self.text.setMaxLength(200)
        self.text.setAccessibleName("Patient name")
        self.text.setMinimumHeight(52)
        self.text.setFont(sans_font(size=22))
        self.text.returnPressed.connect(self.accept)
        layout.addWidget(self.text)
        self._letters = []
        self._uppercase = True
        for letters in ("1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM'-"):
            row = QHBoxLayout()
            row.setSpacing(6)
            for letter in letters:
                key = DSButton(letter, variant="secondary", size="sm")
                key.setMinimumSize(60, 48)
                key.setAutoDefault(False)
                key.setFocusPolicy(Qt.NoFocus)
                key.clicked.connect(lambda _checked, button=key: self.text.insert(button.text()))
                row.addWidget(key)
                if letter.isalpha():
                    self._letters.append(key)
            layout.addLayout(row)
        row = QHBoxLayout()
        for title, action in (("Shift", self._shift), ("Space", lambda: self.text.insert(" ")),
                              ("Backspace", self.text.backspace), ("Cancel", self.reject),
                              ("Done", self.accept)):
            key = DSButton(title, variant="primary" if title == "Done" else "secondary")
            key.setAutoDefault(False)
            key.setFocusPolicy(Qt.NoFocus)
            key.clicked.connect(action)
            row.addWidget(key)
        layout.addLayout(row)

    def _shift(self) -> None:
        self._uppercase = not self._uppercase
        for key in self._letters:
            key.setText(key.text().upper() if self._uppercase else key.text().lower())


class PatientEditor(QDialog):
    """Stage all edits until a complete validated patient is saved successfully."""

    submitted = pyqtSignal(object)
    sign_in_requested = pyqtSignal()
    reconcile_requested = pyqtSignal()
    reload_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setFixedSize(900, 710)
        self._patient: Dict = {}
        self._pending = False
        self._authorized = False
        self._saved = False
        self._editing = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(12)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(8)
        self._scroll.setWidget(content)
        outer.addWidget(self._scroll, 1)
        self._title = QLabel()
        self._title.setFont(sans_font(size=24, weight=600))
        layout.addWidget(self._title)
        account = QHBoxLayout()
        self._account = QLabel("Cloud staff sign-in is required to save patients.")
        self._account.setTextFormat(Qt.PlainText)
        self._account.setWordWrap(True)
        account.addWidget(self._account, 1)
        self._sign_in = DSButton("Cloud sign in", variant="secondary", size="sm")
        self._sign_in.clicked.connect(self.sign_in_requested)
        account.addWidget(self._sign_in)
        layout.addLayout(account)
        self._fields = QWidget()
        grid = QGridLayout(self._fields)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self._name = QLineEdit()
        self._name.setMaxLength(200)
        self._name.setMinimumHeight(52)
        self._name.setAccessibleName("Patient name")
        self._name.setPlaceholderText("Tap to enter patient name")
        self._name.installEventFilter(self)
        self._keyboard = NameKeyboard(self)
        self._keyboard.accepted.connect(lambda: self._name.setText(self._keyboard.text.text()))
        self._protocol = QComboBox()
        self._protocol.setMinimumHeight(52)
        self._protocol.setAccessibleName("Protocol number")
        for number, protocol in enumerate(PROTOCOLS, 1):
            self._protocol.addItem(f"{number} · {protocol['title']}", number)
        for col, (title, widget) in enumerate((("Patient name", self._name),
                                              ("Protocol number", self._protocol))):
            grid.addWidget(QLabel(title), 0, col)
            grid.addWidget(widget, 1, col)
        self._settings = {}
        labels = {"max_left": "Max angle left", "max_right": "Max angle right",
                  "max_pressure": "Max pressure", "pulse_rate": "Pulse rate"}
        for index, (key, label, value, low, high, step, unit) in enumerate(SETTING_SPECS):
            row, col = 2 + (index // 2) * 2, index % 2
            label = labels.get(key, label)
            grid.addWidget(QLabel(label), row, col)
            control = DSSlider(value=value, minimum=low, maximum=high, step=step,
                               unit=unit, with_steps=True)
            control.set_accessible_label(label)
            grid.addWidget(control, row + 1, col)
            self._settings[key] = control
        layout.addWidget(self._fields)
        self._approve = QCheckBox("Approve initial cloud treatment plan")
        self._approve.hide()
        self._approve.toggled.connect(
            lambda checked: self._reason.setVisible(checked and self._editing)
        )
        layout.addWidget(self._approve)
        self._reason = QLineEdit()
        self._reason.setPlaceholderText("Reason for approving the treatment plan")
        self._reason.setAccessibleName("Plan approval reason")
        self._reason.setMaxLength(2000)
        self._reason.setMinimumHeight(48)
        self._reason.installEventFilter(self)
        self._reason.hide()
        layout.addWidget(self._reason)
        self._status = QLabel()
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        recovery = QHBoxLayout()
        self._reconcile = DSButton("Check saved patients", variant="secondary")
        self._reconcile.clicked.connect(self.reconcile_requested)
        self._reload = DSButton("Reload patient", variant="secondary")
        self._reload.clicked.connect(self.reload_requested)
        for button in (self._reconcile, self._reload):
            button.hide()
            recovery.addWidget(button)
        layout.addLayout(recovery)
        actions = QHBoxLayout()
        self._cancel = DSButton("Cancel", variant="secondary")
        self._save = DSButton("Save patient")
        for button in (self._cancel, self._save):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self._cancel.clicked.connect(self.reject)
        self._save.clicked.connect(self._submit)
        outer.addLayout(actions)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is getattr(self, "_reason", None) and event.type() == QEvent.MouseButtonRelease:
            self._reason_keyboard = open_text_keyboard(self._reason, self)
            return True
        if watched is self._name:
            selected = event.type() == QEvent.MouseButtonRelease
            tabbed = event.type() == QEvent.FocusIn and event.reason() in (
                Qt.TabFocusReason, Qt.BacktabFocusReason,
            )
            if (selected or tabbed) and not self._pending:
                if not self._keyboard.isVisible():
                    self._keyboard.text.setText(self._name.text())
                    self._keyboard.open()
                    self._keyboard.text.setFocus()
                return selected
        return super().eventFilter(watched, event)

    def open_patient(self, patient: Mapping, values: Mapping, protocol: int,
                     editing: bool = False) -> None:
        """Load a fresh draft; cancellation never changes the active patient."""
        self._patient = dict(patient)
        self._editing = editing
        self._saved = False
        self._reconcile.hide()
        self._reload.hide()
        self._approve.setChecked(False)
        self._approve.setText("Approve as saved cloud plan" if editing else
                              "Approve initial cloud treatment plan")
        self._reason.clear()
        self._reason.hide()
        title = "Edit patient and treatment plan" if editing else "Add new patient"
        self.setWindowTitle(title)
        self._title.setText(title)
        self._name.setText(patient.get("display_name") or "")
        self._protocol.setCurrentIndex(protocol - 1)
        for key, control in self._settings.items():
            control.set_value(values[key])
        self._status.setText("Settings apply to this treatment. Cloud plan approval is optional."
                             if editing else "")
        self._save.setText("Save patient")
        self.set_pending(False)
        self.open()
        self._scroll.verticalScrollBar().setValue(0)
        self._save.setFocus()

    def _submit(self) -> None:
        name = self._name.text().strip()
        if not name:
            self._status.setText("Enter a patient name before saving.")
            return
        settings = {field: self._settings[key].value()
                    for field, (key, _low, _high, _step) in SETTING_RULES.items()}
        settings["protocol_number"] = self._protocol.currentData()
        patient = dict(self._patient, display_name=name, settings=settings)
        try:
            validate_patient(patient)
        except ValueError:
            self._status.setText("Check the patient details and treatment settings.")
            return
        self.submitted.emit(patient)

    def set_pending(self, pending: bool) -> None:
        self._pending = pending
        self._fields.setEnabled(not pending and not self._saved)
        self._approve.setEnabled(not pending and not self._saved)
        self._reason.setEnabled(not pending and not self._saved)
        self._save.setEnabled(not pending and (self._authorized or self._saved)
                              and self._reconcile.isHidden() and self._reload.isHidden())
        self._cancel.setEnabled(not pending)
        self._sign_in.setEnabled(not pending)
        self._reconcile.setEnabled(not pending)
        self._reload.setEnabled(not pending)
        if pending:
            self._status.setText("Saving patient…")

    def show_error(self, message: str) -> None:
        self.set_pending(False)
        self._status.setText(message)
        self._scroll.ensureWidgetVisible(self._status)

    def set_staff(self, context: Mapping) -> None:
        self._authorized = "patients.edit" in context.get("permissions", [])
        clinic = context.get("clinic") or {}
        self._account.setText(
            f"{context.get('email', '')} · {clinic.get('name', '')}" if self._authorized
            else "Cloud staff sign-in is required to save patients."
        )
        self._sign_in.setText("Change account" if self._authorized else "Cloud sign in")
        self._approve.setVisible("plans.approve" in context.get("permissions", []))
        if not self._approve.isVisible():
            self._approve.setChecked(False)
        self.set_pending(self._pending)

    def set_save_state(self, saved: bool, uncertain: bool, reload_required: bool) -> None:
        self._saved = saved
        self._reconcile.setVisible(uncertain)
        self._reload.setVisible(reload_required)
        self._save.setText("Check patient readiness" if saved else "Save patient")
        self.set_pending(False)

    def reject(self) -> None:
        """Keep a submitted write attached to its result until it finishes."""
        if not self._pending:
            super().reject()
