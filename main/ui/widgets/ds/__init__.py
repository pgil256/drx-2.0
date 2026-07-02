"""KneeSpa DRx design-system widget library (Phase 1).

PyQt5 ports of the design-system components used by the modern control
interface, mirroring `_ds/.../_ds_bundle.js`. The eight components that the
target build actually renders are implemented here; Gauge and Toggle are
deferred (imported-but-unused in `app/bundle.jsx`).
"""

from .badge import DSBadge
from .button import DSButton
from .card import DSCard
from .keypad import DSKeypad
from .nav_rail_button import DSNavRailButton
from .protocol_button import DSProtocolButton
from .slider import DSSlider
from .stat_readout import DSStatReadout

__all__ = [
    "DSBadge",
    "DSButton",
    "DSCard",
    "DSKeypad",
    "DSNavRailButton",
    "DSProtocolButton",
    "DSSlider",
    "DSStatReadout",
]
