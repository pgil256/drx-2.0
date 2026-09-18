# ui/widgets/loading_spinner.py
import os
from typing import Union, Optional
from PyQt5.QtCore    import Qt, QEvent, QSize
from PyQt5.QtGui     import QMovie
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout

SPINNER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "media", "images", "spinners", "loading-spinner.gif",
)


class LoadingSpinner(QWidget):
    """
    Transparent, click-through overlay that shows a looping GIF.
    Call .show() / .hide() as usual.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        size: Union[int, QSize] = 200,          # bigger default
        speed_pct: int = 500                    # 100 = normal, >100 faster
    ) -> None:
        super().__init__(parent, Qt.SubWindow | Qt.FramelessWindowHint)
        print(f"LoadingSpinner: Initializing spinner (size={size}, speed={speed_pct}%)")

        # --- transparent & mouse-through ---
        for w in (self,):                       # QWidget itself
            w.setAttribute(Qt.WA_TranslucentBackground, True)
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # Resize with parent
        if parent is not None:
            self.resize(parent.size())
            parent.installEventFilter(self)

        # --- GIF ---
        self._movie = QMovie(SPINNER_PATH, parent=self)
        if isinstance(size, int):
            size = QSize(size, size)
        self._movie.setScaledSize(size)
        self._movie.setSpeed(speed_pct)         # <-- faster/slower

        label = QLabel(self)
        label.setMovie(self._movie)
        label.setAlignment(Qt.AlignCenter)
        label.setAttribute(Qt.WA_TranslucentBackground, True)
        label.setStyleSheet("background: transparent;")  # belt & suspenders

        # Layout
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        lay.addWidget(label, alignment=Qt.AlignCenter)
        lay.addStretch(1)
        lay.setContentsMargins(0, 0, 0, 0)

        self.hide()
        print("LoadingSpinner: Initialization complete")

    # ------------------------
    # public control
    # ------------------------
    def show(self) -> None:
        print("LoadingSpinner: Showing spinner")
        if self._movie.state() != QMovie.Running:
            self._movie.start()
            print("LoadingSpinner: Animation started")
        super().show()
        self.raise_()

    def hide(self) -> None:
        print("LoadingSpinner: Hiding spinner")
        if self._movie.state() == QMovie.Running:
            self._movie.stop()
            print("LoadingSpinner: Animation stopped")
        super().hide()

    # ------------------------
    # keep overlay sized
    # ------------------------
    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() == QEvent.Resize:
            self.resize(watched.size())
        return super().eventFilter(watched, event)
