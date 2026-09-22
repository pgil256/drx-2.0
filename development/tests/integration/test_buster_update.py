"""Exercise the Buster updater with all package and service commands intercepted."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import List, Tuple

import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name != "posix", reason="Updater uses POSIX flock and permissions"),
]
SCRIPT = Path(__file__).resolve().parents[3] / (
    "devices/maintenance/raspberry-pi/update_buster.py"
)


@pytest.fixture
def maintenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Run the production workflow against a disposable Pi filesystem and command recorder."""
    spec = importlib.util.spec_from_file_location("buster_update_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = tmp_path / "drx with spaces"
    requirements = app / "runtime/raspberry-pi/main/requirements.txt"
    requirements.parent.mkdir(parents=True)
    requirements.write_text("python-dotenv==0.21.1\n")
    apt = tmp_path / "apt"
    (apt / "sources.list.d").mkdir(parents=True)
    (apt / "sources.list").write_text("deb https://example.invalid/raspbian buster main\n")
    os_release = tmp_path / "os-release"
    os_release.write_text('ID=raspbian\nVERSION_CODENAME="buster"\n')
    python = tmp_path / "python3"
    python.touch(mode=0o755)
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(module, "OS_RELEASE", os_release)
    monkeypatch.setattr(module, "APT_ROOT", apt)
    monkeypatch.setattr(module, "SYSTEM_PYTHON", python)
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    masks = []
    monkeypatch.setattr(module.os, "umask", lambda mask: masks.append(mask) or 0o022)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("KNEESPA_APP_DIR", str(app))
    for name in ("KNEESPA_PYTHON", "KNEESPA_DEVICE_DIR", "KNEESPA_SERVICE"):
        monkeypatch.delenv(name, raising=False)
    idle = module.ensure_idle
    monkeypatch.setattr(module, "ensure_idle", lambda runner, service: idle(runner, service, proc))
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=4 * 1024**3))

    class FakeRunner(module.Runner):
        """Intercept every external action; no apt, pip, service, or hardware is touched."""

        def __init__(self) -> None:
            super().__init__()
            self.calls = []
            self.service = "LoadState=loaded\nActiveState=inactive\n"
            self.update_output = "Package lists refreshed\n"
            self.failure = None
            self.venv = False
            self.user_site = True

        def run(self, args: List[str], quiet: bool = False,
                allowed_codes: Tuple[int, ...] = (0,)) -> str:
            self.calls.append(args)
            if self.failure and self.failure in args:
                raise RuntimeError("Simulated failure: " + self.failure)
            if args[0] == "systemctl":
                return self.service
            if module.PYTHON_INFO in args:
                return json.dumps({"version": [3, 7], "venv": self.venv or
                                   "platformio" in args[0], "user_site": self.user_site})
            if args[0] == "dpkg-query":
                return "python3\t3.7.3-1\n"
            if args[-1] == "update":
                return self.update_output
            if args[:2] == ["sudo", "cp"]:
                module.shutil.copyfile(args[-2], args[-1])
            if "venv" in args:
                target = Path(args[-1]) / "bin/python"
                target.parent.mkdir(parents=True)
                target.touch()
            if "freeze" in args:
                return "python-dotenv==0.21.1\n"
            return ""

    runner = FakeRunner()
    monkeypatch.setattr(module, "Runner", lambda: runner)
    monkeypatch.setattr(module.subprocess, "run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--apply"])
    state = app / "devices/local/raspberry-pi"
    return SimpleNamespace(module=module, runner=runner, app=app, apt=apt, state=state,
                           os_release=os_release, python=python, proc=proc, masks=masks)


def test_preview_has_no_writes_or_package_operations(maintenance, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    assert maintenance.module.main() == 0
    assert not maintenance.state.exists()
    assert all(call[1:2] == ["-c"] for call in maintenance.runner.calls)


def test_apply_updates_buster_and_preserves_device_state(maintenance) -> None:
    calibration = maintenance.state / "config/kneespa.cfg"
    calibration.parent.mkdir(parents=True)
    calibration.write_text("private calibration\n")
    assert maintenance.module.main() == 0
    calls = maintenance.runner.calls
    apt_calls = [call for call in calls if "apt-get" in call]
    assert apt_calls[0][-1] == "update"
    assert "--simulate" in apt_calls[1]
    assert apt_calls[2][-1] == "dist-upgrade"
    assert all("--no-remove" in call for call in apt_calls[1:])
    assert "python3.7" in apt_calls[-1]
    installs = [call for call in calls if call[0] == str(maintenance.python)
                and "install" in call]
    assert installs and all("--user" in call for call in installs)
    assert all(call[0] != "sudo" for call in calls if "pip" in call)
    assert all("upload" not in call and "start" not in call and "reboot" not in call
               for call in calls)
    assert calibration.read_text() == "private calibration\n"
    records = list((maintenance.state / "maintenance").iterdir())
    assert len(records) == 1
    assert (records[0] / "SUCCESS").is_file()
    assert (records[0] / "python-before.txt").is_file()
    assert (records[0] / "firmware-tools-after.txt").is_file()
    assert maintenance.masks == [0o077]


@pytest.mark.parametrize("output", [
    "Err:1 https://example.invalid buster Release\n",
    "W: Some index files failed to download. They have been ignored.\n",
    "W: Failed to fetch https://example.invalid/Packages\n",
])
def test_partial_apt_refresh_never_upgrades(maintenance, output: str) -> None:
    maintenance.runner.update_output = output
    assert maintenance.module.main() == 1
    calls = maintenance.runner.calls
    assert not any("dist-upgrade" in call or "install" in call for call in calls)
    assert not list(maintenance.state.glob("maintenance/*/SUCCESS"))


@pytest.mark.parametrize("failure", ["update", "dist-upgrade", "install", "check"])
def test_failure_stops_without_success_or_restart(maintenance, failure: str) -> None:
    maintenance.runner.failure = failure
    assert maintenance.module.main() == 1
    assert not list(maintenance.state.glob("maintenance/*/SUCCESS"))
    assert "firmware-tools-after.txt" not in [p.name for p in maintenance.state.rglob("*")]
    assert not any("start" in call for call in maintenance.runner.calls)


@pytest.mark.parametrize("state", [
    "LoadState=loaded\nActiveState=active\n",
    "LoadState=loaded\nActiveState=activating\n",
    "Failed to connect to bus\n",
])
def test_active_or_unknown_service_blocks_changes(maintenance, state: str) -> None:
    maintenance.runner.service = state
    assert maintenance.module.main() == 1
    assert not maintenance.state.exists()
    assert not any("apt-get" in call for call in maintenance.runner.calls)


def test_desktop_only_install_without_service_is_supported(maintenance) -> None:
    maintenance.runner.service = "LoadState=not-found\nActiveState=inactive\n"
    assert maintenance.module.main() == 0


def test_manual_app_process_blocks_changes(maintenance) -> None:
    command = maintenance.proc / "321/cmdline"
    command.parent.mkdir()
    command.write_bytes(b"python3\0/home/pi/drx/runtime/raspberry-pi/main/kneespa.py\0")
    assert maintenance.module.main() == 1
    assert not maintenance.state.exists()


def test_shared_launcher_lock_blocks_changes(maintenance) -> None:
    import fcntl
    lock = maintenance.state / "logs/desktop-launch.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert maintenance.module.main() == 1
    assert not any("apt-get" in call for call in maintenance.runner.calls)


def test_wrong_os_blocks_even_preview(maintenance, monkeypatch) -> None:
    maintenance.os_release.write_text("ID=raspbian\nVERSION_CODENAME=bookworm\n")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    assert maintenance.module.main() == 1
    assert maintenance.runner.calls == []


@pytest.mark.parametrize("suite", ["bookworm", "stable", "trixie"])
def test_non_buster_repository_is_rejected(maintenance, suite: str) -> None:
    (maintenance.apt / "sources.list").write_text(
        "deb [arch=armhf signed-by=/key] https://example.invalid/ " + suite + " main\n"
    )
    assert maintenance.module.main() == 1
    assert maintenance.runner.calls == []


def test_deb822_sources_and_disabled_entries(maintenance) -> None:
    source = maintenance.apt / "sources.list.d/extra.sources"
    source.write_text("Types: deb\nURIs: https://example.invalid/\nSuites: stable\n"
                      "Enabled: no\n\nTypes: deb\nSuites: buster\n buster-updates\n")
    maintenance.module.check_sources(maintenance.apt)
    source.write_text("Types: deb\nSuites: trixie\n")
    with pytest.raises(RuntimeError, match="trixie"):
        maintenance.module.check_sources(maintenance.apt)


def test_virtualenv_gets_no_user_install_flag(maintenance) -> None:
    maintenance.runner.venv = True
    assert maintenance.module.main() == 0
    assert all("--user" not in call for call in maintenance.runner.calls)


def test_disabled_user_site_is_rejected(maintenance) -> None:
    maintenance.runner.user_site = False
    assert maintenance.module.main() == 1
    assert not maintenance.state.exists()


def test_skip_firmware_tools(maintenance, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--apply", "--skip-firmware-tools"])
    assert maintenance.module.main() == 0
    assert not any("platformio==6.1.19" in call for call in maintenance.runner.calls)


def test_root_invocation_cannot_install_for_wrong_user(maintenance, monkeypatch) -> None:
    monkeypatch.setattr(maintenance.module.os, "geteuid", lambda: 0)
    assert maintenance.module.main() == 1
    assert not maintenance.state.exists()


@pytest.mark.parametrize("mirror", [
    "http://raspbian.raspberrypi.org/raspbian",
    "https://archive.raspbian.org/raspbian/",
    "http://mirrordirector.raspbian.org/raspbian/",
])
def test_legacy_preview_preserves_sources_and_makes_no_writes(
        maintenance, monkeypatch, capsys, mirror: str) -> None:
    source = maintenance.apt / "sources.list"
    original = "deb [arch=armhf signed-by=/key] {} buster main contrib # keep\n".format(mirror)
    original += "# deb {} buster main\n".format(mirror)
    original += "deb http://archive.raspberrypi.org/debian buster main\n"
    original += "deb https://pkgs.tailscale.com/stable/raspbian buster main\n"
    source.write_text(original)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--use-legacy-repository"])
    assert maintenance.module.main() == 0
    assert "Back up " in capsys.readouterr().out
    assert source.read_text() == original
    assert not maintenance.state.exists()
    changes = maintenance.module.legacy_source_changes(maintenance.apt)
    assert len(changes) == 1
    assert changes[0][2] == original.replace(mirror, maintenance.module.LEGACY_URI, 1)
    assert all(call[1:2] == ["-c"] for call in maintenance.runner.calls)


def test_retired_mirror_requires_explicit_repair_option(maintenance, capsys) -> None:
    source = maintenance.apt / "sources.list"
    source.write_text("deb http://raspbian.raspberrypi.org/raspbian buster main\n")
    assert maintenance.module.main() == 1
    assert "--use-legacy-repository" in capsys.readouterr().err
    assert not maintenance.runner.calls
    assert not maintenance.state.exists()


def test_legacy_repair_backs_up_before_apt_and_is_repeatable(maintenance, monkeypatch) -> None:
    source = maintenance.apt / "sources.list"
    original = "deb http://raspbian.raspberrypi.org/raspbian buster main contrib non-free rpi\n"
    source.write_text(original)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--apply", "--use-legacy-repository"])
    assert maintenance.module.main() == 0
    record = next((maintenance.state / "maintenance").iterdir())
    assert (record / "apt-sources/before/sources.list").read_text() == original
    assert source.read_text() == original.replace("http://raspbian.raspberrypi.org/raspbian",
                                                  maintenance.module.LEGACY_URI)
    calls = maintenance.runner.calls
    copies = [i for i, call in enumerate(calls) if call[:2] == ["sudo", "cp"]]
    refresh = next(i for i, call in enumerate(calls) if "apt-get" in call)
    assert len(copies) == 2 and copies[0] < copies[1] < refresh
    assert maintenance.module.legacy_source_changes(maintenance.apt) == []
    assert maintenance.module.main() == 0
    assert sum(call[:2] == ["sudo", "cp"] for call in calls) == 2


def test_source_backup_failure_prevents_rewrite_and_packages(maintenance, monkeypatch) -> None:
    source = maintenance.apt / "sources.list"
    original = "deb http://raspbian.raspberrypi.org/raspbian buster main\n"
    source.write_text(original)
    maintenance.runner.failure = "--preserve=all"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--apply", "--use-legacy-repository"])
    assert maintenance.module.main() == 1
    assert source.read_text() == original
    assert not any("apt-get" in call for call in maintenance.runner.calls)


def test_archive_apt_failure_keeps_backup_and_never_installs(maintenance, monkeypatch) -> None:
    source = maintenance.apt / "sources.list"
    original = "deb http://raspbian.raspberrypi.org/raspbian buster main\n"
    source.write_text(original)
    maintenance.runner.update_output = "W: GPG error: archive signature could not be verified\n"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--apply", "--use-legacy-repository"])
    assert maintenance.module.main() == 1
    record = next((maintenance.state / "maintenance").iterdir())
    assert (record / "apt-sources/before/sources.list").read_text() == original
    assert not (record / "SUCCESS").exists()
    assert not any("install" in call or "dist-upgrade" in call
                   for call in maintenance.runner.calls)


def test_deb822_repair_preserves_disabled_sources_and_signature_options(maintenance) -> None:
    source = maintenance.apt / "sources.list.d/raspbian.sources"
    old = "http://archive.raspbian.org/raspbian/"
    active = ("Types: deb deb-src\nURIs: " + old + "\n"
              " https://example.invalid/raspbian\nSuites: buster\n"
              "Components: main contrib non-free rpi\nSigned-By: /key\n")
    disabled = "\nTypes: deb\nURIs: " + old + "\nSuites: buster\nEnabled: no\n"
    source.write_text(active + disabled)
    maintenance.module.check_sources(maintenance.apt)
    changes = maintenance.module.legacy_source_changes(maintenance.apt)
    assert len(changes) == 1
    assert changes[0][2] == active.replace(old, maintenance.module.LEGACY_URI) + disabled


def test_source_changed_after_plan_is_not_overwritten(maintenance) -> None:
    source = maintenance.apt / "sources.list"
    source.write_text("deb http://raspbian.raspberrypi.org/raspbian buster main\n")
    changes = maintenance.module.legacy_source_changes(maintenance.apt)
    source.write_text("# edited concurrently\n" + source.read_text())
    record = maintenance.app / "record"
    record.mkdir()
    with pytest.raises(RuntimeError, match="changed since preflight"):
        maintenance.module.perform_update(
            maintenance.runner, maintenance.python, ["--user"],
            maintenance.app / "runtime/raspberry-pi/main/requirements.txt", record, False, changes)
    assert source.read_text().startswith("# edited concurrently")
    assert not any("apt-get" in call or "cp" in call for call in maintenance.runner.calls)


def test_symlinked_source_requires_manual_review(maintenance) -> None:
    target = maintenance.apt / "original.list"
    target.write_text("deb http://raspbian.raspberrypi.org/raspbian buster main\n")
    (maintenance.apt / "sources.list.d/link.list").symlink_to(target)
    with pytest.raises(RuntimeError, match="symlinked"):
        maintenance.module.legacy_source_changes(maintenance.apt)
