"""Render the PNG assets that app.qss references as ``url(theme:<name>)``.

QSS sub-controls (combo arrows, checkbox ticks, spin-box buttons) can only show
image files, so the drawn control icons in ``ui/theme/icons.py`` are baked to
small PNGs under ``ui/theme/icons/``. Re-run after changing an icon or colour:

    QT_QPA_PLATFORM=offscreen python development/tools/render_theme_icons.py
"""

import os
import sys

_MAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                     "runtime", "raspberry-pi", "main")
sys.path.insert(0, os.path.abspath(_MAIN))

from PyQt5.QtWidgets import QApplication  # noqa: E402

from ui.theme import resolve  # noqa: E402
from ui.theme.icons import control_pixmap  # noqa: E402

OUT_DIR = os.path.join(os.path.abspath(_MAIN), "ui", "theme", "icons")

# (file name, icon, colour token, pixel size, stroke)
ASSETS = [
    ("chevron-down.png", "chevron-down", "--ink-700", 18, 2.4),
    ("chevron-down-disabled.png", "chevron-down", "--gray-400", 18, 2.4),
    ("check.png", "check", "--white", 18, 3.0),
    ("plus.png", "plus", "--ink-700", 20, 2.4),
    ("plus-disabled.png", "plus", "--gray-400", 20, 2.4),
    ("minus.png", "minus", "--ink-700", 20, 2.4),
    ("minus-disabled.png", "minus", "--gray-400", 20, 2.4),
]


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 - QPixmap needs it
    os.makedirs(OUT_DIR, exist_ok=True)
    for filename, name, token, size, stroke in ASSETS:
        path = os.path.join(OUT_DIR, filename)
        control_pixmap(name, resolve(token), size, stroke).save(path, "PNG")
        print(f"  wrote {os.path.relpath(path)}")


if __name__ == "__main__":
    main()
