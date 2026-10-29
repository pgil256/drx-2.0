"""Boot-time legacy/new chooser: images, firmware decisions and the touch flow."""

import importlib.util
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "devices/maintenance/raspberry-pi/version-chooser"
TEMPLATE = ROOT / "devices/templates/raspberry-pi/version-chooser.cfg.example"
spec = importlib.util.spec_from_file_location("version_chooser", str(FOLDER / "version_chooser.py"))
chooser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chooser)

APP = bytes(range(256)) * 4 + b"\x0c\x94"


@pytest.fixture
def settings(tmp_path: Path) -> "chooser.Settings":
    state = tmp_path / "state"
    (state / "version-chooser").mkdir(parents=True)
    text = TEMPLATE.read_text(encoding="utf-8").replace("command =\ndirectory =\n", "command = python3 'old app.py'\n"
                        "directory = {}\n".format(tmp_path), 1)
    text = text.replace("directory = /home/pi/drx", "directory = {}".format(tmp_path))
    (state / "version-chooser/versions.cfg").write_text(text, encoding="utf-8")
    return chooser.Settings(state)


def hex_file(path: Path, data: bytes) -> Path:
    chooser.write_hex(data, path)
    return path


class Board:
    """Fake avrdude: verify compares bytes with what the Mega holds."""

    def __init__(self, content: bytes, answers: bool = True, writes: bool = True) -> None:
        self.content, self.answers, self.writes = content, answers, writes
        self.operations: List[str] = []

    def __call__(self, command: List[str], timeout: int, log: Path) -> int:
        assert command[:1] == ["avrdude"] and "-V" not in command and "-F" not in command
        operation = command[command.index("-U") + 1]
        action, path = operation[6], Path(operation[8:-2])
        self.operations.append(action)
        if not self.answers:
            return 1
        if action == "v":
            return 0 if path.read_bytes() == self.content else 1
        if action == "r":
            path.write_text("full flash backup\n")
            return 0
        if not self.writes:
            return 1
        self.content = path.read_bytes()
        return 0


@pytest.fixture
def devices(settings: "chooser.Settings", tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Register both images and replace every host and USB check."""
    chooser.register(settings, "legacy", hex_file(tmp_path / "legacy.hex", b"\x01" * 40))
    chooser.register(settings, "new", hex_file(tmp_path / "new.hex", APP))
    monkeypatch.setattr(chooser.Session, "acquire", lambda self: None)
    monkeypatch.setattr(chooser, "find_port", lambda configured: "/dev/ttyACM0")
    monkeypatch.setattr(chooser, "find_avrdude", lambda found: ("avrdude", "avrdude.conf"))
    monkeypatch.setattr(chooser, "port_in_use", lambda ports: False)
    images = {version: settings.image(version).read_bytes() for version in chooser.VERSIONS}
    return SimpleNamespace(settings=settings, images=images)


def test_hex_round_trip_spans_extended_addresses(tmp_path: Path) -> None:
    data = APP + b"\xff" * (0x10000 - len(APP)) + b"\x42" * 3
    image, end, bootloader = chooser.read_hex(hex_file(tmp_path / "a.hex", data))
    assert bytes(image[:end]) == data and not bootloader
    assert ":020000040001F9" in (tmp_path / "a.hex").read_text()


@pytest.mark.parametrize("text", [
    ":0200000001FF\n:00000001FF\n",          # bad checksum
    ":020000000102FB\n",                      # no end-of-file record
    ":020001000102FA\n:00000001FF\n",         # nothing at address 0
    "garbage\n",
])
def test_invalid_hex_is_rejected(tmp_path: Path, text: str) -> None:
    (tmp_path / "bad.hex").write_text(text)
    with pytest.raises(chooser.ChooserError, match="not a usable"):
        chooser.read_hex(tmp_path / "bad.hex")


def test_compiled_image_is_registered_unchanged(settings: "chooser.Settings",
                                                tmp_path: Path) -> None:
    source = hex_file(tmp_path / "firmware.hex", APP)
    message = chooser.register(settings, "new", source)
    assert settings.image("new").read_bytes() == source.read_bytes()
    assert chooser.sha256(source) in settings.checksum_file("new").read_text()
    assert "unchanged" in message
    assert settings.checked_image("new") == settings.image("new")


def test_flash_backup_loses_bootloader_and_blank_space(settings: "chooser.Settings",
                                                       tmp_path: Path) -> None:
    dump = bytearray(b"\xff" * chooser.FLASH_BYTES)
    dump[:len(APP)] = APP
    dump[chooser.BOOTLOADER_START:chooser.BOOTLOADER_START + 4] = b"\x0d\x94\x00\x00"
    message = chooser.register(settings, "legacy", hex_file(tmp_path / "previous.hex", dump))
    image, end, bootloader = chooser.read_hex(settings.image("legacy"))
    assert end == len(APP) and bytes(image[:end]) == APP and not bootloader
    assert "bootloader" in message


def test_same_image_cannot_be_both_versions(settings: "chooser.Settings",
                                            tmp_path: Path) -> None:
    source = hex_file(tmp_path / "firmware.hex", APP)
    chooser.register(settings, "new", source)
    with pytest.raises(chooser.ChooserError, match="already registered"):
        chooser.register(settings, "legacy", source)
    assert not settings.image("legacy").exists()


def test_changed_image_is_refused(devices: SimpleNamespace) -> None:
    image = devices.settings.image("legacy")
    image.write_text(image.read_text().replace("01", "02", 1))
    with pytest.raises(chooser.ChooserError, match="changed or is damaged"):
        devices.settings.checked_image("legacy")


def test_missing_image_and_command_are_setup_errors(settings: "chooser.Settings") -> None:
    with pytest.raises(chooser.ChooserError, match="register new"):
        settings.checked_image("new")
    settings.commands["legacy"] = []
    with pytest.raises(chooser.ChooserError, match="command"):
        settings.launch_command("legacy")
    assert settings.commands["new"][-1].endswith("launch_kneespa.sh")


def test_settings_require_every_section(tmp_path: Path) -> None:
    root = tmp_path / "version-chooser"
    root.mkdir()
    (root / "versions.cfg").write_text("[chooser]\ntimeout = soon\n[legacy]\n[new]\n")
    with pytest.raises(chooser.ChooserError, match="whole number"):
        chooser.Settings(tmp_path)
    (root / "versions.cfg").write_text("[chooser]\n[new]\n")
    with pytest.raises(chooser.ChooserError, match=r"\[legacy\]"):
        chooser.Settings(tmp_path)


def test_matching_firmware_starts_without_writing(devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"])
    session = chooser.Session(devices.settings, board)
    assert session.check("new") == "ready"
    assert board.operations == ["v"]
    assert not list((devices.settings.state / "firmware").iterdir())
    assert session.finish("new")[0][-1].endswith("launch_kneespa.sh")
    assert devices.settings.last_choice() == "new"


def test_other_version_is_switched_and_verified(devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"])
    session = chooser.Session(devices.settings, board)
    assert session.check("legacy") == "switch"
    assert board.operations == ["v", "v"]
    session.switch("legacy")
    assert board.content == devices.images["legacy"]
    assert board.operations[2:] == ["w", "v"]
    assert session.finish("legacy") == (["python3", "old app.py"],
                                        devices.settings.directories["legacy"])


def test_unknown_firmware_is_backed_up_before_any_write(devices: SimpleNamespace) -> None:
    board = Board(b"firmware from a release")
    session = chooser.Session(devices.settings, board)
    assert session.check("new") == "unknown"
    assert board.operations == ["v", "v", "r"]
    assert (session.record / "previous.hex").read_text() == "full flash backup\n"


def test_silent_board_is_never_written(devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"], answers=False)
    session = chooser.Session(devices.settings, board)
    with pytest.raises(chooser.ChooserError, match="did not answer"):
        session.check("legacy")
    assert "w" not in board.operations


def test_failed_write_stops_the_launch(devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"], writes=False)
    session = chooser.Session(devices.settings, board)
    assert session.check("legacy") == "switch"
    with pytest.raises(chooser.ChooserError, match="Do not use the device"):
        session.switch("legacy")


def test_unfinished_app_firmware_update_blocks_legacy_only(devices: SimpleNamespace) -> None:
    (devices.settings.state / "updates").mkdir()
    (devices.settings.state / "updates/firmware-recovery.json").write_text("{}")
    board = Board(b"half written")
    session = chooser.Session(devices.settings, board)
    with pytest.raises(chooser.ChooserError, match="has not finished"):
        session.check("legacy")
    assert session.check("new") == "ready"
    assert board.operations == []


def buttons(window: object) -> list:
    layout = window.buttons
    return [layout.itemAt(index).widget() for index in range(layout.count())]


def test_touch_flow_confirms_before_writing(qtbot: object, devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"])
    window = chooser.make_window(devices.settings, chooser.Session(devices.settings, board))
    qtbot.addWidget(window)
    assert [button.text() for button in buttons(window)] == ["Legacy KneeSpa", "KneeSpa 2.0"]
    buttons(window)[0].click()
    qtbot.waitUntil(lambda: window.title.text() == "Firmware switch needed", timeout=5000)
    assert "nobody is on the device" in window.message.text()
    assert board.operations == ["v", "v"]
    buttons(window)[1].click()
    qtbot.waitUntil(lambda: window.result is not None, timeout=5000)
    assert board.content == devices.images["legacy"]
    assert window.result[0] == ["python3", "old app.py"]


def test_countdown_starts_last_choice_until_touched(qtbot: object,
                                                    devices: SimpleNamespace) -> None:
    from PyQt5.QtCore import Qt

    devices.settings.save_choice("new")
    window = chooser.make_window(devices.settings, chooser.Session(devices.settings,
                                                                   Board(b"")))
    qtbot.addWidget(window)
    assert window.timer.isActive() and "Starting KneeSpa 2.0 in 15 s" in window.message.text()
    qtbot.mouseClick(window, Qt.LeftButton)
    assert not window.timer.isActive()


def test_errors_offer_a_retry(qtbot: object, devices: SimpleNamespace) -> None:
    devices.settings.commands["legacy"] = []
    window = chooser.make_window(devices.settings, chooser.Session(devices.settings,
                                                                   Board(b"")))
    qtbot.addWidget(window)
    buttons(window)[0].click()
    qtbot.waitUntil(lambda: window.title.text() == "Cannot start", timeout=5000)
    assert [button.text() for button in buttons(window)] == ["Back", "Try again"]


@pytest.mark.skipif(os.name != "posix", reason="flock and the installer need POSIX")
def test_lock_is_shared_with_the_desktop_launcher(settings: "chooser.Settings",
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    monkeypatch.setattr(chooser, "service_active", lambda: False)
    monkeypatch.setattr(chooser, "port_in_use", lambda ports: False)
    (settings.state / "logs").mkdir(parents=True)
    with (settings.state / "logs/desktop-launch.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(chooser.ChooserError, match="already running"):
            chooser.Session(settings).acquire()


@pytest.mark.skipif(os.name != "posix", reason="flock and the installer need POSIX")
def test_installer_writes_autostart_and_keeps_settings(tmp_path: Path) -> None:
    environment = dict(os.environ, KNEESPA_APP_DIR=str(ROOT), HOME=str(tmp_path),
                       KNEESPA_DEVICE_DIR=str(tmp_path / "devices"),
                       KNEESPA_DESKTOP_DIR=str(tmp_path / "Desktop"),
                       XDG_CONFIG_HOME=str(tmp_path / "config"),
                       XDG_DATA_HOME=str(tmp_path / "data"))
    settings = tmp_path / "devices/raspberry-pi/version-chooser/versions.cfg"
    result = subprocess.run(["bash", str(FOLDER / "install.sh")], env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    created = settings.read_text()
    assert "directory = {}\n".format(ROOT) in created
    assert "{}/devices/maintenance".format(ROOT) in created
    settings.write_text("kept\n")
    result = subprocess.run(["bash", str(FOLDER / "install.sh")], env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    entry = (tmp_path / "config/autostart/kneespa-version-chooser.desktop").read_text()
    assert "start_version_chooser.sh" in entry and "KNEESPA_APP_DIR=" in entry
    assert (tmp_path / "Desktop/Choose KneeSpa Version.desktop").is_file()
    assert settings.read_text() == "kept\n"
    result = subprocess.run(["bash", str(FOLDER / "install.sh"), "--uninstall"],
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert not (tmp_path / "config/autostart/kneespa-version-chooser.desktop").exists()
