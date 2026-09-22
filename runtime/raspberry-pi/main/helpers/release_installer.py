"""Validate packages before shutdown; replace software or flash a known Mega afterward."""

import ast
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import traceback
from typing import Callable, Dict, Optional
from uuid import uuid4
import zipfile

from helpers.device_records import read_json, write_json

MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MEGA_APPLICATION_BYTES = 253952
MEGA_BUILD = """[platformio]
src_dir = .
[env:mega]
platform = atmelavr
board = megaatmega2560
framework = arduino
build_src_filter = +<*> -<test/> -<.native-build/>
lib_deps = pfeerick/elapsedMillis@^1.0.6
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def contained(path: Path, root: Path) -> Path:
    """Resolve and check every recursive copy, removal, or rename target."""
    resolved, base = path.resolve(), root.resolve()
    try:
        relative = resolved.relative_to(base)
    except ValueError:
        raise ValueError("The update path is outside its installation directory.") from None
    if not relative.parts or path.is_symlink():
        raise ValueError("Invalid update path.")
    return resolved


def remove_tree(path: Path, root: Path) -> None:
    checked = contained(path, root)
    if checked.exists():
        shutil.rmtree(str(checked))


def extract_package(archive: Path, destination: Path, platform: str) -> Path:
    """Accept explicit folder layouts; never extract links, state, or zip traversal."""
    target = "raspberry-pi" if platform == "raspberry-pi" else "arduino"
    sentinel = "main/kneespa.py" if target == "raspberry-pi" else "motor/motor.ino"
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        names = {entry.filename for entry in entries}
        prefixes = (f"runtime/{target}/", f"{target}/", "")
        matches = [prefix for prefix in prefixes if prefix + sentinel in names]
        if len(matches) != 1:
            raise ValueError(f"The ZIP must contain the complete {target} folder ({sentinel}).")
        prefix = matches[0]
        total, seen, files = 0, set(), []
        for entry in entries:
            raw = entry.orig_filename
            parts = PurePosixPath(raw).parts
            if ("\\" in raw or ":" in raw or raw.startswith("/") or ".." in parts
                    or len(entries) > 20000 or entry.flag_bits & 1):
                raise ValueError("The release ZIP contains an unsafe path or unsupported entry.")
            mode = entry.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("Links and special files are not permitted in releases.")
            if entry.is_dir():
                continue
            if not raw.startswith(prefix):
                raise ValueError("The ZIP includes files outside the selected software folder.")
            relative = PurePosixPath(raw[len(prefix):])
            forbidden = {"devices", ".env", "cloud.env", "kneespa.cfg", ".git", ".venv",
                         "__pycache__", "logs", "uploads", "auth-state.json", "service-pin.json"}
            if any(part.lower() in forbidden or part.endswith((".", " ")) or re.fullmatch(
                    r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
                   for part in relative.parts):
                raise ValueError("The release includes device state or unsupported cached files.")
            key = str(relative).casefold()
            if key in seen or not relative.parts:
                raise ValueError("The release includes duplicate file paths.")
            seen.add(key)
            total += entry.file_size
            if total > MAX_EXPANDED_BYTES or entry.file_size > MAX_EXPANDED_BYTES:
                raise ValueError("The expanded release is too large.")
            if target == "raspberry-pi" and relative.parts[0] not in ("main", "launch.sh"):
                raise ValueError("Software ZIPs may contain only main/ and launch.sh.")
            if target == "arduino" and relative.parts[0] != "motor":
                raise ValueError("Firmware source ZIPs must contain the motor/ project.")
            files.append((entry, relative))
        if shutil.disk_usage(destination.parent).free < total * 2 + 16 * 1024 * 1024:
            raise ValueError("Not enough space to stage and back up this release.")
        destination.mkdir()
        try:
            for entry, relative in files:
                path = contained(destination.joinpath(*relative.parts), destination)
                path.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, path.open("xb") as output:
                    copied = 0
                    while True:
                        block = source.read(64 * 1024)
                        if not block:
                            break
                        copied += len(block)
                        if copied > entry.file_size:
                            raise ValueError("Expanded file size does not match the ZIP directory.")
                        output.write(block)
                if copied != entry.file_size:
                    raise ValueError("Incomplete release archive.")
                path.chmod(0o755 if path.suffix == ".sh" else 0o644)
        except Exception:
            remove_tree(destination, destination.parent)
            raise
    return destination


def validate_hex(path: Path) -> None:
    """Validate Intel HEX checksums and the Mega application region, excluding its bootloader."""
    base, ended, count, addresses = 0, False, 0, set()
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError()
        for line in path.read_text(encoding="ascii").splitlines():
            if ended or not line.startswith(":"):
                raise ValueError()
            record = bytes.fromhex(line[1:])
            if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
                raise ValueError()
            size, address, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
            data = record[4:-1]
            if kind == 0:
                first = base + address
                if first + size > MEGA_APPLICATION_BYTES or any(
                        value in addresses for value in range(first, first + size)):
                    raise ValueError()
                addresses.update(range(first, first + size))
                count += size
            elif kind == 1 and size == 0 and address == 0:
                ended = True
            elif kind in (2, 4) and size == 2 and address == 0:
                base = int.from_bytes(data, "big") << (4 if kind == 2 else 16)
            elif kind not in (3, 5) or size != 4:
                raise ValueError()
        if not ended or not count or 0 not in addresses:
            raise ValueError()
    except (UnicodeError, ValueError):
        raise ValueError("Invalid Mega 2560 application HEX file or bootloader overlap.") from None


def firmware_recovery(state: Path) -> Optional[str]:
    """An unreadable recovery record also requires service, never automatic motion."""
    path = state / "updates/firmware-recovery.json"
    if not path.exists():
        return None
    try:
        record = read_json(path)
        return "reset_required" if record.get("status") == "reset_required" else "flashing"
    except (OSError, ValueError, AttributeError):
        return "flashing"


def tree_hashes(source: Path) -> Dict:
    hashes = {}
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("Links are not permitted in the staged application.")
        if path.is_file():
            hashes[path.relative_to(source).as_posix()] = sha256(path)
    return hashes


class ReleaseInstaller:
    """No installation method is called until the controller has fully shut down."""

    def __init__(self, runtime: Path, state: Path) -> None:
        self.runtime = runtime.resolve()
        self.state = state.resolve()
        self.root = self.state / "updates"

    def _run(self, args: list, log: Path, timeout: int = 120,
             environment: Optional[dict] = None) -> None:
        with log.open("ab") as output:
            try:
                result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=output,
                                        stderr=subprocess.STDOUT, timeout=timeout,
                                        env=environment, check=False)
            except (OSError, subprocess.SubprocessError):
                raise RuntimeError("The update tool failed or timed out. See the local update log.")
        if result.returncode:
            raise RuntimeError("The update tool reported failure. See the local update log.")

    @staticmethod
    def _pio() -> Path:
        candidates = [os.environ.get("KNEESPA_PIO", ""), shutil.which("pio") or "",
                      str(Path.home() / ".platformio/penv/bin/pio"),
                      str(Path.home() / ".local/share/kneespa/platformio/bin/pio")]
        for name in candidates:
            if name and Path(name).is_file() and os.access(name, os.X_OK):
                return Path(name).resolve()
        raise ValueError("PlatformIO is not installed. Provision firmware tools before flashing.")

    @staticmethod
    def avrdude() -> tuple:
        roots = [Path(os.environ.get("PLATFORMIO_CORE_DIR", str(Path.home() / ".platformio")))
                 / "packages/tool-avrdude"]
        candidates = [(shutil.which("avrdude"), Path("/etc/avrdude.conf"))]
        for root in roots:
            for executable in (root / "avrdude", root / "bin/avrdude"):
                for config in (root / "avrdude.conf", root / "etc/avrdude.conf"):
                    candidates.append((str(executable), config))
        for executable, config in candidates:
            if executable and Path(executable).is_file() and config.is_file():
                return str(Path(executable).resolve()), str(config.resolve())
        raise ValueError("avrdude and its configuration are required for Mega 2560 flashing.")

    def prepare(self, path: Path, release: Dict, port: str = "", technician: str = "") -> Dict:
        if (path.is_symlink() or path.stat().st_size != release["size_bytes"]
                or sha256(path) != release["sha256"]):
            raise ValueError("The staged download changed. Download and verify it again.")
        self.root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="prepared-", dir=str(self.root)))
        job = {"release": dict(release), "work": str(work), "platform": release["platform"],
               "technician": technician}
        try:
            if release["platform"] == "raspberry-pi":
                source = extract_package(path, work / "raspberry-pi", "raspberry-pi")
                for required in ("main/kneespa.py", "main/ui/app_shell.py",
                                 "main/config/constants.py", "main/helpers/arduino.py"):
                    if not (source / required).is_file():
                        raise ValueError(
                            "The software archive is missing required application files.")
                for script in source.rglob("*.py"):
                    ast.parse(script.read_bytes(), filename=str(script))
                job["source"] = str(source)
                job["files"] = tree_hashes(source)
            else:
                if not re.fullmatch(r"/dev/tty(?:ACM|USB)\d+", port):
                    raise ValueError(
                        "Select the Mega 2560 USB port; GPIO serial is not a flash port.")
                extension = release["extension"]
                image = work / ("firmware.bin" if extension == ".bin" else "firmware.hex")
                if extension in (".zip", ".ino"):
                    if extension == ".zip":
                        source = extract_package(path, work / "arduino", "arduino") / "motor"
                    else:
                        source = work / "motor"
                        source.mkdir()
                        shutil.copy2(str(path), str(source / "motor.ino"))
                        shutil.copy2(str(self.runtime / "arduino/motor/hx711_sampler.h"),
                                     str(source / "hx711_sampler.h"))
                    if not (source / "hx711_sampler.h").is_file():
                        raise ValueError("The firmware source is missing hx711_sampler.h.")
                    if any(p.suffix.lower() in (".py", ".json") for p in source.rglob("*")):
                        raise ValueError("Firmware source packages cannot contain build hooks.")
                    # Never run uploader-supplied build hooks or change the known board target.
                    (source / "platformio.ini").write_text(MEGA_BUILD, encoding="utf-8")
                    environment = dict(os.environ, PLATFORMIO_BUILD_DIR=str(work / "build"),
                                       PLATFORMIO_WORKSPACE_DIR=str(work / "pio"))
                    self._run([str(self._pio()), "run", "--project-dir", str(source),
                               "--environment", "mega"], work / "build.log", 600, environment)
                    shutil.copy2(str(work / "build/mega/firmware.hex"), str(image))
                else:
                    shutil.copy2(str(path), str(image))
                if image.suffix == ".hex":
                    validate_hex(image)
                elif not 1 < image.stat().st_size <= MEGA_APPLICATION_BYTES:
                    raise ValueError("The binary does not fit the Mega 2560 application region.")
                executable, config = self.avrdude()
                job.update(image=str(image), port=port, avrdude=executable, avrdude_config=config,
                           image_sha256=sha256(image))
            job["prepared_at"] = datetime.now(timezone.utc).isoformat()
            write_json(work / "job.json", job)
            return job
        except Exception:
            # Keep build diagnostics for a failed preparation; no live files have changed.
            raise

    def _record(self, job: Dict, backup: Path) -> None:
        path = self.root / "installed.json"
        try:
            records = read_json(path)
            if not isinstance(records, dict):
                records = {}
        except (OSError, ValueError):
            records = {}
        release = job["release"]
        records[job["platform"]] = {
            key: release[key] for key in ("id", "version", "sha256")
        }
        records[job["platform"]].update(
            installed_at=datetime.now(timezone.utc).isoformat(), backup=str(backup))
        write_json(path, records)

    def install(self, job: Dict, progress: Callable[[str], None]) -> str:
        work = contained(Path(job["work"]), self.root)
        if read_json(work / "job.json", maximum=8 * 1024 * 1024) != job:
            raise ValueError("The prepared update changed. Prepare it again.")
        try:
            message = (self._software(job, work, progress) if job["platform"] == "raspberry-pi"
                       else self._firmware(job, work, progress))
        except Exception:
            try:
                (work / "install-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            except OSError:
                pass
            self._history(job, False)
            raise
        self._history(job, True)
        return message

    def _history(self, job: Dict, success: bool) -> None:
        now = datetime.now(timezone.utc)
        path = self.state / "service-reports" / (
            "hardware-update-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        try:
            write_json(path, {"mode": "update", "platform": job["platform"],
                              "updated_at": now.isoformat(), "technician": job["technician"],
                              "release": job["release"], "installed": success,
                              "work": job["work"]})
        except OSError:
            # A history-write problem must not change an already verified installation outcome.
            pass

    def _software(self, job: Dict, work: Path, progress: Callable[[str], None]) -> str:
        source = contained(Path(job["source"]), work)
        if tree_hashes(source) != job["files"]:
            raise ValueError("The staged application changed. Download and verify it again.")
        target = contained(self.runtime / "raspberry-pi", self.runtime)
        backup = contained(work / "previous-software", work)
        candidate = contained(self.runtime / (".software-next-" + uuid4().hex), self.runtime)
        retired = contained(self.runtime / (".software-old-" + uuid4().hex), self.runtime)
        progress("Backing up the current software…")
        shutil.copytree(str(target), str(backup))
        shutil.copytree(str(source), str(candidate))
        moved = False
        try:
            progress("Activating the verified software…")
            os.replace(target, retired)
            moved = True
            os.replace(candidate, target)
            self._record(job, backup)
        except Exception:
            if moved:
                if target.exists():
                    remove_tree(target, self.runtime)
                os.replace(retired, target)
            raise
        finally:
            if candidate.exists():
                remove_tree(candidate, self.runtime)
        if retired.exists():
            try:
                remove_tree(retired, self.runtime)
            except OSError:
                # The verified target and durable backup are already in place.
                pass
        return "Software installed. Previous software is backed up in " + str(backup)

    def _firmware(self, job: Dict, work: Path, progress: Callable[[str], None]) -> str:
        image = contained(Path(job["image"]), work)
        if sha256(image) != job["image_sha256"]:
            raise ValueError("The compiled firmware changed. Prepare it again.")
        port = Path(job["port"])
        if (not re.fullmatch(r"/dev/tty(?:ACM|USB)\d+", str(port.resolve()))
                or not port.is_char_device() or not os.access(port, os.R_OK | os.W_OK)):
            raise ValueError("The Mega USB port is unavailable or inaccessible.")
        backup, log = work / "previous.hex", work / "flash.log"
        command = [job["avrdude"], "-C", job["avrdude_config"], "-p", "atmega2560",
                   "-c", "wiring", "-P", str(port), "-b", "115200", "-D"]
        write_json(self.root / "firmware-recovery.json", {
            "release_id": job["release"]["id"], "status": "flashing", "backup": str(backup),
        })
        progress("Reading a backup of the Mega firmware…")
        self._run(command + ["-U", f"flash:r:{backup}:i"], log)
        if not backup.is_file() or not backup.stat().st_size:
            raise ValueError("No firmware backup was produced. Flashing was cancelled.")
        progress("Writing and verifying the Mega 2560 firmware…")
        image_format = "i" if image.suffix == ".hex" else "r"
        self._run(command + ["-U", f"flash:w:{image}:{image_format}"], log)
        self._record(job, backup)
        write_json(self.root / "firmware-recovery.json", {
            "release_id": job["release"]["id"], "status": "reset_required", "backup": str(backup),
        })
        return "Firmware written and verified. Restart, then reset unloaded and verify before use."
