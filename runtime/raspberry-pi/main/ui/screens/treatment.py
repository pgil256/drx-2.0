"""TreatmentScreen — run a treatment (Protocols page).

Patient identity and records occupy a compact strip above the selected protocol.
The full-width monitor sits above a one-row settings strip and fixed run controls.
Protocol choices stay above the read-only settings; Edit treatment opens their controls.
During treatment, only permitted live settings remain editable. The controller
supplies readiness and measurement validity.

The monitor is two columns — measured pressure with its limit beneath, time
remaining with the phase and outcome beneath — then the progress bar. Nothing
in it changes size between states: the readiness line keeps its height when
empty and readouts keep one size, so an operator watching for 12 minutes never
sees the numbers jump.

Run controls follow the action grammar: START/RESUME green, PAUSE outline,
STOP red. While an outcome is showing, "Prepare next treatment" takes START's
slot; STOP never moves.

The ``TreatmentStatusPanel`` banner (kneespa.py) stays hidden while a protocol
runs -- this page's monitor and STOP button are the operator's view.

View + signal surface only; the controller drives the setters below.

Signals:
    protocol_selected(int)
    patient_change_requested / patient_edit_requested / cloud_error_requested
    start_requested / resume_requested / pause_requested / estop_requested
    setting_changed(str, float) — treatment settings and shared motor_speed
    cloud_status_changed(str) / outcome_recorded(str, int) — mirrored on Home
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from main.config.constants import (
        DEFAULT_PROTOCOL_MINUTES, PROTOCOL_MINUTES_MAX, PROTOCOL_MINUTES_MIN,
        MOTOR_SPEED_DEFAULT, MOTOR_SPEED_DEFAULTS, MOTOR_SPEED_MAX, MOTOR_SPEED_MIN, MOTOR_SPEED_STEP,
    )
except ModuleNotFoundError:
    from config.constants import (
        DEFAULT_PROTOCOL_MINUTES, PROTOCOL_MINUTES_MAX, PROTOCOL_MINUTES_MIN,
        MOTOR_SPEED_DEFAULT, MOTOR_SPEED_DEFAULTS, MOTOR_SPEED_MAX, MOTOR_SPEED_MIN, MOTOR_SPEED_STEP,
    )
from helpers.motor_speed import treatment_motor_speed
from ui.modals.treatment_editor import TreatmentEditorDialog
from ui.theme import control_icon, pause_icon, play_icon
from ui.widgets.common import eyebrow
from ui.widgets.ds import (
    DSBadge,
    DSButton,
    DSCard,
    DSProtocolButton,
    DSStatReadout,
)
from ui.widgets.ds._common import mark_caption, mono_font, resolve, sans_font
from ui.widgets.ds.key_value_list import status_tone

from .content import PHASES, PROTOCOLS

_PAD = 20
_GAP = 8
_TOTAL = DEFAULT_PROTOCOL_MINUTES * 60
NO_PATIENT = "No patient linked"

# Settings sliders: (key, label, default, min, max, step, unit)
SETTING_SPECS = [
    ("duration", "Duration", DEFAULT_PROTOCOL_MINUTES,
     PROTOCOL_MINUTES_MIN, PROTOCOL_MINUTES_MAX, 1, " min"),
    ("max_pressure", "Max Pressure", 40, 10, 80, 1, " lbs"),
    ("max_left", "Max Angle L", 10, 0, 20, 1, "°"),
    ("max_right", "Max Angle R", 10, 0, 20, 1, "°"),
    ("pulse_rate", "Pulse Rate", 2, 0, 5, 0.2, "/sec"),
]
TREATMENT_SETTING_SPECS = SETTING_SPECS + [
    ("motor_speed", "Motor Speed", MOTOR_SPEED_DEFAULT,
     MOTOR_SPEED_MIN, MOTOR_SPEED_MAX, MOTOR_SPEED_STEP, "%"),
]
# Chip order in the settings strip (angles hide per protocol).
_SUMMARY_ORDER = ("duration", "max_pressure", "max_left", "max_right", "pulse_rate",
                  "motor_speed")
_SUMMARY_LABELS = {"duration": "Duration", "max_pressure": "Pressure limit",
                   "max_left": "Left angle", "max_right": "Right angle",
                   "pulse_rate": "Pulse rate", "motor_speed": "Motor speed"}
_OUTCOME_TITLES = {"completed": "Treatment completed", "stopped": "Stopped by operator",
                   "fault": "Ended with a fault"}
_TONE_COLORS = {"success": "--green-600", "warning": "--amber-500", "danger": "--red-500",
                "neutral": "--gray-400", "info": "--blue-500"}


def _mmss(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _retain_when_hidden(widget: QWidget) -> None:
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)


class TreatmentScreen(QWidget):
    protocol_selected = pyqtSignal(int)
    patient_change_requested = pyqtSignal()
    patient_edit_requested = pyqtSignal()
    cloud_error_requested = pyqtSignal()
    next_treatment_requested = pyqtSignal()
    start_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    estop_requested = pyqtSignal()
    setting_changed = pyqtSignal(str, float)
    cloud_status_changed = pyqtSignal(str)
    outcome_recorded = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TreatmentScreen")
        self._access_role = None
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#TreatmentScreen {{ background: {resolve('--surface-page')}; }}")
        self._running = False
        self._paused = False
        self._busy = False  # locked while the device is mid-reset / reconnecting
        self._patient_pending = False
        self._selected = 1
        self._progress_fraction = 0.0
        self._pressure_value = None
        self._pressure_caption = "Waiting for pressure"
        self._adjusting = False
        self._can_start = False
        self._device_detail = "Waiting for device readiness."
        self._device_label = "Preparing"
        self._outcome = None

        root = QVBoxLayout(self)
        root.setContentsMargins(_PAD, 8, _PAD, 8)
        root.setSpacing(_GAP)
        root.addWidget(self._patient_card(), 0)
        root.addWidget(self._protocol_card(), 0)
        self._settings_panel = self._settings_card()
        self._monitor_panel = self._status_card()
        root.addWidget(self._monitor_panel, 1)
        root.addWidget(self._settings_panel)
        root.addLayout(self._run_controls(), 0)

        self.set_run_state(running=False, paused=False)
        self._update_protocol_copy()

    # ----- build: protocol strip -----
    def _protocol_card(self):
        card = DSCard(padded=False)
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(24)

        self._protocol_choices = QWidget()
        tiles = QHBoxLayout(self._protocol_choices)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(8)
        self._proto_group = QButtonGroup(self)
        self._proto_group.setExclusive(True)
        self._proto_buttons = {}
        for protocol in PROTOCOLS:
            number = protocol["n"]
            button = DSProtocolButton(number, protocol["name"])
            button.setFixedWidth(112)
            button.layout().setContentsMargins(8, 6, 8, 6)
            button.clicked.connect(lambda _checked, n=number: self._on_protocol(n))
            self._proto_group.addButton(button)
            self._proto_buttons[number] = button
            tiles.addWidget(button)
        self._proto_buttons[1].setChecked(True)
        row.addWidget(self._protocol_choices)

        rule = QFrame()
        rule.setFixedWidth(1)
        rule.setStyleSheet(f"background: {resolve('--border-divider')}; border: none;")
        row.addWidget(rule)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        self._title = QLabel()
        self._title.setFont(sans_font(size="--text-lg", weight=600, tracking=-0.01))
        self._title.setStyleSheet(f"color: {resolve('--text-strong')}; background: transparent;")
        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setFont(sans_font(size="--text-sm"))
        metrics = self._desc.fontMetrics()
        self._desc.setFixedHeight(metrics.height() + metrics.lineSpacing())
        self._desc.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._desc.setStyleSheet(f"color: {resolve('--text-muted')}; background: transparent;")
        copy.addStretch(1)
        copy.addWidget(self._title)
        copy.addWidget(self._desc)
        copy.addStretch(1)
        row.addLayout(copy, 1)

        card.add_widget(host)
        return card

    # ----- build: patient -----
    def _patient_card(self):
        card = DSCard(padded=False)
        body = QHBoxLayout()
        body.setContentsMargins(16, 6, 16, 6)
        body.setSpacing(20)
        patient = QVBoxLayout()
        patient.setSpacing(0)
        patient.setAlignment(Qt.AlignVCenter)
        self._patient_label = QLabel(NO_PATIENT)
        self._patient_label.setTextFormat(Qt.PlainText)
        self._patient_label.setWordWrap(True)
        self._patient_label.setFont(sans_font(size="--text-base", weight=600))
        patient.addWidget(self._patient_label)
        self._patient_detail = QLabel("This treatment will not upload.")
        self._patient_detail.setFont(sans_font(size="--text-sm"))
        self._patient_detail.setWordWrap(True)
        self._patient_detail.setStyleSheet(f"color: {resolve('--text-muted')};")
        patient.addWidget(self._patient_detail)
        body.addLayout(patient, 3)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._patient_button = DSButton("Select patient", variant="secondary", size="sm")
        self._patient_button.clicked.connect(self.patient_change_requested)
        actions.addWidget(self._patient_button)
        self._edit_patient_button = DSButton("Edit patient", variant="secondary", size="sm")
        self._edit_patient_button.clicked.connect(self.patient_edit_requested)
        self._edit_patient_button.hide()
        actions.addWidget(self._edit_patient_button)
        body.addLayout(actions)

        records = QVBoxLayout()
        records.setSpacing(0)
        records.setAlignment(Qt.AlignVCenter)
        records_heading = QLabel("Treatment records")
        records_heading.setFont(sans_font(size="--text-base", weight=600))
        records.addWidget(records_heading)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._cloud_dot = QFrame()
        self._cloud_dot.setFixedSize(8, 8)
        status_row.addWidget(self._cloud_dot, 0, Qt.AlignVCenter)
        self._cloud_status = QLabel("Cloud not configured")
        self._cloud_status.setTextFormat(Qt.PlainText)
        self._cloud_status.setWordWrap(True)
        self._cloud_status.setFont(sans_font(size="--text-sm"))
        status_row.addWidget(self._cloud_status, 1)
        records.addLayout(status_row)
        body.addLayout(records, 2)
        self._upload_error_button = DSButton("Upload issue", variant="secondary", size="sm")
        self._upload_error_button.setIcon(control_icon("alert", resolve("--amber-500"), 18))
        self._upload_error_button.clicked.connect(self.cloud_error_requested)
        self._upload_error_button.hide()
        body.addWidget(self._upload_error_button)
        card.add_layout(body)
        self._set_patient_status(NO_PATIENT, "--gray-600")
        self._render_cloud_status("Cloud not configured")
        return card

    # ----- build: settings -----
    def _settings_card(self):
        card = DSCard(padded=True)
        card.setAccessibleName("Current treatment settings")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        body = card.body_layout
        body.setContentsMargins(16, 12, 16, 12)
        strip = QHBoxLayout()
        strip.setSpacing(12)
        body.addLayout(strip)

        self._edit_treatment_button = DSButton("Edit treatment", variant="primary", size="md")
        self._edit_treatment_button.setFixedSize(220, 64)
        self._edit_treatment_button.clicked.connect(self.open_treatment_editor)

        self._editor = TreatmentEditorDialog(TREATMENT_SETTING_SPECS, self)
        self._editor.setting_changed.connect(self._setting_edited)
        self._editor.estop_requested.connect(self.estop_requested)
        self._editor.finished.connect(self._editor_closed)
        self._settings = self._editor._settings
        self._summary_rows = {}
        self._summary_values = {}
        chip_style = (
            f"#SettingChip {{ background: {resolve('--blue-050')};"
            f" border-radius: {resolve('--radius-md')}; }}"
            " #SettingChip QLabel { background: transparent; }"
        )
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for key in _SUMMARY_ORDER:
            chip = QFrame()
            chip.setObjectName("SettingChip")
            chip.setAttribute(Qt.WA_StyledBackground, True)
            chip.setStyleSheet(chip_style)
            chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            chip.setMinimumWidth(96)
            text = QVBoxLayout(chip)
            text.setContentsMargins(14, 8, 14, 8)
            text.setSpacing(0)
            caption = QLabel(_SUMMARY_LABELS[key])
            caption.setFont(sans_font(size="--text-xs", weight=600))
            mark_caption(caption)
            caption.setStyleSheet(f"color: {resolve('--text-muted')};")
            value = QLabel()
            value.setFont(mono_font(size="--text-md", weight=600))
            value.setStyleSheet(f"color: {resolve('--text-strong')};")
            text.addWidget(caption)
            text.addWidget(value)
            self._summary_rows[key] = chip
            self._summary_values[key] = value
            chips.addWidget(chip, 1)
        strip.addLayout(chips, 1)
        strip.addWidget(self._edit_treatment_button, 0, Qt.AlignVCenter)
        self._update_settings_summary()
        return card

    def _setting_edited(self, key: str, value: float) -> None:
        """Request a change; its visible value is never an acknowledgement."""
        self.setting_changed.emit(key, value)
        self._update_settings_summary()
        self._update_limit()

    def open_treatment_editor(self) -> None:
        """Open controls with the current defaults or patient settings already loaded."""
        if self._access_role in ("patient", "service_technician"):
            return
        if self._busy or self._patient_pending:
            return
        self._adjusting = True
        self._refresh_settings_access()
        self._editor.show()
        self._editor.raise_()
        self._editor.activateWindow()

    def _editor_closed(self, _result: int) -> None:
        self._adjusting = False
        self._refresh_settings_access()

    def _refresh_settings_access(self) -> None:
        editable = (not self._busy and not self._patient_pending
                    and self._access_role not in ("patient", "service_technician"))
        self._edit_treatment_button.setEnabled(editable)
        for button in self._proto_buttons.values():
            button.setEnabled(editable and not self._running)
        if not editable and self._editor.isVisible():
            self._editor.reject()
        self._editor.set_run_state(
            self._running, editable and (not self._running or self._adjusting)
        )

    def _update_settings_summary(self) -> None:
        for key, _label, _value, _low, _high, _step, unit in TREATMENT_SETTING_SPECS:
            value = self._settings[key].value()
            text = "Off" if key == "pulse_rate" and value == 0 else f"{value:g}{unit}"
            self._summary_values[key].setText(text)
        self._summary_rows["max_left"].setVisible(self._selected in (2, 4))
        self._summary_rows["max_right"].setVisible(self._selected in (3, 4))

    def _update_limit(self) -> None:
        if hasattr(self, "_limit_stat"):
            self._limit_stat.set_value(f"{self._settings['max_pressure'].value():g}", "lbs")

    # ----- build: live status -----
    def _status_card(self):
        card = DSCard(padded=True)
        body = card.body_layout
        body.setContentsMargins(24, 14, 24, 16)
        body.setSpacing(6)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.addWidget(eyebrow("Treatment monitor"))
        hdr.addStretch(1)
        self._angle_stat = DSStatReadout("—", label="Lateral angle (approx.)", size="sm")
        self._inline_stat(self._angle_stat)
        hdr.addWidget(self._angle_stat)
        card.add_layout(hdr)

        # The readiness line keeps its height while empty so the readouts
        # below it never move between states.
        self._readiness = QLabel()
        self._readiness.setWordWrap(False)
        self._readiness.setFont(sans_font(size="--text-sm"))
        self._readiness.setStyleSheet(f"color: {resolve('--text-muted')};")
        self._readiness.setMinimumHeight(self._readiness.fontMetrics().height())
        _retain_when_hidden(self._readiness)
        body.addWidget(self._readiness)

        columns = QHBoxLayout()
        columns.setSpacing(24)
        # Left: measured pressure with its limit directly beneath.
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addStretch(1)
        self._pressure_stat = DSStatReadout("—", unit="lbs", label="Waiting for pressure",
                                            tone="default", size="lg")
        self._compact_stat(self._pressure_stat)
        left.addWidget(self._pressure_stat)
        self._limit_stat = DSStatReadout("40", unit="lbs", label="Limit", size="sm")
        self._inline_stat(self._limit_stat)
        left.addWidget(self._sub_row(self._limit_stat))
        left.addStretch(1)
        columns.addLayout(left, 1)
        # Right: time remaining with the phase (and any outcome) beneath.
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        self._time_stat = DSStatReadout(_mmss(DEFAULT_PROTOCOL_MINUTES * 60),
                                       label="Time remaining", tone="default", size="lg")
        self._time_stat.setMinimumWidth(180)
        self._compact_stat(self._time_stat)
        right.addWidget(self._time_stat)
        phase_row = QHBoxLayout()
        phase_row.setContentsMargins(0, 0, 0, 0)
        phase_row.setSpacing(10)
        phase_row.addStretch(1)
        self._phase_badge = DSBadge(PHASES["idle"][0], tone=PHASES["idle"][1], dot=True,
                                    size="md")
        phase_row.addWidget(self._phase_badge)
        self._outcome_label = QLabel()
        self._outcome_label.setFont(sans_font(size="--text-sm", weight=600))
        self._outcome_label.setStyleSheet(f"color: {resolve('--text-body')};")
        self._outcome_label.hide()
        phase_row.addWidget(self._outcome_label)
        phase_row.addStretch(1)
        phase_host = QWidget()
        phase_host.setLayout(phase_row)
        right.addWidget(self._sub_row(phase_host))
        right.addStretch(1)
        columns.addLayout(right, 1)
        body.addLayout(columns, 1)

        # Progress bar: a fixed-width fill inside a rounded track, re-flowed on
        # resize (QSS cannot animate a sub-control width).
        self._track = QFrame()
        self._track.setObjectName("ProgTrack")
        self._track.setFixedHeight(10)
        self._track.setAttribute(Qt.WA_StyledBackground, True)
        self._track.setStyleSheet(
            f"#ProgTrack {{ background: {resolve('--gray-300')}; border-radius: 5px; }}"
        )
        tlay = QHBoxLayout(self._track)
        tlay.setContentsMargins(0, 0, 0, 0)
        self._fill = QFrame()
        self._fill.setObjectName("ProgFill")
        self._fill.setAttribute(Qt.WA_StyledBackground, True)
        self._fill.setStyleSheet(
            f"#ProgFill {{ border-radius: 5px; background: {resolve('--color-primary')}; }}"
        )
        tlay.addWidget(self._fill, 0)
        tlay.addStretch(1)
        self._track.installEventFilter(self)
        body.addWidget(self._track)
        return card

    @staticmethod
    def _compact_stat(stat: DSStatReadout) -> None:
        """Keep value and caption together so both columns line up exactly."""
        stat.layout().setSpacing(2)
        stat.layout().setAlignment(Qt.AlignCenter)
        stat.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    @staticmethod
    def _sub_row(widget: QWidget) -> QWidget:
        """A fixed-height line under a readout (limit / phase) so columns match."""
        host = QWidget()
        host.setFixedHeight(40)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(widget, 0, Qt.AlignCenter)
        return host

    @staticmethod
    def _inline_stat(stat: DSStatReadout) -> None:
        """Lay a small readout out as ``CAPTION value`` on one line."""
        layout = stat.layout()
        layout.setDirection(QVBoxLayout.LeftToRight)
        layout.insertWidget(0, stat._caption)
        layout.setSpacing(10)
        stat._caption.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        stat._value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        stat.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    # ----- build: run controls -----
    def _run_controls(self):
        row = QHBoxLayout()
        row.setSpacing(_GAP)
        white = resolve("--white")
        self._start_btn = DSButton("START", variant="success", size="lg", full_width=True,
                                   icon=play_icon(white, 22))
        self._start_btn.clicked.connect(self._on_start)
        # After an outcome, preparing the next treatment takes START's slot.
        self._next_button = DSButton("Prepare next treatment", variant="primary", size="lg",
                                     full_width=True)
        self._next_button.clicked.connect(self.next_treatment_requested)
        self._next_button.hide()
        pause = pause_icon(resolve("--ink-800"), 22)
        self._pause_btn = DSButton("PAUSE", variant="secondary", size="lg", full_width=True,
                                   icon=pause)
        self._pause_btn.clicked.connect(self.pause_requested)
        self._estop_btn = DSButton("STOP", variant="danger", size="lg", full_width=True,
                                   icon=control_icon("stop", white, 22))
        self._estop_btn.clicked.connect(self.estop_requested)
        for b in (self._start_btn, self._next_button, self._pause_btn, self._estop_btn):
            row.addWidget(b, 1)
        return row

    # ----- interaction -----
    def _on_protocol(self, n):
        self._selected = n
        self._update_protocol_copy()
        self.protocol_selected.emit(n)

    def _on_start(self):
        if self._paused:
            self.resume_requested.emit()
        else:
            self.start_requested.emit()

    def _update_protocol_copy(self):
        proto = PROTOCOLS[self._selected - 1]
        self._title.setText(proto["title"])
        self._desc.setText(proto["desc"])
        if hasattr(self, "_settings"):
            self._editor.select_protocol(self._selected)
            self._update_settings_summary()

    def eventFilter(self, obj, event):
        if obj is self._track and event.type() == event.Resize:
            self._reflow_progress()
        return super().eventFilter(obj, event)

    def _reflow_progress(self):
        w = int(self._track.width() * max(0.0, min(1.0, self._progress_fraction)))
        self._fill.setFixedWidth(w)

    # ----- run-state model (controller drives this) -----
    def set_run_state(self, running, paused):
        if self._running != running:
            self._editor.reject()
            if running:
                self.clear_outcome()
        self._running = running
        self._paused = paused
        self._start_btn.setText("RESUME" if paused else "START")
        self._start_btn.setEnabled(
            ((not running and self._can_start) or paused)
            and not self._busy and not self._patient_pending
        )
        self._pause_btn.setEnabled((running and not paused) and not self._busy)
        self._next_button.setEnabled(
            self._can_start and not running and not self._busy and not self._patient_pending
        )
        self._patient_button.setEnabled(not running)
        self._edit_patient_button.setEnabled(
            not running and not self._patient_pending
            and self._access_role not in ("patient", "service_technician")
        )
        self._refresh_settings_access()
        self._refresh_readiness()

    def set_access_role(self, role) -> None:
        self._access_role = role
        self._refresh_settings_access()
        self._edit_patient_button.setEnabled(
            not self._running and not self._patient_pending
            and role not in ("patient", "service_technician")
        )
        self._refresh_readiness()

    def _refresh_readiness(self) -> None:
        if self._patient_pending:
            text = "Loading or saving patient · wait before starting."
        elif self._busy or self._device_label not in ("Ready", "Treatment active"):
            text = self._device_detail
        elif self._paused:
            text = "Paused · measurements remain live. Resume when ready."
        elif self._running:
            text = "Treatment active · duration and motor speed are locked."
        else:
            text = ""
        self._readiness.setText(text)
        self._readiness.setVisible(bool(text))

    def set_device_status(self, label: str, detail: str, can_start: bool) -> None:
        """Readiness is supplied by the controller rather than inferred from idle."""
        self._can_start = can_start
        self._device_label = label
        self._device_detail = detail
        self.set_run_state(self._running, self._paused)
        self._next_button.setEnabled(can_start and not self._running and not self._busy)
        if label == "Recovery required":
            self.set_phase("fault")
        elif label == "Stopping / recovering" or label == "Resetting":
            self.set_phase("stopping")
        elif label == "Preparing":
            self.set_phase("starting")
        elif label == "Ready" and not self._running:
            # Reset completion must clear its transient phase as well as the
            # top-bar status. Keep a finished treatment's outcome visible.
            self.set_phase({"completed": "complete", "stopped": "stopped"}.get(
                self._outcome, "idle"
            ))

    def _show_next_slot(self, show_next: bool) -> None:
        self._start_btn.setVisible(not show_next)
        self._next_button.setVisible(show_next)

    def set_outcome(self, outcome: str, duration_seconds: int) -> None:
        """Retain the terminal result independently of reset and cloud delivery."""
        self._outcome = outcome
        title = _OUTCOME_TITLES.get(outcome, "Treatment ended")
        self._outcome_label.setText(f"{title} · active {_mmss(duration_seconds)}")
        self._outcome_label.show()
        self._show_next_slot(True)
        self._next_button.setEnabled(self._can_start and not self._running and not self._busy)
        self.outcome_recorded.emit(outcome, int(duration_seconds))

    def clear_outcome(self) -> None:
        self._outcome = None
        self._outcome_label.hide()
        self._show_next_slot(False)

    def set_busy(self, busy):
        """Lock START/PAUSE while the device is mid-reset / reconnecting."""
        self._busy = busy
        self.set_run_state(self._running, self._paused)

    def set_phase(self, phase):
        label, tone = PHASES.get(phase, PHASES["idle"])
        self._phase_badge.set_text(label)
        self._phase_badge.set_tone(tone)

    def set_progress(self, elapsed_seconds, total_seconds=_TOTAL):
        remaining = max(0, total_seconds - elapsed_seconds)
        self._progress_fraction = (elapsed_seconds / total_seconds) if total_seconds else 0.0
        self._reflow_progress()
        self._time_stat.set_value(_mmss(remaining))
        self._time_stat.set_tone("default")

    def set_pressure(self, lbs):
        import math
        try:
            lbs = float(lbs)
            if not math.isfinite(lbs):
                raise ValueError("Nonfinite pressure")
        except (TypeError, ValueError):
            self._pressure_value = None
            self._pressure_stat.set_value("—", "lbs")
            return
        self._pressure_value = lbs
        self._render_pressure()

    def _render_pressure(self) -> None:
        live = self._pressure_caption == "Pressure live" and self._pressure_value is not None
        self._pressure_stat.set_value(f"{self._pressure_value:.1f}" if live else "—", "lbs")
        self._pressure_stat.set_tone("default")

    def set_pressure_state(self, caption: str) -> None:
        self._pressure_caption = caption
        self._pressure_stat.set_label("Measured pressure" if caption == "Pressure live" else caption)
        self._render_pressure()

    def set_angle(self, degrees):
        import math
        valid = isinstance(degrees, (int, float)) and math.isfinite(degrees)
        self._angle_stat.set_value(f"{degrees:.1f}°" if valid else "—")

    # ----- settings get/set (controller + Mark-As-Default) -----
    def settings_values(self):
        """Current treatment settings, including one shared motor output percentage."""
        return {key: s.value() for key, s in self._settings.items()}

    def set_settings(self, values):
        """Load settings from a dict (no signal re-emit; DSSlider blocks)."""
        values = dict(values or {})
        if "motor_speed" in values or any(key in values for key in MOTOR_SPEED_DEFAULTS):
            values["motor_speed"] = treatment_motor_speed(values)
        for key, value in values.items():
            s = self._settings.get(key)
            if s is not None:
                s.set_value(value)
        if not self._running:
            self.set_progress(0, self.settings_values()["duration"] * 60)
        self._update_limit()
        self._update_settings_summary()

    def hideEvent(self, event) -> None:
        """Keep the editor from remaining open after navigation or logout."""
        self._editor.reject()
        super().hideEvent(event)

    def selected_protocol(self):
        """The currently selected protocol number (1-4)."""
        return self._selected

    def select_protocol(self, n):
        """Programmatically select protocol *n* (1-4)."""
        btn = self._proto_buttons.get(n)
        if btn is not None:
            btn.setChecked(True)
            self._on_protocol(n)

    # ----- patient -----
    def _set_patient_status(self, text, tone):
        self._patient_label.setText(text)
        self._patient_label.setStyleSheet(
            f"color: {resolve(tone)}; background: transparent;"
        )

    def set_patient(self, name):
        self._set_patient_status(name, "--green-600")
        self._patient_detail.setText("Patient linked")
        self._patient_button.setText("Change patient")
        self._edit_patient_button.show()

    def set_patient_error(self, msg):
        self._set_patient_status(msg, "--red-500")

    def set_patient_pin(self, pin: str) -> None:
        self._patient_detail.setText(f"Patient PIN: {pin}")

    def clear_patient(self) -> None:
        self._set_patient_status(NO_PATIENT, "--gray-600")
        self._patient_detail.setText("This treatment will not upload.")
        self._patient_button.setText("Select patient")
        self._edit_patient_button.hide()

    def set_patient_pending(self, pending: bool) -> None:
        """Prevent a start while an identity/plan is still being resolved."""
        self._patient_pending = pending
        self.set_run_state(self._running, self._paused)

    def _render_cloud_status(self, message: str) -> None:
        tone = status_tone(message)
        failed = "fail" in message.lower()
        if failed:
            tone = "warning"
        self._cloud_dot.setStyleSheet(
            f"background: {resolve(_TONE_COLORS[tone])}; border-radius: 4px;")
        color = resolve("--amber-500") if failed else resolve("--text-muted")
        weight = "600" if failed else "400"
        self._cloud_status.setStyleSheet(f"color: {color}; font-weight: {weight};")
        return failed

    def set_cloud_status(self, message: str) -> None:
        self._cloud_status.setText(message)
        if self._render_cloud_status(message):
            # A failure keeps its details one tap away.
            self._upload_error_button.show()
        if message == "Treatments synced":
            self._upload_error_button.hide()
        self.cloud_status_changed.emit(message)

    def set_upload_error(self) -> None:
        """Keep the failure details accessible after its error window is closed."""
        self._upload_error_button.show()
