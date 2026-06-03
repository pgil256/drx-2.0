"""
Dialog module initialization for KneeSpa application.
Makes dialog classes available when importing from ui.dialogs
"""

from ui.dialogs.timer_dialog import TimerDialog
from ui.dialogs.pressure_dialog import PressureDialog 
from ui.dialogs.video_player import VideoPlayer

# Export classes for direct import from ui.dialogs
__all__ = [
    'TimerDialog',
    'PressureDialog',
    'VideoPlayer'
]