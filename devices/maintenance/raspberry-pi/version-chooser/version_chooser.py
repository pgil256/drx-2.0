"""Choose the legacy or new KneeSpa app at login and flash the Mega to match.

The chooser is independent of runtime/ so it still starts when either app is
broken. Selecting a version builds that version's firmware from its source
tree (the last build is reused while the source is unchanged), writes it to
the Mega unless the board already verifies identical, verifies it, and only
then starts the app.
"""

import argparse
import configparser
import glob
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable, Dict, List, Optional, Tuple

VERSIONS = ("legacy", "new")
# The Mega 2560's 8 KB bootloader starts here; the bootloader cannot rewrite it.
BOOTLOADER_START = 0x3E000
SERVICE = "kneespa.service"
MEGA_FQBN = "arduino:avr:mega:cpu=atmega2560"
BUILDERS = ("", "platformio", "arduino")
SOURCE_SUFFIXES = (".ino", ".h", ".hpp", ".c", ".cpp", ".ini")
BUILD_TIMEOUT = 900
VERIFY_TIMEOUT = 90
WRITE_TIMEOUT = 240
READ_TIMEOUT = 240


class ChooserError(Exception):
    """A problem shown to the person at the device; nothing unsafe has happened."""


def default_app_dir() -> Path:
    return Path(os.environ.get("KNEESPA_APP_DIR", "/home/pi/drx"))


def state_dir(app_dir: Path) -> Path:
    """Match the app's KNEESPA_DEVICE_DIR handling (config/paths.py)."""
    device = os.environ.get("KNEESPA_DEVICE_DIR", str(app_dir / "devices" / "local"))
    return Path(device) / "raspberry-pi"


class Settings:
    """versions.cfg: chooser options plus each version's firmware source and launch command."""

    def __init__(self, state: Path, app_dir: Optional[Path] = None) -> None:
        self.state = state
        self.app_dir = app_dir or default_app_dir()
        self.root = state / "version-chooser"
        self.path = self.root / "versions.cfg"
        if not self.path.is_file():
            raise ChooserError("Missing {}. Run the version-chooser install.sh first.".format(
                self.path))
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(str(self.path), encoding="utf-8")
        except configparser.Error as error:
            raise ChooserError("Cannot read {}: {}".format(self.path, error)) from None
        missing = [name for name in ("chooser",) + VERSIONS if not parser.has_section(name)]
        if missing:
            raise ChooserError("{} has no [{}] section.".format(self.path, "], [".join(missing)))
        chooser = parser["chooser"]
        try:
            self.timeout = max(0, chooser.getint("timeout", fallback=15))
        except ValueError:
            raise ChooserError("timeout in {} must be a whole number of seconds.".format(
                self.path)) from None
        self.port = chooser.get("port", "").strip()
        self.avrdude = chooser.get("avrdude", "").strip()
        self.avrdude_config = chooser.get("avrdude_config", "").strip()
        self.pio = chooser.get("pio", "").strip()
        self.arduino = chooser.get("arduino", "").strip()
        self.labels: Dict[str, str] = {}
        self.commands: Dict[str, List[str]] = {}
        self.directories: Dict[str, str] = {}
        self.sources: Dict[str, str] = {}
        self.images: Dict[str, str] = {}
        self.builders: Dict[str, str] = {}
        for version in VERSIONS:
            section = parser[version]
            self.labels[version] = section.get("label", "").strip() or version.title()
            try:
                self.commands[version] = shlex.split(section.get("command", ""))
            except ValueError:
                raise ChooserError("[{}] command in {} has unbalanced quotes.".format(
                    version, self.path)) from None
            self.directories[version] = section.get("directory", "").strip()
            self.sources[version] = section.get("source", "").strip()
            self.images[version] = section.get("image", "").strip()
            self.builders[version] = section.get("builder", "").strip().lower()
            if self.builders[version] not in BUILDERS:
                raise ChooserError("[{}] builder in {} must be blank, {} or {}.".format(
                    version, self.path, *BUILDERS[1:]))

    def build_dir(self, version: str) -> Path:
        return self.root / "build" / version

    @property
    def last_choice_file(self) -> Path:
        return self.root / "last-choice"

    def last_choice(self) -> str:
        try:
            value = self.last_choice_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return value if value in VERSIONS else ""

    def save_choice(self, version: str) -> None:
        self.last_choice_file.write_text(version + "\n", encoding="utf-8")

    def launch_command(self, version: str) -> Tuple[List[str], str]:
        command, directory = self.commands[version], self.directories[version]
        if not command:
            raise ChooserError("Set the [{}] command in {}.".format(version, self.path))
        if directory and not Path(directory).is_dir():
            raise ChooserError("The {} directory does not exist: {}".format(
                self.labels[version], directory))
        return command, directory

    def firmware_source(self, version: str) -> Tuple[Optional[Path], Optional[Path]]:
        """Return (prebuilt image, source tree); exactly one of them is set."""
        image, source = self.images[version], self.sources[version]
        if image:
            path = Path(image)
            if not path.is_file():
                raise ChooserError("The {} firmware image does not exist: {}".format(
                    self.labels[version], image))
            return path, None
        if not source:
            raise ChooserError("Set source (the firmware folder) for [{}] in {}.".format(
                version, self.path))
        path = Path(source)
        if not path.is_dir():
            raise ChooserError("The {} firmware folder does not exist: {}".format(
                self.labels[version], source))
        return None, path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def check_hex(path: Path) -> int:
    """Validate an Intel HEX application image for the Mega 2560; return its byte count."""
    present = bytearray(BOOTLOADER_START)
    base, ended, count = 0, False, 0
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("too large")
        for line in path.read_text(encoding="ascii").splitlines():
            line = line.strip()
            if not line:
                continue
            if ended or not line.startswith(":"):
                raise ValueError("unexpected line")
            record = bytes.fromhex(line[1:])
            if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
                raise ValueError("bad record")
            size, address, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
            payload = record[4:-1]
            if kind == 0:
                first = base + address
                if first + size > BOOTLOADER_START:
                    raise ValueError("data in the bootloader region or beyond the flash")
                for offset in range(size):
                    if present[first + offset]:
                        raise ValueError("overlapping data")
                    present[first + offset] = 1
                count += size
            elif kind == 1 and size == 0:
                ended = True
            elif kind in (2, 4) and size == 2:
                base = int.from_bytes(payload, "big") << (4 if kind == 2 else 16)
            elif kind not in (3, 5) or size != 4:
                raise ValueError("unsupported record")
        if not ended or not count or not present[0]:
            raise ValueError("incomplete image")
    except (OSError, UnicodeError, ValueError) as error:
        raise ChooserError("{} is not a usable Mega 2560 application image ({}).".format(
            path, error)) from None
    return count


def source_hash(source: Path) -> str:
    """Hash the firmware sources so an unchanged tree reuses its last build."""
    digest = hashlib.sha256()
    files = sorted(
        path for path in source.rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
        and not any(part.startswith(".") for part in path.relative_to(source).parts))
    if not files:
        raise ChooserError("No firmware source files in {}.".format(source))
    for path in files:
        digest.update(path.relative_to(source).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def executable(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def find_pio(settings: Settings) -> str:
    """Same search as devices/flash_firmware.sh and the app's release installer."""
    for candidate in (settings.pio, os.environ.get("KNEESPA_PIO", ""), shutil.which("pio") or "",
                      str(Path.home() / ".platformio/penv/bin/pio"),
                      str(Path.home() / ".local/share/kneespa/platformio/bin/pio")):
        if executable(candidate):
            return candidate
    raise ChooserError("PlatformIO was not found. Run Flash KneeSpa Firmware once to install it, "
                       "or set pio in versions.cfg.")


def find_arduino(settings: Settings) -> str:
    """Return arduino-cli, or the directory of an Arduino IDE whose arduino-builder compiles."""
    for candidate in (settings.arduino, shutil.which("arduino-cli") or "",
                      str(Path.home() / ".local/bin/arduino-cli")):
        if executable(candidate):
            return candidate
    directories = [settings.arduino] if settings.arduino else []
    directories += sorted(glob.glob("/opt/arduino-*"), reverse=True) + ["/usr/share/arduino"]
    for directory in directories:
        if executable(os.path.join(directory, "arduino-builder")):
            return directory
    raise ChooserError("No Arduino toolchain was found (arduino-cli, or an Arduino IDE under "
                       "/opt). Set arduino in versions.cfg to one of them.")


def ide_version(ide: Path) -> str:
    """arduino-builder wants the IDE version as digits: 1.8.15 is 10815."""
    try:
        parts = ide.joinpath("lib/version.txt").read_text(encoding="ascii").strip().split(".")
        major, minor, patch = (int(re.match(r"\d+", part).group()) for part in parts[:3])
        return str(major * 10000 + minor * 100 + patch)
    except (OSError, ValueError, AttributeError):
        return "10815"


def sketchbook() -> Path:
    try:
        for line in Path.home().joinpath(".arduino15/preferences.txt").read_text(
                encoding="utf-8").splitlines():
            if line.startswith("sketchbook.path="):
                return Path(line.split("=", 1)[1].strip())
    except OSError:
        pass
    return Path.home() / "Arduino"


def build_plan(settings: Settings, source: Path, build: Path,
               builder: str = "") -> Tuple[List[str], Dict[str, str], Path]:
    """Return (command, extra environment, produced HEX) for one firmware source tree."""
    if builder == "platformio" and not (source / "platformio.ini").is_file():
        raise ChooserError("{} has no platformio.ini for the platformio builder.".format(source))
    if builder == "platformio" or (not builder and (source / "platformio.ini").is_file()):
        # Share Flash KneeSpa Firmware's workspace: its downloaded libraries make
        # the build work without internet, and both tools produce the same HEX.
        workspace = settings.app_dir / ".cache" / "firmware-platformio"
        environment = {
            "PLATFORMIO_CORE_DIR": os.environ.get("PLATFORMIO_CORE_DIR",
                                                  str(Path.home() / ".platformio")),
            "PLATFORMIO_WORKSPACE_DIR": str(workspace),
            "PLATFORMIO_BUILD_DIR": str(workspace / "build"),
        }
        command = [find_pio(settings), "run", "--project-dir", str(source),
                   "--environment", "mega"]
        return command, environment, workspace / "build" / "mega" / "firmware.hex"
    sketches = sorted(source.glob("*.ino"))
    if len(sketches) != 1:
        raise ChooserError("{} must hold one .ino sketch or a platformio.ini.".format(source))
    sketch = sketches[0]
    tool = find_arduino(settings)
    if os.path.isdir(tool):
        ide = Path(tool)
        hardware = [str(ide / "hardware")]
        tools = [str(ide / "tools-builder"), str(ide / "hardware" / "tools" / "avr")]
        packages = Path.home() / ".arduino15" / "packages"
        if packages.is_dir():
            hardware.append(str(packages))
            tools.append(str(packages))
        command = [str(ide / "arduino-builder"), "-compile", "-fqbn", MEGA_FQBN,
                   "-ide-version", ide_version(ide), "-build-path", str(build),
                   "-built-in-libraries", str(ide / "libraries"),
                   "-libraries", str(sketchbook() / "libraries"), "-warnings", "none"]
        for directory in hardware:
            command += ["-hardware", directory]
        for directory in tools:
            command += ["-tools", directory]
        command.append(str(sketch))
    else:
        command = [tool, "compile", "--fqbn", MEGA_FQBN, "--build-path", str(build),
                   str(source)]
    return command, {}, build / (sketch.name + ".hex")


Runner = Callable[..., int]


def run_logged(command: List[str], timeout: int, log: Path,
               environment: Optional[Dict[str, str]] = None) -> int:
    with log.open("ab") as output:
        output.write(("$ " + " ".join(shlex.quote(part) for part in command) + "\n").encode())
        output.flush()
        try:
            return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                                  stderr=subprocess.STDOUT, timeout=timeout,
                                  env=environment).returncode
        except subprocess.TimeoutExpired:
            output.write("Timed out after {} s.\n".format(timeout).encode())
            return 124
        except OSError as error:
            output.write("Cannot run: {}\n".format(error).encode())
            return 127


def build_firmware(settings: Settings, version: str, runner: Runner,
                   log: Path) -> Tuple[Path, bool]:
    """Return (validated image, whether it was built now) for one version."""
    image, source = settings.firmware_source(version)
    if image is not None:
        check_hex(image)
        return image, False
    build = settings.build_dir(version)
    build.mkdir(parents=True, exist_ok=True)
    command, extra, produced = build_plan(settings, source, build, settings.builders[version])
    digest = source_hash(source)
    stamp = build / "source.sha256"
    if produced.is_file() and stamp.is_file() and \
            stamp.read_text(encoding="ascii").strip() == digest:
        check_hex(produced)
        return produced, False
    if stamp.exists():
        stamp.unlink()
    environment = dict(os.environ, **extra) if extra else None
    if runner(command, BUILD_TIMEOUT, log, environment):
        raise ChooserError("Building the {} firmware failed. Fix its source or toolchain and "
                           "try again. Log: {}".format(settings.labels[version], log))
    if not produced.is_file():
        raise ChooserError("The build produced no {}.".format(produced))
    check_hex(produced)
    stamp.write_text(digest + "\n", encoding="ascii")
    return produced, True


def find_port(configured: str) -> str:
    if configured:
        candidates = [configured]
    else:
        megas = [path for path in sorted(glob.glob("/dev/serial/by-id/*"))
                 if "Arduino" in path and "0042" in path]
        candidates = megas if len(megas) == 1 else sorted(glob.glob("/dev/ttyACM*"))
        if len(candidates) != 1:
            raise ChooserError("Found {} possible Mega USB ports. Set port in versions.cfg."
                               .format(len(candidates) or "no"))
    port = candidates[0]
    resolved = os.path.realpath(port)
    if not re.fullmatch(r"/dev/tty(?:ACM|USB)\d+", resolved):
        raise ChooserError("Use the Mega's USB port, not {}.".format(resolved))
    if not os.path.exists(resolved) or not os.access(resolved, os.R_OK | os.W_OK):
        raise ChooserError("Cannot open {}. Check the Mega's USB cable and that pi is in "
                           "the dialout group.".format(resolved))
    return resolved


def find_avrdude(settings: Settings) -> Tuple[str, str]:
    """Same search as the app's release installer, plus versioned PlatformIO packages."""
    if settings.avrdude:
        candidates = [(settings.avrdude, settings.avrdude_config or "/etc/avrdude.conf")]
    else:
        candidates = [(shutil.which("avrdude") or "", "/etc/avrdude.conf")]
        core = os.environ.get("PLATFORMIO_CORE_DIR", str(Path.home() / ".platformio"))
        for root in sorted(glob.glob(os.path.join(core, "packages", "tool-avrdude*"))):
            for binary in ("avrdude", "bin/avrdude"):
                for config in ("avrdude.conf", "etc/avrdude.conf"):
                    candidates.append((os.path.join(root, binary), os.path.join(root, config)))
    for binary, config in candidates:
        if executable(binary) and os.path.isfile(config):
            return binary, config
    raise ChooserError("avrdude was not found. Run Flash KneeSpa Firmware once to install it, "
                       "or set avrdude in versions.cfg.")


class Mega:
    """avrdude over the Mega's USB bootloader, as in devices/flash_firmware.sh."""

    def __init__(self, avrdude: str, config: str, port: str, log: Path,
                 runner: Runner = run_logged) -> None:
        self.base = [avrdude, "-C", config, "-p", "atmega2560", "-c", "wiring",
                     "-P", port, "-b", "115200", "-D"]
        self.log, self.runner = log, runner

    def matches(self, image: Path) -> bool:
        """A failed verify means a different image or no answer; backup() tells which."""
        return self.runner(self.base + ["-U", "flash:v:{}:i".format(image)],
                           VERIFY_TIMEOUT, self.log) == 0

    def backup(self, path: Path) -> None:
        status = self.runner(self.base + ["-U", "flash:r:{}:i".format(path)],
                             READ_TIMEOUT, self.log)
        if status or not path.is_file() or not path.stat().st_size:
            raise ChooserError("The Mega did not answer over USB. Check its USB cable and "
                               "power, then try again. Nothing was written.")

    def write(self, image: Path) -> None:
        # avrdude verifies after writing unless -V is passed; it never is here.
        if self.runner(self.base + ["-U", "flash:w:{}:i".format(image)],
                       WRITE_TIMEOUT, self.log):
            raise ChooserError("Writing the firmware failed. Do not use the device. "
                               "Try again; if it keeps failing, flash it from the Flash "
                               "KneeSpa Firmware shortcut. Log: {}".format(self.log))


def port_in_use(ports: List[str]) -> bool:
    """fuser without sudo sees pi's processes, which is how both apps run."""
    if not shutil.which("fuser"):
        return False
    existing = [port for port in ports if os.path.exists(port)]
    return bool(existing) and subprocess.run(
        ["fuser"] + existing, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def service_active() -> bool:
    if not shutil.which("systemctl"):
        return False
    return subprocess.run(["systemctl", "is-active", "--quiet", SERVICE]).returncode == 0


Progress = Callable[[str], None]


class Session:
    """One pass from choice to launch; the UI runs it on a worker thread."""

    def __init__(self, settings: Settings, runner: Runner = run_logged) -> None:
        self.settings, self.runner = settings, runner
        self.lock: Optional[object] = None
        self.record: Optional[Path] = None

    def acquire(self) -> None:
        """Share the KneeSpa launcher's and firmware flasher's lock until exec."""
        logs = self.settings.state / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        if self.lock is None:
            import fcntl  # POSIX only; imported here so tests can load this module anywhere.

            handle = (logs / "desktop-launch.lock").open("w")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                raise ChooserError("KneeSpa or a firmware update is already running. "
                                   "Close it first.") from None
            self.lock = handle
        if service_active():
            raise ChooserError("{} is running. Disable it so only the chooser starts an app: "
                               "sudo systemctl disable --now {}".format(SERVICE, SERVICE))
        if port_in_use(["/dev/serial0"]):
            raise ChooserError("Another program is using /dev/serial0. Close KneeSpa first.")

    def run(self, version: str, progress: Progress) -> str:
        """Build, flash and verify the version's firmware; return what was done."""
        label = self.settings.labels[version]
        self.acquire()
        self.settings.launch_command(version)
        if (self.settings.state / "updates" / "firmware-recovery.json").exists():
            # KneeSpa 2.0 finishes its own interrupted firmware update on startup.
            if version == "new":
                return "recovering"
            raise ChooserError("A firmware update from {} has not finished. Choose it so the "
                               "update can complete; the chooser will not change the firmware "
                               "until then.".format(self.settings.labels["new"]))
        port = find_port(self.settings.port)
        if port_in_use([port]):
            raise ChooserError("Another program is using {}. Close any serial monitor."
                               .format(port))
        avrdude, config = find_avrdude(self.settings)
        firmware = self.settings.state / "firmware"
        firmware.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.record = Path(tempfile.mkdtemp(prefix=stamp + "-choose-" + version + "-",
                                            dir=str(firmware)))
        progress("Building the {} firmware…".format(label))
        image, built = build_firmware(self.settings, version, self.runner,
                                      self.record / "build.log")
        mega = Mega(avrdude, config, port, self.record / "avrdude.log", self.runner)
        progress("Checking the firmware on the Mega…")
        if mega.matches(image):
            if not built:
                # Keep records only for starts that changed something.
                shutil.rmtree(str(self.record), ignore_errors=True)
                self.record = None
            return "verified"
        progress("Backing up the firmware on the Mega…")
        mega.backup(self.record / "previous.hex")
        progress("Writing and verifying the {} firmware. Do not turn off the device or "
                 "unplug the Mega.".format(label))
        mega.write(image)
        if not mega.matches(image):
            raise ChooserError("The firmware did not verify after writing. Do not use the "
                               "device. Log: {}".format(mega.log))
        shutil.copyfile(str(image), str(self.record / "current.hex"))
        return "written"

    def finish(self, version: str) -> Tuple[List[str], str]:
        self.settings.save_choice(version)
        return self.settings.launch_command(version)


def launch(command: List[str], directory: str) -> None:
    """Replace this process; the lock descriptor is not inherited, so it is released."""
    if directory:
        os.chdir(directory)
    sys.stdout.flush()
    os.execvp(command[0], command)


def make_window(settings: Settings, session: Optional[Session] = None) -> object:
    """Build the chooser window; its result is the launch command, or None."""
    from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
    from PyQt5.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                                 QWidget)

    class Task(QThread):
        progress = pyqtSignal(str)
        done = pyqtSignal(object, str)

        def __init__(self, work: Callable[[Progress], object]) -> None:
            super().__init__()
            self.work = work

        def run(self) -> None:
            try:
                self.done.emit(self.work(self.progress.emit), "")
            except ChooserError as error:
                self.done.emit(None, str(error))
            except Exception as error:  # Shown on screen instead of a silent exit.
                self.done.emit(None, "Unexpected error: {!r}".format(error))

    class Window(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Choose KneeSpa version")
            self.setStyleSheet(
                "QWidget { background: #10233a; color: white; font-size: 24px; }"
                "QPushButton { background: #2f6fb0; border-radius: 12px; padding: 24px;"
                " font-size: 30px; min-height: 110px; }"
                "QPushButton:pressed { background: #1d4e80; }")
            self.title = QLabel()
            self.title.setStyleSheet("font-size: 36px; font-weight: bold;")
            self.message = QLabel()
            self.message.setWordWrap(True)
            self.buttons = QHBoxLayout()
            layout = QVBoxLayout(self)
            layout.setContentsMargins(48, 40, 48, 40)
            layout.addWidget(self.title, 0, Qt.AlignHCenter)
            layout.addStretch(1)
            layout.addWidget(self.message)
            layout.addStretch(1)
            layout.addLayout(self.buttons)
            self.session = session or Session(settings)
            self.version = ""
            self.task: Optional[Task] = None
            self.result: Optional[Tuple[List[str], str]] = None
            self.remaining = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.choices()

        def page(self, title: str, message: str,
                 buttons: List[Tuple[str, Callable[[], None]]]) -> None:
            self.timer.stop()
            self.title.setText(title)
            self.message.setText(message)
            while self.buttons.count():
                widget = self.buttons.takeAt(0).widget()
                if widget is not None:
                    widget.deleteLater()
            for label, action in buttons:
                button = QPushButton(label)
                button.clicked.connect(action)
                self.buttons.addWidget(button)

        def choices(self) -> None:
            self.page("Choose KneeSpa version", "", [
                (settings.labels[version], lambda _=False, v=version: self.choose(v))
                for version in VERSIONS])
            last = settings.last_choice()
            if last and settings.timeout:
                self.version, self.remaining = last, settings.timeout
                self.tick()
                self.timer.start(1000)

        def tick(self) -> None:
            if self.remaining <= 0:
                self.choose(self.version)
                return
            self.message.setText("Starting {} in {} s. Touch the screen to wait.".format(
                settings.labels[self.version], self.remaining))
            self.remaining -= 1

        def mousePressEvent(self, event: object) -> None:
            if self.timer.isActive():
                self.timer.stop()
                self.message.setText("")

        def choose(self, version: str) -> None:
            self.version = version
            self.page("Preparing {}".format(settings.labels[version]), "", [])
            self.task = Task(lambda progress: self.session.run(version, progress))
            self.task.progress.connect(self.message.setText)
            self.task.done.connect(lambda result, error: self.failed(error) if error
                                   else self.start())
            self.task.start()

        def start(self) -> None:
            try:
                self.result = self.session.finish(self.version)
            except ChooserError as error:
                self.failed(str(error))
                return
            self.page("Starting", "Starting {}…".format(settings.labels[self.version]), [])
            QTimer.singleShot(300, QApplication.instance().quit)

        def failed(self, error: str) -> None:
            self.page("Cannot start", error, [
                ("Back", self.choices),
                ("Try again", lambda _=False: self.choose(self.version))])

    return Window()


def run_ui(settings: Settings) -> int:
    from PyQt5.QtWidgets import QApplication

    application = QApplication(sys.argv[:1])
    window = make_window(settings)
    window.showFullScreen()
    application.exec_()
    if window.result is None:
        return 1
    print("Starting {}: {}".format(window.version, " ".join(window.result[0])))
    launch(*window.result)
    return 0


def status(settings: Settings) -> int:
    """Print setup problems without touching the Mega."""
    problems = 0
    for version in VERSIONS:
        checks = [lambda v=version: settings.launch_command(v)]
        checks.append(lambda v=version: print("[{}] {}".format(v, firmware_summary(settings, v))))
        for check in checks:
            try:
                check()
            except ChooserError as error:
                problems += 1
                print("[{}] {}".format(version, error))
    for check in (lambda: print("Mega port:", find_port(settings.port)),
                  lambda: print("avrdude:", " ".join(find_avrdude(settings)))):
        try:
            check()
        except ChooserError as error:
            problems += 1
            print(error)
    print("Last choice:", settings.last_choice() or "none")
    print("OK" if not problems else "{} problem(s) to fix before use.".format(problems))
    return 1 if problems else 0


def firmware_summary(settings: Settings, version: str) -> str:
    image, source = settings.firmware_source(version)
    if image is not None:
        return "image {} ({} bytes)".format(image, check_hex(image))
    command, _, produced = build_plan(settings, source, settings.build_dir(version),
                                      settings.builders[version])
    state = "built" if produced.is_file() else "not built yet"
    return "source {} with {} ({})".format(source, command[0], state)


def build(settings: Settings, version: str) -> int:
    """Build (or reuse) one version's firmware without touching the Mega."""
    log = settings.build_dir(version) / "build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists():
        log.unlink()
    image, built = build_firmware(settings, version, run_logged, log)
    print("{} firmware {}: {} ({} bytes, sha256 {})".format(
        settings.labels[version], "built" if built else "unchanged", image, check_hex(image),
        sha256(image)))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command")
    add = commands.add_parser("build", help="build one version's firmware without flashing")
    add.add_argument("version", choices=VERSIONS)
    commands.add_parser("status", help="check the setup without touching the Mega")
    args = parser.parse_args(argv)
    try:
        app_dir = default_app_dir()
        settings = Settings(state_dir(app_dir), app_dir)
        if args.command == "build":
            return build(settings, args.version)
        if args.command == "status":
            return status(settings)
    except ChooserError as error:
        print("ERROR:", error, file=sys.stderr)
        if args.command is None:
            show_error(str(error))
        return 1
    return run_ui(settings)


def show_error(message: str) -> None:
    """At login there is no terminal; a setup error must still reach the screen."""
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
    except ImportError:
        return
    application = QApplication(sys.argv[:1])
    QMessageBox.critical(None, "KneeSpa version chooser", message)
    del application


if __name__ == "__main__":
    sys.exit(main())
