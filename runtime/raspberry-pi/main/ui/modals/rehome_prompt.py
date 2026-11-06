"""Nonmodal prompt that asks before homing after an on-screen STOP."""

import time
from typing import Callable, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.widgets.ds import DSButton
from ui.widgets.ds._common import resolve, sans_font


def format_elapsed(seconds: float) -> str:
    """Minutes and seconds, e.g. 0:07 or 12:30."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class RehomePrompt(QDialog):
    """Ask before homing. Nothing moves until the operator taps Re-home.

    The elapsed time is only shown: no action is taken when time passes.
    """

    rehome_requested = pyqtSignal()

    TICK_MS = 1000

    def __init__(self, load_cleared: bool = True, parent: Optional[QWidget] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(parent)
        self._clock = clock
        self._shown_at = clock()
        self.setWindowTitle("Re-home the device?")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFont(sans_font(size="--text-base"))
        self.setStyleSheet(f"QDialog {{ background: {resolve('--surface-page')}; }}")
        self.setFixedWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)
        lead = ("Treatment stopped and traction was released." if load_cleared
                else "Treatment stopped.")
        text = QLabel(
            f"{lead} The device has not re-homed. Make sure the patient is clear "
            "of the device, then tap Re-home now. Nothing moves until you do.", self
        )
        text.setWordWrap(True)
        root.addWidget(text)
        if not load_cleared:
            warning = QLabel(
                "Pressure did not drop fully during the release. Check the "
                "patient before re-homing.", self
            )
            warning.setWordWrap(True)
            warning.setStyleSheet(
                f"color: {resolve('--red-500')}; font-weight: 600; background: transparent;"
            )
            root.addWidget(warning)
        self.elapsed_label = QLabel(self)
        root.addWidget(self.elapsed_label)
        buttons = QHBoxLayout()
        self.later_button = DSButton("Not now", variant="secondary")
        self.rehome_button = DSButton("Re-home now", variant="primary")
        self.later_button.clicked.connect(self.close)
        self.rehome_button.clicked.connect(self._rehome)
        buttons.addWidget(self.later_button)
        buttons.addWidget(self.rehome_button)
        root.addLayout(buttons)
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self.refresh_elapsed)
        self._timer.start()
        self.refresh_elapsed()
        # A wrapped QLabel's size hint can be shorter than its text needs.
        self.setMinimumHeight(root.heightForWidth(self.width()))

    def refresh_elapsed(self) -> None:
        elapsed = format_elapsed(self._clock() - self._shown_at)
        self.elapsed_label.setText(f"Waiting to re-home: {elapsed}")

    def _rehome(self) -> None:
        self._timer.stop()
        self.rehome_requested.emit()
        self.close()
