"""Touchscreen forms for network credentials and inspectable service reports."""

import json
from typing import Dict, List, Optional

from PyQt5.QtCore import QEvent, QSize, Qt
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QScroller,
    QVBoxLayout, QWidget,
)

from ui.modals.text_keyboard import TextKeyboard
from ui.widgets.ds import DSButton
from ui.widgets.ds._common import sans_font


class WifiDialog(QDialog):
    """Select a scanned network and pass the password only to the current operation."""

    def __init__(self, networks: List[Dict[str, str]], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to Wi-Fi")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(650)
        self.setFont(sans_font(size="--text-base"))
        self.networks = networks
        self.keyboard = None
        layout = QVBoxLayout(self)
        label = QLabel("Choose a network. Changing networks may interrupt cloud access.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.network = QComboBox()
        self.network.setMinimumHeight(48)
        self.network.setAccessibleName("Wi-Fi network")
        for row in networks:
            self.network.addItem(f"{row['ssid']} · {row['signal']} · {row['security'] or 'Open'}")
            self.network.setItemData(self.network.count() - 1, QSize(0, 48), Qt.SizeHintRole)
        layout.addWidget(self.network)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setMaxLength(64)
        self.password.setMinimumHeight(52)
        self.password.setPlaceholderText("Tap to enter Wi-Fi password")
        self.password.setAccessibleName("Wi-Fi password")
        self.password.installEventFilter(self)
        layout.addWidget(self.password)
        actions = QHBoxLayout()
        cancel = DSButton("Cancel", variant="secondary")
        cancel.clicked.connect(self.reject)
        connect = DSButton("Connect", variant="primary")
        connect.setEnabled(bool(networks))
        connect.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(connect)
        layout.addLayout(actions)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.password and event.type() == QEvent.MouseButtonRelease:
            if self.keyboard is None:
                keyboard = TextKeyboard("Wi-Fi password", self.password.text(), 64,
                                        parent=self, secret=True)
                self.keyboard = keyboard

                def finish(result: int) -> None:
                    if result == QDialog.Accepted:
                        self.password.setText(keyboard.value())
                    keyboard.editor.clear()
                    self.keyboard = None
                    keyboard.deleteLater()

                keyboard.finished.connect(finish)
                keyboard.open()
            return True
        return super().eventFilter(watched, event)


class TimezoneDialog(QDialog):
    """Select an installed time zone with touch-sized rows and actions."""

    def __init__(self, zones: List[str], current: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Time zone")
        self.setFont(sans_font(size="--text-base"))
        self.resize(680, 240)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the device's local time zone."))
        self.choice = QComboBox()
        self.choice.setMinimumHeight(52)
        self.choice.setMaxVisibleItems(8)
        self.choice.setAccessibleName("Time zone")
        for zone in zones:
            self.choice.addItem(zone)
            self.choice.setItemData(self.choice.count() - 1, QSize(0, 48), Qt.SizeHintRole)
        if current in zones:
            self.choice.setCurrentText(current)
        QScroller.grabGesture(self.choice.view().viewport(), QScroller.TouchGesture)
        layout.addWidget(self.choice)
        actions = QHBoxLayout()
        for text, callback in (("Cancel", self.reject), ("Save Time Zone", self.accept)):
            button = DSButton(text, variant="secondary" if text == "Cancel" else "primary")
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)


class CalibrationRestoreDialog(QDialog):
    """Review a complete backup without squeezing position tables into a message box."""

    def __init__(self, data: dict, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review calibration restore")
        self.resize(950, 620)
        self.setFont(sans_font(size="--text-base"))
        layout = QVBoxLayout(self)
        summary = QLabel(
            f"Backup by {data['operator']} on {data['created_at']}. "
            "The current calibration will be backed up first. Remove all loads, then reset "
            "and verify calibration after restoring, before using the device."
        )
        summary.setTextFormat(Qt.PlainText)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))
        QScroller.grabGesture(details.viewport(), QScroller.TouchGesture)
        layout.addWidget(details, 1)
        actions = QHBoxLayout()
        cancel = DSButton("Cancel", variant="secondary")
        cancel.clicked.connect(self.reject)
        restore = DSButton("Restore This Calibration", variant="danger")
        restore.setAutoDefault(False)
        restore.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(restore)
        layout.addLayout(actions)


def show_report(title: str, record: dict, parent: QWidget) -> QDialog:
    """Show a report as plain text; never execute record contents or open a browser."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(950, 620)
    layout = QVBoxLayout(dialog)
    text = QPlainTextEdit()
    text.setReadOnly(True)
    text.setFont(sans_font(size="--text-base"))
    text.setPlainText(json.dumps(record, indent=2, ensure_ascii=False))
    layout.addWidget(text)
    close = DSButton("Close", variant="secondary")
    close.clicked.connect(dialog.accept)
    layout.addWidget(close)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    dialog.open()
    return dialog
