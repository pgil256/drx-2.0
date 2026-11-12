"""Touchscreen USB watchdog: when it acts, on which device, and what it writes."""

import importlib.util
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "devices/maintenance/raspberry-pi/touch-watchdog/touch_watchdog.py"
spec = importlib.util.spec_from_file_location("touch_watchdog", str(SCRIPT))
watchdog_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog_module)

pytestmark = pytest.mark.unit

TOUCH = ("27c0", "0859")
HUB = ("1a86", "8095")
MEGA = ("2341", "0042")


def descriptors(configuration_value: int = 1) -> bytes:
    """An 18-byte device descriptor followed by one configuration descriptor."""
    device = bytes([18, 1]) + bytes(16)
    configuration = bytes([9, 2, 0x5B, 0, 3, configuration_value, 0, 0x80, 100])
    return device + configuration


class FakeUsb:
    """A sysfs-shaped directory tree under tmp_path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.devices = root / "devices"
        self.hub_driver = root / "drivers" / "hub"
        self.devices.mkdir(parents=True)
        self.hub_driver.mkdir(parents=True)

    def add(self, name: str, usb_id, configured: bool = True, bound: bool = True,
            configuration_value: int = 1) -> Path:
        device = self.devices / name
        device.mkdir()
        (device / "idVendor").write_text(usb_id[0] + "\n")
        (device / "idProduct").write_text(usb_id[1] + "\n")
        (device / "bConfigurationValue").write_text(
            "%d\n" % configuration_value if configured else "\n")
        (device / "descriptors").write_bytes(descriptors(configuration_value))
        # On the Pi the interface folder is "<name>:1.0"; Windows cannot create
        # that name, and the watchdog finds interfaces by content, not by name.
        interface = device / (name + "_1.0")
        interface.mkdir()
        (interface / "bInterfaceNumber").write_text("00\n")
        if configured and bound:
            (interface / "driver").mkdir()  # a symlink on the Pi; presence is what counts
        return device

    def written(self, relative: str) -> str:
        path = self.root / relative
        return path.read_text() if path.is_file() else ""


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def usb(tmp_path: Path) -> FakeUsb:
    return FakeUsb(tmp_path / "usb")


def make(usb: FakeUsb, clock: Clock, log: List[str], dry_run: bool = False):
    tree = watchdog_module.UsbTree(str(usb.root), TOUCH, HUB, sleep=lambda seconds: None)
    return watchdog_module.Watchdog(tree, clock=clock, log=log.append, dry_run=dry_run)


def run_for(watchdog, clock: Clock, seconds: float, poll: float = 2.0) -> None:
    """Poll at the service's cadence for a stretch of fake time."""
    end = clock.now + seconds
    while clock.now <= end:
        watchdog.step()
        clock.now += poll


@pytest.mark.parametrize("text, expected", [
    ("27c0:0859", ("27c0", "0859")),
    (" 1A86:8095\n", ("1a86", "8095")),
])
def test_parse_usb_id_accepts_vendor_product(text, expected):
    assert watchdog_module.parse_usb_id(text) == expected


@pytest.mark.parametrize("text", ["", "27c0", "27c0:85", "27c00859", "zzzz:0859"])
def test_parse_usb_id_rejects_malformed(text):
    with pytest.raises(ValueError):
        watchdog_module.parse_usb_id(text)


def test_state_healthy_when_configured_and_bound(usb):
    usb.add("1-1.1", HUB)
    usb.add("1-1.1.1", TOUCH)
    tree = watchdog_module.UsbTree(str(usb.root), TOUCH, HUB)
    assert tree.state() == watchdog_module.HEALTHY


def test_state_unconfigured_when_kernel_gave_up(usb):
    usb.add("1-1.1", HUB)
    usb.add("1-1.1.1", TOUCH, configured=False)
    tree = watchdog_module.UsbTree(str(usb.root), TOUCH, HUB)
    assert tree.state() == watchdog_module.UNCONFIGURED


def test_state_unconfigured_when_no_driver_claimed_it(usb):
    usb.add("1-1.1.1", TOUCH, bound=False)
    tree = watchdog_module.UsbTree(str(usb.root), TOUCH, HUB)
    assert tree.state() == watchdog_module.UNCONFIGURED


def test_state_missing_when_only_the_monitor_hub_is_there(usb):
    usb.add("1-1.1", HUB)
    usb.add("1-1.4", MEGA)
    tree = watchdog_module.UsbTree(str(usb.root), TOUCH, HUB)
    assert tree.state() == watchdog_module.MISSING


def test_state_no_monitor_when_neither_is_there(usb):
    usb.add("1-1.4", MEGA)
    tree = watchdog_module.UsbTree(str(usb.root), TOUCH, HUB)
    assert tree.state() == watchdog_module.NO_MONITOR


def test_healthy_touchscreen_is_left_alone(usb):
    usb.add("1-1.1", HUB)
    touch = usb.add("1-1.1.1", TOUCH)
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 600)
    assert (touch / "bConfigurationValue").read_text() == "1\n"
    assert usb.written("drivers/hub/unbind") == ""
    assert log == ["touchscreen is working"]


def test_no_action_inside_the_grace_period(usb):
    usb.add("1-1.1", HUB)
    touch = usb.add("1-1.1.1", TOUCH, configured=False)
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 4)
    assert (touch / "bConfigurationValue").read_text() == "\n"
    assert usb.written("drivers/hub/bind") == ""


def test_unconfigured_touchscreen_gets_its_configuration_selected(usb):
    usb.add("1-1.1", HUB)
    touch = usb.add("1-1.1.1", TOUCH, configured=False)
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 8)
    assert (touch / "bConfigurationValue").read_text() == "1"
    assert usb.written("drivers/hub/bind") == ""
    assert "attempt 1: selecting the configuration of touchscreen 1-1.1.1" in log


def test_configuration_number_comes_from_the_descriptors(usb):
    touch = usb.add("1-1.1.1", TOUCH, configured=False, configuration_value=3)
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 8)
    assert (touch / "bConfigurationValue").read_text() == "3"


def test_configuration_number_defaults_to_one_without_descriptors(usb):
    touch = usb.add("1-1.1.1", TOUCH, configured=False)
    (touch / "descriptors").unlink()
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 8)
    assert (touch / "bConfigurationValue").read_text() == "1"


def test_second_attempt_reprobes_the_monitor_hub(usb):
    usb.add("1-1.1", HUB)
    # Stays unbound whatever is written, like a controller that keeps failing.
    usb.add("1-1.1.1", TOUCH, bound=False)
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 14)
    assert usb.written("drivers/hub/unbind") == "1-1.1_1.0"
    assert usb.written("drivers/hub/bind") == "1-1.1_1.0"
    assert "attempt 2: re-probing monitor hub 1-1.1" in log


def test_missing_touchscreen_reprobes_the_hub_on_the_first_attempt(usb):
    usb.add("1-1.1", HUB)
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 8)
    assert usb.written("drivers/hub/bind") == "1-1.1_1.0"
    assert "attempt 1: re-probing monitor hub 1-1.1" in log


def test_without_a_monitor_hub_it_keeps_trying_the_touchscreen_itself(usb):
    touch = usb.add("1-1.1.1", TOUCH, bound=False)
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 30)
    assert usb.written("drivers/hub/bind") == ""
    assert (touch / "bConfigurationValue").read_text() == "1"
    assert "attempt 2: selecting the configuration of touchscreen 1-1.1.1" in log


def test_attempts_back_off(usb):
    usb.add("1-1.1", HUB)
    clock, log = Clock(), []
    watchdog = make(usb, clock, log)
    started, attempt_times = clock.now, []
    while len(attempt_times) < 5:
        before = watchdog.attempts
        watchdog.step()
        if watchdog.attempts != before:
            attempt_times.append(clock.now - started)
        clock.now += 1.0
    # Grace of 6 s, then gaps of 5, 10, 20 and 40 s.
    assert attempt_times == [6.0, 11.0, 21.0, 41.0, 81.0]


def test_retry_gap_is_capped(usb):
    usb.add("1-1.1", HUB)
    clock, log = Clock(), []
    watchdog = make(usb, clock, log)
    run_for(watchdog, clock, 3600)
    before = watchdog.attempts
    run_for(watchdog, clock, 3600)
    # About one attempt per 300 s once the cap is reached.
    assert 10 <= watchdog.attempts - before <= 13


def test_recovery_is_reported_and_resets_the_attempt_count(usb):
    usb.add("1-1.1", HUB)
    clock, log = Clock(), []
    watchdog = make(usb, clock, log)
    run_for(watchdog, clock, 8)
    assert watchdog.attempts == 1
    usb.add("1-1.1.1", TOUCH)  # the re-probe found the controller
    watchdog.step()
    assert log[-1] == "touchscreen is working again after 1 recovery attempt(s)"
    assert watchdog.attempts == 0


def test_brief_dropouts_never_trigger_recovery(usb):
    usb.add("1-1.1", HUB)
    touch = usb.add("1-1.1.1", TOUCH)
    driver = usb.devices / "1-1.1.1" / "1-1.1.1_1.0" / "driver"
    clock, log = Clock(), []
    watchdog = make(usb, clock, log)
    for _ in range(50):  # down 4 s, up 2 s, over and over
        driver.rmdir()
        run_for(watchdog, clock, 2)
        driver.mkdir()
        run_for(watchdog, clock, 0)
    assert usb.written("drivers/hub/bind") == ""
    assert (touch / "bConfigurationValue").read_text() == "1\n"
    assert not any(line.startswith("attempt") for line in log)


def test_unplugged_monitor_is_never_acted_on(usb):
    mega = usb.add("1-1.4", MEGA, configured=False)
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 3600)
    assert log == ["no monitor hub or touchscreen on USB; nothing to recover"]
    assert (mega / "bConfigurationValue").read_text() == "\n"
    assert usb.written("drivers/hub/bind") == ""


def test_other_devices_are_never_written_to(usb):
    usb.add("1-1", ("2109", "3431"))
    mega = usb.add("1-1.4", MEGA, configured=False)
    usb.add("1-1.1", HUB)
    usb.add("1-1.1.1", TOUCH, bound=False)
    clock, log = Clock(), []
    run_for(make(usb, clock, log), clock, 3600)
    assert (mega / "bConfigurationValue").read_text() == "\n"
    assert usb.written("drivers/hub/unbind") == "1-1.1_1.0"
    assert usb.written("drivers/hub/bind") == "1-1.1_1.0"


def test_dry_run_writes_nothing(usb):
    usb.add("1-1.1", HUB)
    touch = usb.add("1-1.1.1", TOUCH, configured=False)
    clock, log = Clock(), []
    run_for(make(usb, clock, log, dry_run=True), clock, 60)
    assert (touch / "bConfigurationValue").read_text() == "\n"
    assert usb.written("drivers/hub/bind") == ""
    assert any("would be selecting the configuration" in line for line in log)
    assert any("would be re-probing monitor hub" in line for line in log)


def test_a_failed_write_is_logged_and_retried(usb):
    touch = usb.add("1-1.1.1", TOUCH, configured=False)
    (touch / "bConfigurationValue").unlink()
    (touch / "bConfigurationValue").mkdir()  # opening it for writing now fails
    clock, log = Clock(), []
    watchdog = make(usb, clock, log)
    run_for(watchdog, clock, 20)
    assert any(line.startswith("attempt 1: failed: ") for line in log)
    assert watchdog.attempts >= 2


@pytest.mark.parametrize("configured, expected_code, expected_word", [
    (True, 0, "healthy"),
    (False, 1, "unconfigured"),
])
def test_status_command(usb, capsys, configured, expected_code, expected_word):
    usb.add("1-1.1", HUB)
    usb.add("1-1.1.1", TOUCH, configured=configured)
    code = watchdog_module.main(["status", "--usb-root", str(usb.root)])
    output = capsys.readouterr().out
    assert code == expected_code
    assert output.startswith(expected_word)
    assert "touchscreen=1-1.1.1" in output and "monitor-hub=1-1.1" in output
