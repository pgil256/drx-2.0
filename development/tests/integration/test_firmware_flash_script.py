"""Exercise firmware update ordering with a PTY and entirely mocked device tools."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import List

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name != "posix", reason="Firmware fixtures require POSIX PTYs"),
]
SCRIPT = Path(__file__).resolve().parents[3] / "devices" / "flash_firmware.sh"


@pytest.fixture
def flash_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace every privileged, network, and device operation with a recorder."""
    app, commands, core = (tmp_path / name for name in ("drx with spaces", "bin", "core"))
    firmware = app / "runtime/arduino/motor"
    firmware.mkdir(parents=True)
    commands.mkdir()
    for name in ("motor.ino", "hx711_sampler.h", "platformio.ini"):
        (firmware / name).write_text("current source\n", encoding="utf-8")
    trace = tmp_path / "trace.jsonl"
    service = tmp_path / "service-state"
    service.write_text("active", encoding="utf-8")
    mock = '''import json, os, pathlib, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["FLASH_TRACE"], "a") as stream:
    stream.write(json.dumps([name, *args]) + "\\n")
if name == "sudo":
    if args == ["-v"]:
        sys.exit(0)
    assert args[0] in ("systemctl", "fuser", "apt-get")
    sys.exit(subprocess.call(args))
if name == "systemctl":
    state = pathlib.Path(os.environ["FLASH_SERVICE"])
    if args[0] == "show":
        print(state.read_text())
    elif args[0] == "stop":
        if os.environ.get("FAIL_STOP"):
            sys.exit(1)
        state.write_text("inactive")
elif name == "fuser":
    sys.exit(0 if os.environ.get("PORT_BUSY") else 1)
elif name == "pio":
    if args[:2] == ["device", "list"]:
        print(json.dumps(json.loads(os.environ.get("USB_PORTS", "[]"))))
    elif args == ["system", "info", "--json-output"]:
        print(json.dumps({"python_exe": {"value": os.environ["FLASH_PIO_PYTHON"]}}))
    elif "clean" not in args:
        if os.environ.get("FAIL_BUILD"):
            sys.exit(1)
        output = pathlib.Path(os.environ["PLATFORMIO_BUILD_DIR"]) / "mega/firmware.hex"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(":00000001FF\\n")
elif name == "pio-python":
    environment = dict(os.environ, PYTHONPATH=os.environ["FLASH_PIO_MODULES"])
    sys.exit(subprocess.call([sys.executable, *args], env=environment))
elif name == "avrdude":
    assert pathlib.Path(args[args.index("-C") + 1]).is_file()
    operation = args[args.index("-U") + 1]
    _, action, path, _ = operation.split(":")
    if action == "r":
        if os.environ.get("FAIL_BACKUP"):
            sys.exit(1)
        pathlib.Path(path).write_text("old firmware\\n")
    else:
        assert action == "w" and pathlib.Path(path).is_file()
        if os.environ.get("FAIL_UPLOAD"):
            sys.exit(1)
elif name == "zenity":
    if os.environ.get("CANCEL_PICKER"):
        sys.exit(1)
    print(os.environ["FLASH_PORT"])
elif name == "apt-get":
    raise AssertionError("Unexpected package installation")
'''
    for name in ("pio", "pio-python", "avrdude", "sudo", "systemctl", "fuser", "zenity",
                 "apt-get"):
        executable = commands / name
        executable.write_text(f"#!{sys.executable}\n{mock}", encoding="utf-8")
        executable.chmod(0o755)
    # A fresh PlatformIO build has no optional uploader. Only the interpreter
    # reported by `pio system info` can import this isolated PlatformIO fixture.
    modules = tmp_path / "pio modules"
    platform = modules / "platformio/platform"
    platform.mkdir(parents=True)
    (platform.parent / "__init__.py").touch()
    (platform / "__init__.py").touch()
    (platform / "factory.py").write_text('''import json, os, pathlib, shutil

def record(*event):
    with open(os.environ["FLASH_TRACE"], "a") as stream:
        stream.write(json.dumps(event) + "\\n")

class PlatformFactory:
    @classmethod
    def from_env(cls, environment, targets=None):
        assert environment == "mega" and targets == ["upload"]
        assert pathlib.Path.cwd() == pathlib.Path(os.environ["KNEESPA_APP_DIR"]) / \\
            "runtime/arduino/motor"
        record("prepare-uploader")
        return cls()

    def get_package_dir(self, name):
        assert name == "tool-avrdude"
        return os.environ["FLASH_UPLOADER_DIR"]

    def install_package(self, name):
        directory = pathlib.Path(self.get_package_dir(name))
        if directory.is_dir():
            return
        record("install-uploader", str(directory))
        if os.environ.get("FAIL_INSTALL"):
            raise SystemExit("Upload tool download failed")
        directory.mkdir(parents=True)
        binary = directory / os.environ.get("UPLOADER_BINARY", "avrdude")
        config = directory / os.environ.get("UPLOADER_CONFIG", "avrdude.conf")
        if not os.environ.get("MISSING_BINARY"):
            binary.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(os.environ["FLASH_MOCK_UPLOADER"], binary)
        if not os.environ.get("MISSING_CONFIG"):
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("mock config", encoding="utf-8")
''', encoding="utf-8")
    master, slave = os.openpty()
    port = os.ttyname(slave)
    for name in ("KNEESPA_DEVICE_DIR", "FAIL_STOP", "PORT_BUSY", "FAIL_BUILD", "FAIL_BACKUP",
                 "FAIL_UPLOAD", "CANCEL_PICKER", "USB_PORTS", "FAIL_INSTALL",
                 "MISSING_BINARY", "MISSING_CONFIG", "UPLOADER_BINARY", "UPLOADER_CONFIG",
                 "PYTHONPATH"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "PATH": f"{commands}:{os.environ['PATH']}", "KNEESPA_APP_DIR": str(app),
        "KNEESPA_PIO": str(commands / "pio"), "PLATFORMIO_CORE_DIR": str(core),
        "KNEESPA_SERVICE": "kneespa-fixture.service", "FLASH_TRACE": str(trace),
        "FLASH_SERVICE": str(service), "FLASH_PORT": port,
        "FLASH_PIO_PYTHON": str(commands / "pio-python"), "FLASH_PIO_MODULES": str(modules),
        "FLASH_UPLOADER_DIR": str(core / "packages/tool-avrdude"),
        "FLASH_MOCK_UPLOADER": str(commands / "avrdude"),
    }.items():
        monkeypatch.setenv(name, value)
    yield SimpleNamespace(app=app, trace=trace, service=service, port=port, core=core,
                          commands=commands)
    os.close(master)
    os.close(slave)


def run_flash(fixture: SimpleNamespace, automatic: bool = False) -> subprocess.CompletedProcess:
    """Run with intercepted tools; an explicit PTY never represents real hardware."""
    args = [] if automatic else ["--port", fixture.port]
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=20)


def events(fixture: SimpleNamespace) -> List[List[str]]:
    """Return requested external actions in execution order."""
    if not fixture.trace.exists():
        return []
    return [json.loads(line) for line in fixture.trace.read_text().splitlines()]


def uploads(fixture: SimpleNamespace) -> List[List[str]]:
    """Select only requests that write board flash."""
    return [event for event in events(fixture)
            if event[0] == "avrdude" and any(arg.startswith("flash:w:") for arg in event)]


def test_build_backup_upload_and_leave_service_stopped(flash_fixture: SimpleNamespace) -> None:
    result = run_flash(flash_fixture)
    assert result.returncode == 0, result.stdout + result.stderr
    trace = events(flash_fixture)
    build = next(i for i, event in enumerate(trace) if event[0] == "pio" and "clean" not in event)
    install = next(i for i, event in enumerate(trace) if event[0] == "install-uploader")
    stop = next(i for i, event in enumerate(trace) if event[:2] == ["systemctl", "stop"])
    backup = next(i for i, event in enumerate(trace)
                  if any(arg.startswith("flash:r:") for arg in event))
    write = next(i for i, event in enumerate(trace)
                 if any(arg.startswith("flash:w:") for arg in event))
    assert build < install < stop < backup < write
    assert any(event[0] == "pio-python" for event in trace)
    assert not any(event[0] == "pio" and "upload" in event for event in trace)
    assert flash_fixture.service.read_text() == "inactive"
    assert not any(event[:2] == ["systemctl", "start"] for event in trace)
    assert "-V" not in uploads(flash_fixture)[0]  # Readback verification must stay enabled.
    assert "-F" not in uploads(flash_fixture)[0]  # Never ignore a different chip signature.
    records = list((flash_fixture.app / "devices/local/raspberry-pi/firmware").iterdir())
    assert len(records) == 1
    assert (records[0] / "previous.hex").read_text() == "old firmware\n"
    assert (records[0] / "current.hex").is_file()
    assert (records[0] / "sha256.txt").is_file()


@pytest.mark.parametrize("failure", [
    "FAIL_BUILD", "FAIL_INSTALL", "MISSING_BINARY", "MISSING_CONFIG", "FAIL_STOP",
    "PORT_BUSY", "FAIL_BACKUP",
])
def test_failures_prevent_flash(
    flash_fixture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    monkeypatch.setenv(failure, "1")
    result = run_flash(flash_fixture)
    assert result.returncode != 0
    assert not uploads(flash_fixture)
    if failure in ("FAIL_BUILD", "FAIL_INSTALL", "MISSING_BINARY", "MISSING_CONFIG", "FAIL_STOP"):
        assert flash_fixture.service.read_text() == "active"
    else:
        assert flash_fixture.service.read_text() == "inactive"


@pytest.mark.parametrize("binary, config", [
    ("avrdude", "avrdude.conf"),
    ("bin/avrdude", "avrdude.conf"),
    ("bin/avrdude", "etc/avrdude.conf"),
])
def test_resolved_package_location_and_layout(
    flash_fixture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, binary: str, config: str,
) -> None:
    """Use the selected package even when it lives outside the default core directory."""
    directory = flash_fixture.app / "custom packages/tool-avrdude@selected-version"
    monkeypatch.setenv("FLASH_UPLOADER_DIR", str(directory))
    monkeypatch.setenv("UPLOADER_BINARY", binary)
    monkeypatch.setenv("UPLOADER_CONFIG", config)
    result = run_flash(flash_fixture)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Upload tool: {directory / binary}" in result.stdout
    upload = uploads(flash_fixture)[0]
    assert upload[upload.index("-C") + 1] == str(directory / config)


def test_existing_upload_tool_needs_no_download(
    flash_fixture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already installed uploader can be used without downloading it again."""
    import shutil

    directory = flash_fixture.core / "packages/tool-avrdude"
    directory.mkdir(parents=True)
    shutil.copy2(flash_fixture.commands / "avrdude", directory / "avrdude")
    (directory / "avrdude.conf").write_text("mock config", encoding="utf-8")
    monkeypatch.setenv("FAIL_INSTALL", "1")
    result = run_flash(flash_fixture)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(event[0] == "install-uploader" for event in events(flash_fixture))


def test_upload_failure_leaves_backup_and_service_stopped(
    flash_fixture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAIL_UPLOAD", "1")
    result = run_flash(flash_fixture)
    assert result.returncode != 0
    assert "SUCCESS" not in result.stdout
    assert flash_fixture.service.read_text() == "inactive"
    assert list((flash_fixture.app / "devices/local/raspberry-pi/firmware").glob("*/previous.hex"))


def test_running_desktop_blocks_build_and_flash(flash_fixture: SimpleNamespace) -> None:
    import fcntl

    lock = flash_fixture.app / "devices/local/raspberry-pi/logs/desktop-launch.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_flash(flash_fixture)
    assert result.returncode != 0
    assert "Close the KneeSpa app" in result.stdout + result.stderr
    assert not events(flash_fixture)


@pytest.mark.parametrize("cancel", [False, True])
def test_graphical_port_choice(
    flash_fixture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, cancel: bool,
) -> None:
    monkeypatch.setenv("USB_PORTS", json.dumps([
        {"port": "/dev/ttyUSB0", "description": "USB serial clone", "hwid": "unknown"},
    ]))
    if cancel:
        monkeypatch.setenv("CANCEL_PICKER", "1")
    result = run_flash(flash_fixture, automatic=True)
    assert (result.returncode != 0) == cancel, result.stdout + result.stderr
    assert bool(uploads(flash_fixture)) != cancel
    if cancel:
        assert flash_fixture.service.read_text() == "active"


def test_no_usb_board_does_not_stop_service(flash_fixture: SimpleNamespace) -> None:
    result = run_flash(flash_fixture, automatic=True)
    assert result.returncode != 0
    assert "No USB serial board" in result.stdout
    assert flash_fixture.service.read_text() == "active"
    assert not uploads(flash_fixture)
