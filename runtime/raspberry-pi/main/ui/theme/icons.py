"""Glyph fallbacks and drawn icons for the KneeSpa DRx modern UI.

The design (`app/bundle.jsx`) uses a handful of Unicode pictographs — jog
triangles ``◀◀ ◀ ▶ ▶▶``, a gapped reset ``⟲``, a close ``✕``, pause bars
``❚❚`` — that **do not exist in the bundled IBM Plex fonts** (verified with
``QFontMetrics.inFont``) and would render as tofu boxes on the offline Pi.

Two strategies cover them:

* :data:`GLYPH` — Plex-safe text substitutes (guillemets, ``↺``, ``×`` …) for
  glyphs that only need to read as a symbol inside a button label.
* :func:`play_icon` / :func:`pause_icon` — crisp, recolorable ``QIcon``s drawn
  with ``QPainter`` for the prominent START / PAUSE / video transport controls,
  where a real triangle/bars pair carries more weight than a substitute glyph.
* :func:`control_icon` — the same drawn treatment for every control glyph
  (jog chevrons, reset, close, backspace, stop, lock …). Text substitutes read
  as punctuation; controls should look like controls.

All of this is font-independent, so the device renders identically regardless of
which fonts happen to be installed.
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

#: Plex-safe text substitutes for design glyphs IBM Plex lacks. Keys are intent
#: names; values render in IBM Plex Sans/Mono (confirmed via QFontMetrics).
GLYPH = {
    "jog_rev_fast": "«",   # «  (design ◀◀)
    "jog_rev": "‹",        # ‹  (design ◀)
    "jog_fwd": "›",        # ›  (design ▶)
    "jog_fwd_fast": "»",   # »  (design ▶▶)
    "reset": "↺",          # ↺  (design ⟲ gapped circle — absent in Plex)
    "close": "×",          # ×  (design ✕ U+2715 — absent)
    "estop": "×",          # ×  (design ⨯ U+2A2F — absent)
    "pause": "‖",          # ‖ — NB absent in Plex; prefer pause_icon()
    "check": "✓",          # ✓  (present in Plex)
    "bullet": "›",         # ›  (design ▸ small triangle — absent)
    "accordion_closed": "+",
    "accordion_open": "×",  # × (design rotates + 45°; we swap the char)
}


def _pixmap(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    return pm


def play_icon(color="#ffffff", size=22):
    """A filled right-pointing play triangle as a recolorable QIcon."""
    pm = _pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    i = size * 0.26
    tri = QPolygonF([
        QPointF(i, i),
        QPointF(size - i, size / 2.0),
        QPointF(i, size - i),
    ])
    p.drawPolygon(tri)
    p.end()
    return QIcon(pm)


def pause_icon(color="#ffffff", size=22):
    """Two vertical bars (pause) as a recolorable QIcon."""
    pm = _pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    bar_w = size * 0.22
    top = size * 0.24
    bottom = size * 0.76
    gap = size * 0.16
    left_x = size / 2.0 - gap / 2.0 - bar_w
    right_x = size / 2.0 + gap / 2.0
    radius = bar_w * 0.4
    p.drawRoundedRect(QRectF(left_x, top, bar_w, bottom - top), radius, radius)
    p.drawRoundedRect(QRectF(right_x, top, bar_w, bottom - top), radius, radius)
    p.end()
    return QIcon(pm)


# ── Nav-rail line icons ──────────────────────────────────────────────────────
# Lucide-style line icons drawn from the exact paths in bundle.jsx's `Icon`
# component (24×24 space). Font-independent and recolorable so the active rail
# item can tint its icon cyan to match its label.

def _line(p, x1, y1, x2, y2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _poly(p, pts):
    p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))


def nav_icon(name, color="#ffffff", size=26):
    """A 24-space Lucide-style line icon as a recolorable QIcon.

    Names: home · setup · protocols · help · support · device · play.
    """
    pm = _pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / 24.0, size / 24.0)
    pen = QPen(QColor(color))
    pen.setWidthF(1.9)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    if name == "home":
        _poly(p, [(3, 10.6), (12, 3.2), (21, 10.6)])
        _poly(p, [(5.4, 9.4), (5.4, 20), (6.4, 21), (17.6, 21), (18.6, 20), (18.6, 9.4)])
        _poly(p, [(9.6, 21), (9.6, 14.8), (14.4, 14.8), (14.4, 21)])
    elif name == "setup":
        for y in (7, 12, 17):
            _line(p, 3, y, 21, y)
        for cx, cy in ((8, 7), (16, 12), (10, 17)):
            p.drawEllipse(QPointF(cx, cy), 2.3, 2.3)
    elif name == "protocols":
        p.drawRoundedRect(QRectF(6, 4, 12, 17), 2, 2)
        p.drawRoundedRect(QRectF(9.2, 2, 5.6, 2.6), 1.3, 1.3)  # clip
        _line(p, 9.5, 9.5, 14.5, 9.5)
        _line(p, 9.5, 13, 14.5, 13)
        _line(p, 9.5, 16.5, 12.5, 16.5)
    elif name == "help":
        p.drawEllipse(QPointF(12, 12), 9.2, 9.2)
        hook = QPainterPath()
        hook.moveTo(9.6, 9.6)
        hook.cubicTo(9.6, 8.0, 11.0, 7.0, 12.6, 7.6)   # up over the top
        hook.cubicTo(14.2, 8.2, 14.0, 10.4, 12.4, 11.2)  # down the right
        hook.cubicTo(11.6, 11.6, 11.4, 12.4, 11.4, 13.4)  # tail down
        p.drawPath(hook)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(11.4, 16.4), 1.0, 1.0)  # dot
    elif name == "support":
        p.drawEllipse(QPointF(12, 12), 9, 9)
        p.drawEllipse(QPointF(12, 12), 3.4, 3.4)
        _line(p, 5.6, 5.6, 9.6, 9.6)
        _line(p, 14.4, 14.4, 18.4, 18.4)
        _line(p, 18.4, 5.6, 14.4, 9.6)
        _line(p, 9.6, 14.4, 5.6, 18.4)
    elif name == "device":
        wrench = QPainterPath()
        wrench.moveTo(14, 3)
        wrench.cubicTo(11, 3, 9, 6, 10, 9)
        wrench.lineTo(3.5, 15.5)
        wrench.cubicTo(1, 18, 5, 22, 7.5, 19.5)
        wrench.lineTo(14, 13)
        wrench.cubicTo(18, 14, 22, 11, 21, 7)
        wrench.lineTo(17.5, 10.5)
        wrench.lineTo(13.5, 6.5)
        wrench.lineTo(17, 3)
        wrench.closeSubpath()
        p.drawPath(wrench)
        p.drawEllipse(QPointF(5.5, 17.5), 0.65, 0.65)
    elif name == "play":
        p.drawEllipse(QPointF(12, 12), 9, 9)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(10, 8.4), QPointF(16.2, 12), QPointF(10, 15.6)]))

    p.end()
    return QIcon(pm)


# ── Control icons ────────────────────────────────────────────────────────────
# Drawn in the same 24-unit space as the rail icons. Each entry is a painter
# routine; ``control_icon`` wraps it in a recolorable QIcon.

CONTROL_ICONS = (
    "chevron-left", "chevron-right", "chevron-up", "chevron-down",
    "chevrons-left", "chevrons-right", "rotate-ccw", "close", "backspace",
    "stop", "lock", "check", "plus", "minus", "alert", "info",
)


def _draw_control(p, name, color):
    fill = QColor(color)
    if name == "chevron-left":
        _poly(p, [(15, 5.5), (8.5, 12), (15, 18.5)])
    elif name == "chevron-right":
        _poly(p, [(9, 5.5), (15.5, 12), (9, 18.5)])
    elif name == "chevron-up":
        _poly(p, [(5.5, 15), (12, 8.5), (18.5, 15)])
    elif name == "chevron-down":
        _poly(p, [(5.5, 9), (12, 15.5), (18.5, 9)])
    elif name == "chevrons-left":
        _poly(p, [(12, 5.5), (5.5, 12), (12, 18.5)])
        _poly(p, [(19, 5.5), (12.5, 12), (19, 18.5)])
    elif name == "chevrons-right":
        _poly(p, [(5, 5.5), (11.5, 12), (5, 18.5)])
        _poly(p, [(12, 5.5), (18.5, 12), (12, 18.5)])
    elif name == "rotate-ccw":
        # 300° arc with an arrowhead at its start (top-left).
        p.drawArc(QRectF(4, 4, 16, 16), 150 * 16, -300 * 16)
        _poly(p, [(3.2, 5.2), (4.9, 9.9), (9.6, 8.3)])
    elif name == "close":
        _line(p, 6, 6, 18, 18)
        _line(p, 18, 6, 6, 18)
    elif name == "backspace":
        body = QPainterPath()
        body.moveTo(9, 5)
        body.lineTo(20, 5)
        body.quadTo(21.5, 5, 21.5, 6.5)
        body.lineTo(21.5, 17.5)
        body.quadTo(21.5, 19, 20, 19)
        body.lineTo(9, 19)
        body.lineTo(2.5, 12)
        body.closeSubpath()
        p.drawPath(body)
        _line(p, 11.5, 9, 17.5, 15)
        _line(p, 17.5, 9, 11.5, 15)
    elif name == "stop":
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
    elif name == "lock":
        p.drawRoundedRect(QRectF(5, 11, 14, 10), 2, 2)
        arc = QPainterPath()
        arc.moveTo(8, 11)
        arc.lineTo(8, 7.5)
        arc.cubicTo(8, 2.5, 16, 2.5, 16, 7.5)
        arc.lineTo(16, 11)
        p.drawPath(arc)
    elif name == "check":
        _poly(p, [(5, 12.5), (10, 17.5), (19.5, 7)])
    elif name == "plus":
        _line(p, 12, 5, 12, 19)
        _line(p, 5, 12, 19, 12)
    elif name == "minus":
        _line(p, 5, 12, 19, 12)
    elif name == "alert":
        tri = QPainterPath()
        tri.moveTo(12, 3.5)
        tri.lineTo(21.5, 20)
        tri.lineTo(2.5, 20)
        tri.closeSubpath()
        p.drawPath(tri)
        _line(p, 12, 9.5, 12, 14)
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(12, 17), 1.2, 1.2)
    elif name == "info":
        p.drawEllipse(QPointF(12, 12), 9, 9)
        _line(p, 12, 11, 12, 16.5)
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(12, 7.8), 1.2, 1.2)
    else:
        raise ValueError(f"Unknown control icon {name!r}")


def control_pixmap(name, color="#ffffff", size=24, stroke=2.0):
    """Render a control icon to a transparent pixmap (also used for QSS assets)."""
    pm = _pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / 24.0, size / 24.0)
    pen = QPen(QColor(color))
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    _draw_control(p, name, color)
    p.end()
    return pm


def control_icon(name, color="#ffffff", size=24, stroke=2.0, disabled_color=None):
    """A recolorable control icon; ``disabled_color`` adds a Disabled-mode pixmap."""
    icon = QIcon(control_pixmap(name, color, size, stroke))
    if disabled_color is not None:
        icon.addPixmap(control_pixmap(name, disabled_color, size, stroke), QIcon.Disabled)
    return icon
