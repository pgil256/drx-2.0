"""Run the deploy script offline against real rsync and disposable device state."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name != "posix", reason="Deployment fixtures require POSIX"),
]
SCRIPT = Path(__file__).resolve().parents[2] / "sync" / "sync_pis.sh"
STATE_SCRIPT = SCRIPT.with_name("sync_device_state.sh")
STATE_FILES = (
    "config/kneespa.cfg", "data/user_pins.csv", "data/auth_state.json",
    "data/pending_uploads.json", "logs/device.log", "__pycache__/module.pyc",
)


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Intercept SSH and redirect rsync to a local destination without changing its filters."""
    rsync = shutil.which("rsync")
    assert rsync is not None, "Install rsync to run deployment regression tests"
    source, target, commands = (tmp_path / name for name in ("source", "target", "bin"))
    for folder in (source, target, commands):
        folder.mkdir()
    target = target / "runtime"
    target.mkdir()
    for relative in ("raspberry-pi/main/kneespa.py", "arduino/motor/motor.ino"):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("shared update")
    trace = tmp_path / "trace.jsonl"
    scripts = {
        "ssh": (
            "import json, os, sys\n"
            "with open(os.environ['DEPLOY_TEST_TRACE'], 'a') as stream:\n"
            "    stream.write(json.dumps(['ssh', *sys.argv[1:]]) + '\\n')\n"
            "if 'systemctl start' in sys.argv[-1]:\n"
            "    sys.exit(int(os.environ.get('DEPLOY_TEST_START_FAILURE', '0')))\n"
            "sys.exit(int(os.environ.get('DEPLOY_TEST_SSH_FAILURE', '0')))\n"
        ),
        "rsync": (
            "import json, os, subprocess, sys\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['DEPLOY_TEST_TRACE'], 'a') as stream:\n"
            "    stream.write(json.dumps(['rsync', *args]) + '\\n')\n"
            "if os.environ.get('DEPLOY_TEST_RSYNC_FAILURE') == '1':\n"
            "    sys.exit(23)\n"
            "prefix = 'fixture@offline.invalid:/fixture/'\n"
            "for index, arg in enumerate(args):\n"
            "    if arg.startswith(prefix):\n"
            "        args[index] = os.environ['DEPLOY_TEST_ROOT'] + '/' + arg[len(prefix):]\n"
            "index = args.index('-e')\n"
            "del args[index:index + 2]\n"
            "sys.exit(subprocess.call([os.environ['DEPLOY_TEST_RSYNC'], *args]))\n"
        ),
    }
    for name, code in scripts.items():
        executable = commands / name
        executable.write_text(f"#!{sys.executable}\n{code}", encoding="utf-8")
        executable.chmod(0o755)
    for key, value in {
        "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
        "SOURCE_DIR": f"{source}/", "DEST_ROOT": "/fixture/",
        "PI_USER": "fixture", "PI_HOSTS": "offline.invalid",
        "SERVICE": "kneespa-fixture.service", "SSH_OPTS": "-o BatchMode=yes",
        "DEPLOY_TEST_TRACE": str(trace), "DEPLOY_TEST_ROOT": str(target.parent),
        "DEPLOY_TEST_RSYNC": rsync,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DEPLOY_TEST_RSYNC_FAILURE", raising=False)
    monkeypatch.delenv("DEPLOY_TEST_SSH_FAILURE", raising=False)
    monkeypatch.delenv("DEPLOY_TEST_START_FAILURE", raising=False)
    monkeypatch.delenv("DEST_DIR", raising=False)
    return SimpleNamespace(source=source, target=target, trace=trace)


def run_deploy(mode: str = "--apply") -> subprocess.CompletedProcess:
    """Run only the intercepted deployment process, with a bounded timeout."""
    args = [mode] if mode else []
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=20)


def trace_events(deployment: SimpleNamespace) -> list:
    """Read the external actions requested by the production script."""
    if not deployment.trace.exists():
        return []
    return [json.loads(line) for line in deployment.trace.read_text().splitlines()]


@pytest.mark.parametrize("source_has_state", [False, True])
def test_sync_preserves_device_state_and_updates_code(
    deployment: SimpleNamespace, source_has_state: bool,
) -> None:
    expected = {}
    for relative in STATE_FILES:
        destination = deployment.target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected[relative] = f"device-specific bytes: {relative}\n".encode()
        destination.write_bytes(expected[relative])
        if source_has_state:
            source = deployment.source / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"conflicting source state must never deploy\n")
    (deployment.target / "obsolete.py").write_text("obsolete code")
    (deployment.target / "current.py").write_text("old code")
    (deployment.source / "current.py").write_text("updated application code")
    sibling = deployment.target.parent / "devices/local/raspberry-pi/config/kneespa.cfg"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("actual device calibration and identity")
    result = run_deploy()
    assert result.returncode == 0, result.stdout + result.stderr
    for relative, content in expected.items():
        assert (deployment.target / relative).read_bytes() == content
    assert not (deployment.target / "obsolete.py").exists()
    assert (deployment.target / "current.py").read_text() == "updated application code"
    assert sibling.read_text() == "actual device calibration and identity"
    assert (deployment.target / "arduino/motor/motor.ino").read_text() == "shared update"
    events = trace_events(deployment)
    assert [event[0] for event in events] == ["ssh", "rsync", "ssh"]
    assert "systemctl stop 'kneespa-fixture.service'" in events[0][-1]
    assert "systemctl start 'kneespa-fixture.service'" in events[-1][-1]


def test_failed_sync_leaves_service_stopped(
    deployment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEPLOY_TEST_RSYNC_FAILURE", "1")
    result = run_deploy()
    assert result.returncode != 0
    assert [event[0] for event in trace_events(deployment)] == ["ssh", "rsync"]
    assert "service left STOPPED" in result.stderr


def test_unreachable_device_does_not_sync_or_restart(
    deployment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEPLOY_TEST_SSH_FAILURE", "255")
    assert run_deploy().returncode != 0
    assert [event[0] for event in trace_events(deployment)] == ["ssh"]


@pytest.mark.parametrize("hosts", [None, "", "   "])
def test_requires_explicit_hosts_before_any_external_action(
    deployment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, hosts: str | None,
) -> None:
    if hosts is None:
        monkeypatch.delenv("PI_HOSTS", raising=False)
    else:
        monkeypatch.setenv("PI_HOSTS", hosts)
    result = run_deploy()
    assert result.returncode != 0
    assert "PI_HOSTS" in result.stderr
    assert not trace_events(deployment)


def test_preview_does_not_stop_service_or_change_files(deployment: SimpleNamespace) -> None:
    (deployment.target / "old.py").write_text("keep until apply")
    result = run_deploy("")
    assert result.returncode == 0, result.stderr
    assert (deployment.target / "old.py").exists()
    assert not (deployment.target / "raspberry-pi").exists()
    assert [event[0] for event in trace_events(deployment)] == ["rsync"]


def test_restart_failure_is_reported(
    deployment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEPLOY_TEST_START_FAILURE", "1")
    result = run_deploy()
    assert result.returncode != 0
    assert "restart failed" in result.stderr


def test_runtime_update_excludes_state_docs_and_build_outputs(deployment: SimpleNamespace) -> None:
    for name in ("devices/local/secret", "development/tests/test.py", "raspberry-pi/main/.env",
                 "arduino/motor/.pio/build.hex", "arduino/motor/test/test.cpp", "guide.md"):
        path = deployment.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must not ship")
    result = run_deploy()
    assert result.returncode == 0, result.stderr
    assert {p.relative_to(deployment.target).as_posix() for p in deployment.target.rglob("*")
            if p.is_file()} == {"raspberry-pi/main/kneespa.py", "arduino/motor/motor.ino"}


@pytest.mark.parametrize("root", ["/", "/fixture/../", "/fixture;bad"])
def test_invalid_destination_rejected_before_ssh(
    deployment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, root: str,
) -> None:
    monkeypatch.setenv("DEST_ROOT", root)
    assert run_deploy().returncode != 0
    assert not trace_events(deployment)


@pytest.mark.parametrize("direction", ["pull", "push"])
def test_state_transfer_is_scoped_to_one_profile_and_category(
    deployment: SimpleNamespace, tmp_path: Path, direction: str,
) -> None:
    script = tmp_path / "checkout/development/sync/sync_device_state.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(STATE_SCRIPT, script)
    local = tmp_path / "checkout/devices/profiles/device-2/raspberry-pi"
    remote = deployment.target.parent / "devices/local/raspberry-pi"
    for folder in (local, remote):
        (folder / "config").mkdir(parents=True)
        (folder / "data").mkdir()
        (folder / "config/kneespa.cfg").write_text(str(folder))
        (folder / "data/user_pins.csv").write_text("credentials unchanged")
    source, destination = (remote, local) if direction == "pull" else (local, remote)
    expected = (source / "config/kneespa.cfg").read_bytes()
    args = ["bash", str(script), direction, "device-2", "offline.invalid", "config"]
    preview = subprocess.run(args, capture_output=True, text=True, timeout=20)
    assert preview.returncode == 0, preview.stderr
    assert (destination / "config/kneespa.cfg").read_bytes() != expected
    assert [e[0] for e in trace_events(deployment)] == ["rsync"]
    result = subprocess.run([*args, "--apply"], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert (destination / "config/kneespa.cfg").read_bytes() == expected
    assert (destination / "data/user_pins.csv").read_text() == "credentials unchanged"
    assert len(list((destination / "config").glob("kneespa.cfg.backup-*"))) == 1


@pytest.mark.parametrize("category", ["logs", "uploads"])
def test_device_generated_records_cannot_be_pushed(
    deployment: SimpleNamespace, category: str,
) -> None:
    result = subprocess.run(
        ["bash", str(STATE_SCRIPT), "push", "device-2", "offline.invalid", category, "--apply"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert not trace_events(deployment)
