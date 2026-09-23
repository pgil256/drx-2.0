"""Operator-guided hardware checks with staged, reviewable calibration edits."""

from typing import Any, Dict, Optional

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QScrollArea, QScroller, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ui.theme import control_icon
from ui.widgets.ds import DSButton, DSDialog
from ui.widgets.ds._common import resolve, sans_font

try:
    from main.config.constants import ACTUATORS, PRESSURE_MAX
except ModuleNotFoundError:  # Direct script entry point
    from config.constants import ACTUATORS, PRESSURE_MAX


_STEPS = (
    ("preparation", "Prepare"),
    ("communication", "Connection & sensors"),
    ("axial", "Axial actuator"),
    ("horizontal", "Horizontal actuator"),
    ("lateral", "Lateral actuator"),
    ("leg", "Leg-length actuator"),
    ("loadcell", "Load cell"),
    ("stops", "Stops & inspection"),
    ("review", "Review & save"),
)
_AXES = ("axial", "horizontal", "lateral")
_BENCH_CHECKS = (
    ("pressure_control", "Pressure regulation & pulse"),
    ("pressure_accuracy", "Independent load reference / repeatability"),
    ("dynamic_stops", "Loaded motion stop & safe release"),
    ("watchdog", "Heartbeat / communication-loss watchdog"),
    ("power_recovery", "Power-loss & restart safety"),
    ("limit_switches", "Installed limits & interlocks"),
    ("mechanical", "Cabling, mountings & mechanical condition"),
)


class HardwareServiceDialog(DSDialog):
    """Display a service draft; the controller owns device access and persistence.

    All movement requests require a new operator confirmation. Test outcomes
    are operator observations, never inferred from clicking a test button.
    """

    action_requested = pyqtSignal(str, object)
    stop_requested = pyqtSignal()
    leaving = pyqtSignal()
    step_changed = pyqtSignal(str)

    def __init__(self, draft: Any, parent: Optional[QWidget] = None,
                 mode: str = "calibration") -> None:
        if mode not in ("tests", "calibration"):
            raise ValueError("Unknown service mode")
        # "Close service" in the footer is the only exit, so it can confirm.
        super().__init__(parent, title="Hardware tests" if mode == "tests" else "Calibration",
                         closable=False)
        self.mode = mode
        self._steps = tuple(
            (key, "Review results" if mode == "tests" and key == "review" else name)
            for key, name in _STEPS if mode == "tests" or key not in ("leg", "stops")
        )
        self.draft = draft
        self._ready = False
        self._busy = False
        self._aborted = False
        self._measurement_ready = False
        self._pressure_actions = []
        self._closed = False
        self._actions = []
        self._stationary_actions = []
        self._result_buttons = []
        self._results: Dict[str, tuple] = {}
        self._bench_results: Dict[str, tuple] = {}
        self._tables: Dict[str, QTableWidget] = {}
        self._measured: Dict[str, QDoubleSpinBox] = {}
        self._factor_labels: Dict[str, QLabel] = {}
        self._anchor_labels: Dict[str, QLabel] = {}
        self._notes: Dict[str, QPlainTextEdit] = {}
        self._result_labels: Dict[str, QLabel] = {}
        self._recorded: Dict[str, set] = {axis: set() for axis in _AXES}
        self.setWindowModality(Qt.ApplicationModal)
        self.resize(1080, 700)
        self.setMinimumSize(900, 620)
        self.setFont(sans_font(size="--text-base"))
        # Lists, tables, combos, spin boxes and checkboxes use the global theme.
        self.add_style(
            "#DSDialogBody QScrollArea { border: none; background: transparent; }"
            "#DSDialogBody QScrollArea > QWidget > QWidget { background: transparent; }"
        )

        root = self.body_layout
        root.setContentsMargins(20, 14, 20, 12)
        root.setSpacing(10)
        heading = QHBoxLayout()
        heading.setSpacing(12)
        self.live = self._label("Live readings: waiting for the device.")
        self.live.setMinimumHeight(48)
        self.live.setStyleSheet(
            f"background: {resolve('--surface-page')}; padding: 8px 12px;"
            f" border-radius: {resolve('--radius-md')};"
        )
        heading.addWidget(self.live, 1)
        self.stop_button = DSButton("STOP", variant="danger",
                                    icon=control_icon("stop", resolve("--white"), 20))
        self.stop_button.setMinimumWidth(160)
        self.stop_button.setMinimumHeight(48)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        heading.addWidget(self.stop_button)
        root.addLayout(heading)
        body = QHBoxLayout()
        body.setSpacing(18)
        self.steps = QListWidget()
        self.steps.setFixedWidth(240)
        self.steps.setWordWrap(True)
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        QScroller.grabGesture(self.steps.viewport(), QScroller.TouchGesture)
        for index, (key, name) in enumerate(self._steps):
            item = QListWidgetItem(f"{index + 1}. {name}")
            item.setData(Qt.UserRole, key)
            item.setSizeHint(QSize(220, 64))
            self.steps.addItem(item)
        body.addWidget(self.steps)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)
        self._build_preparation()
        self._build_communication()
        for axis in _AXES:
            self._build_axis(axis)
        if self.mode == "tests":
            self._build_leg()
        self._build_loadcell()
        if self.mode == "tests":
            self._build_stops()
        self._build_review()

        self.message = self._label("Complete the preparation checklist to begin.")
        self.message.setMinimumHeight(42)
        root.addWidget(self.message)
        self.close_button = DSButton("Close service", variant="secondary")
        self.close_button.setMinimumHeight(48)
        self.close_button.clicked.connect(self.reject)
        self.add_action(self.close_button)
        self.add_action_stretch(1)
        self.previous_button = DSButton("Back", variant="secondary")
        self.previous_button.setMinimumHeight(48)
        self.previous_button.clicked.connect(lambda: self._navigate(-1))
        self.add_action(self.previous_button)
        self.next_button = DSButton("Next step", variant="primary")
        self.next_button.setMinimumHeight(48)
        self.next_button.clicked.connect(lambda: self._navigate(1))
        self.add_action(self.next_button)
        self.steps.currentRowChanged.connect(self._change_step)
        self.steps.setCurrentRow(0)
        self.refresh_draft()
        self.set_available(False, False)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        return label

    def _page(self, title: str, instructions: str) -> QVBoxLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        QScroller.grabGesture(scroll.viewport(), QScroller.TouchGesture)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 0, 10, 12)
        layout.setSpacing(12)
        heading = self._label(title)
        heading.setFont(sans_font(size="--text-lg", weight=700))
        layout.addWidget(heading)
        layout.addWidget(self._label(instructions))
        scroll.setWidget(content)
        self.pages.addWidget(scroll)
        return layout

    def _button(self, text: str, action: str, payload: Any = None,
                movement: bool = False, variant: str = "secondary") -> DSButton:
        button = DSButton(text, variant=variant)
        button.setMinimumHeight(48)
        button.clicked.connect(
            lambda _checked=False: self._request(action, payload, movement)
        )
        self._actions.append(button)
        if action in ("pressure_capture", "pressure_calculate"):
            self._pressure_actions.append(button)
        return button

    def _request(self, action: str, payload: Any = None, movement: bool = False) -> None:
        if movement and QMessageBox.question(
            self, "Confirm unloaded movement",
            "Confirm there is no patient on the device, the travel path is clear, "
            "and you can reach the physical emergency stop.\n\n"
            "Watch the device throughout this movement. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.action_requested.emit(action, payload() if callable(payload) else payload)

    def _build_preparation(self) -> None:
        layout = self._page(
            "Prepare the device",
            "This wizard sends real movement commands. "
            "Use an unloaded device on a stable bench and remain at the controls.",
        )
        self.preflight_checks = []
        for text in (
            "No patient; all straps, accessories and travel paths are clear.",
            "Physical emergency stop is accessible and an operator is present.",
            "Cables, mounts and actuator connections have been visually inspected.",
            "Measuring tools are available, or unsupported checks will be marked skipped.",
        ):
            check = QCheckBox()
            check.setAccessibleName(text)
            check.toggled.connect(self._update_available)
            self.preflight_checks.append(check)
            row = QHBoxLayout()
            row.addWidget(check, 0, Qt.AlignTop)
            row.addWidget(self._label(text), 1)
            layout.addLayout(row)
        layout.addWidget(self._label(
            "Suggested equipment: ruler for travel, angle gauge for horizontal/lateral "
            "position, and a known force or calibrated force gauge for the load cell. "
            "Confirm the installed hardware against these steps; document any additional "
            "sensors, switches or accessories in the inspection notes."
        ))
        self.begin_button = DSButton("Confirm preparation & begin", variant="primary")
        self.begin_button.setMinimumHeight(48)
        self.begin_button.clicked.connect(lambda: self._request("begin"))
        layout.addWidget(self.begin_button)
        layout.addStretch()

    def _build_communication(self) -> None:
        layout = self._page(
            "Check connection and sensor readings",
            "Request a device check. With the device stationary, inspect all three "
            "position readings and the load reading for stability and plausibility. "
            "A connection response alone does not verify a sensor or wiring.",
        )
        check_link = self._button("Read connection & diagnostics", "check_link")
        self._stationary_actions.append(check_link)
        layout.addWidget(check_link)
        self.diagnostics = self._label("No diagnostic snapshot captured yet.")
        self.diagnostics.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.diagnostics)
        layout.addWidget(self._label(
            "Observe whether readings update when you perform the later movement checks. "
            "Record intermittent readings, unexpected offsets or hardware absent from this wizard."
        ))
        self._add_result(layout, "communication")
        layout.addStretch()

    def _build_axis(self, axis: str) -> None:
        title = axis.title()
        unit = "inches" if axis == "axial" else "degrees"
        layout = self._page(
            f"{'Test' if self.mode == 'tests' else 'Calibrate'} the {axis} actuator",
            ("Start with a small jog. Observe direction and smooth motion, then reverse and "
            "check that the position reading follows movement. Approach measured points "
            "from both directions to assess repeatability. Stop before any obstruction or "
            "mechanical end stop; do not drive into an end stop to find travel limits.")
            if self.mode == "tests" else
            "Move to a physically measured position, record its sensor count, and review the "
            "position table. Use only points that can be reached safely. Hardware Tests "
            "contains direction, smoothness and repeatability checks.",
        )
        if axis == "axial" and self.mode == "calibration":
            layout.addWidget(self._label(
                "Axial calibration needs physically measured 0.0 and 4.0 inch positions. "
                "Existing table values are unverified until recorded during this session. "
                "Do not record a point that cannot be reached safely."
            ))
        jog = QHBoxLayout()
        for delta in (-200, -50, 50, 200):
            jog.addWidget(self._button(f"Jog {delta:+d}", "jog", delta, movement=True))
        layout.addLayout(jog)
        layout.addWidget(self._label(
            "Jog sizes are position counts. Each jog requires confirmation; the controller "
            "checks the travel envelope and fresh sensor readings."
        ))
        if self.mode == "tests":
            self._add_result(layout, axis)
            layout.addStretch()
            return
        measured = QDoubleSpinBox()
        measured.setDecimals(1)
        measured.setRange(*ACTUATORS[axis.upper()]["LIMITS"])
        measured.setSingleStep(0.5 if axis == "axial" else 2.5)
        measured.setSuffix(f" {unit}")
        self._measured[axis] = measured
        row = QHBoxLayout()
        row.addWidget(self._label("Measured position:"))
        row.addWidget(measured, 1)
        row.addWidget(self._button("Record current reading", "record", measured.value))
        layout.addLayout(row)
        table = self._table([f"Measured ({unit})", "Position counts", "Source"])
        table.setMinimumHeight(170)
        self._tables[axis] = table
        layout.addWidget(table)
        row = QHBoxLayout()
        move = DSButton("Move to selected point", variant="secondary")
        move.setMinimumHeight(48)
        move.clicked.connect(lambda: self._selected_mark_action(axis, "goto"))
        remove = DSButton("Remove selected point", variant="ghost")
        remove.setMinimumHeight(48)
        remove.clicked.connect(lambda: self._selected_mark_action(axis, "remove"))
        self._actions.extend((move, remove))
        row.addWidget(move)
        row.addWidget(remove)
        layout.addLayout(row)
        self._factor_labels[axis] = self._label("")
        layout.addWidget(self._factor_labels[axis])
        layout.addWidget(self._label(
            "Optional travel-factor calibration: capture a stationary start, jog safely to "
            "a stationary end, then measure actual actuator stroke between them in inches. "
            "For horizontal/lateral axes use actuator stroke, not the platform angle."
        ))
        anchors = QHBoxLayout()
        anchors.addWidget(self._button("Capture start", "anchor", "start"))
        anchors.addWidget(self._button("Capture end", "anchor", "end"))
        layout.addLayout(anchors)
        self._anchor_labels[axis] = self._label("Start: not captured    End: not captured")
        layout.addWidget(self._anchor_labels[axis])
        stroke = QDoubleSpinBox()
        stroke.setDecimals(3)
        stroke.setRange(0.001, 12.0)
        stroke.setValue(1.0)
        stroke.setSuffix(" inches")
        row = QHBoxLayout()
        row.addWidget(self._label("Measured stroke:"))
        row.addWidget(stroke)
        row.addWidget(self._button("Calculate proposed factor", "factor", stroke.value))
        layout.addLayout(row)
        self._add_result(layout, axis)
        layout.addStretch()

    def _build_leg(self) -> None:
        layout = self._page(
            "Check the leg-length actuator",
            "Use short, supervised movements in both directions. Observe direction, "
            "smooth travel, mounting security and whether the actuator stops at the end "
            "of each timed command. Keep clear of mechanical end stops.",
        )
        row = QHBoxLayout()
        row.addWidget(self._button("Brief retract", "leg", "-", movement=True))
        row.addWidget(self._button("Brief extend", "leg", "+", movement=True))
        layout.addLayout(row)
        layout.addWidget(self._label(
            "This actuator has no position feedback in the current interface. The wizard "
            "cannot certify its position or travel limits and does not calculate a "
            "position calibration from timed movement. Record your physical observations."
        ))
        self._add_result(layout, "leg")
        layout.addStretch()

    def _build_loadcell(self) -> None:
        layout = self._page(
            "Test the load cell" if self.mode == "tests" else "Calibrate the load cell",
            "Use an unloaded, stationary device for the zero sample. Apply a known "
            "reference force using a suitable bench fixture, let the reading settle, "
            "then capture the loaded sample. Never use a patient as the reference load.",
        )
        layout.addWidget(self._button("1. Capture unloaded raw sample", "pressure_capture", "zero"))
        self.pressure_zero = self._label("Unloaded sample: not captured")
        layout.addWidget(self.pressure_zero)
        layout.addWidget(self._button(
            "2. Capture known-force raw sample", "pressure_capture", "loaded"
        ))
        self.pressure_loaded = self._label("Loaded sample: not captured")
        layout.addWidget(self.pressure_loaded)
        self.pressure_factor = self._label("")
        if self.mode == "tests":
            layout.addWidget(self._label(
                "Compare the live force with the known reference. Record the measured force, "
                "reference force and repeatability in the observation. These captures do not "
                "change calibration. Use Calibration if adjustment is required."
            ))
            self._add_result(layout, "loadcell")
            layout.addStretch()
            return
        reference = QDoubleSpinBox()
        reference.setDecimals(2)
        reference.setRange(0.01, float(PRESSURE_MAX))
        reference.setValue(10.0)
        reference.setSuffix(" lbs")
        form = QFormLayout()
        form.addRow("Applied reference force:", reference)
        layout.addLayout(form)
        layout.addWidget(self._button(
            "3. Calculate proposed load-cell factor", "pressure_calculate", reference.value
        ))
        layout.addWidget(self.pressure_factor)
        layout.addWidget(self._label(
            "Use a reference force below the device limit. The calculated span is only a "
            "proposal. After saving and resetting the device, remove all external load "
            "for zeroing, then independently verify the zero and multiple known forces. "
            "Record drift, repeatability and reference-tool details. This wizard does "
            "not run pressure-building movements."
        ))
        self._add_result(layout, "loadcell")
        layout.addStretch()

    def _build_stops(self) -> None:
        layout = self._page(
            "Check stops and inspect remaining hardware",
            "These checks verify a stationary stop request or input only. A stop check "
            "ends this service session's ability to move. Record what you observe; "
            "restart service to perform another active check.",
        )
        for text, kind in (
            ("Check stationary UI stop", "software"),
            ("Check physical stop input", "physical"),
        ):
            button = self._button(text, "stop_check", kind)
            self._stationary_actions.append(button)
            layout.addWidget(button)
        layout.addWidget(self._label(
            "Physical stop input: press the emergency-stop control and observe its "
            "response. Keep it engaged until the controller confirms the stop state. "
            "Neither button proves stopping distance or safe release during movement."
        ))
        layout.addWidget(self._label(
            "Additional bench inspection: cables and strain relief; actuator fasteners; "
            "unusual noise, heat or binding; installed limit switches; physical stop "
            "and release; UI stop during movement; watchdog/link-loss behavior; "
            "pressure limit and release behavior. Dynamic and fault-response tests "
            "require the approved bench procedure. This wizard does not inject faults "
            "or automatically drive to mechanical or pressure limits."
        ))
        layout.addWidget(self._label(
            "List each independently verified item in the notes. Mark any untested "
            "hardware or behavior as incomplete or skipped; one observed stop does "
            "not establish that all safety functions passed."
        ))
        self._add_result(layout, "stops")
        layout.addWidget(self._label("Individual bench-verification record"))
        layout.addWidget(self._label(
            "Keep the device free of patients. Use your approved test procedure and "
            "suitable test rig for these checks. Record the procedure, conditions and "
            "measured outcome for each item. These controls only record observations; "
            "they do not start a hardware test. Incomplete checks remain unverified."
        ))
        self.bench_table = self._table(["Bench check", "Operator result"])
        self.bench_table.setMinimumHeight(200)
        layout.addWidget(self.bench_table)
        self.bench_check = QComboBox()
        for key, title in _BENCH_CHECKS:
            self.bench_check.addItem(title, key)
        layout.addWidget(self.bench_check)
        self.bench_notes = QPlainTextEdit()
        self.bench_notes.setPlaceholderText(
            "Procedure/reference, test conditions, measured result or reason not tested…"
        )
        self.bench_notes.setFixedHeight(90)
        layout.addWidget(self.bench_notes)
        self.bench_check.currentIndexChanged.connect(self._change_bench_check)
        row = QHBoxLayout()
        for status, label, variant in (
            # Recording an observation is not a motion or go/stop action.
            ("pass", "Observed pass", "secondary"),
            ("skip", "Skip / not tested", "secondary"),
            ("fail", "Observed failure", "secondary"),
        ):
            button = DSButton(label, variant=variant)
            button.setMinimumHeight(48)
            button.clicked.connect(
                lambda _checked=False, value=status: self._request("bench_result", {
                    "check": self.bench_check.currentData(), "status": value,
                    "notes": self.bench_notes.toPlainText().strip(),
                })
            )
            self._result_buttons.append(button)
            row.addWidget(button)
        layout.addLayout(row)
        layout.addStretch()

    def _build_review(self) -> None:
        layout = self._page(
            "Review test results" if self.mode == "tests" else "Review proposed calibration",
            "Results below are operator observations. Incomplete, failed and skipped "
            "checks remain visible in the report.",
        )
        self.results_table = self._table(["Check", "Operator result", "Notes"])
        self.results_table.setMinimumHeight(230)
        self.results_table.setVisible(self.mode == "tests")
        if self.mode == "tests":
            layout.addWidget(self.results_table)
        self.bench_review_table = self._table(["Bench check", "Operator result", "Notes"])
        self.bench_review_table.setMinimumHeight(200)
        if self.mode == "tests":
            layout.addWidget(self.bench_review_table)
        self.changes_table = self._table(["Setting", "Current", "Proposed"])
        self.changes_table.setMinimumHeight(170)
        layout.addWidget(self.changes_table)
        self.change_summary = self._label("")
        layout.addWidget(self.change_summary)
        if self.mode == "calibration":
            layout.addWidget(self._label(
                "Save writes the reviewed calibration and creates a backup. Device reset "
                "is required to apply changes. Remove external load before reset and "
                "independently verify movement, zero and reference loads afterward. "
                "A saved configuration is not authorization for patient use."
            ))
        row = QHBoxLayout()
        self.export_button = DSButton("Export service report", variant="secondary")
        self.export_button.setMinimumHeight(48)
        self.export_button.clicked.connect(lambda: self._request("export"))
        row.addWidget(self.export_button)
        self.save_button = DSButton("Save reviewed calibration", variant="success")
        self.save_button.setMinimumHeight(48)
        self.save_button.clicked.connect(self._confirm_save)
        self.save_button.setVisible(self.mode == "calibration")
        self.changes_table.setVisible(self.mode == "calibration")
        self.change_summary.setVisible(self.mode == "calibration")
        row.addWidget(self.save_button)
        layout.addLayout(row)
        layout.addStretch()

    @staticmethod
    def _table(columns: list) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(56)
        table.verticalHeader().setMinimumSectionSize(48)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setWordWrap(True)
        return table

    def _add_result(self, layout: QVBoxLayout, step: str) -> None:
        if self.mode != "tests":
            return
        layout.addWidget(self._label("Operator observation (not an automatic test result):"))
        notes = QPlainTextEdit()
        notes.setPlaceholderText(
            "Observed direction, travel, repeatability, reference equipment, "
            "untested items or reason for failure/skip…"
        )
        notes.setFixedHeight(90)
        self._notes[step] = notes
        layout.addWidget(notes)
        row = QHBoxLayout()
        for status, label, variant in (
            # Recording an observation is not a motion or go/stop action.
            ("pass", "Observed pass", "secondary"),
            ("skip", "Skip / not tested", "secondary"),
            ("fail", "Observed failure", "secondary"),
        ):
            button = DSButton(label, variant=variant)
            button.setMinimumHeight(48)
            button.clicked.connect(
                lambda _checked=False, value=status, key=step: self._request(
                    "result", {"status": value, "notes": self._notes[key].toPlainText().strip()}
                )
            )
            self._result_buttons.append(button)
            row.addWidget(button)
        layout.addLayout(row)
        self._result_labels[step] = self._label("Result: incomplete — no observation recorded")
        layout.addWidget(self._result_labels[step])

    def _selected_mark_action(self, axis: str, action: str) -> None:
        table = self._tables[axis]
        row = table.currentRow()
        if row < 0:
            self.show_message("Select a measured point in the table first.", error=True)
            return
        self._request(action, table.item(row, 0).text(), movement=action == "goto")

    def _confirm_save(self) -> None:
        if self.mode != "calibration" or self.current_step() != "review":
            return
        if QMessageBox.question(
            self, "Save reviewed calibration?",
            "Save the proposed settings shown in this review and create a backup?\n\n"
            "Reset the device unloaded and independently verify calibration afterward.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes:
            self.action_requested.emit("save", None)

    def current_step(self) -> str:
        return self._steps[max(0, self.steps.currentRow())][0]

    def current_axis(self) -> str:
        step = self.current_step()
        return step if step in _AXES else ""

    def _navigate(self, delta: int) -> None:
        row = self.steps.currentRow() + delta
        if not self._busy and 0 <= row < len(self._steps):
            self.steps.setCurrentRow(row)

    def _change_step(self, index: int) -> None:
        if index < 0:
            return
        self.pages.setCurrentIndex(index)
        self.refresh_draft()
        self._update_available()
        self.step_changed.emit(self.current_step())

    def set_available(self, ready: bool, busy: bool, aborted: bool = False) -> None:
        self._ready = ready
        self._busy = busy
        self._aborted = aborted
        self._update_available()

    def set_measurement_available(self, ready: bool) -> None:
        """Enable load-cell capture independently of actuator readiness."""
        self._measurement_ready = ready
        self._update_available()

    def _update_available(self, _checked: bool = False) -> None:
        active = self._ready and not self._busy and not self._aborted
        for button in self._actions:
            button.setEnabled(active)
        for button in self._pressure_actions:
            button.setEnabled(self._measurement_ready and not self._busy and not self._aborted)
        for button in self._stationary_actions:
            button.setEnabled(not self._busy)
        for button in self._result_buttons:
            button.setEnabled(not self._busy)
        self.begin_button.setEnabled(
            not self._busy and not self._aborted and not self._ready
            and all(check.isChecked() for check in self.preflight_checks)
        )
        self.steps.setEnabled(not self._busy)
        self.previous_button.setEnabled(not self._busy and self.steps.currentRow() > 0)
        self.next_button.setEnabled(
            not self._busy and self.steps.currentRow() < len(self._steps) - 1
        )
        self.export_button.setEnabled(not self._busy)
        self.save_button.setEnabled(
            self.mode == "calibration" and not self._busy
            and self.current_step() == "review" and bool(self.draft.changes())
        )

    def refresh_draft(self) -> None:
        """Refresh staged settings without replacing the operator's selection or notes."""
        for axis, table in self._tables.items():
            selection = table.item(table.currentRow(), 0) if table.currentRow() >= 0 else None
            selected_key = selection.text() if selection else None
            marks = self.draft.marks[axis]
            recorded = getattr(self.draft, "recorded", self._recorded).get(axis, set())
            table.setRowCount(len(marks))
            sorted_marks = sorted(marks.items(), key=lambda item: float(item[0]))
            for row, (key, count) in enumerate(sorted_marks):
                source = "Recorded this session" if key in recorded else "Existing / unverified"
                for column, value in enumerate((key, count, source)):
                    table.setItem(row, column, QTableWidgetItem(str(value)))
                if key == selected_key:
                    table.selectRow(row)
            self._factor_labels[axis].setText(
                f"Proposed travel factor: {self.draft.factors[axis]}"
            )
        self.pressure_factor.setText(f"Proposed load-cell factor: {self.draft.scale}")
        changes = self.draft.changes()
        self.changes_table.setRowCount(len(changes))
        for row, change in enumerate(changes):
            for column, value in enumerate(change):
                self.changes_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.changes_table.resizeRowsToContents()
        self.change_summary.setText(
            f"{len(changes)} proposed configuration changes."
            if changes else "No configuration changes are staged."
        )
        self._refresh_results()
        if self.mode == "tests":
            self._refresh_bench_results()
        if hasattr(self, "previous_button"):
            self._update_available()

    def _refresh_results(self) -> None:
        rows = [(key, title) for key, title in self._steps if key != "review"]
        self.results_table.setRowCount(len(rows))
        for row, (step, title) in enumerate(rows):
            status, detail = self._results.get(step, ("incomplete", "No observation recorded"))
            status_label = {
                "pass": "Observed pass", "fail": "Observed failure",
                "skip": "Skipped / not tested", "incomplete": "Incomplete",
            }.get(status, status)
            for column, value in enumerate((title, status_label, detail)):
                self.results_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.results_table.resizeRowsToContents()

    def show_message(self, message: str, error: bool = False) -> None:
        self.message.setText(message)
        color = resolve("--red-500") if error else resolve("--ink-700")
        self.message.setStyleSheet(f"color: {color};")

    def set_live(self, text: str) -> None:
        self.live.setText(text)

    def set_result(self, step: str, status: str, detail: str) -> None:
        self._results[step] = (status, detail)
        if step in self._result_labels:
            label = {"pass": "Observed pass", "fail": "Observed failure", "skip": "Skipped"}
            self._result_labels[step].setText(f"Result: {label.get(status, status)} — {detail}")
        self._refresh_results()

    def _refresh_bench_results(self) -> None:
        for table in (self.bench_table, self.bench_review_table):
            table.setRowCount(len(_BENCH_CHECKS))
            for row, (key, title) in enumerate(_BENCH_CHECKS):
                status, notes = self._bench_results.get(key, ("not_tested", ""))
                status_label = {
                    "pass": "Observed pass", "fail": "Observed failure",
                    "skip": "Skipped / not tested", "not_tested": "Not tested",
                }.get(status, status)
                for column, text in enumerate((title, status_label, notes)):
                    if column < table.columnCount():
                        table.setItem(row, column, QTableWidgetItem(str(text)))
            table.resizeRowsToContents()

    def set_bench_result(self, check: str, status: str, notes: str) -> None:
        self._bench_results[check] = (status, notes)
        if self.mode == "tests":
            self._refresh_bench_results()

    def _change_bench_check(self, _index: int) -> None:
        _status, notes = self._bench_results.get(self.bench_check.currentData(), ("", ""))
        self.bench_notes.setPlainText(notes)

    def set_diagnostics(self, text: str) -> None:
        self.diagnostics.setText(text)

    def set_anchors(self, axis: str, start: Any, end: Any) -> None:
        self._anchor_labels[axis].setText(
            f"Start: {start if start is not None else 'not captured'}    "
            f"End: {end if end is not None else 'not captured'}"
        )

    def set_pressure_capture(self, kind: str, raw: Any) -> None:
        label = self.pressure_zero if kind == "zero" else self.pressure_loaded
        name = "Unloaded" if kind == "zero" else "Known-force"
        label.setText(f"{name} raw sample: {raw}")

    def set_recorded(self, axis: str, key: str) -> None:
        self._recorded[axis].add(key)
        self.refresh_draft()

    def reject(self) -> None:
        """Stop before even asking whether staged calibration should be discarded."""
        if self._closed:
            return
        self.leaving.emit()
        if self.draft.changes() and QMessageBox.question(
            self, "Discard proposed calibration?",
            "Movement has been stopped. Close service and discard unsaved calibration "
            "changes? Choose No to keep the wizard open and review or export the report.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._closed = True
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.reject()
        if self._closed:
            event.accept()
        else:
            event.ignore()
