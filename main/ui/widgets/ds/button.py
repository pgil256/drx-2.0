"""DSButton — touch-first action button.

Mirrors `Button` in the design system (variant × size). Styling lives in the
global `app.qss` via `variant`/`size` dynamic properties; this class just sets
the properties and keeps them switchable at runtime.

Variants: primary · success · danger · secondary · ghost
Sizes:    sm · md · lg   (md is the default; lg is START/keypad scale)
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QPushButton, QSizePolicy

from ._common import repolish

VARIANTS = ("primary", "success", "danger", "secondary", "ghost")
SIZES = ("sm", "md", "lg")


class DSButton(QPushButton):
    def __init__(self, text="", variant="primary", size="md", full_width=False, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._variant = "primary"
        self._size = "md"
        self.set_variant(variant)
        self.set_size(size)
        self.set_full_width(full_width)

    def set_variant(self, variant):
        self._variant = variant if variant in VARIANTS else "primary"
        self.setProperty("variant", self._variant)
        repolish(self)

    def variant(self):
        return self._variant

    def set_size(self, size):
        # NB: the property is "dsSize", not "size" — QWidget already has a
        # built-in "size" (QSize) Q_PROPERTY, so setProperty("size", ...) is
        # silently rejected and the [size=...] QSS selector would never match.
        self._size = size if size in SIZES else "md"
        self.setProperty("dsSize", self._size)
        repolish(self)

    def size_variant(self):
        return self._size

    def set_full_width(self, full_width):
        self.setSizePolicy(
            QSizePolicy.Expanding if full_width else QSizePolicy.Preferred,
            QSizePolicy.Fixed,
        )

    def changeEvent(self, event):
        super().changeEvent(event)
        # Mirror the DS cursor: not-allowed when disabled, pointer when enabled.
        if event.type() == event.EnabledChange:
            self.setCursor(
                Qt.PointingHandCursor if self.isEnabled() else Qt.ForbiddenCursor
            )
