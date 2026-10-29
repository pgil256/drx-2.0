"""Choose the legacy or new KneeSpa app at login and match the Mega firmware to it.

The chooser is independent of runtime/ so it still starts when either app is
broken. It flashes only registered images, only after a touch confirmation,
and starts an app only after avrdude has verified the matching firmware.
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
FLASH_BYTES = 262144
# The Mega 2560's 8 KB bootloader starts here; the bootloader cannot rewrite it.
BOOTLOADER_START = 0x3E000
SERVICE = "kneespa.service"
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
    """versions.cfg plus the registered images beside it."""

    def __init__(self, state: Path) -> None:
        self.state = state
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
        self.labels: Dict[str, str] = {}
        self.commands: Dict[str, List[str]] = {}
        self.directories: Dict[str, str] = {}
        for version in VERSIONS:
            section = parser[version]
            self.labels[version] = section.get("label", "").strip() or version.title()
            try:
                self.commands[version] = shlex.split(section.get("command", ""))
            except ValueError:
                raise ChooserError("[{}] command in {} has unbalanced quotes.".format(
                    version, self.path)) from None
            self.directories[version] = section.get("directory", "").strip()

    def image(self, version: str) -> Path:
        return self.root / "images" / (version + ".hex")

    def checksum_file(self, version: str) -> Path:
        return self.root / "images" / (version + ".sha256")

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

    def checked_image(self, version: str) -> Path:
        """Return the registered image only if it still matches its recorded checksum."""
        image, record = self.image(version), self.checksum_file(version)
        if not image.is_file() or not record.is_file():
            raise ChooserError(
                "No {} firmware image is registered. Run: python3 version_chooser.py "
                "register {} FILE.hex".format(self.labels[version], version))
        expected = record.read_text(encoding="ascii").split()[0].lower() if \
            record.stat().st_size else ""
        if sha256(image) != expected:
            raise ChooserError("The registered {} firmware image changed or is damaged. "
                               "Register it again.".format(self.labels[version]))
        return image

    def launch_command(self, version: str) -> Tuple[List[str], str]:
        command, directory = self.commands[version], self.directories[version]
        if not command:
            raise ChooserError("Set the [{}] command in {}.".format(version, self.path))
        if directory and not Path(directory).is_dir():
            raise ChooserError("The {} directory does not exist: {}".format(
                self.labels[version], directory))
        return command, directory


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def read_hex(path: Path) -> Tuple[bytearray, int, bool]:
    """Return (flash image, end address, has bootloader data) for an Intel HEX file."""
    data, present = bytearray(b"\xff" * FLASH_BYTES), bytearray(FLASH_BYTES)
    base, ended, end, bootloader = 0, False, 0, False
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
                if first + size > FLASH_BYTES:
                    raise ValueError("beyond the Mega's flash")
                for offset, value in enumerate(payload):
                    if present[first + offset]:
                        raise ValueError("overlapping data")
                    present[first + offset] = 1
                    data[first + offset] = value
                if size:
                    end = max(end, first + size)
                    bootloader = bootloader or first + size > BOOTLOADER_START
            elif kind == 1 and size == 0:
                ended = True
            elif kind in (2, 4) and size == 2:
                base = int.from_bytes(payload, "big") << (4 if kind == 2 else 16)
            elif kind not in (3, 5) or size != 4:
                raise ValueError("unsupported record")
        if not ended or not end or not present[0]:
            raise ValueError("incomplete image")
    except (OSError, UnicodeError, ValueError) as error:
        raise ChooserError("{} is not a usable Mega 2560 HEX file ({}).".format(
            path, error)) from None
    return data, end, bootloader


def write_hex(data: bytes, path: Path) -> None:
    """Write data from address 0 as Intel HEX with extended linear addresses."""
    lines = []
    for offset in range(0, len(data), 16):
        if offset and offset % 0x10000 == 0:
            record = bytes([2, 0, 0, 4]) + (offset >> 16).to_bytes(2, "big")
            lines.append(":" + (record + bytes([-sum(record) & 255])).hex().upper())
        chunk = data[offset:offset + 16]
        record = bytes([len(chunk)]) + (offset & 0xFFFF).to_bytes(2, "big") + b"\x00" + chunk
        lines.append(":" + (record + bytes([-sum(record) & 255])).hex().upper())
    lines.append(":00000001FF")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def register(settings: Settings, version: str, source: Path) -> str:
    """Copy an image into place; a full-flash backup loses its bootloader region."""
    data, end, bootloader = read_hex(source)
    settings.image(version).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(settings.image(version).parent), suffix=".hex",
                                     delete=False) as handle:
        staged = Path(handle.name)
    size = end
    try:
        if bootloader:
            # avrdude's flash:r backups include the bootloader and blank space.
            application = bytes(data[:BOOTLOADER_START]).rstrip(b"\xff")
            if not application:
                raise ChooserError("{} holds no application firmware.".format(source))
            write_hex(application, staged)
            size = len(application)
            note = "Removed the bootloader region from this flash backup."
        else:
            shutil.copyfile(str(source), str(staged))
            note = "Copied unchanged."
        digest = sha256(staged)
        other = [name for name in VERSIONS if name != version]
        for name in other:
            record = settings.checksum_file(name)
            if record.is_file() and record.read_text(encoding="ascii").split()[:1] == [digest]:
                raise ChooserError("This image is already registered as {}.".format(
                    settings.labels[name]))
        os.replace(str(staged), str(settings.image(version)))
    except BaseException:
        staged.unlink()
        raise
    settings.checksum_file(version).write_text(
        "{}  {}.hex\n".format(digest, version), encoding="ascii")
    return "{} firmware registered ({} bytes, sha256 {}). {}".format(
        settings.labels[version], size, digest, note)


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
            for executable in ("avrdude", "bin/avrdude"):
                for config in ("avrdude.conf", "etc/avrdude.conf"):
                    candidates.append((os.path.join(root, executable),
                                       os.path.join(root, config)))
    for executable, config in candidates:
        if executable and os.access(executable, os.X_OK) and os.path.isfile(config):
            return executable, config
    raise ChooserError("avrdude was not found. Run Flash KneeSpa Firmware once to install it, "
                       "or set avrdude in versions.cfg.")


Runner = Callable[[List[str], int, Path], int]


def run_logged(command: List[str], timeout: int, log: Path) -> int:
    with log.open("ab") as output:
        output.write(("$ " + " ".join(shlex.quote(part) for part in command) + "\n").encode())
        output.flush()
        try:
            return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                                  stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            output.write("Timed out after {} s.\n".format(timeout).encode())
            return 124
        except OSError as error:
            output.write("Cannot run: {}\n".format(error).encode())
            return 127


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


class Session:
    """One pass from choice to launch; the UI calls these steps on a worker thread."""

    def __init__(self, settings: Settings, runner: Runner = run_logged) -> None:
        self.settings, self.runner = settings, runner
        self.lock: Optional[object] = None
        self.mega: Optional[Mega] = None
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

    def check(self, version: str) -> str:
        """Return 'ready', 'switch' (board holds the other image) or 'unknown'."""
        self.acquire()
        self.settings.launch_command(version)
        image = self.settings.checked_image(version)
        if (self.settings.state / "updates" / "firmware-recovery.json").exists():
            # KneeSpa 2.0 finishes its own interrupted firmware update on startup.
            if version == "new":
                return "ready"
            raise ChooserError("A firmware update from {} has not finished. Choose it so the "
                               "update can complete; the chooser will not change the firmware "
                               "until then.".format(self.settings.labels["new"]))
        port = find_port(self.settings.port)
        if port_in_use([port]):
            raise ChooserError("Another program is using {}. Close any serial monitor."
                               .format(port))
        avrdude, config = find_avrdude(self.settings)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        firmware = self.settings.state / "firmware"
        firmware.mkdir(parents=True, exist_ok=True)
        self.record = Path(tempfile.mkdtemp(prefix=stamp + "-choose-" + version + "-",
                                            dir=str(firmware)))
        self.mega = Mega(avrdude, config, port, self.record / "avrdude.log", self.runner)
        if self.mega.matches(image):
            # Keep records only for boots that needed attention.
            shutil.rmtree(str(self.record), ignore_errors=True)
            self.record = None
            return "ready"
        other = VERSIONS[1 - VERSIONS.index(version)]
        try:
            other_image = self.settings.checked_image(other)
        except ChooserError:
            other_image = None
        if other_image is not None and self.mega.matches(other_image):
            return "switch"
        # Proves the board answers, and keeps what it held before replacing it.
        self.mega.backup(self.record / "previous.hex")
        return "unknown"

    def switch(self, version: str) -> None:
        if self.mega is None:
            raise ChooserError("Check the firmware before switching it.")
        image = self.settings.checked_image(version)
        self.mega.write(image)
        if not self.mega.matches(image):
            raise ChooserError("The firmware did not verify after writing. Do not use the "
                               "device. Log: {}".format(self.mega.log))

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
        done = pyqtSignal(object, str)

        def __init__(self, work: Callable[[], object]) -> None:
            super().__init__()
            self.work = work

        def run(self) -> None:
            try:
                self.done.emit(self.work(), "")
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
                "QPushButton:pressed { background: #1d4e80; }"
                "QPushButton#danger { background: #b05a2f; }")
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
                 buttons: List[Tuple[str, Callable[[], None], bool]]) -> None:
            self.timer.stop()
            self.title.setText(title)
            self.message.setText(message)
            while self.buttons.count():
                widget = self.buttons.takeAt(0).widget()
                if widget is not None:
                    widget.deleteLater()
            for label, action, danger in buttons:
                button = QPushButton(label)
                if danger:
                    button.setObjectName("danger")
                button.clicked.connect(action)
                self.buttons.addWidget(button)

        def choices(self) -> None:
            self.page("Choose KneeSpa version", "", [
                (settings.labels[version], lambda _=False, v=version: self.choose(v), False)
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

        def run(self, work: Callable[[], object], then: Callable[[object], None]) -> None:
            self.task = Task(work)
            self.task.done.connect(lambda result, error: self.failed(error) if error
                                   else then(result))
            self.task.start()

        def choose(self, version: str) -> None:
            self.version = version
            self.page("Checking firmware", "Checking that the Mega has the {} firmware…"
                      .format(settings.labels[version]), [])
            self.run(lambda: self.session.check(version), self.checked)

        def checked(self, state: object) -> None:
            label = settings.labels[self.version]
            if state == "ready":
                self.start()
                return
            if state == "switch":
                text = "The Mega has the {} firmware.".format(
                    settings.labels[VERSIONS[1 - VERSIONS.index(self.version)]])
            else:
                text = ("The Mega has firmware that matches neither version. It may have "
                        "been updated from KneeSpa 2.0 or the Flash KneeSpa Firmware "
                        "shortcut. A backup was saved in {}.".format(self.session.record))
            self.page("Firmware switch needed", text + "\n\nWriting the {} firmware takes "
                      "under a minute and resets the Mega. Make sure nobody is on the "
                      "device.".format(label), [
                          ("Back", self.choices, False),
                          ("Write {} firmware".format(label), self.switch, True)])

        def switch(self) -> None:
            self.page("Writing firmware", "Writing and verifying the {} firmware. Do not "
                      "turn off the device or unplug the Mega.".format(
                          settings.labels[self.version]), [])
            self.run(lambda: self.session.switch(self.version), lambda _: self.start())

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
                ("Back", self.choices, False),
                ("Try again", lambda _=False: self.choose(self.version), False)])

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
        for check in (settings.checked_image, settings.launch_command):
            try:
                check(version)
            except ChooserError as error:
                problems += 1
                print("[{}] {}".format(version, error))
        if settings.image(version).is_file():
            print("[{}] image {}".format(version, settings.image(version)))
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command")
    add = commands.add_parser("register", help="install the firmware image for one version")
    add.add_argument("version", choices=VERSIONS)
    add.add_argument("hex", type=Path)
    commands.add_parser("status", help="check the setup without touching the Mega")
    args = parser.parse_args(argv)
    try:
        settings = Settings(state_dir(default_app_dir()))
        if args.command == "register":
            print(register(settings, args.version, args.hex))
            return 0
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
