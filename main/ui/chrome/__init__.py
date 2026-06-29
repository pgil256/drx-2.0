"""Persistent chrome for the modern KneeSpa DRx interface: the dark top bar and
the left navigation rail. Composed by ``ui/app_shell.py``."""

from .nav_rail import NavRail
from .top_bar import TopBar

__all__ = ["TopBar", "NavRail"]
