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

from config.constants import APP_VERSION
from ui.widgets.common import KeyValueLabel
from ui.widgets.ds import DSButton, DSCard
from ui.widgets.ds._common import resolve, sans_font
from ui.widgets.ds.slider import _TouchSlider

_ROW_GAP = 12
_BUTTON_MIN_WIDTH = 180


class DeviceScreen(QWidget):
    """Expose device intent; the controller owns privilege checks and OS calls."""

    hardware_tests_requested = pyqtSignal()
    calibration_requested = pyqtSignal()
    setting_requested = pyqtSignal(str, int)
    refresh_requested = pyqtSignal()
    action_requested = pyqtSignal(str, object)
    service_access_requested = pyqtSignal()
    service_locked = pyqtSignal()

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
        # Same tab pattern as Help and Support: the open section is filled.
        for index, title in enumerate(("Overview", "Settings", "Service")):
            button = DSButton(title, variant="secondary", full_width=True)
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
        # Controller feedback line ("Working…", "Diagnostics saved: …"): quiet
        # and muted so it reads as status, not as another card of content.
        self.status = self._label("Device settings are ready.")
        self.status.setFont(sans_font(size="--text-sm"))
        self.status.setStyleSheet(f"color: {resolve('--text-muted')}; padding: 2px 4px 0 4px;")
        root.addWidget(self.status)
        self._select_section(0)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setFont(sans_font(size="--text-base"))
        return label

    @staticmethod
    def _note(text: str) -> QLabel:
        """Secondary copy under a control, in the smaller arm's-length size."""
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setFont(sans_font(size="--text-sm"))
        label.setStyleSheet(f"color: {resolve('--text-muted')};")
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

    @staticmethod
    def _card(title: str) -> DSCard:
        """A card whose content stays at the top when the grid stretches it."""
        card = DSCard(title)
        card.body_layout.setSpacing(10)
        return card

    @staticmethod
    def _finish(card: DSCard) -> None:
        card.body_layout.addStretch(1)

    def _value(self, card: DSCard, key: str, text: str) -> QLabel:
        label = KeyValueLabel(text)
        self.values[key] = label
        card.add_widget(label)
        return label

    @staticmethod
    def _button(title: str, variant: str = "secondary") -> DSButton:
        button = DSButton(title, variant=variant)
        button.setMinimumWidth(_BUTTON_MIN_WIDTH)
        return button

    @staticmethod
    def _row(card: DSCard, *widgets: QWidget, stretch_last: bool = False) -> QHBoxLayout:
        """A left-aligned action row (centred stacks read as a dialog footer)."""
        row = QHBoxLayout()
        row.setSpacing(_ROW_GAP)
        for index, widget in enumerate(widgets):
            last = index == len(widgets) - 1
            row.addWidget(widget, 1 if (stretch_last and last) else 0)
        if not stretch_last:
            row.addStretch(1)
        card.add_layout(row)
        return row

    def _action(self, title: str, key: str, payload: object = None,
                variant: str = "secondary") -> DSButton:
        """A registered action button; the caller places it in a row."""
        button = self._button(title, variant)
        button.clicked.connect(lambda: self.action_requested.emit(
            key, payload() if callable(payload) else payload,
        ))
        self.actions[key] = button
        return button

    def _overview(self) -> None:
        layout = self._page()
        power = self._card("App and device power")
        power.add_widget(self._label("Finish treatment and device service before restarting."))
        self._row(
            power,
            self._action("Restart App", "restart_app"),
            self._action("Restart Device", "reboot"),
            self._action("Shut Down", "poweroff", variant="destructive"),
        )
        self._finish(power)
        layout.addWidget(power, 0, 0)
        identity = self._card("Device information")
        self._version = self._value(identity, "version", f"Software version: {APP_VERSION}")
        self._firmware = self._value(identity, "firmware", "Firmware version: Not checked")
        self._device_id = self._value(identity, "device_id", "Device ID: Unavailable")
        self._device_id.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._finish(identity)
        layout.addWidget(identity, 1, 0)
        health = self._card("Connections and records")
        self._value(health, "controller", "Arduino: Not checked")
        self._value(health, "internet", "Internet: Test connection to check")
        self._value(health, "cloud", "Cloud: Not checked")
        self._value(health, "pending", "Pending uploads: Not checked")
        self._value(health, "last_sync", "Last successful sync: Not recorded yet")
        refresh = self._button("Refresh device status")
        refresh.clicked.connect(self.refresh_requested)
        self._row(health, refresh)
        self._finish(health)
        layout.addWidget(health, 0, 1, 2, 1)
        layout.setRowStretch(2, 1)

    def _connections(self, layout: QGridLayout) -> None:
        network = self._card("Network")
        self._value(network, "network", "Network: Not checked")
        self._value(network, "addresses", "IP addresses: Not checked")
        self._value(network, "wifi_backend", "Wi-Fi setup: Not checked")
        self._row(
            network,
            self._action("Test Connection", "test_connection", variant="primary"),
            self._action("Set Up Wi-Fi", "wifi"),
        )
        network.add_widget(self._note(
            "Network changes require administrator or technician access."))
        self._finish(network)
        layout.addWidget(network, 0, 0)
        sync = self._card("Cloud synchronization")
        self._value(sync, "sync_detail", "Check device status for upload information.")
        self._value(sync, "sync_time", "Last successful sync: Not recorded yet")
        self._row(sync, self._action("Sync", "retry_sync", variant="primary"))
        sync.add_widget(self._note(
            "Treatment records stay on the device until the server acknowledges receipt."
        ))
        self._finish(sync)
        layout.addWidget(sync, 0, 1)

    def _comfort(self, layout: QGridLayout) -> None:
        controls = self._card("Sound and display")
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
            detail = self._note("Checking device controls…")
            grid.addWidget(detail, 2, 0, 1, 2)
            self.sliders[key] = slider
            self.setting_labels[key] = value
            self.setting_details[key] = detail
            controls.add_widget(host)
        self._row(controls, self._action("Test Sound", "test_sound"))
        self._finish(controls)
        layout.addWidget(controls, 1, 0)
        idle = self._card("Screen timeout")
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
        self._row(
            idle, self.idle_timeout,
            self._action("Save Dimming Timeout", "idle_timeout", self.idle_timeout.currentData),
        )
        self._value(idle, "dimming", "Uses the display backlight when available.")
        self._finish(idle)
        layout.addWidget(idle, 1, 1)

    def _service(self) -> None:
        layout = self._page()
        tasks = self._card("Hardware tests and calibration")
        tasks.add_widget(self._label("Keep the device unoccupied throughout service."))
        self.hardware_button = self._button("Hardware Tests", variant="primary")
        self.hardware_button.clicked.connect(self.hardware_tests_requested)
        self._row(tasks, self.hardware_button, self._note(
            "Check movement, sensors, stops and mechanical condition. "
            "Record pass/fail observations."
        ), stretch_last=True)
        self.calibration_button = self._button("Calibration")
        self.calibration_button.clicked.connect(self.calibration_requested)
        self._row(tasks, self.calibration_button, self._note(
            "Measure position marks and the load-cell factor. Review and save calibration changes."
        ), stretch_last=True)
        self._row(tasks, self._action("Lock Service", "lock_service", variant="ghost"))
        self._finish(tasks)
        layout.addWidget(tasks, 0, 0)
        updates = self._card("Software and firmware")
        self.release_status = self._value(
            updates, "release_status", "Sign in to the cloud to check the latest releases.")
        self._row(updates, self._action("Check Latest Releases", "check_releases"))
        self.software_release = self._value(updates, "software_release", "Software: Not checked")
        self._row(updates, self._action("Flash Software", "flash_software"))
        self.firmware_release = self._value(updates, "firmware_release", "Firmware: Not checked")
        self._row(updates, self._action("Flash Firmware", "flash_firmware"))
        self.actions["flash_software"].setEnabled(False)
        self.actions["flash_firmware"].setEnabled(False)
        self._finish(updates)
        layout.addWidget(updates, 0, 1)
        history = self._card("Service history")
        self._value(history, "last_test", "Last hardware test: Not recorded yet")
        self._value(history, "last_calibration", "Last calibration save: Not recorded yet")
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["Date", "Work", "Operator", "Result"])
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setShowGrid(False)
        self.history_table.verticalHeader().hide()
        self.history_table.verticalHeader().setDefaultSectionSize(60)
        self.history_table.verticalHeader().setMinimumSectionSize(60)
        self.history_table.setMinimumHeight(120)
        self.history_table.setFont(sans_font(size="--text-base"))
        history.add_widget(self.history_table)
        self._row(
            history,
            self._action("View Selected Report", "view_report", self.selected_report),
            self._action("Export Diagnostics", "export_diagnostics"),
        )
        self._finish(history)
        layout.addWidget(history, 1, 0)
        backups = self._card("Calibration backups")
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
        self._row(
            backups,
            self._action("Back Up Calibration", "backup_calibration"),
            self._action("Review and Restore Backup", "restore_calibration",
                         self.backup_choice.currentData),
        )
        self._finish(backups)
        layout.addWidget(backups, 1, 1)
        layout.setRowStretch(2, 1)

    def _system(self, layout: QGridLayout) -> None:
        clock = self._card("Date and time")
        self._value(clock, "clock", "Current time: Not checked")
        self._value(clock, "timezone", "Time zone: Not checked")
        self._value(clock, "ntp", "Automatic time: Not checked")
        self._row(
            clock,
            self._action("Change Time Zone", "timezone"),
            self._action("Enable Automatic Time", "sync_clock"),
        )
        self._finish(clock)
        layout.addWidget(clock, 2, 0)
        session = self._card("Automatic logout")
        session.add_widget(self._label(
            "Log out after inactivity. The timer waits for treatment, motion, reset and "
            "service work to finish before starting a fresh inactivity period."
        ))
        self.logout_timeout = QComboBox()
        self.logout_timeout.setMinimumHeight(48)
        self.logout_timeout.setAccessibleName("Automatic logout timer")
        for minutes in (0, 1, 5, 10, 15, 30, 60):
            self.logout_timeout.addItem("Never" if minutes == 0 else f"{minutes} minutes", minutes)
        self._row(
            session, self.logout_timeout,
            self._action("Save Logout Timer", "logout_timeout", self.logout_timeout.currentData),
        )
        self._finish(session)
        layout.addWidget(session, 2, 1)
        layout.setRowStretch(3, 1)

    def _select_section(self, index: int) -> None:
        if index == 2 and not self.service_unlocked:
            # The tap checked the Service tab; show the section that is still open.
            self._show_section(self._sections.currentIndex())
            self.service_access_requested.emit()
            return
        if index != 2 and self.service_unlocked:
            self.lock_service()
        self._show_section(index)

    def _show_section(self, index: int) -> None:
        self._sections.setCurrentIndex(index)
        for i, button in enumerate(self._section_buttons):
            button.setChecked(i == index)
            button.set_variant("primary" if i == index else "secondary")

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

    def set_status(self, message: str) -> None:
        self.status.setText(message)

    def set_details(self, details: Dict[str, str]) -> None:
        for key, value in details.items():
            if key in self.values:
                self.values[key].setText(value)

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
        self._fit_history_table()
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

    def _fit_history_table(self) -> None:
        """Size the table to its rows so no blank grid trails the last entry."""
        table = self.history_table
        rows = sum(table.rowHeight(row) for row in range(table.rowCount()))
        wanted = table.horizontalHeader().height() + rows + 2 * table.frameWidth() + 2
        table.setFixedHeight(max(120, min(wanted, 360)))

    def selected_report(self) -> str:
        row = self.history_table.currentRow()
        item = self.history_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else ""

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh_requested.emit()
