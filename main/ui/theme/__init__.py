"""KneeSpa DRx modern UI theme.

Phase 0 foundation: design tokens, a ``var(--x)`` resolver, the global QSS
stylesheet, and bundled-font loading.

Typical use in ``main()`` (after ``app.setStyle("Fusion")``)::

    from ui.theme import apply_theme
    apply_theme(app)
"""

from .tokens import TOKENS
from .qss import apply_theme, load_app_qss, load_fonts, qss, resolve
from .icons import GLYPH, nav_icon, pause_icon, play_icon

__all__ = [
    "TOKENS",
    "apply_theme",
    "load_app_qss",
    "load_fonts",
    "qss",
    "resolve",
    "GLYPH",
    "play_icon",
    "pause_icon",
    "nav_icon",
]
