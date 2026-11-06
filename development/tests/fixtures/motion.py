"""A real MotionController with a fake for every collaborator (checklist A3).

``make_motion()`` returns the controller; its fakes hang off it:

- ``motion.arduino``: ``fixtures.protocols.make_arduino()`` (``send`` returns True);
- ``motion.config``: a ``Configuration`` with the default marks, calibrated;
- ``motion.state``: a ``DeviceState`` after a successful reset;
- ``motion.view``: a ``MagicMock`` limited to ``SetupView`` (``row_value`` is 0);
- ``motion.leg``: a ``MagicMock`` leg-length controller that is not moving;
- ``motion.logger``: a ``MagicMock``.

``mock_controls=True`` replaces the enable and disable methods with mocks, for
tests of one handler that only check whether it unlocks the controls.
"""

import threading
from unittest.mock import MagicMock

from config.config import Configuration
from controllers.device_state import DeviceState
from controllers.motion_controller import MotionController, SetupView
from fixtures.protocols import make_arduino


def make_config() -> Configuration:
    """The default marks, treated as a calibrated device."""
    config = Configuration()
    config._set_default_a_marks()
    config._set_default_b_marks()
    config._set_default_c_marks()
    config.marks_valid = True
    config.scale_calibrated = True
    config.axial_service_calibrated = False
    return config


def make_view() -> MagicMock:
    view = MagicMock(spec_set=SetupView)
    view.row_value.return_value = 0
    return view


def make_motion(*, config=None, arduino=None, view=None, state=None, leg=None,
                protocol_running=False, mock_controls=False, **positions) -> MotionController:
    """``positions``: ``axial``, ``horizontal`` and ``lateral`` start values."""
    config = make_config() if config is None else config
    arduino = make_arduino() if arduino is None else arduino
    if state is None:
        state = DeviceState()
        state.initial_setup_complete = True
    if leg is None:
        leg = MagicMock()
        leg.active = False
    motion = MotionController(
        lambda: arduino, lambda: config, state, make_view() if view is None else view,
        logger=MagicMock(), leg=lambda: leg, done_event=threading.Event(),
        protocol_running=lambda: protocol_running, release_leg_gpio=MagicMock(),
    )
    for axis in ("axial", "horizontal", "lateral"):
        if axis in positions:
            setattr(motion, f"{axis}_flexion_position", positions.pop(axis))
    if positions:
        raise TypeError(f"unknown make_motion options: {sorted(positions)}")
    if mock_controls:
        motion.enable_actuator_controls = MagicMock()
        motion.disable_actuator_controls = MagicMock()
    return motion
