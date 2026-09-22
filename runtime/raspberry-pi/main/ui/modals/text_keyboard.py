"""Touch text entry for support requests, including email and punctuation."""

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ui.widgets.ds import DSButton
from ui.widgets.ds._common import sans_font


class TextKeyboard(QDialog):
    """Stage text until Done; Cancel preserves the original field contents."""

    def __init__(self, title: str, value: str, limit: int, multiline: bool = False,
                 parent: Optional[QWidget] = None, secret: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setFixedWidth(880)
        self.limit = limit
        self.multiline = multiline
        self._letters = []
        self._uppercase = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setFont(sans_font(size="--text-lg", weight=600))
        layout.addWidget(heading)
        self.editor = QPlainTextEdit() if multiline else QLineEdit()
        self.editor.setAccessibleName(title)
        self.editor.setFont(sans_font(size="--text-md"))
        self.editor.setFixedHeight(112 if multiline else 52)
        if multiline:
            self.editor.setPlainText(value)
        else:
            self.editor.setMaxLength(limit)
            self.editor.setText(value)
            if secret:
                self.editor.setEchoMode(QLineEdit.Password)
                self.editor.setInputMethodHints(Qt.ImhSensitiveData | Qt.ImhNoPredictiveText)
            self.editor.returnPressed.connect(self.accept)
        layout.addWidget(self.editor)
        self.count = QLabel()
        self.count.setFont(sans_font(size="--text-sm"))
        layout.addWidget(self.count)
        for letters in ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm", "@._-+/?!,:'"):
            row = QHBoxLayout()
            row.setSpacing(6)
            for letter in letters:
                key = self._button(letter)
                key.clicked.connect(lambda _checked, button=key: self._insert(button.text()))
                row.addWidget(key)
                if letter.isalpha():
                    self._letters.append(key)
            layout.addLayout(row)
        actions = QHBoxLayout()
        for title, action in (
            ("Shift", self._shift), ("Space", lambda: self._insert(" ")),
            ("Backspace", self._backspace), ("Cancel", self.reject),
        ):
            key = self._button(title)
            key.clicked.connect(action)
            actions.addWidget(key)
        if multiline:
            newline = self._button("New line")
            newline.clicked.connect(lambda: self._insert("\n"))
            actions.addWidget(newline)
        self.done_button = self._button("Done")
        self.done_button.set_variant("primary")
        self.done_button.clicked.connect(self.accept)
        actions.addWidget(self.done_button)
        layout.addLayout(actions)
        self.editor.textChanged.connect(self._update_count)
        self._update_count()

    @staticmethod
    def _button(title: str) -> DSButton:
        button = DSButton(title, variant="secondary", size="sm")
        button.setMinimumSize(48, 48)
        button.setAutoDefault(False)
        button.setFocusPolicy(Qt.NoFocus)
        return button

    def value(self) -> str:
        return self.editor.toPlainText() if self.multiline else self.editor.text()

    def _insert(self, text: str) -> None:
        if self.multiline:
            self.editor.insertPlainText(text)
        else:
            self.editor.insert(text)

    def _backspace(self) -> None:
        if self.multiline:
            cursor = self.editor.textCursor()
            cursor.deletePreviousChar()
            self.editor.setTextCursor(cursor)
        else:
            self.editor.backspace()

    def _shift(self) -> None:
        self._uppercase = not self._uppercase
        for button in self._letters:
            text = button.text()
            button.setText(text.upper() if self._uppercase else text.lower())

    def _update_count(self) -> None:
        count = len(self.value())
        self.count.setText(f"{count:,} / {self.limit:,} characters")
        self.done_button.setEnabled(count <= self.limit)

    def accept(self) -> None:
        if len(self.value()) <= self.limit:
            super().accept()
