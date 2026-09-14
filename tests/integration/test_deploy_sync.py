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
SCRIPT = Path(__file__).resolve().parents[2] / "rpi" / "sync_pis.sh"
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
    trace = tmp_path / "trace.jsonl"
    scripts = {
        "ssh": (
            "import json, os, sys\n"
            "with open(os.environ['DEPLOY_TEST_TRACE'], 'a') as stream:\n"
            "    stream.write(json.dumps(['ssh', *sys.argv[1:]]) + '\\n')\n"
            "sys.exit(int(os.environ.get('DEPLOY_TEST_SSH_FAILURE', '0')))\n"
        ),
        "rsync": (
            "import json, os, subprocess, sys\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['DEPLOY_TEST_TRACE'], 'a') as stream:\n"
            "    stream.write(json.dumps(['rsync', *args]) + '\\n')\n"
            "if os.environ.get('DEPLOY_TEST_RSYNC_FAILURE') == '1':\n"
            "    sys.exit(23)\n"
            "assert args[-1] == 'fixture@offline.invalid:/fixture/'\n"
            "args[-1] = os.environ['DEPLOY_TEST_TARGET'] + '/'\n"
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
        "SOURCE_DIR": f"{source}/", "DEST_DIR": "/fixture/",
        "PI_USER": "fixture", "PI_HOSTS": "offline.invalid",
        "SERVICE": "kneespa-fixture.service", "SSH_OPTS": "-o BatchMode=yes",
        "DEPLOY_TEST_TRACE": str(trace), "DEPLOY_TEST_TARGET": str(target),
        "DEPLOY_TEST_RSYNC": rsync,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DEPLOY_TEST_RSYNC_FAILURE", raising=False)
    monkeypatch.delenv("DEPLOY_TEST_SSH_FAILURE", raising=False)
    return SimpleNamespace(source=source, target=target, trace=trace)


def run_deploy() -> subprocess.CompletedProcess:
    """Run only the intercepted deployment process, with a bounded timeout."""
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=20)


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
    result = run_deploy()
    assert result.returncode == 0, result.stdout + result.stderr
    for relative, content in expected.items():
        assert (deployment.target / relative).read_bytes() == content
    assert not (deployment.target / "obsolete.py").exists()
    assert (deployment.target / "current.py").read_text() == "updated application code"
    events = trace_events(deployment)
    assert [event[0] for event in events] == ["ssh", "rsync", "ssh"]
    assert "systemctl stop kneespa-fixture.service" in events[0][-1]
    assert "systemctl start kneespa-fixture.service" in events[-1][-1]


def test_failed_sync_leaves_service_stopped(
    deployment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEPLOY_TEST_RSYNC_FAILURE", "1")
    result = run_deploy()
    assert result.returncode != 0
    assert [event[0] for event in trace_events(deployment)] == ["ssh", "rsync"]
    assert "service left STOPPED" in result.stdout


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
