"""Boot-time legacy/new chooser: builds, firmware decisions and the touch flow."""

import configparser
import importlib.util
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "devices/maintenance/raspberry-pi/version-chooser"
TEMPLATE = ROOT / "devices/templates/raspberry-pi/version-chooser.cfg.example"
spec = importlib.util.spec_from_file_location("version_chooser", str(FOLDER / "version_chooser.py"))
chooser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chooser)


def hex_text(data: bytes) -> str:
    """Intel HEX from address 0 with extended linear address records."""
    lines = []
    for offset in range(0, len(data), 16):
        if offset and offset % 0x10000 == 0:
            record = bytes([2, 0, 0, 4]) + (offset >> 16).to_bytes(2, "big")
            lines.append(":" + (record + bytes([-sum(record) & 255])).hex().upper())
        chunk = data[offset:offset + 16]
        record = bytes([len(chunk)]) + (offset & 0xFFFF).to_bytes(2, "big") + b"\x00" + chunk
        lines.append(":" + (record + bytes([-sum(record) & 255])).hex().upper())
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"


def hex_file(path: Path, data: bytes) -> Path:
    path.write_bytes(hex_text(data).encode("ascii"))  # Bytes: no newline translation.
    return path


@pytest.fixture
def settings(tmp_path: Path) -> "chooser.Settings":
    """Two fake source trees, fake build tools, and a config made from the template."""
    state = tmp_path / "state"
    (state / "version-chooser").mkdir(parents=True)
    legacy, new, tools = tmp_path / "legacy src", tmp_path / "new-src", tmp_path / "bin"
    for directory in (legacy, new, tools, new / ".pio" / "libdeps"):
        directory.mkdir(parents=True)
    (legacy / "motor.ino").write_text("legacy sketch 1\n")
    (legacy / "hx711_sampler.h").write_text("header\n")
    (legacy / "NOTES.md").write_text("not source\n")
    (new / "motor.ino").write_text("new sketch 1\n")
    (new / "platformio.ini").write_text("[env:mega]\n")
    (new / ".pio" / "libdeps" / "lib.h").write_text("build output, ignored\n")
    for name in ("pio", "arduino-cli"):
        (tools / name).write_text("#!/bin/sh\n")
        (tools / name).chmod(0o755)
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(str(TEMPLATE), encoding="utf-8")
    parser["chooser"].update({"pio": str(tools / "pio"), "arduino": str(tools / "arduino-cli")})
    parser["legacy"].update({"command": "python3 'old app.py'", "directory": str(tmp_path),
                             "source": str(legacy)})
    parser["new"].update({"directory": str(tmp_path), "source": str(new)})
    with (state / "version-chooser" / "versions.cfg").open("w", encoding="utf-8") as stream:
        parser.write(stream)
    return chooser.Settings(state, tmp_path / "app")


class Board:
    """Fake toolchain and avrdude: a build encodes the sketch text; verify compares bytes."""

    def __init__(self, content: bytes = b"", answers: bool = True, writes: bool = True,
                 builds: bool = True) -> None:
        self.content, self.answers, self.writes, self.builds = content, answers, writes, builds
        self.operations: List[str] = []

    def __call__(self, command: List[str], timeout: int, log: Path,
                 environment: Optional[Dict[str, str]] = None) -> int:
        tool = Path(command[0]).name
        with log.open("a") as stream:  # Like run_logged, so records hold the tool logs.
            stream.write(" ".join(command) + "\n")
        if tool in ("pio", "arduino-cli", "arduino-builder"):
            self.operations.append("build")
            if not self.builds:
                return 1
            if tool == "pio":
                source = Path(command[command.index("--project-dir") + 1])
                produced = Path(environment["PLATFORMIO_BUILD_DIR"]) / "mega" / "firmware.hex"
            else:
                source = Path(command[-1])
                source = source if source.is_dir() else source.parent
                flag = "--build-path" if tool == "arduino-cli" else "-build-path"
                produced = Path(command[command.index(flag) + 1]) / "motor.ino.hex"
            produced.parent.mkdir(parents=True, exist_ok=True)
            hex_file(produced, (source / "motor.ino").read_bytes())
            return 0
        assert tool == "avrdude" and "-V" not in command and "-F" not in command
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


def expected_image(settings: "chooser.Settings", version: str) -> bytes:
    """What the fake build produces for the version's current source."""
    return hex_text(Path(settings.sources[version], "motor.ino").read_bytes()).encode("ascii")


@pytest.fixture
def devices(settings: "chooser.Settings", monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace every host and USB check; firmware comes from the fake builds."""
    monkeypatch.setattr(chooser.Session, "acquire", lambda self: None)
    monkeypatch.setattr(chooser, "find_port", lambda configured: "/dev/ttyACM0")
    monkeypatch.setattr(chooser, "find_avrdude", lambda found: ("avrdude", "avrdude.conf"))
    monkeypatch.setattr(chooser, "port_in_use", lambda ports: False)
    images = {version: expected_image(settings, version) for version in chooser.VERSIONS}
    return SimpleNamespace(settings=settings, images=images)


def records(settings: "chooser.Settings") -> List[Path]:
    firmware = settings.state / "firmware"
    return sorted(firmware.iterdir()) if firmware.is_dir() else []


def test_hex_check_spans_extended_addresses(tmp_path: Path) -> None:
    data = b"x" * 0x10000 + b"\x42" * 3
    assert chooser.check_hex(hex_file(tmp_path / "a.hex", data)) == len(data)
    assert ":020000040001F9" in (tmp_path / "a.hex").read_text()


@pytest.mark.parametrize("text", [
    ":0200000001FF\n:00000001FF\n",                    # bad checksum
    ":020000000102FB\n",                                # no end-of-file record
    ":020001000102FA\n:00000001FF\n",                   # nothing at address 0
    ":0100000001FE\n:020000040003F7\n:01E000000C13\n:00000001FF\n",  # bootloader region
    "garbage\n",
])
def test_invalid_hex_is_rejected(tmp_path: Path, text: str) -> None:
    (tmp_path / "bad.hex").write_text(text)
    with pytest.raises(chooser.ChooserError, match="not a usable"):
        chooser.check_hex(tmp_path / "bad.hex")


def test_source_hash_follows_source_files_only(settings: "chooser.Settings") -> None:
    legacy, new = (Path(settings.sources[version]) for version in chooser.VERSIONS)
    before = chooser.source_hash(legacy)
    (legacy / "NOTES.md").write_text("edited notes\n")
    assert chooser.source_hash(legacy) == before
    (legacy / "hx711_sampler.h").write_text("edited header\n")
    assert chooser.source_hash(legacy) != before
    before = chooser.source_hash(new)
    (new / ".pio" / "libdeps" / "lib.h").write_text("rebuilt output\n")
    assert chooser.source_hash(new) == before


def test_build_plan_for_platformio_and_arduino_cli(settings: "chooser.Settings") -> None:
    build = settings.build_dir("new")
    command, environment, produced = chooser.build_plan(settings, Path(settings.sources["new"]),
                                                        build)
    assert command == [settings.pio, "run", "--project-dir", settings.sources["new"],
                       "--environment", "mega"]
    workspace = settings.app_dir / ".cache" / "firmware-platformio"  # flash_firmware.sh's
    assert environment["PLATFORMIO_WORKSPACE_DIR"] == str(workspace)
    assert environment["PLATFORMIO_BUILD_DIR"] == str(workspace / "build")
    assert produced == workspace / "build" / "mega" / "firmware.hex"
    build = settings.build_dir("legacy")
    command, environment, produced = chooser.build_plan(
        settings, Path(settings.sources["legacy"]), build)
    assert command == [settings.arduino, "compile", "--fqbn", chooser.MEGA_FQBN,
                       "--build-path", str(build), settings.sources["legacy"]]
    assert environment == {} and produced == build / "motor.ino.hex"
    # A Pi without internet builds the PlatformIO project with the Arduino toolchain.
    command, _, produced = chooser.build_plan(settings, Path(settings.sources["new"]), build,
                                              "arduino")
    assert command[:2] == [settings.arduino, "compile"] and produced == build / "motor.ino.hex"
    with pytest.raises(chooser.ChooserError, match="no platformio.ini"):
        chooser.build_plan(settings, Path(settings.sources["legacy"]), build, "platformio")


def test_builder_setting_is_validated(settings: "chooser.Settings") -> None:
    text = settings.path.read_text(encoding="utf-8").replace("[new]\n", "[new]\nbuilder = make\n")
    settings.path.write_text(text, encoding="utf-8")
    with pytest.raises(chooser.ChooserError, match="builder"):
        chooser.Settings(settings.state)


def test_build_plan_for_arduino_ide(settings: "chooser.Settings", tmp_path: Path) -> None:
    ide = tmp_path / "arduino-1.8.15"
    (ide / "lib").mkdir(parents=True)
    (ide / "lib" / "version.txt").write_text("1.8.15\n")
    (ide / "arduino-builder").write_text("#!/bin/sh\n")
    (ide / "arduino-builder").chmod(0o755)
    settings.arduino = str(ide)
    source = Path(settings.sources["legacy"])
    command, _, produced = chooser.build_plan(settings, source, settings.build_dir("legacy"))
    assert command[0] == str(ide / "arduino-builder") and command[-1] == str(source / "motor.ino")
    assert command[command.index("-ide-version") + 1] == "10815"
    assert command[command.index("-fqbn") + 1] == chooser.MEGA_FQBN
    assert str(ide / "hardware") in command and produced.name == "motor.ino.hex"
    (source / "second.ino").write_text("two sketches\n")
    with pytest.raises(chooser.ChooserError, match="one .ino sketch"):
        chooser.build_plan(settings, source, settings.build_dir("legacy"))


def test_build_is_reused_until_the_source_changes(settings: "chooser.Settings",
                                                  tmp_path: Path) -> None:
    board = Board()
    log = tmp_path / "build.log"
    image, built = chooser.build_firmware(settings, "legacy", board, log)
    assert built and board.operations == ["build"]
    assert image.read_bytes() == expected_image(settings, "legacy")
    assert chooser.build_firmware(settings, "legacy", board, log) == (image, False)
    assert board.operations == ["build"]
    Path(settings.sources["legacy"], "motor.ino").write_text("legacy sketch 2\n")
    assert chooser.build_firmware(settings, "legacy", board, log) == (image, True)
    assert image.read_bytes() == expected_image(settings, "legacy")


def test_fixed_image_skips_building(settings: "chooser.Settings", tmp_path: Path) -> None:
    fixed = hex_file(tmp_path / "release.hex", b"release image")
    settings.images["new"], settings.sources["new"] = str(fixed), ""
    board = Board()
    assert chooser.build_firmware(settings, "new", board, tmp_path / "log") == (fixed, False)
    assert board.operations == []


def test_failed_build_is_reported(settings: "chooser.Settings", tmp_path: Path) -> None:
    with pytest.raises(chooser.ChooserError, match="Building the Legacy KneeSpa firmware failed"):
        chooser.build_firmware(settings, "legacy", Board(builds=False), tmp_path / "log")
    assert not (settings.build_dir("legacy") / "source.sha256").exists()


def test_setup_problems_are_reported(settings: "chooser.Settings", tmp_path: Path) -> None:
    settings.sources["legacy"] = ""
    with pytest.raises(chooser.ChooserError, match="Set source"):
        settings.firmware_source("legacy")
    settings.sources["legacy"] = str(tmp_path / "missing")
    with pytest.raises(chooser.ChooserError, match="does not exist"):
        settings.firmware_source("legacy")
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


def test_matching_firmware_is_verified_not_written(devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"])
    messages: List[str] = []
    assert chooser.Session(devices.settings, board).run("new", messages.append) == "verified"
    assert board.operations == ["build", "v"]
    assert sorted(path.name for path in records(devices.settings)[0].iterdir()) == [
        "avrdude.log", "build.log"]
    assert chooser.Session(devices.settings, board).run("new", messages.append) == "verified"
    assert board.operations == ["build", "v", "v"]
    assert len(records(devices.settings)) == 1  # A cached, matching start leaves no record.
    assert "Checking the firmware on the Mega…" in messages


def test_other_version_is_written_and_verified(devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"])
    session = chooser.Session(devices.settings, board)
    messages: List[str] = []
    assert session.run("legacy", messages.append) == "written"
    assert board.operations == ["build", "v", "r", "w", "v"]
    assert board.content == devices.images["legacy"]
    assert (session.record / "previous.hex").read_text() == "full flash backup\n"
    assert (session.record / "current.hex").read_bytes() == devices.images["legacy"]
    assert any(message.startswith("Writing and verifying") for message in messages)
    assert session.finish("legacy") == (["python3", "old app.py"],
                                        devices.settings.directories["legacy"])
    assert devices.settings.last_choice() == "legacy"


def test_edited_source_is_rebuilt_and_flashed(devices: SimpleNamespace) -> None:
    board = Board(devices.images["legacy"])
    assert chooser.Session(devices.settings, board).run("legacy", lambda _: None) == "verified"
    Path(devices.settings.sources["legacy"], "motor.ino").write_text("legacy sketch 2\n")
    assert chooser.Session(devices.settings, board).run("legacy", lambda _: None) == "written"
    assert board.content == expected_image(devices.settings, "legacy")


def test_silent_board_is_never_written(devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"], answers=False)
    with pytest.raises(chooser.ChooserError, match="did not answer"):
        chooser.Session(devices.settings, board).run("legacy", lambda _: None)
    assert "w" not in board.operations


def test_failed_write_stops_the_launch(devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"], writes=False)
    with pytest.raises(chooser.ChooserError, match="Do not use the device"):
        chooser.Session(devices.settings, board).run("legacy", lambda _: None)


def test_failed_build_never_touches_the_board(devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"], builds=False)
    with pytest.raises(chooser.ChooserError, match="failed"):
        chooser.Session(devices.settings, board).run("legacy", lambda _: None)
    assert board.operations == ["build"]


def test_unfinished_app_firmware_update_blocks_legacy_only(devices: SimpleNamespace) -> None:
    (devices.settings.state / "updates").mkdir()
    (devices.settings.state / "updates" / "firmware-recovery.json").write_text("{}")
    board = Board(b"half written")
    session = chooser.Session(devices.settings, board)
    with pytest.raises(chooser.ChooserError, match="has not finished"):
        session.run("legacy", lambda _: None)
    assert session.run("new", lambda _: None) == "recovering"
    assert board.operations == []


def buttons(window: object) -> list:
    layout = window.buttons
    return [layout.itemAt(index).widget() for index in range(layout.count())]


def test_touch_flow_flashes_then_starts(qtbot: object, devices: SimpleNamespace) -> None:
    board = Board(devices.images["new"])
    window = chooser.make_window(devices.settings, chooser.Session(devices.settings, board))
    qtbot.addWidget(window)
    assert [button.text() for button in buttons(window)] == ["Legacy KneeSpa", "KneeSpa 2.0"]
    buttons(window)[0].click()
    qtbot.waitUntil(lambda: window.result is not None, timeout=5000)
    assert board.operations == ["build", "v", "r", "w", "v"]
    assert board.content == devices.images["legacy"]
    assert window.result[0] == ["python3", "old app.py"]
    assert window.title.text() == "Starting" and buttons(window) == []


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
    with (settings.state / "logs" / "desktop-launch.lock").open("w") as held:
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
    settings = tmp_path / "devices" / "raspberry-pi" / "version-chooser" / "versions.cfg"
    result = subprocess.run(["bash", str(FOLDER / "install.sh")], env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    created = settings.read_text()
    assert "directory = {}\n".format(ROOT) in created
    assert "source = {}/runtime/arduino/motor\n".format(ROOT) in created
    settings.write_text("kept\n")
    result = subprocess.run(["bash", str(FOLDER / "install.sh")], env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    entry = (tmp_path / "config" / "autostart" / "kneespa-version-chooser.desktop").read_text()
    assert "start_version_chooser.sh" in entry and "KNEESPA_APP_DIR=" in entry
    assert (tmp_path / "Desktop" / "Choose KneeSpa Version.desktop").is_file()
    assert settings.read_text() == "kept\n"
    result = subprocess.run(["bash", str(FOLDER / "install.sh"), "--uninstall"],
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert not (tmp_path / "config" / "autostart" / "kneespa-version-chooser.desktop").exists()
