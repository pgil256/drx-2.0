"""Per-screen view modules for the modern KneeSpa DRx interface.

Each screen composes the DS widget library into one page of the design
(`app/bundle.jsx`). Screens are pure view + signal surface — no backend logic;
the controller connects their signals to the Arduino / Protocols layer in
Phase 3. Built in code (not Qt Designer) per the modernization plan.
"""

from .help import HelpScreen
from .home import HomeScreen
from .setup import SetupScreen
from .support import SupportScreen
from .treatment import TreatmentScreen

__all__ = [
    "HomeScreen",
    "SetupScreen",
    "TreatmentScreen",
    "HelpScreen",
    "SupportScreen",
]
