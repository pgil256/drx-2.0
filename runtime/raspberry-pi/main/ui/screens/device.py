"""Device overview, connectivity, comfort settings, service history and power."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QShowEvent
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QScrollArea, QScroller, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from main.config.constants import APP_VERSION
from ui.widgets.ds import DSButton, DSCard
from ui.widgets.ds._common import resolve, sans_font
from ui.widgets.ds.slider import _TouchSlider


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
        self.setStyleSheet(f"#DeviceScreen {{ background: {resolve('--surface-page')}; }}")
        self.actions: Dict[str, DSButton] = {}
        self.values: Dict[str, QLabel] = {}
        self.service_unlocked = False
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)
        tabs = QHBoxLayout()
        self._section_buttons = []
        self._sections = QStackedWidget()
        titles = ("Overview", "Settings", "Service")
        for index, (title, variant) in enumerate(zip(titles, ("dark", "secondary", "primary"))):
            button = DSButton(title, variant=variant, full_width=True)
            button.setProperty("sectionTab", True)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, i=index: self._select_section(i))
            self._section_buttons.append(button)
            tabs.addWidget(button)
        root.addLayout(tabs)
        root.addWidget(self._sections, 1)
        self._overview()
        settings = self._page()
        self._connections(settings)
        self._comfort(settings)
        self._system(settings)
        self._service()
        self.status = self._label("Device settings are ready.")
        root.addWidget(self.status)
        self._select_section(0)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setFont(sans_font(size="--text-base"))
        return label

    def _page(self) -> QGridLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        QScroller.grabGesture(scroll.viewport(), QScroller.TouchGesture)
        host = QWidget()
        layout = QGridLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        scroll.setWidget(host)
        self._sections.addWidget(scroll)
        return layout

    def _value(self, card: DSCard, key: str, text: str) -> QLabel:
        label = self._label(text)
        self.values[key] = label
        card.add_widget(label)
        return label

    @staticmethod
    def _card_button(card: DSCard, title: str, variant: str = "secondary") -> DSButton:
        """Add a compact, centered action with a generous touch target."""
        button = DSButton(title, variant=variant)
        button.setMinimumWidth(200)
        card.body_layout.addWidget(button, 0, Qt.AlignHCenter)
        return button

    def _action(self, card: DSCard, title: str, key: str,
                payload: object = None, variant: str = "secondary") -> DSButton:
        button = self._card_button(card, title, variant)
        button.clicked.connect(lambda: self.action_requested.emit(
            key, payload() if callable(payload) else payload,
        ))
        self.actions[key] = button
        return button

    def _overview(self) -> None:
        layout = self._page()
        power = DSCard("App and device power")
        power.add_widget(self._label("Finish treatment and device service before restarting."))
        self._action(power, "Restart App", "restart_app", variant="dark")
        self._action(power, "Restart Device", "reboot", variant="secondary")
        self._action(power, "Shut Down", "poweroff", variant="primary")
        layout.addWidget(power, 0, 0)
        identity = DSCard("Device information")
        self._version = self._value(identity, "version", f"Software version: {APP_VERSION}")
        self._firmware = self._value(identity, "firmware", "Firmware version: Not checked")
        self._device_id = self._value(identity, "device_id", "Device ID: Unavailable")
        self._device_id.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(identity, 1, 0)
        health = DSCard("Connections and records")
        self._value(health, "controller", "Arduino: Not checked")
        self._value(health, "internet", "Internet: Test connection to check")
        self._value(health, "cloud", "Cloud: Not checked")
        self._value(health, "pending", "Pending uploads: Not checked")
        self._value(health, "last_sync", "Last successful sync: Not recorded yet")
        refresh = self._card_button(health, "Refresh device status")
        refresh.clicked.connect(self.refresh_requested)
        layout.addWidget(health, 0, 1, 2, 1)
        layout.setRowStretch(2, 1)

    def _connections(self, layout: QGridLayout) -> None:
        network = DSCard("Network")
        self._value(network, "network", "Network: Not checked")
        self._value(network, "addresses", "IP addresses: Not checked")
        self._value(network, "wifi_backend", "Wi-Fi setup: Not checked")
        self._action(network, "Test Connection", "test_connection", variant="primary")
        self._action(network, "Set Up Wi-Fi", "wifi")
        network.add_widget(self._label(
            "Network changes require administrator or technician access."))
        layout.addWidget(network, 0, 0)
        sync = DSCard("Cloud synchronization")
        self._value(sync, "sync_detail", "Check device status for upload information.")
        self._value(sync, "sync_time", "Last successful sync: Not recorded yet")
        self._action(sync, "Sync", "retry_sync", variant="primary")
        sync.add_widget(self._label(
            "Treatment records stay on the device until the server acknowledges receipt."
        ))
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
            detail = self._label("Checking device controls…")
            grid.addWidget(detail, 2, 0, 1, 2)
            self.sliders[key] = slider
            self.setting_labels[key] = value
            self.setting_details[key] = detail
            controls.add_widget(host)
        self._action(controls, "Test Sound", "test_sound")
        layout.addWidget(controls, 1, 0)
        idle = DSCard("Screen timeout")
        idle.add_widget(self._label(
            "Dim after inactivity while the device is idle. Touch to restore brightness; "
            "the first touch only wakes the display. The screen stays bright during treatment "
            "and service work."
        ))
        self.idle_timeout = QComboBox()
        self.idle_timeout.setMinimumHeight(48)
        self.idle_timeout.setAccessibleName("Idle dimming timeout")
        for minutes in (0, 1, 2, 5, 10, 15, 30):
            self.idle_timeout.addItem("Never" if minutes == 0 else f"{minutes} minutes", minutes)
        idle.add_widget(self.idle_timeout)
        self._action(idle, "Save Dimming Timeout", "idle_timeout", self.idle_timeout.currentData)
        self._value(idle, "dimming", "Uses the display backlight when available.")
        layout.addWidget(idle, 1, 1)

    def _service(self) -> None:
        layout = self._page()
        tasks = DSCard("Hardware tests and calibration")
        tasks.add_widget(self._label("Keep the device unoccupied throughout service."))
        self.hardware_button = self._card_button(tasks, "Hardware Tests", variant="primary")
        self.hardware_button.clicked.connect(self.hardware_tests_requested)
        tasks.add_widget(self._label(
            "Check movement, sensors, stops and mechanical condition. "
            "Record pass/fail observations."
        ))
        self.calibration_button = self._card_button(tasks, "Calibration")
        self.calibration_button.clicked.connect(self.calibration_requested)
        tasks.add_widget(self._label(
            "Measure position marks and the load-cell factor. Review and save calibration changes."
        ))
        self._action(tasks, "Lock Service", "lock_service", variant="ghost")
        layout.addWidget(tasks, 0, 0)
        updates = DSCard("Software and firmware")
        self.release_status = self._value(
            updates, "release_status", "Sign in to the cloud to check the latest releases.")
        self._action(updates, "Check Latest Releases", "check_releases")
        self.software_release = self._value(updates, "software_release", "Software: Not checked")
        self._action(updates, "Flash Software", "flash_software")
        self.firmware_release = self._value(updates, "firmware_release", "Firmware: Not checked")
        self._action(updates, "Flash Firmware", "flash_firmware")
        self.actions["flash_software"].setEnabled(False)
        self.actions["flash_firmware"].setEnabled(False)
        layout.addWidget(updates, 0, 1)
        history = DSCard("Service history")
        self._value(history, "last_test", "Last hardware test: Not recorded yet")
        self._value(history, "last_calibration", "Last calibration save: Not recorded yet")
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["Date", "Work", "Operator", "Result"])
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.verticalHeader().hide()
        self.history_table.verticalHeader().setDefaultSectionSize(60)
        self.history_table.verticalHeader().setMinimumSectionSize(60)
        self.history_table.setMinimumHeight(200)
        self.history_table.setFont(sans_font(size="--text-base"))
        history.add_widget(self.history_table)
        self._action(history, "View Selected Report", "view_report", self.selected_report)
        self._action(history, "Export Diagnostics", "export_diagnostics")
        layout.addWidget(history, 1, 0)
        backups = DSCard("Calibration backups")
        backups.add_widget(self._label(
            "Backups contain calibration for this device. Restore requires technician access, "
            "creates a backup first, and requires an unloaded reset and verification afterward."
        ))
        self.backup_choice = QComboBox()
        self.backup_choice.setMinimumHeight(48)
        self.backup_choice.setAccessibleName("Calibration backup")
        self.backup_choice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.backup_choice.setMinimumContentsLength(12)
        backups.add_widget(self.backup_choice)
        self._action(backups, "Back Up Calibration", "backup_calibration")
        self._action(backups, "Review and Restore Backup", "restore_calibration",
                     self.backup_choice.currentData)
        layout.addWidget(backups, 1, 1)
        layout.setRowStretch(2, 1)

    def _system(self, layout: QGridLayout) -> None:
        clock = DSCard("Date and time")
        self._value(clock, "clock", "Current time: Not checked")
        self._value(clock, "timezone", "Time zone: Not checked")
        self._value(clock, "ntp", "Automatic time: Not checked")
        self._action(clock, "Change Time Zone", "timezone")
        self._action(clock, "Enable Automatic Time", "sync_clock")
        layout.addWidget(clock, 2, 0)
        session = DSCard("Automatic logout")
        session.add_widget(self._label(
            "Log out after inactivity. The timer waits for treatment, motion, reset and "
            "service work to finish before starting a fresh inactivity period."
        ))
        self.logout_timeout = QComboBox()
        self.logout_timeout.setMinimumHeight(48)
        self.logout_timeout.setAccessibleName("Automatic logout timer")
        for minutes in (0, 1, 5, 10, 15, 30, 60):
            self.logout_timeout.addItem("Never" if minutes == 0 else f"{minutes} minutes", minutes)
        session.add_widget(self.logout_timeout)
        self._action(session, "Save Logout Timer", "logout_timeout",
                     self.logout_timeout.currentData)
        layout.addWidget(session, 2, 1)
        layout.setRowStretch(3, 1)

    def _select_section(self, index: int) -> None:
        if index == 2 and not self.service_unlocked:
            self.service_access_requested.emit()
            return
        if index != 2 and self.service_unlocked:
            self.lock_service()
        self._show_section(index)

    def _show_section(self, index: int) -> None:
        self._sections.setCurrentIndex(index)
        for i, button in enumerate(self._section_buttons):
            button.setChecked(i == index)

    def unlock_service(self) -> None:
        self.service_unlocked = True
        self._show_section(2)

    def lock_service(self) -> None:
        self.service_unlocked = False
        self._show_section(0)
        self.actions["flash_software"].setEnabled(False)
        self.actions["flash_firmware"].setEnabled(False)
        self.service_locked.emit()

    def hideEvent(self, event: object) -> None:
        self.lock_service()
        super().hideEvent(event)

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
        self._device_id.setText(f"Device ID: {device_id or 'Unavailable'}")

    def set_firmware(self, version: Optional[str], connected: bool) -> None:
        value = ((version or "Not reported by controller") if connected
                 else "Controller disconnected")
        self._firmware.setText(f"Firmware version: {value}")
        self.values["controller"].setText(
            "Arduino: " + ("Connected" if connected else "Disconnected"))
        self.details_changed.emit({"controller": self.values["controller"].text()})

    def set_status(self, message: str) -> None:
        self.status.setText(message)

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
            title = "Last hardware test" if key == "last_test" else "Last calibration save"
            value = (f"{self.local_date(matches[0]['date'])} · {matches[0]['operator']} · "
                     f"{matches[0]['result']}"
                     if matches else "Not recorded yet")
            self.values[key].setText(f"{title}: {value}")

    def selected_report(self) -> str:
        row = self.history_table.currentRow()
        item = self.history_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else ""

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh_requested.emit()
