"""Unified support references, troubleshooting, and contact form."""

from typing import Optional

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme import control_icon
from ui.modals.text_keyboard import TextKeyboard
from ui.widgets.ds import DSButton, DSCard, DSSegmentedTabs
from ui.widgets.ds._common import resolve, sans_font

from helpers.support_ticket import validate_ticket

from .content import TROUBLESHOOTING
from .help import HelpScreen


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
        self._header.setMinimumHeight(56)
        self._header.setAccessibleName(question)
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setLayoutDirection(Qt.LeftToRight)
        self._render_header()
        hlay = QHBoxLayout(self._header)
        hlay.setContentsMargins(18, 12, 18, 12)
        hlay.setSpacing(12)
        self._q = QLabel(question)
        self._q.setFont(sans_font(size="--text-base", weight=600))
        self._q.setStyleSheet(f"color: {resolve('--ink-900')}; background: transparent;")
        self._q.setWordWrap(True)
        self._q.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # A drawn chevron reads as a control; "+" / "×" read as punctuation.
        self._indicator = QLabel()
        self._indicator.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._indicator.setFixedSize(24, 24)
        self._indicator.setStyleSheet("background: transparent;")
        self._render_indicator()
        hlay.addWidget(self._q, 1)
        hlay.addWidget(self._indicator, 0, Qt.AlignVCenter)
        self._header.clicked.connect(self._toggle)
        lay.addWidget(self._header)

        self._body = QLabel(answer)
        self._body.setWordWrap(True)
        self._body.setFont(sans_font(size="--text-base"))
        self._body.setContentsMargins(18, 0, 18, 14)
        self._body.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        self._body.setVisible(False)
        lay.addWidget(self._body)

    def is_open(self) -> bool:
        return self._open

    def _render_indicator(self):
        icon = "chevron-up" if self._open else "chevron-down"
        self._indicator.setPixmap(
            control_icon(icon, resolve("--color-primary"), 24).pixmap(24, 24))

    def _render_header(self):
        self._header.setStyleSheet(
            "QPushButton { text-align: left; border: none; padding: 12px 18px;"
            " min-height: 32px;"
            f" background: {resolve('--gray-050') if self._open else 'transparent'}; }}"
            f" QPushButton:hover {{ background: {resolve('--gray-050')}; }}"
            f" QPushButton[keyboardFocus=\"true\"]:focus {{"
            f" border: 2px solid {resolve('--border-focus')}; }}"
        )

    def _toggle(self):
        self._open = not self._open
        self._body.setVisible(self._open)
        self._render_indicator()
        self._render_header()
        if self._open:
            self.activated.emit(self._question)


class SupportScreen(HelpScreen):
    issue_activated = pyqtSignal(str)
    submit_ticket_requested = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, section_titles=(
            "Protocols", "Controls", "Troubleshooting", "Contact support",
        ))
        self.setObjectName("SupportScreen")
        # Renamed after HelpScreen styled itself; restate the page wash.
        self.setStyleSheet(f"#SupportScreen {{ background: {resolve('--surface-page')}; }}")
        self._sending = False
        self._keyboard = None
        self._keyboard_targets = {}
        self._deferred_contact = None
        self._issue = "General support request"
        self._add_section().addWidget(self._troubleshooting_card())
        self._add_section().addWidget(self._contact_card())

    def _troubleshooting_card(self) -> DSCard:
        card = DSCard("Troubleshooting", padded=False)
        host = QWidget()
        vlay = QVBoxLayout(host)
        vlay.setContentsMargins(18, 12, 18, 16)
        vlay.setSpacing(10)
        intro = QLabel("Choose a topic, then tap an issue for checks and next steps.")
        intro.setWordWrap(True)
        intro.setFont(sans_font(size="--text-base"))
        intro.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        vlay.addWidget(intro)
        self._trouble_pages = QStackedWidget()
        self._topics = DSSegmentedTabs(list(TROUBLESHOOTING), size="sm")
        self._topics.tab_requested.connect(self._select_topic)
        self._trouble_buttons = self._topics.buttons()
        for entries in TROUBLESHOOTING.values():
            page = QWidget()
            rows = QVBoxLayout(page)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(10)
            for question, answer in entries:
                item = _FailureItem(question, answer)
                item.activated.connect(self._select_issue)
                rows.addWidget(item)
            rows.addStretch(1)
            self._trouble_pages.addWidget(page)
        vlay.addWidget(self._topics)
        vlay.addWidget(self._trouble_pages)
        self._select_topic(0)
        card.add_widget(host)
        return card

    def _select_topic(self, index: int) -> None:
        self._trouble_pages.setCurrentIndex(index)
        self._topics.set_current(index)

    def _contact_card(self) -> DSCard:
        card = DSCard("Contact support", padded=False)
        host = QWidget()
        form = QVBoxLayout(host)
        form.setContentsMargins(20, 16, 20, 16)
        form.setSpacing(10)
        phone = QLabel("Phone support: 1-833-KNEE-SPA")
        phone.setFont(sans_font(size="--text-md", weight=600))
        form.addWidget(phone)
        note = QLabel(
            "Describe the problem and how we can reach you. Device ID, software and firmware "
            "versions are included automatically. Do not include patient information."
        )
        note.setWordWrap(True)
        note.setFont(sans_font(size="--text-base"))
        form.addWidget(note)
        self._selected_issue = QLabel("Related issue: " + self._issue)
        self._selected_issue.setTextFormat(Qt.PlainText)
        self._selected_issue.setWordWrap(True)
        form.addWidget(self._selected_issue)
        identity = QHBoxLayout()
        self.contact_name = QLineEdit()
        self.contact_name.setPlaceholderText("Your name (required)")
        self.contact_name.setAccessibleName("Your name")
        self.contact_name.setMaxLength(100)
        self.contact_email = QLineEdit()
        self.contact_email.setPlaceholderText("Reply email (required)")
        self.contact_email.setAccessibleName("Reply email")
        self.contact_email.setMaxLength(254)
        self.contact_email.setInputMethodHints(Qt.ImhEmailCharactersOnly)
        identity.addWidget(self.contact_name)
        identity.addWidget(self.contact_email)
        form.addLayout(identity)
        self.subject = QLineEdit()
        self.subject.setPlaceholderText("Brief summary (required)")
        self.subject.setAccessibleName("Ticket summary")
        self.subject.setMaxLength(160)
        form.addWidget(self.subject)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText(
            "What happened? What did you expect? Include any error message and steps "
            "already tried. (Required, maximum 4,000 characters)"
        )
        self.description.setAccessibleName("Problem description")
        self.description.setFixedHeight(120)
        form.addWidget(self.description)
        self._fields = (self.contact_name, self.contact_email, self.subject, self.description)
        for field in self._fields:
            field.setFont(sans_font(size="--text-base"))
            if isinstance(field, QLineEdit):
                field.setMinimumHeight(48)
            target = field.viewport() if isinstance(field, QPlainTextEdit) else field
            self._keyboard_targets[target] = field
            target.installEventFilter(self)
        self._delivery_status = QLabel("Complete the form to create a support ticket.")
        self._delivery_status.setTextFormat(Qt.PlainText)
        self._delivery_status.setWordWrap(True)
        self._delivery_status.setFont(sans_font(size="--text-base"))
        form.addWidget(self._delivery_status)
        self.ticket_button = DSButton("Submit ticket", variant="primary")
        self.ticket_button.clicked.connect(self._submit)
        self._send_buttons = (self.ticket_button,)
        form.addWidget(self.ticket_button, 0, Qt.AlignRight)
        card.add_widget(host)
        return card

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        field = self._keyboard_targets.get(watched)
        if field is not None and not self._sending and event.type() == QEvent.MouseButtonRelease:
            if self._keyboard is None:
                multiline = isinstance(field, QPlainTextEdit)
                value = field.toPlainText() if multiline else field.text()
                keyboard = TextKeyboard(
                    field.accessibleName(), value, 4000 if multiline else field.maxLength(),
                    multiline=multiline, parent=self,
                )
                self._keyboard = keyboard

                def finish(result: int) -> None:
                    if result == TextKeyboard.Accepted and not self._sending:
                        if multiline:
                            field.setPlainText(keyboard.value())
                        else:
                            field.setText(keyboard.value())
                    self._keyboard = None
                    keyboard.deleteLater()

                keyboard.finished.connect(finish)
                keyboard.open()
                keyboard.editor.setFocus()
            return True
        return super().eventFilter(watched, event)

    def _select_issue(self, question: str) -> None:
        if not self._sending:
            self._issue = question
            self._selected_issue.setText("Related issue: " + question)
            if not self.subject.text().strip():
                self.subject.setText(question)
        self.issue_activated.emit(question)

    def set_contact(self, username: str, email: str = "") -> None:
        """Clear the previous operator's draft when the signed-in identity changes."""
        if self._keyboard is not None:
            self._keyboard.reject()
        if self._sending:
            self._deferred_contact = (username, email)
            return
        self.contact_name.setText(username)
        self.contact_email.setText(email)
        self.subject.clear()
        self.description.clear()
        self._issue = "General support request"
        self._selected_issue.setText("Related issue: " + self._issue)
        self.set_delivery_state("idle", "Complete the form to create a support ticket.")

    def _submit(self) -> None:
        if self._sending:
            return
        payload = {
            "name": self.contact_name.text(), "email": self.contact_email.text(),
            "subject": self.subject.text(), "description": self.description.toPlainText(),
            "issue": self._issue,
        }
        try:
            payload = validate_ticket(payload)
        except ValueError as exc:
            self.set_delivery_state("invalid", str(exc))
            return
        self.submit_ticket_requested.emit(payload)

    def set_delivery_state(self, state: str, message: str) -> None:
        """Preserve failed drafts, prevent duplicate sends, and show persistent results."""
        self._sending = state == "sending"
        if self._sending and self._keyboard is not None:
            self._keyboard.reject()
        self._delivery_status.setText(message)
        tone = "--red-500" if state in ("failed", "invalid") else "--ink-800"
        self._delivery_status.setStyleSheet(f"color: {resolve(tone)};")
        for field in self._fields:
            field.setEnabled(not self._sending)
        self.ticket_button.setEnabled(not self._sending)
        self.ticket_button.setText("Retry ticket" if state == "failed" else "Submit ticket")
        if state == "sent":
            self.subject.clear()
            self.description.clear()
            self._issue = "General support request"
            self._selected_issue.setText("Related issue: " + self._issue)
        if not self._sending and self._deferred_contact is not None:
            contact = self._deferred_contact
            self._deferred_contact = None
            self.set_contact(*contact)
