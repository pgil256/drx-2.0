"""In-app modal overlays for the modern KneeSpa DRx interface.

LoginModal (DS Keypad PIN entry — replaces login.ui and fixes its missing-0 bug),
AddPinModal (admin provisioning of a new user PIN), and VideoModal (the
demo-video frame the VLC player gets restyled into). All are dim-backdrop
overlays centered over the app shell.
"""

from .add_pin_modal import AddPinModal
from .login_modal import LoginModal
from .video_modal import VideoModal

__all__ = ["LoginModal", "VideoModal", "AddPinModal"]
