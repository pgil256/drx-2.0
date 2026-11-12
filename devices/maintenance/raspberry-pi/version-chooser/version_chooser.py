"""Choose the legacy or new KneeSpa app at login and flash the Mega to match.

The chooser is independent of runtime/ so it still starts when either app is
broken. Selecting a version builds that version's firmware from its source
tree (the last build is reused while the source is unchanged), writes it to
the Mega unless the board already verifies identical, verifies it, and only
then starts the app. A USB conversation that breaks part-way is repeated; it
never counts as "different firmware" (see LINK_TROUBLE).
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
# avrdude prints these when the USB conversation itself broke. Its stk500v2
# receive loop times out on the wall clock, and a Pi has no clock battery: the
# first network time sync after boot steps the clock by days, which ends any
# read in progress with "timeout" and garbage data. A conversation that started
# and then broke is repeated instead of being taken for different firmware.
LINK_TROUBLE = ("timeout", "not in sync", "not responding", "protocol error",
                "can't open device", "ser_open", "ser_recv", "ser_send")
VERIFY_ATTEMPTS = 3
BACKUP_ATTEMPTS = 2
WRITE_ATTEMPTS = 2
RETRY_PAUSE = 2.0


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
        if not find_program(command[0], directory):
            raise ChooserError("The {} start command was not found: {}".format(
                self.labels[version], command[0]))
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


def find_program(program: str, directory: str) -> str:
    """Resolve a start command as exec will: on PATH, or relative to its directory."""
    if os.sep in program and not os.path.isabs(program):
        program = os.path.join(directory or os.getcwd(), program)
    return shutil.which(program) or ""


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


def link_trouble(output: str) -> bool:
    text = output.lower()
    return any(marker in text for marker in LINK_TROUBLE)


def read_from(path: Path, start: int) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(start)
            return stream.read().decode("utf-8", "replace")
    except OSError:
        return ""


class Mega:
    """avrdude over the Mega's USB bootloader, as in devices/flash_firmware.sh."""

    def __init__(self, avrdude: str, config: str, port: str, log: Path,
                 runner: Runner = run_logged) -> None:
        self.base = [avrdude, "-C", config, "-p", "atmega2560", "-c", "wiring",
                     "-P", port, "-b", "115200", "-D"]
        self.log, self.runner = log, runner

    def run(self, operation: str, timeout: int, attempts: int,
            trust_success: bool = True) -> Tuple[int, str]:
        """Run one avrdude operation and return (status, its output).

        It is repeated while the board answered and the conversation then broke
        (see LINK_TROUBLE). A board that never answers is not asked again.
        """
        status, output = 1, ""
        for attempt in range(attempts):
            if attempt:
                time.sleep(RETRY_PAUSE)
            start = self.log.stat().st_size if self.log.exists() else 0
            status = self.runner(self.base + ["-U", operation], timeout, self.log)
            output = read_from(self.log, start)
            broke = link_trouble(output) and "device initialized" in output.lower()
            if not broke or (status == 0 and trust_success):
                break
        return status, output

    def matches(self, image: Path) -> bool:
        """Whether the board holds exactly this image; an unclear answer is an error."""
        status, output = self.run("flash:v:{}:i".format(image), VERIFY_TIMEOUT, VERIFY_ATTEMPTS)
        if status == 0:
            return True
        if link_trouble(output):
            raise ChooserError("The Mega did not answer reliably over USB. Check its USB "
                               "cable and power, then try again. Log: {}".format(self.log))
        if "verification error" in output.lower():
            return False
        raise ChooserError("The firmware on the Mega could not be checked. "
                           "Log: {}".format(self.log))

    def backup(self, path: Path) -> None:
        # A read that recovered from a broken conversation can hold shifted
        # data, so success with link trouble is not trusted.
        status, output = self.run("flash:r:{}:i".format(path), READ_TIMEOUT, BACKUP_ATTEMPTS,
                                  trust_success=False)
        if status or link_trouble(output) or not path.is_file() or not path.stat().st_size:
            raise ChooserError("The Mega did not answer over USB. Check its USB cable and "
                               "power, then try again. Nothing was written.")

    def write(self, image: Path) -> None:
        # avrdude verifies after writing unless -V is passed; it never is here.
        status, _ = self.run("flash:w:{}:i".format(image), WRITE_TIMEOUT, WRITE_ATTEMPTS)
        if status:
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
        self.stage = ""  # One of STAGES; the UI shows it beside each progress message.

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

    def step(self, stage: str, message: str, progress: Progress) -> None:
        self.stage = stage
        progress(message)

    def run(self, version: str, progress: Progress) -> str:
        """Build, flash and verify the version's firmware; return what was done."""
        try:
            return self.prepare(version, progress)
        except OSError as error:
            raise ChooserError("The Pi could not prepare the firmware ({}). Check its free "
                               "disk space.".format(error.strerror or error)) from None

    def prepare(self, version: str, progress: Progress) -> str:
        label = self.settings.labels[version]
        self.stage = "build"
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
        self.step("build", "Building the {} firmware…".format(label), progress)
        image, built = build_firmware(self.settings, version, self.runner,
                                      self.record / "build.log")
        mega = Mega(avrdude, config, port, self.record / "avrdude.log", self.runner)
        self.step("check", "Checking the firmware on the Mega…", progress)
        if mega.matches(image):
            if not built:
                # Keep records only for starts that changed something.
                shutil.rmtree(str(self.record), ignore_errors=True)
                self.record = None
            return "verified"
        self.step("backup", "Backing up the firmware on the Mega…", progress)
        mega.backup(self.record / "previous.hex")
        self.step("write", "Writing and verifying the {} firmware. Do not turn off the "
                  "device or unplug the Mega.".format(label), progress)
        mega.write(image)
        try:
            verified = mega.matches(image)
        except ChooserError:
            verified = False
        if not verified:
            raise ChooserError("The firmware did not verify after writing. Do not use the "
                               "device. Log: {}".format(mega.log))
        shutil.copyfile(str(image), str(self.record / "current.hex"))
        return "written"

    def finish(self, version: str) -> Tuple[List[str], str]:
        result = self.settings.launch_command(version)
        try:
            self.settings.save_choice(version)
        except OSError as error:
            # Only the countdown's default is lost; a full disk must not block the start.
            print("Could not remember the choice: {}".format(error), file=sys.stderr)
        return result


def launch(command: List[str], directory: str) -> None:
    """Replace this process; the lock descriptor is not inherited, so it is released."""
    if directory:
        os.chdir(directory)
    sys.stdout.flush()
    os.execvp(command[0], command)


STAGES = ("build", "check", "backup", "write", "start")
STEP_NAMES = {"build": "Build the firmware", "check": "Check the Mega",
              "backup": "Back up the Mega", "write": "Write the firmware", "start": "Start"}
CHOICES_NOTE = "The Mega's firmware is checked, and changed if needed, before the app starts."
PROGRESS_NOTE = ("Starting the same version again takes a few seconds. "
                 "Changing versions takes about a minute.")
STOPPED_NOTE = "Countdown stopped. Choose a version to start."

# The app's bundled fonts and logo are used when present; the chooser never
# imports runtime/, so it still starts when either app is broken.
APP_UI = ("runtime", "raspberry-pi", "main", "ui")
# Values of the shared KneeSpa design system (design/tokens.json, the --ks-*
# names in runtime's tokens_shared.py), copied for the same reason.
KS = {
    "surface": "#ffffff", "surface2": "#f3f6f9", "line": "#e2e7ec", "line_strong": "#7f8e9c",
    "ink": "#152029", "ink2": "#3a4855", "muted": "#5f6e7d",
    "action": "#0b6bb0", "action_hover": "#08578f", "action_soft": "#e6f2fb",
    "ok": "#1a7a4a", "warn": "#8a5a00", "warn_soft": "#fdf2d6",
    "danger": "#c0302e", "neutral_soft": "#edf1f4",
    "sans": '"IBM Plex Sans", "Segoe UI", "DejaVu Sans", sans-serif',
    "mono": '"IBM Plex Mono", "DejaVu Sans Mono", Consolas, monospace',
}
# Kiosk sizes: 16 px smallest text, 48/64/88 px touch targets.
STYLE = """
QWidget { color: $ink; font-family: $sans; font-size: 20px; }
QWidget#root, QMessageBox { background: $surface2; }
QFrame#bar { background: $surface; border: none; border-bottom: 1px solid $line; }
QLabel#wordmark { font-size: 22px; font-weight: 600; }
QLabel#title { font-size: 28px; font-weight: 600; }
QLabel#message { color: $ink2; }
QPushButton { background: $surface; color: $action; border: 1px solid $line_strong;
    border-radius: 8px; padding: 0 28px; min-height: 64px; font-size: 22px; font-weight: 500; }
QPushButton:pressed { background: $action_soft; border-color: $action; }
QPushButton#primary { background: $action; color: #ffffff; border-color: $action; }
QPushButton#primary:pressed { background: $action_hover; border-color: $action_hover; }
QPushButton#quiet { color: $ink2; border-color: $line; min-height: 48px; padding: 0 20px;
    font-size: 16px; }
QPushButton#card { border-radius: 12px; padding: 0; }
QPushButton#card[primary="true"] { border: 2px solid $action; }
QPushButton#card:pressed { background: $action_soft; border: 2px solid $action; }
QLabel#cardName { font-size: 36px; font-weight: 600; }
QLabel#cardDetail { font-family: $mono; font-size: 16px; color: $muted; }
QLabel#badge { background: $action_soft; color: $action; border-radius: 4px; padding: 4px 10px;
    font-size: 16px; font-weight: 600; }
QLabel#go { color: $action; border: 1px solid $action; border-radius: 8px; padding: 12px 32px;
    font-size: 22px; font-weight: 500; }
QLabel#go[primary="true"] { background: $action; color: #ffffff; }
QProgressBar#countdown { background: $line; border: none; border-radius: 3px; }
QProgressBar#countdown::chunk { background: $action; border-radius: 3px; }
QLabel#note { color: $ink2; min-height: 28px; }
QFrame#panel { background: $surface; border: 1px solid $line; border-radius: 12px; }
QLabel#stepName { font-size: 22px; }
QLabel#stepName[state="pending"], QLabel#stepName[state="skipped"] { color: $muted; }
QLabel#stepName[state="active"] { font-weight: 600; }
QLabel#stepStatus { font-size: 16px; color: $muted; }
QLabel#caution { background: $warn_soft; color: $warn; border-radius: 8px; padding: 16px 24px;
    font-weight: 600; }
QFrame#problem { background: $surface; border: 1px solid $line; border-left: 6px solid $danger;
    border-radius: 8px; }
QLabel#problemText { font-size: 22px; }
QLabel#logTitle { font-size: 16px; font-weight: 600; color: $muted; }
QLabel#log { background: $neutral_soft; color: $ink2; border-radius: 4px; padding: 12px 16px;
    font-family: $mono; font-size: 16px; }
"""


def style_sheet() -> str:
    from string import Template

    return Template(STYLE).substitute(KS)


def load_fonts(app_dir: Path) -> None:
    """Register the app's IBM Plex files with Qt; without them system fonts are used."""
    from PyQt5.QtGui import QFontDatabase

    for path in sorted(app_dir.joinpath(*APP_UI, "theme", "fonts").glob("IBMPlex*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def split_log(message: str) -> Tuple[str, str]:
    """Separate a trailing "Log: <path>" so the screen can set the path apart."""
    text, mark, path = message.rpartition(" Log: ")
    return (text, path) if mark else (message, "")


def make_window(settings: Settings, session: Optional[Session] = None) -> object:
    """Build the chooser window; its result is the launch command, or None."""
    from PyQt5.QtCore import QEvent, QPointF, QRectF, QThread, QTimer, Qt, pyqtSignal
    from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap, QPolygonF
    from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar,
                                 QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

    load_fonts(settings.app_dir)

    class Task(QThread):
        progress = pyqtSignal(str, str)
        done = pyqtSignal(object, str)

        def __init__(self, work: Callable[[Callable[[str, str], None]], object]) -> None:
            super().__init__()
            self.work = work

        def run(self) -> None:
            try:
                self.done.emit(self.work(self.progress.emit), "")
            except ChooserError as error:
                self.done.emit(None, str(error))
            except Exception as error:  # noqa: BLE001 - shown on screen, not a silent exit
                self.done.emit(None, "Unexpected error: {!r}".format(error))

    def text(name: str, value: str = "", wrap: bool = False) -> QLabel:
        label = QLabel(value)
        label.setObjectName(name)
        label.setWordWrap(wrap)
        return label

    def restyle(widget: QWidget, name: str, value: object) -> None:
        """Set a property the style sheet selects on, and apply the matching rules."""
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def keep_space(widget: QWidget) -> None:
        policy = widget.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        widget.setSizePolicy(policy)

    class Elided(QLabel):
        """One line of text, shortened in the middle when it does not fit."""

        def __init__(self, name: str, value: str) -> None:
            super().__init__(value)
            self.setObjectName(name)
            self.full = value
            self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        def resizeEvent(self, event: object) -> None:
            self.setText(QFontMetrics(self.font()).elidedText(self.full, Qt.ElideMiddle,
                                                              self.width()))

    class Card(QPushButton):
        """One version: the whole card is the touch target."""

        def __init__(self, version: str, last: bool) -> None:
            super().__init__()
            self.setObjectName("card")
            self.setAccessibleName(settings.labels[version])
            self.setProperty("primary", last)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            badge = text("badge", "Last used")
            keep_space(badge)
            badge.setVisible(last)
            name = text("cardName", settings.labels[version])
            place = Elided("cardDetail", settings.directories[version]
                           or " ".join(settings.commands[version]))
            go = text("go", "Start")
            go.setProperty("primary", last)
            top, bottom = QHBoxLayout(), QHBoxLayout()
            top.addWidget(badge)
            top.addStretch(1)
            bottom.addWidget(go)
            bottom.addStretch(1)
            column = QVBoxLayout(self)
            column.setContentsMargins(32, 28, 32, 32)
            column.setSpacing(8)
            column.addLayout(top)
            column.addStretch(1)
            column.addWidget(name)
            column.addWidget(place)
            column.addStretch(2)
            column.addLayout(bottom)
            for child in (badge, name, place, go):
                child.setAttribute(Qt.WA_TransparentForMouseEvents)

    class Mark(QWidget):
        """A step's state as a shape as well as a colour: ring, arc, tick or dash."""

        def __init__(self) -> None:
            super().__init__()
            self.setFixedSize(32, 32)
            self.state, self.angle = "pending", 0

        def paintEvent(self, event: object) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            circle = QRectF(5, 5, 22, 22)
            if self.state == "done":
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(KS["ok"]))
                painter.drawEllipse(QRectF(3, 3, 26, 26))
                painter.setPen(QPen(QColor("#ffffff"), 3, Qt.SolidLine, Qt.RoundCap,
                                    Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                painter.drawPolyline(QPolygonF([QPointF(10, 16.5), QPointF(14.5, 21),
                                                QPointF(22, 11.5)]))
            elif self.state == "active":
                painter.setPen(QPen(QColor(KS["line"]), 4))
                painter.drawEllipse(circle)
                painter.setPen(QPen(QColor(KS["action"]), 4, Qt.SolidLine, Qt.RoundCap))
                painter.drawArc(circle, -self.angle * 16, 100 * 16)
            elif self.state == "skipped":
                painter.setPen(QPen(QColor(KS["line_strong"]), 3, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(QPointF(11, 16), QPointF(21, 16))
            else:
                painter.setPen(QPen(QColor(KS["line_strong"]), 2))
                painter.drawEllipse(circle)
            painter.end()

    class Step(QWidget):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.mark, self.name, self.status = Mark(), text("stepName", name), text("stepStatus")
            self.started = 0.0
            self.setFixedHeight(60)
            row = QHBoxLayout(self)
            row.setContentsMargins(24, 0, 24, 0)
            row.setSpacing(16)
            row.addWidget(self.mark)
            row.addWidget(self.name, 1)
            row.addWidget(self.status)

        @property
        def state(self) -> str:
            return self.mark.state

        def set(self, state: str, status: str = "") -> None:
            self.mark.state = state
            self.mark.update()
            restyle(self.name, "state", state)
            self.status.setText(status)
            self.started = time.monotonic()

    class Window(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("root")
            self.setAttribute(Qt.WA_StyledBackground, True)
            self.setWindowTitle("Choose KneeSpa version")
            self.setStyleSheet(style_sheet())
            self.session = session or Session(settings)
            self.version = ""
            self.task: Optional[Task] = None
            self.result: Optional[Tuple[List[str], str]] = None
            self.remaining = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.spin = QTimer(self)
            self.spin.setInterval(50)
            self.spin.timeout.connect(self.animate)
            # Closing the only window ends the event loop; run_ui then starts the app.
            self.handover = QTimer(self)
            self.handover.setSingleShot(True)
            self.handover.timeout.connect(self.close)

            bar = QFrame()
            bar.setObjectName("bar")
            bar.setFixedHeight(72)
            logo = QLabel()
            image = QPixmap(str(settings.app_dir.joinpath(*APP_UI, "media", "images", "logos",
                                                          "knee.png")))
            if not image.isNull():
                logo.setPixmap(image.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.exit = QPushButton("Exit to desktop")
            self.exit.setObjectName("quiet")
            self.exit.clicked.connect(self.leave)
            row = QHBoxLayout(bar)
            row.setContentsMargins(24, 0, 24, 0)
            row.setSpacing(12)
            row.addWidget(logo)
            row.addWidget(text("wordmark", "KneeSpa"))
            row.addStretch(1)
            row.addWidget(self.exit)

            self.title, self.message = text("title"), text("message", wrap=True)
            self.pages = QStackedWidget()
            self.choice_page, self.progress_page, self.error_page = (
                self.build_choices(), self.build_progress(), self.build_error())
            for page in (self.choice_page, self.progress_page, self.error_page):
                self.pages.addWidget(page)
            body = QVBoxLayout()
            body.setContentsMargins(48, 28, 48, 36)
            body.setSpacing(8)
            body.addWidget(self.title)
            body.addWidget(self.message)
            body.addSpacing(16)
            body.addWidget(self.pages, 1)
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            outer.addWidget(bar)
            outer.addLayout(body, 1)
            self.choices()

        def build_choices(self) -> QWidget:
            page, last = QWidget(), settings.last_choice()
            cards = QHBoxLayout()
            cards.setSpacing(24)
            for version in VERSIONS:
                card = Card(version, version == last)
                card.clicked.connect(lambda _=False, v=version: self.choose(v))
                cards.addWidget(card)
            self.count = QProgressBar()
            self.count.setObjectName("countdown")
            self.count.setTextVisible(False)
            self.count.setFixedHeight(6)
            keep_space(self.count)
            self.note = text("note")
            column = QVBoxLayout(page)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(16)
            column.addLayout(cards, 1)
            column.addWidget(self.count)
            column.addWidget(self.note)
            return page

        def build_progress(self) -> QWidget:
            page, panel = QWidget(), QFrame()
            panel.setObjectName("panel")
            panel.setMaximumWidth(860)
            rows = QVBoxLayout(panel)
            rows.setContentsMargins(0, 8, 0, 8)
            rows.setSpacing(0)
            self.steps = {stage: Step(STEP_NAMES[stage]) for stage in STAGES}
            for stage in STAGES:
                rows.addWidget(self.steps[stage])
            self.caution = text("caution", "Do not turn off the device or unplug the Mega.")
            self.caution.setMaximumWidth(860)
            keep_space(self.caution)
            column = QVBoxLayout(page)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(16)
            column.addWidget(panel)
            column.addWidget(self.caution)
            column.addStretch(1)
            return page

        def build_error(self) -> QWidget:
            page, problem = QWidget(), QFrame()
            problem.setObjectName("problem")
            self.problem = text("problemText", wrap=True)
            self.log_title, self.log = text("logTitle", "Log file"), text("log", wrap=True)
            inner = QVBoxLayout(problem)
            inner.setContentsMargins(28, 24, 28, 24)
            inner.setSpacing(12)
            for widget in (self.problem, self.log_title, self.log):
                inner.addWidget(widget)
            back, again = QPushButton("Back"), QPushButton("Try again")
            again.setObjectName("primary")
            back.clicked.connect(lambda _=False: self.choices(countdown=False))
            again.clicked.connect(lambda _=False: self.choose(self.version))
            row = QHBoxLayout()
            row.setSpacing(16)
            row.addStretch(1)
            for button in (back, again):
                button.setMinimumSize(260, 88)
                row.addWidget(button)
            column = QVBoxLayout(page)
            column.setContentsMargins(0, 0, 0, 0)
            column.addWidget(problem)
            column.addStretch(1)
            column.addLayout(row)
            return page

        def show_page(self, page: QWidget, title: str, message: str) -> None:
            self.title.setText(title)
            self.message.setText(message)
            self.pages.setCurrentWidget(page)

        def buttons(self) -> List[QPushButton]:
            """The actions offered now, for the screen's tests."""
            return self.pages.currentWidget().findChildren(QPushButton)

        def choices(self, countdown: bool = True) -> None:
            """Offer both versions; only the first showing counts down to the last one."""
            self.spin.stop()
            self.exit.show()
            self.show_page(self.choice_page, "Choose a version", CHOICES_NOTE)
            last = settings.last_choice()
            if countdown and last and settings.timeout:
                self.version, self.remaining = last, settings.timeout
                self.count.setRange(0, settings.timeout)
                self.count.show()
                self.tick()
                self.timer.start(1000)
                # Any touch or key stops the countdown, wherever on the screen it lands.
                QApplication.instance().installEventFilter(self)
            else:
                self.stop_countdown("")

        def tick(self) -> None:
            if self.remaining <= 0:
                self.choose(self.version)
                return
            self.count.setValue(self.remaining)
            self.note.setText("{} starts in {} s. Touch anywhere to cancel.".format(
                settings.labels[self.version], self.remaining))
            self.remaining -= 1

        def stop_countdown(self, note: str) -> None:
            self.timer.stop()
            QApplication.instance().removeEventFilter(self)
            self.count.hide()
            self.note.setText(note)

        def eventFilter(self, watched: object, event: object) -> bool:
            if self.timer.isActive() and event.type() in (
                    QEvent.MouseButtonPress, QEvent.TouchBegin, QEvent.KeyPress) and \
                    isinstance(watched, QWidget) and (
                        watched is self or self.isAncestorOf(watched)):
                self.stop_countdown(STOPPED_NOTE)
            return False

        def choose(self, version: str) -> None:
            if self.task is not None and self.task.isRunning():
                return
            self.stop_countdown("")
            self.version = version
            label = settings.labels[version]
            for step in self.steps.values():
                step.set("pending")
            self.steps["start"].name.setText("Start {}".format(label))
            self.caution.hide()
            self.exit.hide()
            self.show_page(self.progress_page, "Starting {}".format(label), PROGRESS_NOTE)
            self.advance("build")
            self.spin.start()
            self.task = Task(lambda report: self.session.run(
                version, lambda message: report(self.session.stage, message)))
            self.task.progress.connect(lambda stage, message: self.advance(stage))
            self.task.done.connect(self.finished)
            self.task.start()

        def advance(self, stage: str) -> None:
            """Mark the stage as running and every earlier one as done."""
            if stage not in self.steps:
                return
            for name in STAGES:
                step = self.steps[name]
                if name == stage:
                    if step.state != "active":
                        step.set("active", "0 s")
                    break
                if step.state in ("pending", "active"):
                    step.set("done", "Done")
            self.caution.setVisible(stage == "write")

        def animate(self) -> None:
            for step in self.steps.values():
                if step.state == "active":
                    step.mark.angle = (step.mark.angle + 18) % 360
                    step.mark.update()
                    status = "{} s".format(int(time.monotonic() - step.started))
                    if step.status.text() != status:
                        step.status.setText(status)

        def finished(self, outcome: object, error: str) -> None:
            self.task.wait()
            if error:
                self.failed(error)
                return
            try:
                self.result = self.session.finish(self.version)
            except ChooserError as problem:
                self.failed(str(problem))
                return
            self.advance("start")
            skipped = {"verified": ("backup", "write"),
                       "recovering": ("build", "check", "backup", "write")}.get(outcome, ())
            for name in skipped:
                self.steps[name].set("skipped", "Not needed")
            if outcome == "recovering":
                self.message.setText("{} finishes its own firmware update when it starts."
                                     .format(settings.labels[self.version]))
            self.handover.start(600)

        def failed(self, error: str) -> None:
            self.spin.stop()
            self.exit.show()
            body, log = split_log(error)
            self.problem.setText(body)
            # Zero-width spaces let a long path wrap at its slashes.
            self.log.setText(log.replace("/", "/​"))
            self.log.setVisible(bool(log))
            self.log_title.setVisible(bool(log))
            self.show_page(self.error_page, "Cannot start {}".format(
                settings.labels.get(self.version, "KneeSpa")), "Neither app was started.")

        def leave(self) -> None:
            self.result = None
            self.close()

        def closeEvent(self, event: object) -> None:
            # Closing mid-flash would orphan avrdude and hide its result.
            if self.task is not None and self.task.isRunning():
                event.ignore()
            else:
                event.accept()

    return Window()


def run_ui(settings: Settings) -> int:
    from PyQt5.QtWidgets import QApplication

    application = QApplication(sys.argv[:1])
    application.setStyle("Fusion")
    window = make_window(settings)
    window.showFullScreen()
    application.exec_()
    if window.result is None:
        return 1
    print("Starting {}: {}".format(window.version, " ".join(window.result[0])))
    try:
        launch(*window.result)
    except OSError as error:
        print("ERROR: could not start {}: {}".format(window.version, error), file=sys.stderr)
        return 1
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
    application.setStyle("Fusion")
    load_fonts(default_app_dir())
    application.setStyleSheet(style_sheet())
    QMessageBox.critical(None, "KneeSpa version chooser", message)
    del application


if __name__ == "__main__":
    sys.exit(main())
