"""TreatmentScreen — run a treatment (Protocols page).

Mirrors `TreatmentScreen` in `bundle.jsx`: a "Treatment Monitor" card (knee
visual, protocol title, 4-step stepper, progress + timer, START/PAUSE/EMERGENCY
STOP) beside a Protocol picker, Settings sliders, and a Live Status readout.

This is the view + signal surface only — no treatment simulation. Phase 3 drives
the stepper / progress / live readouts from the Protocols worker signals and
honors the run-state model below.

Signals:
    protocol_selected(int)
    start_requested / resume_requested / pause_requested / estop_requested
    setting_changed(str, float)   — key: max_pressure|max_left|max_right|pulse_rate
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap, QTransform
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from config.constants import (
    DEFAULT_PROTOCOL_MINUTES,
    PROTOCOL_MINUTES_MAX,
    PROTOCOL_MINUTES_MIN,
)
from ui.theme import GLYPH, pause_icon, play_icon
from ui.widgets.common import eyebrow
from ui.widgets.ds import (
    DSBadge,
    DSButton,
    DSCard,
    DSProtocolButton,
    DSSlider,
    DSStatReadout,
)
from ui.widgets.ds._common import image_path, mono_font, resolve, sans_font

from .content import PHASES, PROTOCOLS, STEPS

_PAD = 20
_GAP = 16
_TOTAL = 30  # nominal treatment seconds (matches the design's demo clock)
_MONITOR_W = 680  # fixed inner width for the monitor blocks (DS maxWidth 700)


def _phase_step(phase):
    if phase == "ramping":
        return 0
    if phase == "positioning":
        return 1
    if phase in ("holding", "pulsing", "oscillating"):
        return 2
    if phase == "complete":
        return 4
    return -1


class _Stepper(QWidget):
    """The four-phase progress stepper (circles connected by lines, labels below).

    A 2-row grid: row 0 holds the dots with connector bars between them (the bars
    align to the dot centers via vertical centering), row 1 holds the captions.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self._dots = []
        self._labels = []
        self._connectors = []
        for i, label in enumerate(STEPS):
            col = i * 2
            dot = QLabel()
            dot.setFixedSize(26, 26)
            dot.setAlignment(Qt.AlignCenter)
            dot.setFont(mono_font(size="--text-xs", weight=600))
            grid.addWidget(dot, 0, col, Qt.AlignHCenter | Qt.AlignVCenter)
            cap = QLabel(label)
            cap.setFont(sans_font(size=11, weight=600))
            cap.setAlignment(Qt.AlignCenter)
            grid.addWidget(cap, 1, col, Qt.AlignHCenter | Qt.AlignTop)
            grid.setColumnStretch(col, 0)
            self._dots.append(dot)
            self._labels.append(cap)
            if i < len(STEPS) - 1:
                conn = QFrame()
                conn.setFixedHeight(3)
                # Connector lives in row 0 between dots, centered on their axis.
                grid.addWidget(conn, 0, col + 1)
                grid.setColumnStretch(col + 1, 1)
                self._connectors.append(conn)
        self.set_step(-1)

    def set_step(self, current):
        for i, dot in enumerate(self._dots):
            done = current > i
            cur = current == i
            if done:
                bg = border = resolve("--green-500")
                fg = "#ffffff"
                text = GLYPH["check"]
            elif cur:
                bg = border = resolve("--blue-500")
                fg = "#ffffff"
                text = str(i + 1)
            else:
                bg = resolve("--gray-200")
                border = resolve("--gray-400")
                fg = resolve("--gray-600")
                text = str(i + 1)
            dot.setText(text)
            dot.setStyleSheet(
                f"background: {bg}; color: {fg}; border: 2px solid {border};"
                " border-radius: 13px;"
            )
            self._labels[i].setStyleSheet(
                f"color: {resolve('--ink-800') if cur else resolve('--gray-600')};"
                " background: transparent;"
            )
        for i, conn in enumerate(self._connectors):
            filled = current > i
            conn.setStyleSheet(
                f"background: {resolve('--green-500') if filled else resolve('--gray-300')};"
                " border-radius: 2px;"
            )


class TreatmentScreen(QWidget):
    protocol_selected = pyqtSignal(int)
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
        self._selected = 1

        grid = QHBoxLayout(self)
        grid.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        grid.setSpacing(_GAP)
        grid.addWidget(self._monitor_card(), 1)
        right = self._right_column()
        grid.addLayout(right, 0)

        self.set_run_state(running=False, paused=False)
        self._update_monitor_protocol()

    # ----- left: Treatment Monitor -----
    def _monitor_card(self):
        self._phase_badge = DSBadge(PHASES["idle"][0], tone=PHASES["idle"][1], dot=True)
        card = DSCard("Treatment Monitor", header_right=self._phase_badge, padded=False)
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(18)
        v.setAlignment(Qt.AlignHCenter)

        # Knee visual in a gradient panel.
        viz = QFrame()
        viz.setObjectName("KneeViz")
        viz.setAttribute(Qt.WA_StyledBackground, True)
        viz.setFixedWidth(_MONITOR_W)
        viz.setStyleSheet(
            "#KneeViz { border-radius: 8px;"
            " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {resolve('--gray-050')}, stop:1 #e9ecef); }}"
        )
        vlay = QVBoxLayout(viz)
        vlay.setContentsMargins(22, 22, 22, 22)
        self._knee_base = QPixmap(image_path("logos", "knee.png"))
        self._knee = QLabel()
        self._knee.setAlignment(Qt.AlignCenter)
        self._knee.setStyleSheet("background: transparent;")
        if not self._knee_base.isNull():
            self._knee.setPixmap(
                self._knee_base.scaled(210, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        vlay.addWidget(self._knee, 0, Qt.AlignCenter)
        v.addWidget(viz, 0, Qt.AlignHCenter)

        self._title = QLabel(PROTOCOLS[0]["title"])
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setFont(sans_font(size=36, weight=700, tracking=-0.01))
        self._title.setStyleSheet(f"color: {resolve('--ink-900')}; background: transparent;")
        self._title.setMaximumWidth(700)
        v.addWidget(self._title, 0, Qt.AlignHCenter)

        self._stepper = _Stepper()
        self._stepper.setFixedWidth(_MONITOR_W)
        v.addWidget(self._stepper, 0, Qt.AlignHCenter)

        # Progress bar + timer.
        prog_row = QHBoxLayout()
        prog_row.setSpacing(14)
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
        self._timer = QLabel("0:30")
        self._timer.setFont(mono_font(size=18, weight=600))
        self._timer.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        prog_row.addWidget(self._track, 1)
        prog_row.addWidget(self._timer, 0)
        prog_host = QWidget()
        prog_host.setFixedWidth(_MONITOR_W)
        prog_host.setLayout(prog_row)
        v.addWidget(prog_host, 0, Qt.AlignHCenter)
        self._progress_fraction = 0.0
        self._track.installEventFilter(self)  # re-flow fill width on resize

        # Action buttons.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self._start_btn = DSButton("START", variant="success", full_width=True,
                                   icon=play_icon("#ffffff", 20))
        self._start_btn.clicked.connect(self._on_start)
        self._pause_btn = DSButton("PAUSE", variant="secondary", full_width=True,
                                   icon=pause_icon(resolve("--ink-800"), 18))
        self._pause_btn.clicked.connect(self.pause_requested)
        self._estop_btn = DSButton(f"{GLYPH['estop']} EMERGENCY STOP", variant="danger",
                                   full_width=True)
        self._estop_btn.clicked.connect(self.estop_requested)
        for b in (self._start_btn, self._pause_btn, self._estop_btn):
            btn_row.addWidget(b, 1)
        btn_host = QWidget()
        btn_host.setFixedWidth(_MONITOR_W)
        btn_host.setLayout(btn_row)
        v.addWidget(btn_host, 0, Qt.AlignHCenter)

        v.addStretch(1)
        card.add_widget(host)
        return card

    def eventFilter(self, obj, event):
        if obj is self._track and event.type() == event.Resize:
            self._reflow_progress()
        return super().eventFilter(obj, event)

    def _reflow_progress(self):
        w = int(self._track.width() * max(0.0, min(1.0, self._progress_fraction)))
        self._fill.setFixedWidth(w)

    # ----- right: Protocol / Settings / Live Status -----
    def _right_column(self):
        col = QVBoxLayout()
        col.setSpacing(_GAP)

        # Protocol picker.
        pick = DSCard(padded=True)
        pick.add_widget(eyebrow("Protocol"))
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self._proto_group = QButtonGroup(self)
        self._proto_group.setExclusive(True)
        self._proto_buttons = {}
        for i, p in enumerate(PROTOCOLS):
            tile = DSProtocolButton(p["n"], p["name"])
            tile.clicked.connect(lambda _c, n=p["n"]: self._on_protocol(n))
            self._proto_group.addButton(tile)
            self._proto_buttons[p["n"]] = tile
            grid.addWidget(tile, 0, i)
        self._proto_buttons[1].setChecked(True)
        pick.add_widget(grid_host)
        col.addWidget(pick, 0)

        # Settings sliders.
        settings = DSCard(padded=True)
        settings.add_widget(eyebrow("Settings"))
        s_host = QWidget()
        sv = QVBoxLayout(s_host)
        sv.setContentsMargins(0, 6, 0, 6)
        sv.setSpacing(24)
        self._settings = {}
        slider_specs = [
            ("duration", "Duration", DEFAULT_PROTOCOL_MINUTES,
             PROTOCOL_MINUTES_MIN, PROTOCOL_MINUTES_MAX, 1, " min"),
            ("max_pressure", "Max Pressure", 50, 10, 80, 1, " lbs"),
            ("max_left", "Max Angle L", 10, 0, 20, 1, "°"),
            ("max_right", "Max Angle R", 10, 0, 20, 1, "°"),
            ("pulse_rate", "Pulse Rate", 2, 0, 5, 0.2, "/sec"),
        ]
        for key, label, val, lo, hi, step, unit in slider_specs:
            sld = DSSlider(label=label, value=val, minimum=lo, maximum=hi, step=step, unit=unit)
            sld.valueChanged.connect(lambda v, k=key: self.setting_changed.emit(k, v))
            self._settings[key] = sld
            sv.addWidget(sld)
        settings.add_widget(s_host)
        col.addWidget(settings, 0)

        # Live Status.
        status = DSCard(padded=True)
        status.add_widget(eyebrow("Live Status"))
        st_host = QWidget()
        st = QHBoxLayout(st_host)
        st.setContentsMargins(0, 0, 0, 0)
        self._time_stat = DSStatReadout("0:30", label="Time Left", tone="default", size="sm")
        self._pressure_stat = DSStatReadout("0", unit="lbs", label="Pressure",
                                            tone="success", size="sm")
        self._angle_stat = DSStatReadout("0°", label="Lateral Angle", tone="cyan", size="sm")
        for w in (self._time_stat, self._pressure_stat, self._angle_stat):
            st.addStretch(1)
            st.addWidget(w)
        st.addStretch(1)
        status.add_widget(st_host)
        col.addWidget(status, 0)

        col.addStretch(1)
        # Fix the right column to the design's 408px.
        wrap = QWidget()
        wrap.setLayout(col)
        wrap.setFixedWidth(408)
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrap)
        return outer

    # ----- interaction -----
    def _on_protocol(self, n):
        self._selected = n
        self._update_monitor_protocol()
        self.protocol_selected.emit(n)

    def _on_start(self):
        if self._paused:
            self.resume_requested.emit()
        else:
            self.start_requested.emit()

    def _update_monitor_protocol(self):
        proto = PROTOCOLS[self._selected - 1]
        self._title.setText(proto["title"])

    # ----- run-state model (Phase 3 drives this) -----
    def set_run_state(self, running, paused):
        self._running = running
        self._paused = paused
        self._start_btn.setText("RESUME" if paused else "START")
        self._start_btn.setEnabled((not running or paused) and not self._busy)
        self._pause_btn.setEnabled((running and not paused) and not self._busy)
        for tile in self._proto_buttons.values():
            tile.setEnabled(not running)
        # Duration is a pre-run parameter: lock it during an active run (incl.
        # while paused) so a stray drag can't silently shorten/end the treatment.
        self._settings["duration"].setEnabled(not running)
        self._set_knee_glow(running and not paused)

    def set_busy(self, busy):
        """Lock START/PAUSE while the device is mid-reset / reconnecting."""
        self._busy = busy
        self.set_run_state(self._running, self._paused)

    def set_phase(self, phase):
        label, tone = PHASES.get(phase, PHASES["idle"])
        self._phase_badge.set_text(label)
        self._phase_badge.set_tone(tone)
        self._stepper.set_step(_phase_step(phase))

    def set_progress(self, elapsed_seconds, total_seconds=_TOTAL):
        remaining = max(0, total_seconds - elapsed_seconds)
        self._progress_fraction = (elapsed_seconds / total_seconds) if total_seconds else 0.0
        self._reflow_progress()
        mm = int(remaining // 60)
        ss = int(remaining % 60)
        self._timer.setText(f"{mm}:{ss:02d}")
        tone = "danger" if remaining <= 5 else "warning" if remaining <= 10 else "default"
        self._time_stat.set_value(f"{mm}:{ss:02d}")
        self._time_stat.set_tone(tone)

    def set_pressure(self, lbs):
        tone = "danger" if lbs >= 70 else "warning" if lbs >= 50 else "success"
        self._pressure_stat.set_value(str(int(round(lbs))), "lbs")
        self._pressure_stat.set_tone(tone)

    def set_angle(self, degrees):
        self._angle_stat.set_value(f"{int(round(degrees))}°")
        if not self._knee_base.isNull():
            rot = self._knee_base.transformed(
                QTransform().rotate(degrees * 0.4), Qt.SmoothTransformation
            )
            self._knee.setPixmap(
                rot.scaled(210, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    # ----- settings get/set (Phase 3 controller + Mark-As-Default) -----
    def settings_values(self):
        """Current Settings slider values: max_pressure/max_left/max_right/pulse_rate."""
        return {key: sld.value() for key, sld in self._settings.items()}

    def set_settings(self, values):
        """Load Settings sliders from a dict (no signal re-emit; DSSlider blocks)."""
        for key, value in (values or {}).items():
            sld = self._settings.get(key)
            if sld is not None:
                sld.set_value(value)

    def selected_protocol(self):
        """The currently selected protocol number (1-4)."""
        return self._selected

    def _set_knee_glow(self, on):
        if on:
            glow = QGraphicsDropShadowEffect(self._knee)
            glow.setBlurRadius(28)
            glow.setOffset(0, 0)
            c = QColor(resolve("--brand-cyan"))
            c.setAlpha(166)
            glow.setColor(c)
            self._knee.setGraphicsEffect(glow)
        else:
            self._knee.setGraphicsEffect(None)
