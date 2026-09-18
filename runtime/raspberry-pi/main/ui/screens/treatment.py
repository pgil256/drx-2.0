"""TreatmentScreen — run a treatment (Protocols page).

Treatment controls on one 1366×768 screen; patient PIN entry uses a modal::

    ┌ [1][2][3][4] │ selected protocol title + one-line description ─┐
    ├ PATIENT ───────┬ SETTINGS ──────────────────┬ LIVE STATUS ──────┤
    │ identity / PIN │ ‹ value › steppers ×5      │ time · lbs · °    │
    ├────────────────┴────────────────────────────┴───────────────────┤
    │ [ ▶ START ]           [ ❚❚ PAUSE ]           [ STOP/RESET ]     │
    └─────────────────────────────────────────────────────────────────┘

The ``TreatmentStatusPanel`` banner (kneespa.py) stays hidden while a protocol
runs -- this page's Live Status card and STOP button are the operator's view.

View + signal surface only; the controller drives the setters below.

Signals:
    protocol_selected(int)
    patient_change_requested / cloud_retry_requested
    start_requested / resume_requested / pause_requested / estop_requested
    setting_changed(str, float) — treatment settings and axial/lateral/pulse_speed
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from main.config.constants import (
        DEFAULT_PROTOCOL_MINUTES, PROTOCOL_MINUTES_MAX, PROTOCOL_MINUTES_MIN,
        MOTOR_SPEED_DEFAULTS, MOTOR_SPEED_MAX, MOTOR_SPEED_MIN, MOTOR_SPEED_STEP,
    )
except ModuleNotFoundError:
    from config.constants import (
        DEFAULT_PROTOCOL_MINUTES, PROTOCOL_MINUTES_MAX, PROTOCOL_MINUTES_MIN,
        MOTOR_SPEED_DEFAULTS, MOTOR_SPEED_MAX, MOTOR_SPEED_MIN, MOTOR_SPEED_STEP,
    )
from ui.theme import pause_icon, play_icon
from ui.widgets.common import eyebrow
from ui.widgets.ds import (
    DSBadge,
    DSButton,
    DSCard,
    DSProtocolButton,
    DSSlider,
    DSStatReadout,
)
from ui.widgets.ds._common import resolve, sans_font

from .content import PHASES, PROTOCOLS

_PAD = 20
_GAP = 14
_TOTAL = 30  # nominal treatment seconds (matches the design's demo clock)
_TILE_W = 112
NO_PATIENT = "No patient linked"

# Settings steppers: (key, label, default, min, max, step, unit)
SETTING_SPECS = [
    ("duration", "Duration", DEFAULT_PROTOCOL_MINUTES,
     PROTOCOL_MINUTES_MIN, PROTOCOL_MINUTES_MAX, 1, " min"),
    ("max_pressure", "Max Pressure", 40, 10, 80, 1, " lbs"),
    ("max_left", "Max Angle L", 10, 0, 20, 1, "°"),
    ("max_right", "Max Angle R", 10, 0, 20, 1, "°"),
    ("pulse_rate", "Pulse Rate", 2, 0, 5, 0.2, "/sec"),
]


def _mmss(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class TreatmentScreen(QWidget):
    protocol_selected = pyqtSignal(int)
    patient_change_requested = pyqtSignal()
    cloud_retry_requested = pyqtSignal()
    start_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    estop_requested = pyqtSignal()
    setting_changed = pyqtSignal(str, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TreatmentScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#TreatmentScreen {{ background: {resolve('--surface-page')}; }}")
        self._running = False
        self._paused = False
        self._busy = False  # locked while the device is mid-reset / reconnecting
        self._patient_pending = False
        self._selected = 1
        self._progress_fraction = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        root.setSpacing(_GAP)
        root.addWidget(self._protocol_card(), 0)
        panels = QHBoxLayout()
        panels.setSpacing(_GAP)
        panels.addWidget(self._patient_card(), 3)
        panels.addWidget(self._settings_card(), 4)
        panels.addWidget(self._status_card(), 3)
        root.addLayout(panels, 1)
        root.addLayout(self._run_controls(), 0)

        self.set_run_state(running=False, paused=False)
        self._update_protocol_copy()

    # ----- build: protocol strip -----
    def _protocol_card(self):
        card = DSCard(padded=False)
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(24, 16, 24, 16)
        row.setSpacing(24)

        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self._proto_group = QButtonGroup(self)
        self._proto_group.setExclusive(True)
        self._proto_buttons = {}
        for p in PROTOCOLS:
            tile = DSProtocolButton(p["n"], p["name"])
            tile.setFixedWidth(_TILE_W)
            tile.clicked.connect(lambda _c, n=p["n"]: self._on_protocol(n))
            self._proto_group.addButton(tile)
            self._proto_buttons[p["n"]] = tile
            tiles.addWidget(tile)
        self._proto_buttons[1].setChecked(True)
        row.addLayout(tiles, 0)

        rule = QFrame()
        rule.setFrameShape(QFrame.VLine)
        rule.setFixedWidth(1)
        rule.setStyleSheet(f"background: {resolve('--gray-300')}; border: none;")
        row.addWidget(rule)

        copy = QVBoxLayout()
        copy.setSpacing(4)
        self._title = QLabel()
        self._title.setFont(sans_font(size="--text-lg", weight=700, tracking=-0.01))
        self._title.setStyleSheet(f"color: {resolve('--ink-900')}; background: transparent;")
        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setFont(sans_font(size="--text-sm"))
        self._desc.setStyleSheet(f"color: {resolve('--gray-600')}; background: transparent;")
        copy.addStretch(1)
        copy.addWidget(self._title)
        copy.addWidget(self._desc)
        copy.addStretch(1)
        row.addLayout(copy, 1)

        card.add_widget(host)
        return card

    # ----- build: patient -----
    def _patient_card(self):
        card = DSCard(padded=True)
        body = card.body_layout
        card.add_widget(eyebrow("Patient"))
        body.addStretch(1)
        self._patient_label = QLabel(NO_PATIENT)
        self._patient_label.setTextFormat(Qt.PlainText)
        self._patient_label.setAlignment(Qt.AlignCenter)
        self._patient_label.setWordWrap(True)
        self._patient_label.setFont(sans_font(size="--text-sm", weight=600))
        body.addWidget(self._patient_label)
        self._patient_button = DSButton("Enter / change patient PIN", variant="secondary",
                                        full_width=True)
        self._patient_button.clicked.connect(self.patient_change_requested)
        body.addWidget(self._patient_button)
        self._cloud_status = QLabel("Cloud not configured")
        self._cloud_status.setTextFormat(Qt.PlainText)
        self._cloud_status.setWordWrap(True)
        self._cloud_status.setAlignment(Qt.AlignCenter)
        self._cloud_status.setFont(sans_font(size="--text-xs"))
        body.addWidget(self._cloud_status)
        self._retry_button = DSButton("Retry uploads", variant="secondary", size="sm")
        self._retry_button.clicked.connect(self.cloud_retry_requested)
        body.addWidget(self._retry_button)
        body.addStretch(1)
        self._set_patient_status(NO_PATIENT, "--gray-600")
        return card

    # ----- build: settings -----
    def _settings_card(self):
        card = DSCard(padded=True)
        body = card.body_layout
        card.add_widget(eyebrow("Settings"))
        tabs = QHBoxLayout()
        self._settings_pages = QStackedWidget()
        self._settings_tabs = []
        for index, title in enumerate(("Treatment", "Motor Speed")):
            button = DSButton(title, variant="primary" if index == 0 else "secondary",
                              size="sm", full_width=True)
            button.clicked.connect(lambda _checked, i=index: self._select_settings_page(i))
            self._settings_tabs.append(button)
            tabs.addWidget(button)
        body.addLayout(tabs)
        body.addWidget(self._settings_pages, 1)
        treatment_page = QWidget()
        body = QVBoxLayout(treatment_page)
        body.setContentsMargins(0, 0, 0, 0)
        self._settings_pages.addWidget(treatment_page)
        self._settings = {}
        for key, label, val, lo, hi, step, unit in SETTING_SPECS:
            body.addStretch(1)  # even vertical distribution
            s = DSSlider(label=label, value=val, minimum=lo, maximum=hi, step=step,
                         unit=unit, mode="stepper", label_width=116)
            s.valueChanged.connect(lambda v, k=key: self.setting_changed.emit(k, v))
            self._settings[key] = s
            body.addWidget(s)
        body.addStretch(1)
        self._settings_pages.addWidget(self._speed_settings_page())
        return card

    def _select_settings_page(self, index: int) -> None:
        """Switch settings without hiding treatment status or stop controls."""
        self._settings_pages.setCurrentIndex(index)
        for i, button in enumerate(self._settings_tabs):
            button.set_variant("primary" if i == index else "secondary")

    def _speed_settings_page(self) -> QWidget:
        """Three independent sliders with explicit output limits and values."""
        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(0, 8, 0, 0)
        note = QLabel("Set before starting treatment.")
        note.setWordWrap(True)
        note.setFont(sans_font(size="--text-sm"))
        body.addWidget(note)
        for key, label in (("axial_speed", "Axial movement"),
                           ("lateral_speed", "Lateral movement"),
                           ("pulse_speed", "Pulsation movement")):
            body.addStretch(1)
            title = QLabel(label)
            title.setFont(sans_font(size="--text-base", weight=600))
            body.addWidget(title)
            slider = DSSlider(value=MOTOR_SPEED_DEFAULTS[key], minimum=MOTOR_SPEED_MIN,
                              maximum=MOTOR_SPEED_MAX, step=MOTOR_SPEED_STEP, unit="%")
            slider._slider.setMinimumHeight(40)
            slider._slider.setAccessibleName(label + " speed")
            slider._slider.setTracking(False)
            slider.valueChanged.connect(lambda v, k=key: self.setting_changed.emit(k, v))
            self._settings[key] = slider
            body.addWidget(slider)
        body.addStretch(1)
        limits = QLabel(
            f"Min {MOTOR_SPEED_MIN}%  ·  Max {MOTOR_SPEED_MAX}% of treatment output"
        )
        limits.setFont(sans_font(size="--text-sm"))
        body.addWidget(limits)
        return page

    # ----- build: live status -----
    def _status_card(self):
        card = DSCard(padded=True)
        body = card.body_layout
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.addWidget(eyebrow("Live Status"))
        hdr.addStretch(1)
        self._phase_badge = DSBadge(PHASES["idle"][0], tone=PHASES["idle"][1], dot=True)
        hdr.addWidget(self._phase_badge)
        card.add_layout(hdr)

        # Readouts reserve the width of their widest value ("12:00", "80 lbs",
        # "-20°") so the row doesn't re-flow every time the digit count changes.
        body.addStretch(2)
        self._time_stat = DSStatReadout(_mmss(DEFAULT_PROTOCOL_MINUTES * 60),
                                       label="Time Left", tone="default", size="lg")
        self._time_stat.setMinimumWidth(180)
        body.addWidget(self._time_stat, 0, Qt.AlignHCenter)
        body.addStretch(2)

        pair = QHBoxLayout()
        pair.setContentsMargins(0, 0, 0, 0)
        self._pressure_stat = DSStatReadout("--", unit="lbs", label="Waiting for pressure",
                                            tone="success", size="md")
        self._angle_stat = DSStatReadout("0°", label="Lateral Angle", tone="cyan", size="md")
        for stat in (self._pressure_stat, self._angle_stat):
            stat.setMinimumWidth(120)
        pair.addStretch(1)
        pair.addWidget(self._pressure_stat)
        pair.addStretch(2)
        pair.addWidget(self._angle_stat)
        pair.addStretch(1)
        body.addLayout(pair)
        body.addStretch(2)

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
            "#ProgFill { border-radius: 5px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {resolve('--blue-500')}, stop:1 {resolve('--blue-600')}); }}"
        )
        tlay.addWidget(self._fill, 0)
        tlay.addStretch(1)
        self._track.installEventFilter(self)
        body.addWidget(self._track)
        body.addStretch(1)
        return card

    # ----- build: run controls -----
    def _run_controls(self):
        row = QHBoxLayout()
        row.setSpacing(_GAP)
        self._start_btn = DSButton("START", variant="success", size="lg", full_width=True,
                                   icon=play_icon("#ffffff", 22))
        self._start_btn.clicked.connect(self._on_start)
        self._pause_btn = DSButton("PAUSE", variant="secondary", size="lg", full_width=True,
                                   icon=pause_icon(resolve("--ink-800"), 20))
        self._pause_btn.clicked.connect(self.pause_requested)
        self._estop_btn = DSButton("STOP/RESET", variant="danger", size="lg", full_width=True)
        self._estop_btn.clicked.connect(self.estop_requested)
        for b in (self._start_btn, self._pause_btn, self._estop_btn):
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

    def eventFilter(self, obj, event):
        if obj is self._track and event.type() == event.Resize:
            self._reflow_progress()
        return super().eventFilter(obj, event)

    def _reflow_progress(self):
        w = int(self._track.width() * max(0.0, min(1.0, self._progress_fraction)))
        self._fill.setFixedWidth(w)

    # ----- run-state model (controller drives this) -----
    def set_run_state(self, running, paused):
        self._running = running
        self._paused = paused
        self._start_btn.setText("RESUME" if paused else "START")
        self._start_btn.setEnabled(
            (not running or paused) and not self._busy and not self._patient_pending
        )
        self._pause_btn.setEnabled((running and not paused) and not self._busy)
        for tile in self._proto_buttons.values():
            tile.setEnabled(not running)
        # Pre-run inputs lock during an active run (incl. paused): the patient
        # link (a lookup re-applies settings + protocol) and the duration.
        self._patient_button.setEnabled(not running)
        self._settings["duration"].setEnabled(not running)
        for key in MOTOR_SPEED_DEFAULTS:
            self._settings[key].setEnabled(not running and not self._busy)

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
        tone = "danger" if remaining <= 5 else "warning" if remaining <= 10 else "default"
        self._time_stat.set_value(_mmss(remaining))
        self._time_stat.set_tone(tone)

    def set_pressure(self, lbs):
        import math
        try:
            lbs = float(lbs)
            if not math.isfinite(lbs):
                raise ValueError("Nonfinite pressure")
        except (TypeError, ValueError):
            self._pressure_stat.set_value("--", "lbs")
            self._pressure_stat.set_label("Waiting for pressure")
            return
        tone = "danger" if lbs >= 70 else "warning" if lbs >= 50 else "success"
        self._pressure_stat.set_value(f"{lbs:.1f}", "lbs")
        self._pressure_stat.set_tone(tone)

    def set_pressure_state(self, caption: str) -> None:
        self._pressure_stat.set_label(caption)

    def set_angle(self, degrees):
        self._angle_stat.set_value(f"{int(round(degrees))}°")

    # ----- settings get/set (controller + Mark-As-Default) -----
    def settings_values(self):
        """Current treatment settings, including the three motor output percentages."""
        return {key: s.value() for key, s in self._settings.items()}

    def set_settings(self, values):
        """Load Settings steppers from a dict (no signal re-emit; DSSlider blocks)."""
        for key, value in (values or {}).items():
            s = self._settings.get(key)
            if s is not None:
                s.set_value(value)
        if not self._running:
            self.set_progress(0, self.settings_values()["duration"] * 60)

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

    def set_patient_error(self, msg):
        self._set_patient_status(msg, "--red-500")

    def clear_patient(self) -> None:
        self._set_patient_status(NO_PATIENT, "--gray-600")

    def set_patient_pending(self, pending: bool) -> None:
        """Prevent a start while an identity/plan is still being resolved."""
        self._patient_pending = pending
        self.set_run_state(self._running, self._paused)

    def set_cloud_status(self, message: str) -> None:
        self._cloud_status.setText(message)
