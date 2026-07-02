"""Theme helpers for the KneeSpa DRx modern UI.

Responsibilities:
  * ``resolve()`` / ``qss()`` — expand CSS ``var(--token)`` references against
    :data:`ui.theme.tokens.TOKENS` (Qt's QSS has no ``var()``).
  * ``load_app_qss()`` — read ``app.qss`` and return it fully resolved.
  * ``load_fonts()`` — register any bundled ``.ttf``/``.otf`` in ``fonts/`` with
    Qt (so the offline Pi can use IBM Plex without a network).
  * ``apply_theme(app)`` — the Phase 0 entry point: load fonts, set the base
    application font, and install the global stylesheet.

PyQt5 is imported lazily inside the Qt-only functions so this module (and the
pure ``resolve``/``qss`` helpers) can be imported in unit tests without Qt.
"""

import os
import re

from .tokens import TOKENS

_THEME_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_QSS_PATH = os.path.join(_THEME_DIR, "app.qss")
_FONT_DIR = os.path.join(_THEME_DIR, "fonts")

_VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)")
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def strip_comments(text):
    """Remove ``/* ... */`` comments.

    Qt ignores QSS comments, but stripping them keeps the rendered stylesheet
    clean and lets source comments mention ``var(...)`` as documentation without
    that prose being treated as a rule.
    """
    return _COMMENT_RE.sub("", text)


def _resolve_name(name, _seen):
    """Fully resolve a single ``--token`` to a literal, following var() chains."""
    if name in _seen:
        raise ValueError(f"Cyclic token reference involving {name}")
    raw = TOKENS.get(name)
    if raw is None:
        # Unknown token: leave the original var(...) text so it's visible.
        return None
    return _resolve_text(raw, _seen | {name})


def _resolve_text(text, _seen):
    """Replace every ``var(--x)`` in *text* with its resolved literal."""
    def _sub(match):
        resolved = _resolve_name(match.group(1), _seen)
        return resolved if resolved is not None else match.group(0)

    return _VAR_RE.sub(_sub, text)


def resolve(token):
    """Resolve a token name (``"--color-primary"``) or any string containing
    ``var(--x)`` to its literal value.

    >>> resolve("--color-primary")
    '#3498db'
    >>> resolve("2px solid var(--gray-400)")
    '2px solid #bdc3c7'
    """
    if token in TOKENS:
        return _resolve_text(TOKENS[token], {token})
    return _resolve_text(token, set())


def qss(template):
    """Render a QSS template: drop comments, then resolve every ``var(--x)``."""
    return _resolve_text(strip_comments(template), set())


def load_app_qss():
    """Return the global ``app.qss`` stylesheet, fully resolved."""
    with open(_APP_QSS_PATH, encoding="utf-8") as fh:
        return qss(fh.read())


def load_fonts():
    """Register bundled fonts with Qt.

    Scans ``ui/theme/fonts`` for ``.ttf``/``.otf`` files and registers each via
    ``QFontDatabase.addApplicationFont``. Returns the list of font families that
    loaded (empty if the directory is missing or holds no usable fonts — in that
    case the ``--font-sans`` fallback stack, e.g. Segoe UI, is used instead).
    Never raises.
    """
    from PyQt5.QtGui import QFontDatabase

    families = []
    if not os.path.isdir(_FONT_DIR):
        return families
    for filename in sorted(os.listdir(_FONT_DIR)):
        if filename.lower().endswith((".ttf", ".otf")):
            font_id = QFontDatabase.addApplicationFont(
                os.path.join(_FONT_DIR, filename)
            )
            if font_id != -1:
                families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return families


def apply_theme(app, set_base_font=True):
    """Apply the KneeSpa DRx theme to a ``QApplication``.

    Call this after ``app.setStyle("Fusion")`` in ``main()``. It:
      1. registers any bundled fonts,
      2. sets the base application font to IBM Plex Sans **iff** it loaded
         (otherwise leaves Qt's default so the QSS ``--font-sans`` fallback
         applies — avoids forcing a wrong family on the Pi),
      3. installs the resolved global stylesheet.

    Returns a small dict describing what happened (handy for logs/tests).
    Designed to be safe: a stylesheet/font problem must never stop the device
    app from launching, so callers should still wrap this defensively.
    """
    from PyQt5.QtGui import QFont

    families = load_fonts()
    plex_loaded = any("Plex Sans" in fam for fam in families)

    if set_base_font and plex_loaded:
        base = QFont("IBM Plex Sans")
        base.setPixelSize(int(resolve("--text-base").replace("px", "")))  # 17px
        app.setFont(base)

    app.setStyleSheet(load_app_qss())

    return {"font_families": families, "plex_loaded": plex_loaded}
