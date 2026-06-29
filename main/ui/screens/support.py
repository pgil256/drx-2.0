"""SupportScreen — troubleshooting + contact (absorbs the old Profile actions).

Mirrors `SupportScreen` in `bundle.jsx`: a "Troubleshooting" card with an
accordion of common failures, and a "Contact Support" card (phone, Request
Assistance, Submit a Ticket). The accordion expands/collapses here; the
ticket-email wiring (§15.5) lands in Phase 3.5.

Signals:
    issue_activated(str)        — a troubleshooting item header was tapped
    request_assistance          — "Request Assistance" button
    submit_ticket_requested     — "Submit a Ticket" button
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import GLYPH
from ui.widgets.common import eyebrow
from ui.widgets.ds import DSButton, DSCard
from ui.widgets.ds._common import mono_font, resolve, sans_font

from .content import HELP_FAILURES

_PAD = 20
_GAP = 16


class _FailureItem(QFrame):
    """A collapsible troubleshooting row (question header + answer body)."""

    activated = pyqtSignal(str)

    def __init__(self, question, answer, parent=None):
        super().__init__(parent)
        self._question = question
        self._open = False
        self.setObjectName("FailureItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#FailureItem {{ background: #ffffff;"
            f" border: 1px solid {resolve('--gray-300')};"
            f" border-radius: {resolve('--radius-md')}; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._header = QPushButton()
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setLayoutDirection(Qt.LeftToRight)
        self._header.setStyleSheet(
            "QPushButton { text-align: left; border: none; background: transparent;"
            " padding: 12px 18px; }"
            f" QPushButton:hover {{ background: {resolve('--gray-050')}; }}"
        )
        hlay = QHBoxLayout(self._header)
        hlay.setContentsMargins(18, 12, 18, 12)
        hlay.setSpacing(12)
        self._q = QLabel(question)
        self._q.setFont(sans_font(size="--text-sm", weight=700))
        self._q.setStyleSheet(f"color: {resolve('--ink-900')}; background: transparent;")
        self._q.setWordWrap(True)
        self._indicator = QLabel(GLYPH["accordion_closed"])
        self._indicator.setFont(sans_font(size="--text-lg", weight=600))
        self._indicator.setStyleSheet(
            f"color: {resolve('--brand-cyan')}; background: transparent;"
        )
        hlay.addWidget(self._q, 1)
        hlay.addWidget(self._indicator, 0, Qt.AlignVCenter)
        self._header.clicked.connect(self._toggle)
        lay.addWidget(self._header)

        self._body = QLabel(answer)
        self._body.setWordWrap(True)
        self._body.setFont(sans_font(size="--text-sm"))
        self._body.setContentsMargins(18, 0, 18, 14)
        self._body.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        self._body.setVisible(False)
        lay.addWidget(self._body)

    def _toggle(self):
        self._open = not self._open
        self._body.setVisible(self._open)
        self._indicator.setText(
            GLYPH["accordion_open"] if self._open else GLYPH["accordion_closed"]
        )
        self._header.setStyleSheet(
            "QPushButton { text-align: left; border: none; padding: 12px 18px;"
            f" background: {resolve('--gray-050') if self._open else 'transparent'}; }}"
            f" QPushButton:hover {{ background: {resolve('--gray-050')}; }}"
        )
        self.activated.emit(self._question)


class SupportScreen(QWidget):
    issue_activated = pyqtSignal(str)
    request_assistance = pyqtSignal()
    submit_ticket_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SupportScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#SupportScreen {{ background: {resolve('--surface-page')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        lay.setSpacing(_GAP)

        lay.addWidget(self._troubleshooting_card(), 1)
        lay.addWidget(self._contact_card(), 0)

    def _troubleshooting_card(self):
        card = DSCard("Troubleshooting", padded=False)
        host = QWidget()
        vlay = QVBoxLayout(host)
        vlay.setContentsMargins(18, 12, 18, 16)
        vlay.setSpacing(10)
        intro = QLabel("Common points of failure — tap any item to see how to resolve it.")
        intro.setFont(sans_font(size="--text-sm"))
        intro.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        vlay.addWidget(intro)
        for q, a in HELP_FAILURES:
            item = _FailureItem(q, a)
            item.activated.connect(self.issue_activated)
            vlay.addWidget(item)
        vlay.addStretch(1)
        card.add_widget(host)
        return card

    def _contact_card(self):
        card = DSCard("Contact Support", padded=False)
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(_GAP)

        info = QHBoxLayout()
        info.setSpacing(20)
        phone_box = QVBoxLayout()
        phone_box.setSpacing(3)
        phone_box.addWidget(eyebrow("Phone Support"))
        phone = QLabel("1-833-KNEE-SPA")
        phone.setFont(mono_font(size=26, weight=600))  # DS 26px (between --text-lg/xl)
        phone.setStyleSheet(f"color: {resolve('--ink-900')}; background: transparent;")
        phone_box.addWidget(phone)
        info.addLayout(phone_box, 0)
        helper = QLabel(
            "Still stuck? Open a support ticket or request live assistance and our "
            "team will follow up."
        )
        helper.setWordWrap(True)
        helper.setFont(sans_font(size="--text-xs"))
        helper.setMaximumWidth(320)
        helper.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        info.addWidget(helper, 1)
        row.addLayout(info, 1)

        btns = QHBoxLayout()
        btns.setSpacing(12)
        assist = DSButton("Request Assistance", variant="secondary")
        assist.clicked.connect(self.request_assistance)
        ticket = DSButton("Submit a Ticket", variant="primary")
        ticket.clicked.connect(self.submit_ticket_requested)
        btns.addWidget(assist)
        btns.addWidget(ticket)
        row.addLayout(btns, 0)

        card.add_widget(host)
        return card
