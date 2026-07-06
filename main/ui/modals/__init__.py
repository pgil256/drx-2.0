"""In-app modal overlays for the modern KneeSpa DRx interface.

LoginModal (DS Keypad PIN entry — replaces login.ui and fixes its missing-0 bug)
and VideoModal (the demo-video frame the VLC player gets restyled into). Both
are dim-backdrop overlays centered over the app shell.
"""

from .login_modal import LoginModal
from .video_modal import VideoModal

__all__ = ["LoginModal", "VideoModal"]
