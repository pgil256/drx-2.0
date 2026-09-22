"""Device overview, connectivity, comfort settings, service history and power.

Three segmented sections (Overview · Settings · Service). Facts render as
key/value rows (muted label left, strong value right, status dots where a
state is shown); each card's actions sit left-aligned in its footer. Screen
and logout timeouts apply as soon as they change, with a brief "Saved" note.
The Service section is PIN-gated: its tab shows a lock while locked, and a
lock button beside the tabs re-locks it. Controller results appear in a slim
status strip under the sections.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QShowEvent
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QScrollArea, QScroller, QSizePolicy, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from main.config.constants import APP_VERSION
from ui.theme import control_icon
from ui.widgets.ds import DSButton, DSCard, DSKeyValueList, DSSegmentedTabs
from ui.widgets.ds._common import resolve, sans_font
from ui.widgets.ds.slider import _TouchSlider

READY_STATUS = "Device settings are ready."
# Controller confirmations that belong next to a specific control.
_SAVED_NOTES = {
    "Idle dimming timeout saved.": "idle_timeout",
    "Automatic logout timer saved.": "logout_timeout",
}


def _retain_when_hidden(widget: QWidget) -> None:
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)


class DeviceScreen(QWidget):
    """Expose device intent; the controller owns privilege checks and OS calls."""

    hardware_tests_requested = pyqtSignal()
    calibration_requested = pyqtSignal()
    setting_requested = pyqtSignal(str, int)
    refresh_requested = pyqtSignal()
    action_requested = pyqtSignal(str, object)
    service_access_requested = pyqtSignal()
    service_locked = pyqtSignal()
    details_changed = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DeviceScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#DeviceScreen {{ background: {resolve('--surface-page')}; }}")
        self.actions: Dict[str, QPushButton] = {}
        self.values: Dict[str, QLabel] = {}
        self._saved_notes: Dict[str, QWidget] = {}
        self.service_unlocked = False
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 12)
        root.setSpacing(12)

        tabs = QHBoxLayout()
        tabs.setSpacing(12)
        self._tabs = DSSegmentedTabs(("Overview", "Settings", "Service"))
        self._tabs.tab_requested.connect(self._select_section)
        self._section_buttons = self._tabs.buttons()
        self._section_buttons[2].setIconSize(QSize(18, 18))
        tabs.addWidget(self._tabs, 1)
        lock = QPushButton()
        lock.setObjectName("LockService")
        lock.setAccessibleName("Lock service")
        lock.setToolTip("Lock service")
        lock.setCursor(Qt.PointingHandCursor)
        lock.setFocusPolicy(Qt.TabFocus)
        lock.setFixedSize(56, 56)
        lock.setIcon(control_icon("lock", resolve("--ink-800"), 22))
        lock.setIconSize(QSize(22, 22))
        lock.setStyleSheet("#LockService { padding: 0; min-height: 0; }")
        lock.clicked.connect(lambda: self.action_requested.emit("lock_service", None))
        lock.hide()
        self.actions["lock_service"] = lock
        tabs.addWidget(lock)
        root.addLayout(tabs)

        self._sections = QStackedWidget()
        root.addWidget(self._sections, 1)
        self._overview()
        settings = self._page()
        self._connections(settings)
        self._comfort(settings)
        self._system(settings)
        self._service()

        self._status_strip = QFrame()
        self._status_strip.setObjectName("StatusStrip")
        self._status_strip.setAttribute(Qt.WA_StyledBackground, True)
        self._status_strip.setStyleSheet(
            f"#StatusStrip {{ background: {resolve('--blue-050')};"
            f" border: 1px solid {resolve('--blue-100')};"
            f" border-radius: {resolve('--radius-md')}; }}"
            " #StatusStrip QLabel { background: transparent; }"
        )
        strip = QHBoxLayout(self._status_strip)
        strip.setContentsMargins(14, 8, 14, 8)
        strip.setSpacing(10)
        info = QLabel()
        info.setPixmap(control_icon("info", resolve("--blue-700"), 20).pixmap(20, 20))
        strip.addWidget(info)
        self.status = self._label(READY_STATUS)
        self.status.setStyleSheet(f"color: {resolve('--blue-700')};")
        strip.addWidget(self.status, 1)
        _retain_when_hidden(self._status_strip)
        self._status_strip.hide()
        root.addWidget(self._status_strip)
        self._select_section(0)

    # ----- builders -----
    @staticmethod
    def _label(text: str, muted: bool = False) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setFont(sans_font(size="--text-sm" if muted else "--text-base"))
        if muted:
            label.setStyleSheet(f"color: {resolve('--text-muted')};")
        return label

    def _page(self) -> QGridLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        QScroller.grabGesture(scroll.viewport(), QScroller.TouchGesture)
        host = QWidget()
        layout = QGridLayout(host)
        # Breathing room so scrolled cards never butt against the tab row.
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(16)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        scroll.setWidget(host)
        self._sections.addWidget(scroll)
        return layout

    @staticmethod
    def _rows(card: DSCard) -> DSKeyValueList:
        rows = DSKeyValueList()
        card.add_widget(rows)
        return rows

    def _row(self, rows: DSKeyValueList, key: str, label: str, value: str,
             strip=None, status: bool = False, selectable: bool = False) -> QLabel:
        widget = rows.add_row(key, label, value, strip=strip, status=status,
                              selectable=selectable)
        self.values[key] = widget
        return widget

    @staticmethod
    def _button(card: DSCard, title: str, variant: str = "secondary") -> DSButton:
        return card.add_action(DSButton(title, variant=variant))

    def _action(self, card: DSCard, title: str, key: str,
                payload: object = None, variant: str = "secondary") -> DSButton:
        button = self._button(card, title, variant)
        button.clicked.connect(lambda: self.action_requested.emit(
            key, payload() if callable(payload) else payload,
        ))
        self.actions[key] = button
        return button

    def _timeout(self, card: DSCard, key: str, name: str, options) -> QComboBox:
        """A combo that applies on change, with a transient "Saved" note."""
        row = QHBoxLayout()
        row.setSpacing(12)
        combo = QComboBox()
        combo.setMinimumHeight(48)
        combo.setMinimumWidth(220)
        combo.setAccessibleName(name)
        for minutes in options:
            combo.addItem("Never" if minutes == 0 else f"{minutes} minutes", minutes)
        # activated fires for operator choices only, never for controller restores.
        combo.activated.connect(
            lambda _index, k=key, c=combo: self.action_requested.emit(k, c.currentData()))
        row.addWidget(combo)
        saved = QWidget()
        saved_row = QHBoxLayout(saved)
        saved_row.setContentsMargins(0, 0, 0, 0)
        saved_row.setSpacing(6)
        tick = QLabel()
        tick.setPixmap(control_icon("check", resolve("--green-600"), 18).pixmap(18, 18))
        saved_row.addWidget(tick)
        note = QLabel("Saved")
        note.setFont(sans_font(size="--text-sm", weight=600))
        note.setStyleSheet(f"color: {resolve('--green-600')};")
        saved_row.addWidget(note)
        _retain_when_hidden(saved)
        saved.hide()
        row.addWidget(saved)
        row.addStretch(1)
        card.add_layout(row)
        self._saved_notes[key] = saved
        return combo

    def _overview(self) -> None:
        layout = self._page()
        power = DSCard("App and device power")
        power.add_widget(self._label(
            "Finish treatment and device service before restarting.", muted=True))
        self._action(power, "Restart app", "restart_app")
        self._action(power, "Restart device", "reboot", variant="destructive")
        self._action(power, "Shut down", "poweroff", variant="destructive")
        layout.addWidget(power, 0, 0)
        identity = DSCard("Device information")
        rows = self._rows(identity)
        self._version = self._row(rows, "version", "Software version", APP_VERSION)
        self._firmware = self._row(rows, "firmware", "Firmware version", "Not checked")
        self._device_id = self._row(rows, "device_id", "Device ID", "Unavailable",
                                    selectable=True)
        layout.addWidget(identity, 1, 0)
        health = DSCard("Connections and records")
        rows = self._rows(health)
        self._row(rows, "controller", "Controller", "Not checked", strip=("Arduino",),
                  status=True)
        self._row(rows, "internet", "Internet", "Test connection to check", status=True)
        self._row(rows, "cloud", "Cloud", "Not checked", status=True)
        self._row(rows, "pending", "Pending uploads", "Not checked")
        self._row(rows, "last_sync", "Last sync", "Not recorded yet",
                  strip=("Last successful sync",))
        refresh = self._button(health, "Refresh device status")
        refresh.clicked.connect(self.refresh_requested)
        layout.addWidget(health, 0, 1, 2, 1)
        layout.setRowStretch(2, 1)

    def _connections(self, layout: QGridLayout) -> None:
        network = DSCard("Network")
        rows = self._rows(network)
        self._row(rows, "network", "Network", "Not checked")
        self._row(rows, "addresses", "IP addresses", "Not checked")
        self._row(rows, "wifi_backend", "Wi-Fi setup", "Not checked")
        network.add_widget(self._label(
            "Network changes require administrator or technician access.", muted=True))
        self._action(network, "Test connection", "test_connection", variant="primary")
        self._action(network, "Set up Wi-Fi", "wifi")
        layout.addWidget(network, 0, 0)
        sync = DSCard("Cloud synchronization")
        detail = self._label("Check device status for upload information.")
        self.values["sync_detail"] = detail
        sync.add_widget(detail)
        rows = self._rows(sync)
        self._row(rows, "sync_time", "Last sync", "Not recorded yet",
                  strip=("Last successful sync",))
        sync.add_widget(self._label(
            "Treatment records stay on the device until the server acknowledges receipt.",
            muted=True))
        self._action(sync, "Sync now", "retry_sync", variant="primary")
        layout.addWidget(sync, 0, 1)

    def _comfort(self, layout: QGridLayout) -> None:
        controls = DSCard("Sound and display")
        self.sliders = {}
        self.setting_labels = {}
        self.setting_details = {}
        for key, title, minimum in (
            ("volume", "System volume", 0), ("brightness", "Brightness", 10),
        ):
            host = QWidget()
            grid = QGridLayout(host)
            grid.setContentsMargins(0, 4, 0, 4)
            grid.addWidget(self._label(title), 0, 0)
            value = self._label("Unavailable")
            value.setFont(sans_font(size="--text-base", weight=600))
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(value, 0, 1)
            slider = _TouchSlider(Qt.Horizontal)
            slider.setRange(minimum, 100)
            slider.setMinimumHeight(48)
            slider.setAccessibleName(title)
            slider.setEnabled(False)
            slider.setTracking(False)
            slider.valueChanged.connect(lambda v, k=key: self._changed(k, v))
            grid.addWidget(slider, 1, 0, 1, 2)
            detail = self._label("Checking device controls…", muted=True)
            grid.addWidget(detail, 2, 0, 1, 2)
            self.sliders[key] = slider
            self.setting_labels[key] = value
            self.setting_details[key] = detail
            controls.add_widget(host)
        self._action(controls, "Test sound", "test_sound")
        layout.addWidget(controls, 1, 0)
        idle = DSCard("Screen timeout")
        idle.add_widget(self._label(
            "Dim after inactivity while the device is idle. Touch to restore brightness; "
            "the first touch only wakes the display. The screen stays bright during treatment "
            "and service work.", muted=True,
        ))
        self.idle_timeout = self._timeout(idle, "idle_timeout", "Idle dimming timeout",
                                          (0, 1, 2, 5, 10, 15, 30))
        dimming = self._label("Uses the display backlight when available.", muted=True)
        self.values["dimming"] = dimming
        idle.add_widget(dimming)
        idle.body_layout.addStretch(1)
        layout.addWidget(idle, 1, 1)

    def _system(self, layout: QGridLayout) -> None:
        clock = DSCard("Date and time")
        rows = self._rows(clock)
        self._row(rows, "clock", "Current time", "Not checked")
        self._row(rows, "timezone", "Time zone", "Not checked")
        self._row(rows, "ntp", "Automatic time", "Not checked", status=True)
        self._action(clock, "Change time zone", "timezone")
        self._action(clock, "Enable automatic time", "sync_clock")
        layout.addWidget(clock, 2, 0)
        session = DSCard("Automatic logout")
        session.add_widget(self._label(
            "Log out after inactivity. The timer waits for treatment, motion, reset and "
            "service work to finish before starting a fresh inactivity period.", muted=True,
        ))
        self.logout_timeout = self._timeout(session, "logout_timeout", "Automatic logout timer",
                                            (0, 1, 5, 10, 15, 30, 60))
        session.body_layout.addStretch(1)
        layout.addWidget(session, 2, 1)
        layout.setRowStretch(3, 1)

    def _service(self) -> None:
        layout = self._page()
        tasks = DSCard("Hardware tests and calibration")
        tasks.add_widget(self._label("Keep the device unoccupied throughout service."))
        for title, detail, attr, signal, variant in (
            ("Hardware tests", "Check movement, sensors, stops and mechanical condition. "
             "Record pass/fail observations.", "hardware_button",
             self.hardware_tests_requested, "primary"),
            ("Calibration", "Measure position marks and the load-cell factor. Review and "
             "save calibration changes.", "calibration_button",
             self.calibration_requested, "secondary"),
        ):
            row = QHBoxLayout()
            row.setSpacing(16)
            text = QVBoxLayout()
            text.setSpacing(2)
            heading = self._label(title)
            heading.setFont(sans_font(size="--text-base", weight=600))
            text.addWidget(heading)
            text.addWidget(self._label(detail, muted=True))
            row.addLayout(text, 1)
            button = DSButton(title, variant=variant)
            button.setMinimumWidth(180)
            button.clicked.connect(signal)
            setattr(self, attr, button)
            row.addWidget(button, 0, Qt.AlignVCenter)
            tasks.add_layout(row)
        tasks.body_layout.addStretch(1)
        layout.addWidget(tasks, 0, 0)
        updates = DSCard("Software and firmware")
        self.release_status = self._label("Sign in to the cloud to check the latest releases.")
        self.values["release_status"] = self.release_status
        updates.add_widget(self.release_status)
        rows = self._rows(updates)
        self.software_release = self._row(rows, "software_release", "Software", "Not checked")
        self.firmware_release = self._row(rows, "firmware_release", "Firmware", "Not checked")
        self._action(updates, "Check releases", "check_releases")
        self._action(updates, "Flash software", "flash_software")
        self._action(updates, "Flash firmware", "flash_firmware")
        self.actions["flash_software"].setEnabled(False)
        self.actions["flash_firmware"].setEnabled(False)
        layout.addWidget(updates, 0, 1)
        history = DSCard("Service history")
        rows = self._rows(history)
        self._row(rows, "last_test", "Last hardware test", "Not recorded yet")
        self._row(rows, "last_calibration", "Last calibration save", "Not recorded yet")
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["Date", "Work", "Operator", "Result"])
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.setShowGrid(False)
        self.history_table.setWordWrap(True)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setHighlightSections(False)
        self.history_table.verticalHeader().hide()
        self.history_table.verticalHeader().setDefaultSectionSize(60)
        self.history_table.verticalHeader().setMinimumSectionSize(60)
        self.history_table.setMinimumHeight(200)
        self.history_table.setFont(sans_font(size="--text-base"))
        history.add_widget(self.history_table)
        self._action(history, "View report", "view_report", self.selected_report)
        self._action(history, "Export diagnostics", "export_diagnostics")
        layout.addWidget(history, 1, 0)
        backups = DSCard("Calibration backups")
        backups.add_widget(self._label(
            "Backups contain calibration for this device. Restore requires technician access, "
            "creates a backup first, and requires an unloaded reset and verification afterward.",
            muted=True,
        ))
        self.backup_choice = QComboBox()
        self.backup_choice.setMinimumHeight(48)
        self.backup_choice.setAccessibleName("Calibration backup")
        self.backup_choice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.backup_choice.setMinimumContentsLength(12)
        backups.add_widget(self.backup_choice)
        self._action(backups, "Back up calibration", "backup_calibration")
        self._action(backups, "Review and restore", "restore_calibration",
                     self.backup_choice.currentData, variant="destructive")
        layout.addWidget(backups, 1, 1)
        layout.setRowStretch(2, 1)

    # ----- sections -----
    def _select_section(self, index: int) -> None:
        if index == 2 and not self.service_unlocked:
            self.service_access_requested.emit()
            return
        if index != 2 and self.service_unlocked:
            self.lock_service()
        self._show_section(index)

    def _show_section(self, index: int) -> None:
        self._sections.setCurrentIndex(index)
        self._tabs.set_current(index)

    def _render_lock(self) -> None:
        """The Service tab carries a lock while locked; a lock button re-locks it."""
        service = self._section_buttons[2]
        if self.service_unlocked:
            service.setIcon(control_icon("check", resolve("--white"), 18))
        else:
            service.setIcon(control_icon("lock", resolve("--ink-700"), 18))
        self.actions["lock_service"].setVisible(self.service_unlocked)

    def unlock_service(self) -> None:
        self.service_unlocked = True
        self._show_section(2)
        self._render_lock()

    def lock_service(self) -> None:
        self.service_unlocked = False
        self._show_section(0)
        self.actions["flash_software"].setEnabled(False)
        self.actions["flash_firmware"].setEnabled(False)
        self._render_lock()
        self.service_locked.emit()

    def hideEvent(self, event: object) -> None:
        self.lock_service()
        super().hideEvent(event)

    # ----- controller setters -----
    def _changed(self, key: str, value: int) -> None:
        self.setting_labels[key].setText(f"{value}%")
        self.setting_requested.emit(key, value)

    def set_setting(self, key: str, value: Optional[int], detail: str = "") -> None:
        slider = self.sliders[key]
        slider.blockSignals(True)
        if value is not None:
            slider.setValue(value)
        slider.blockSignals(False)
        slider.setEnabled(value is not None)
        self.setting_labels[key].setText(f"{value}%" if value is not None else "Unavailable")
        self.setting_details[key].setText(detail)

    def set_device_id(self, device_id: str) -> None:
        self._device_id.setText(device_id or "Unavailable")

    def set_firmware(self, version: Optional[str], connected: bool) -> None:
        value = ((version or "Not reported by controller") if connected
                 else "Controller disconnected")
        self._firmware.setText(value)
        self.values["controller"].setText(
            "Arduino: " + ("Connected" if connected else "Disconnected"))
        self.details_changed.emit({"controller": self.values["controller"].text()})

    def set_status(self, message: str) -> None:
        self.status.setText(message)
        self._status_strip.setVisible(bool(message) and message != READY_STATUS)
        note = self._saved_notes.get(_SAVED_NOTES.get(message, ""))
        if note is not None:
            note.show()
            QTimer.singleShot(2500, note.hide)

    def set_details(self, details: Dict[str, str]) -> None:
        for key, value in details.items():
            if key in self.values:
                self.values[key].setText(value)
        self.details_changed.emit(dict(details))

    @staticmethod
    def local_date(value: str) -> str:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime(
                "%Y-%m-%d %H:%M")
        except ValueError:
            return value

    def set_history(self, rows: List[Dict[str, Any]], backups: List[str]) -> None:
        selected = self.selected_report()
        self.history_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for col, key in enumerate(("date", "kind", "operator", "result")):
                text = row[key]
                if key == "date":
                    text = self.local_date(text)
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, row["file"])
                self.history_table.setItem(index, col, item)
            if row["file"] == selected:
                self.history_table.selectRow(index)
        self.history_table.resizeRowsToContents()
        if rows and self.history_table.currentRow() < 0:
            self.history_table.selectRow(0)
        choice = self.backup_choice.currentData()
        self.backup_choice.clear()
        for name in backups:
            title = name
            stamp = name[len("calibration-"):-len(".json")]
            for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S%fZ"):
                try:
                    date = datetime.strptime(stamp, pattern).replace(tzinfo=timezone.utc)
                    title = date.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    break
                except ValueError:
                    continue
            self.backup_choice.addItem(title, name)
        self.backup_choice.setCurrentIndex(max(0, self.backup_choice.findData(choice)))
        self.actions["view_report"].setEnabled(bool(rows))
        self.actions["restore_calibration"].setEnabled(bool(backups))
        for key, matches in (
            ("last_test", [r for r in rows if r["kind"] == "Hardware tests"]),
            ("last_calibration", [r for r in rows if r["saved"]]),
        ):
            value = (f"{self.local_date(matches[0]['date'])} · {matches[0]['operator']} · "
                     f"{matches[0]['result']}"
                     if matches else "Not recorded yet")
            self.values[key].setText(value)

    def selected_report(self) -> str:
        row = self.history_table.currentRow()
        item = self.history_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else ""

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh_requested.emit()
