#!/usr/bin/env python3
"""Maintain Buster with its distro Python; preview unless --apply is supplied.

This standalone tool deliberately does not import KneeSpa or its logging setup,
which would load application/device state. It supports the Pi's Python 3.7.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, TextIO, Tuple


REPO_ROOT = Path(__file__).resolve().parents[3]
OS_RELEASE = Path("/etc/os-release")
APT_ROOT = Path("/etc/apt")
SYSTEM_PYTHON = Path("/usr/bin/python3")
PACKAGING = ["pip==24.0", "setuptools==67.8.0", "wheel==0.42.0"]
SYSTEM_PACKAGES = [
    "python3", "python3-minimal", "python3.7", "python3.7-minimal",
    "python3-dev", "python3-pip", "python3-venv", "python3-pyqt5",
    "python3-rpi.gpio", "vlc", "libvlc5", "alsa-utils", "ca-certificates",
    "build-essential", "psmisc", "zenity",
]
BUSTER_SUITES = {"buster", "buster-updates", "buster-backports", "buster/updates",
                 "buster-security"}
LEGACY_URI = "https://legacy.raspbian.org/raspbian"
OLD_RASPBIAN_URI = (
    r"https?://(?:raspbian\.raspberrypi\.org|archive\.raspbian\.org|"
    r"mirrordirector\.raspbian\.org)/raspbian/?"
)
SourceChange = Tuple[Path, str, str]
PYTHON_INFO = (
    "import json,site,sys; print(json.dumps(dict(version=list(sys.version_info[:2]),"
    "venv=sys.prefix!=sys.base_prefix,user_site=site.ENABLE_USER_SITE)))"
)
IMPORT_CHECK = """
import configparser
import serial
import dotenv
import RPi.GPIO as GPIO
import vlc
from PyQt5 import QtCore, QtWidgets
print('PyQt:', QtCore.PYQT_VERSION_STR, 'Qt:', QtCore.qVersion())
print('GPIO:', GPIO.VERSION, 'VLC:', vlc.libvlc_get_version().decode())
print('Dependency imports passed; no GPIO setup, serial open, or app launch performed.')
"""


def read_os_release(path: Path) -> Dict[str, str]:
    """Read OS metadata without executing shell expressions."""
    return dict(line.split("=", 1) for line in path.read_text().replace('"', '').splitlines()
                if "=" in line and not line.startswith("#"))


def deb822_fields(stanza: str) -> Dict[str, str]:
    """Read APT stanza fields, including continuation lines and disabled entries."""
    fields = {}
    key = ""
    for line in stanza.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() and key:
            fields[key] += " " + line.strip()
        elif ":" in line:
            key, value = line.split(":", 1)
            key = key.lower()
            fields[key] = value.strip()
    return fields


def check_sources(root: Path) -> None:
    """Reject enabled suites that could move this device away from Buster."""
    suites = []
    paths = [root / "sources.list"] + sorted((root / "sources.list.d").glob("*.list"))
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            words = shlex.split(line, comments=True)
            if not words or words[0] not in ("deb", "deb-src"):
                continue
            words = words[1:]
            if words and words[0].startswith("["):
                while words and not words.pop(0).endswith("]"):
                    pass
            if len(words) < 2:
                raise RuntimeError("Malformed APT source in {}".format(path))
            suites.append((path.name, words[1]))
    for path in sorted((root / "sources.list.d").glob("*.sources")):
        for stanza in re.split(r"\n\s*\n", path.read_text()):
            fields = deb822_fields(stanza)
            if fields.get("enabled", "yes").lower() == "no":
                continue
            if fields:
                values = fields.get("suites", "").split()
                if not values:
                    raise RuntimeError("Missing Suites in {}".format(path))
                suites.extend((path.name, suite) for suite in values)
    if not suites:
        raise RuntimeError("No enabled Buster APT sources found.")
    for filename, suite in suites:
        if suite not in BUSTER_SUITES:
            raise RuntimeError("APT source {} uses {!r}, not a Buster suite. "
                               "Review it before updating.".format(filename, suite))


def legacy_source_changes(root: Path) -> List[SourceChange]:
    """Plan exact Buster mirror replacements without changing other sources or options."""
    paths = [root / "sources.list"] + sorted((root / "sources.list.d").glob("*.list"))
    paths += sorted((root / "sources.list.d").glob("*.sources"))
    changes = []
    for path in paths:
        if not path.exists():
            continue
        before = path.read_text()
        if path.suffix == ".sources":
            # Keep stanza separators, comments, Signed-By and other fields verbatim.
            parts = re.split(r"(\n[ \t]*\n)", before)
            for index in range(0, len(parts), 2):
                fields = deb822_fields(parts[index])
                if fields.get("enabled", "yes").lower() == "no":
                    continue
                if set(fields.get("suites", "").split()) != {"buster"}:
                    continue
                lines = parts[index].splitlines(keepends=True)
                uri_field = False
                for number, line in enumerate(lines):
                    if line.lstrip().startswith("#"):
                        continue
                    if not line[:1].isspace():
                        uri_field = line.lower().startswith("uris:")
                    if uri_field:
                        lines[number] = re.sub(
                            r"(?<!\S)" + OLD_RASPBIAN_URI + r"(?=\s|$)", LEGACY_URI, line)
                parts[index] = "".join(lines)
            after = "".join(parts)
        else:
            pattern = (r"^([ \t]*deb(?:-src)?[ \t]+(?:\[[^\]\r\n]*\][ \t]+)?)" +
                       OLD_RASPBIAN_URI + r"([ \t]+buster(?=[ \t]|$))")
            after = re.sub(pattern, lambda match: match[1] + LEGACY_URI + match[2],
                           before, flags=re.MULTILINE)
        if before != after:
            if path.is_symlink():
                raise RuntimeError("Review symlinked APT source manually: {}".format(path))
            changes.append((path, before, after))
    return changes


class Runner:
    """Run commands without a shell, streaming output to the console and a private log."""

    def __init__(self, log: Optional[TextIO] = None) -> None:
        self.log = log

    def run(self, args: List[str], quiet: bool = False,
            allowed_codes: Tuple[int, ...] = (0,)) -> str:
        """Return command output, failing the maintenance run on any command error."""
        if not quiet:
            self.write("$ " + " ".join(shlex.quote(arg) for arg in args) + "\n")
        environment = dict(os.environ, LC_ALL="C", LANG="C", PYTHONUNBUFFERED="1")
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True, env=environment) as process:
            output = []
            for line in process.stdout:
                output.append(line)
                if not quiet:
                    self.write(line)
            status = process.wait()
        result = "".join(output)
        if status not in allowed_codes:
            if quiet:
                self.write(result)
            command = " ".join(shlex.quote(arg) for arg in args[:2])
            raise RuntimeError("Command failed ({}): {}".format(status, command))
        return result

    def write(self, message: str) -> None:
        """Keep progress visible during potentially long package downloads."""
        print(message, end="", flush=True)
        if self.log:
            self.log.write(message)
            self.log.flush()


def choose_python(app: Path) -> Path:
    """Use the same interpreter priority as the desktop launcher."""
    override = os.environ.get("KNEESPA_PYTHON")
    candidates = [Path(override)] if override else [
        app / "kneespa_env/bin/python", app / ".venv/bin/python",
        Path.home() / "kneespa_env/bin/python", SYSTEM_PYTHON,
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            # Do not resolve a venv's symlink: its invocation path selects the venv.
            return candidate.absolute()
    raise RuntimeError("KneeSpa's Python interpreter was not found.")


def python_install_flags(python: Path, runner: Runner) -> List[str]:
    """Protect APT-owned Python packages by using the user's site or an existing venv."""
    info = json.loads(runner.run([str(python), "-c", PYTHON_INFO], quiet=True))
    if info["version"] != [3, 7]:
        raise RuntimeError("This maintenance profile requires Python 3.7: {}".format(python))
    if info["venv"]:
        return []
    if not info["user_site"]:
        raise RuntimeError("Python user packages are disabled; check KNEESPA_PYTHON.")
    return ["--user"]


def ensure_idle(runner: Runner, service: str, proc: Path = Path("/proc")) -> None:
    """Refuse to update a running device; never kill its control process."""
    output = runner.run(["systemctl", "show", "-p", "LoadState", "-p", "ActiveState", service],
                        quiet=True, allowed_codes=(0, 1, 4))
    properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    state = properties.get("ActiveState", "unknown")
    if properties.get("LoadState") not in ("loaded", "masked", "not-found") or state not in (
            "inactive", "failed"):
        raise RuntimeError("Close KneeSpa and stop {} before --apply. "
                           "Reported service state: {}".format(service, state))
    for entry in proc.glob("[0-9]*/cmdline"):
        try:
            arguments = entry.read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        except PermissionError:
            raise RuntimeError("Cannot inspect running processes; cannot confirm KneeSpa is idle.")
        if any(Path(os.fsdecode(arg)).name == "kneespa.py" for arg in arguments if arg):
            raise RuntimeError("Close the running KneeSpa app before --apply.")


def install_dependencies(runner: Runner, python: Path, flags: List[str],
                         requirements: Path) -> None:
    """Install compatible packaging tools and the repository's exact application pins."""
    pip = [str(python), "-m", "pip", "--isolated", "--disable-pip-version-check"]
    runner.run(pip + ["install", "--upgrade"] + flags + PACKAGING)
    runner.run(pip + ["install", "--upgrade", "--no-build-isolation"] + flags +
               ["-r", str(requirements)])
    runner.run(pip + ["check"])
    runner.run([str(python), "-c", IMPORT_CHECK])


def perform_update(runner: Runner, python: Path, flags: List[str], requirements: Path,
                   record: Path, firmware_tools: bool,
                   source_changes: Optional[List[SourceChange]] = None) -> None:
    """Apply signed repository updates, then Python packages, stopping on failure."""
    before = runner.run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], quiet=True)
    (record / "system-before.txt").write_text(before)
    before = runner.run([str(python), "-m", "pip", "--disable-pip-version-check",
                         "freeze", "--all"], quiet=True)
    (record / "python-before.txt").write_text(before)
    shutil.copyfile(str(requirements), str(record / "requirements.txt"))

    for path, before, after in source_changes or []:
        if path.is_symlink() or path.read_text() != before:
            raise RuntimeError("APT source changed since preflight; rerun: {}".format(path))
        relative = path.relative_to(APT_ROOT)
        backup = record / "apt-sources/before" / relative
        replacement = record / "apt-sources/after" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        replacement.parent.mkdir(parents=True, exist_ok=True)
        replacement.write_text(after)
        runner.run(["sudo", "cp", "--preserve=all", "--", str(path), str(backup)])
        # Copy into the existing regular file, retaining its owner and permissions.
        runner.run(["sudo", "cp", "--", str(replacement), str(path)])
        runner.write("Buster archive source installed; original saved at {}\n".format(backup))

    output = runner.run(["sudo", "apt-get", "-o", "APT::Update::Error-Mode=any", "update"])
    # Buster's APT predates Error-Mode=any and may exit zero after a partial failure.
    if re.search(r"^(Err:|[WE]:)", output, re.MULTILINE):
        raise RuntimeError("APT reported repository errors/warnings. No packages were upgraded. "
                           "Review the log; repository and signature checks were not bypassed.")
    apt = ["sudo", "apt-get", "--no-remove", "-o", "Dpkg::Options::=--force-confold"]
    runner.run(apt + ["--simulate", "dist-upgrade"])
    runner.run(apt + ["--assume-yes", "dist-upgrade"])
    runner.run(apt + ["--assume-yes", "install"] + SYSTEM_PACKAGES)
    runner.run([str(SYSTEM_PYTHON), "--version"])
    # Recheck after system updates before running pip against the selected interpreter.
    if python_install_flags(python, runner) != flags:
        raise RuntimeError("The selected Python environment changed during the update.")
    install_dependencies(runner, python, flags, requirements)

    if firmware_tools:
        tool_env = Path.home() / ".local/share/kneespa/platformio"
        tool_python = tool_env / "bin/python"
        if not tool_env.exists():
            runner.run([str(SYSTEM_PYTHON), "-m", "venv", str(tool_env)])
        if not tool_python.is_file():
            raise RuntimeError("Incomplete PlatformIO environment: {}".format(tool_env))
        if python_install_flags(tool_python, runner):
            raise RuntimeError("PlatformIO must have its own virtual environment.")
        pip = [str(tool_python), "-m", "pip", "--isolated", "--disable-pip-version-check"]
        runner.run(pip + ["install", "--upgrade"] + PACKAGING)
        # Let Requires-Python select compatible dependencies; never update AVR packages here.
        runner.run(pip + ["install", "--upgrade", "--upgrade-strategy", "eager",
                          "platformio==6.1.19"])
        runner.run(pip + ["check"])
        runner.run([str(tool_env / "bin/pio"), "--version"])
        packages = runner.run(pip + ["freeze", "--all"], quiet=True)
        (record / "firmware-tools-after.txt").write_text(packages)

    after = runner.run([str(python), "-m", "pip", "--disable-pip-version-check",
                        "freeze", "--all"], quiet=True)
    (record / "python-after.txt").write_text(after)
    after = runner.run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], quiet=True)
    (record / "system-after.txt").write_text(after)
    (record / "SUCCESS").write_text(datetime.now().isoformat() + "\n")


def main() -> int:
    """Preview maintenance or apply it while holding the shared desktop/flash lock."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the printed maintenance")
    parser.add_argument("--skip-firmware-tools", action="store_true",
                        help="leave the private PlatformIO environment unchanged")
    parser.add_argument("--use-legacy-repository", action="store_true",
                        help="back up and replace retired Raspbian Buster mirror URLs")
    args = parser.parse_args()
    runner = Runner()
    try:
        release = read_os_release(OS_RELEASE)
        if release.get("VERSION_CODENAME") != "buster" or release.get("ID") != "raspbian":
            raise RuntimeError("This script targets Raspbian Buster only.")
        check_sources(APT_ROOT)
        source_changes = legacy_source_changes(APT_ROOT)
        if source_changes and not args.use_legacy_repository:
            raise RuntimeError("Retired Raspbian Buster mirror detected. Preview with "
                               "--use-legacy-repository, then add --apply to back up the "
                               "source files and use {}.".format(LEGACY_URI))
        app = Path(os.environ.get("KNEESPA_APP_DIR", str(REPO_ROOT))).resolve()
        requirements = app / "runtime/raspberry-pi/main/requirements.txt"
        if not requirements.is_file():
            raise RuntimeError("Missing {}".format(requirements))
        python = choose_python(app)
        flags = python_install_flags(python, runner)
        service = os.environ.get("KNEESPA_SERVICE", "kneespa.service")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", service):
            raise RuntimeError("Invalid KNEESPA_SERVICE.")
        print("Project: {}\nApplication Python: {}\nInstall scope: {}".format(
            app, python, "user packages" if flags else "existing virtualenv"))
        print("Plan: refresh Buster package lists; simulate and apply upgrades without removals;")
        print("install system Python 3.7, PyQt5, VLC and build dependencies;")
        print("install {} and {}.".format(", ".join(PACKAGING), requirements))
        if not args.skip_firmware_tools:
            print("Maintain PlatformIO 6.1.19 in ~/.local/share/kneespa/platformio.")
        print("System Python stays on Buster's 3.7 packages. Existing config files are kept.")
        print("No OS migration, Arduino flash, app restart, or automatic reboot.")
        if args.use_legacy_repository:
            for path, before, after in source_changes:
                print("Back up {} and replace its retired Buster mirror with {}.".format(
                    path, LEGACY_URI))
            if not source_changes:
                print("No retired Raspbian Buster mirror URLs need replacement.")
        if not args.apply:
            print("Preview only. Close KneeSpa, stop its service if present, then run with --apply.")
            return 0
        if os.geteuid() == 0:
            raise RuntimeError("Run as the KneeSpa desktop user, without sudo; sudo is requested "
                               "only for APT and source-file repair.")
        ensure_idle(runner, service)
        if shutil.disk_usage(str(app)).free < 1024 ** 3:
            raise RuntimeError("At least 1 GiB of free space is required before starting.")
        state = Path(os.environ.get("KNEESPA_DEVICE_DIR", str(app / "devices/local")))
        if not state.is_absolute():
            state = app / "runtime/raspberry-pi/main" / state
        state = state / "raspberry-pi"
        os.umask(0o077)
        (state / "logs").mkdir(parents=True, exist_ok=True)
        import fcntl
        with (state / "logs/desktop-launch.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Close KneeSpa or the firmware updater before maintenance.")
            ensure_idle(runner, service)
            # Prompt on the terminal before redirecting subprocess output into the log.
            subprocess.run(["sudo", "-v"], check=True)
            records = state / "maintenance"
            records.mkdir(parents=True, exist_ok=True)
            record = Path(tempfile.mkdtemp(prefix="buster-" + datetime.now().strftime(
                "%Y%m%d-%H%M%S") + "-", dir=str(records)))
            print("Maintenance log and inventories: {}".format(record))
            with (record / "update.log").open("w") as log:
                runner.log = log
                try:
                    perform_update(runner, python, flags, requirements, record,
                                   not args.skip_firmware_tools, source_changes)
                except Exception as error:
                    runner.write("FAILED: {}\n".format(error))
                    raise
                finally:
                    runner.log = None
        print("SUCCESS: packages installed and dependency imports checked.")
        print("Reboot the Pi during maintenance, then check KneeSpa before treatment use.")
        print("Package inventories are not a full rollback image; retain your SD-card backup.")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        print("Stopped. Completed package changes are not automatically rolled back.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
