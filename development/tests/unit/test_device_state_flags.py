"""A1: DeviceState owns the window's device flags and answers from them."""

import pytest

from controllers.device_state import (
    WINDOW_ATTRIBUTES, DeviceState, DeviceStateAttributes,
)

pytestmark = pytest.mark.unit


def ready() -> DeviceState:
    state = DeviceState()
    state.initial_setup_complete = True
    return state


class TestDefaults:
    def test_a_new_state_is_idle_and_not_yet_set_up(self):
        state = DeviceState()
        assert state.protocol_state == "idle"
        assert state.initial_setup_complete is False
        for field in WINDOW_ATTRIBUTES.values():
            if field not in ("protocol_state",):
                assert getattr(state, field) is False, field

    def test_before_the_first_reset_nothing_may_move(self):
        assert DeviceState().can_move() is False


class TestCanMove:
    def test_a_ready_device_may_move(self):
        assert ready().can_move() is True

    @pytest.mark.parametrize("field, value", [
        ("closing", True),
        ("calibration_active", True),
        ("device_maintenance_active", True),
        ("reset_in_progress", True),
        ("initial_setup_complete", False),
        ("protocol_state", "fault"),
    ])
    def test_each_blocking_condition(self, field, value):
        state = ready()
        setattr(state, field, value)
        assert state.can_move() is False

    @pytest.mark.parametrize("state_name", ["idle", "starting", "running", "stopping"])
    def test_only_a_fault_state_blocks(self, state_name):
        state = ready()
        state.protocol_state = state_name
        assert state.can_move() is True

    def test_a_command_in_progress_does_not_block(self):
        """Completing that command is what re-enables the controls."""
        state = ready()
        state.actuator_command_in_progress = True
        assert state.can_move() is True

    def test_reset_and_setup_flags_are_read_by_truthiness(self):
        state = ready()
        state.reset_in_progress = 1
        assert state.can_move() is False
        state.reset_in_progress = 0
        state.initial_setup_complete = 1
        assert state.can_move() is True


class TestCanExit:
    def test_an_idle_device_may_be_left(self):
        state = DeviceState()
        assert state.can_exit() is True
        assert state.busy_reason() is None

    @pytest.mark.parametrize("field, reason", [
        ("device_maintenance_active", "device service"),
        ("calibration_active", "device service"),
        ("reset_in_progress", "reset"),
        ("actuator_command_in_progress", "movement"),
    ])
    def test_busy_work_blocks_leaving(self, field, reason):
        state = DeviceState()
        setattr(state, field, True)
        assert state.can_exit() is False
        assert state.busy_reason() == reason

    def test_busy_flags_must_be_true_not_merely_truthy(self):
        """The exit guard always required `is True`."""
        state = DeviceState()
        state.reset_in_progress = 1
        assert state.can_exit() is True

    def test_a_latched_fault_does_not_block_leaving(self):
        state = DeviceState()
        state.protocol_state = "fault"
        state.physical_stop_active = True
        assert state.can_exit() is True

    def test_the_controls_lock_of_a_latched_fault_does_not_block_leaving(self):
        """A treatment takes the Setup controls and a fault keeps them locked
        for the recovery reset. Nothing is moving, and the reset may never
        succeed, so the lock must not hold the operator in the app."""
        state = DeviceState()
        state.actuator_command_in_progress = True
        state.protocol_state = "fault"
        assert state.busy_reason() is None
        assert state.can_exit() is True

    @pytest.mark.parametrize("state_name", ["idle", "starting", "running", "stopping"])
    def test_a_command_in_progress_blocks_leaving_outside_a_fault(self, state_name):
        state = DeviceState()
        state.actuator_command_in_progress = True
        state.protocol_state = state_name
        assert state.busy_reason() == "movement"

    @pytest.mark.parametrize("field", [
        "device_maintenance_active", "calibration_active", "reset_in_progress",
    ])
    def test_service_and_reset_block_leaving_during_a_fault(self, field):
        state = DeviceState()
        state.protocol_state = "fault"
        setattr(state, field, True)
        assert state.can_exit() is False


class Owner(DeviceStateAttributes):
    pass


class TestWindowAttributes:
    def test_every_window_name_delegates_to_its_field(self):
        owner = Owner()
        for attribute, field in WINDOW_ATTRIBUTES.items():
            setattr(owner, attribute, "sentinel-" + field)
            assert getattr(owner.device_state, field) == "sentinel-" + field
            assert getattr(owner, attribute) == "sentinel-" + field

    def test_writing_the_state_shows_through_the_window_names(self):
        owner = Owner()
        owner.device_state.reset_in_progress = True
        owner.device_state.protocol_state = "running"
        assert owner.reset_in_progress is True
        assert owner.protocol_state == "running"

    def test_the_state_is_created_once_on_first_use(self):
        owner = Owner()
        assert owner.device_state is owner.device_state
        owner._closing = True
        assert owner.device_state.closing is True

    def test_getattr_defaults_still_work(self):
        """The old `getattr(window, name, False) is True` reads keep their meaning."""
        owner = Owner()
        assert getattr(owner, "_physical_stop_active", False) is False
        owner._physical_stop_active = True
        assert getattr(owner, "_physical_stop_active", False) is True

    def test_each_owner_has_its_own_state(self):
        first, second = Owner(), Owner()
        first.reset_in_progress = True
        assert second.reset_in_progress is False


def test_the_window_exposes_its_flags_through_device_state(qtbot):
    """The real window: attribute writes land in its DeviceState."""
    from kneespa import KneeSpa

    assert issubclass(KneeSpa, DeviceStateAttributes)
    for attribute in WINDOW_ATTRIBUTES:
        assert isinstance(getattr(KneeSpa, attribute), property), attribute
