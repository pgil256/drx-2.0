"""Shared helpers for the KneeSpa DRx design-system widgets.

Components mirror the design-system JSX (`_ds/.../_ds_bundle.js`). Two styling
strategies are used, matching how the DS itself is authored:

* **Base controls** (``DSButton`` → ``QPushButton``, the ``QSlider`` inside
  ``DSSlider``) are themed by the global ``app.qss`` via dynamic ``variant`` /
  ``size`` properties.
* **Composite components** (Badge, Card, StatReadout, ProtocolButton,
  NavRailButton, Keypad) self-style from tokens with a per-instance stylesheet,
  keeping each component exact and self-contained.

All colors/sizes come from the design tokens via ``ui.theme.resolve`` — the
single source of truth shared with ``app.qss``.
"""

import os

from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

from ui.theme import resolve

# IBM Plex families (bundled in ui/theme/fonts; Qt falls back via the
# --font-sans/--font-mono stacks if they are ever absent).
SANS = "IBM Plex Sans"
MONO = "IBM Plex Mono"

# Bundled art lives at main/ui/media/images (this file is main/ui/widgets/ds/).
_IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "media",
    "images",
)


def image_path(*parts):
    """Absolute path to a bundled image, e.g. ``image_path('logos', 'knee.png')``."""
    return os.path.join(_IMAGES_DIR, *parts)

_WEIGHTS = {400: QFont.Normal, 500: QFont.Medium, 600: QFont.DemiBold, 700: QFont.Bold}


def px(value):
    """Resolve a token/length to an int pixel count. ``px('--text-lg') -> 24``."""
    if isinstance(value, str) and value.startswith("--"):
        value = resolve(value)
    return int(round(float(str(value).replace("px", "").strip())))


def _font(family, size=None, weight=400, tracking=None):
    f = QFont(family)
    f.setStyleHint(QFont.Monospace if family == MONO else QFont.SansSerif)
    if size is not None:
        f.setPixelSize(px(size))
    f.setWeight(_WEIGHTS.get(weight, QFont.Normal))
    if tracking is not None:
        # tracking is an em fraction (e.g. 0.03 == "0.03em") → percentage spacing.
        f.setLetterSpacing(QFont.PercentageSpacing, 100 + tracking * 100)
    return f


def sans_font(size=None, weight=400, tracking=None):
    return _font(SANS, size, weight, tracking)


def mono_font(size=None, weight=400, tracking=None):
    return _font(MONO, size, weight, tracking)


def repolish(widget):
    """Re-evaluate QSS after a dynamic property change (variant/size/selected)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def drop_shadow(widget, blur=24, dx=0, dy=4, color="#000000", alpha=38):
    """Attach a soft drop shadow (QSS has no box-shadow). Mirrors --shadow-md."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(dx, dy)
    qc = QColor(color)
    qc.setAlpha(alpha)
    effect.setColor(qc)
    widget.setGraphicsEffect(effect)
    return effect
