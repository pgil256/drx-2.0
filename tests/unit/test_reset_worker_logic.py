"""Ordered reset, typed reply proof, bounded replay and cancellation."""
import pytest
from fixtures.nb2 import NB2Controller
from fixtures.reset import make_config, make_main_window
from helpers.reset_worker import ResetWorker

pytestmark = pytest.mark.unit


def run_reset(link):
    worker = ResetWorker(link, make_config(), make_main_window())
    finished, errors = [], []
    worker.signals.finished.connect(finished.append)
    worker.signals.error.connect(errors.append)
    worker.run()
    assert worker.completed.is_set()
    return worker, finished, errors


@pytest.mark.parametrize("v2", [False, True])
def test_full_order_requires_calibration_and_baseline(protocol_clock, v2):
    link = NB2Controller(v2)
    _, finished, errors = run_reset(link)
    assert finished == [True] and not errors
    assert link.commands == ["Y", "L5|0|1900", "K1450", "I131140", "I120",
                             "L01.0", "L1|BASELINE"]
    assert link.baseline_valid


@pytest.mark.parametrize("missing", ["Y", "L5", "K", "I13", "I120", "L0"])
def test_timeout_replays_whole_sequence_once(protocol_clock, missing):
    link = NB2Controller()
    failures = []
    def hook(command, replies):
        if command.startswith(missing) and not failures:
            failures.append(command)
            return []
        return replies
    link.hook = hook
    _, finished, _ = run_reset(link)
    assert finished == [True]
    assert link.commands.count("Y") == 2
    # The first command after the timed-out operation is a full MCU reset.
    first = link.commands.index(failures[0])
    assert link.commands[first + 1] == "Y"


@pytest.mark.parametrize("kind", ["missing", "unstable", "wrong_factor", "no_started", "bare_done"])
def test_failed_baseline_is_fatal_and_never_replayed(protocol_clock, kind):
    link = NB2Controller()
    replies = {"missing": [], "unstable": ["CALIBRATION|TARE|REJECTED|UNSTABLE"],
               "wrong_factor": ["CALIBRATION|TARE|STARTED", "CALIBRATION|TARE|OK|12|2", "DONE"],
               "no_started": ["CALIBRATION|TARE|OK|12|1", "DONE"], "bare_done": ["DONE"]}
    link.hook = lambda command, normal: replies[kind] if command == "L1|BASELINE" else normal
    _, finished, errors = run_reset(link)
    assert finished == [False] and errors
    assert link.commands.count("Y") == 1
    assert link.commands[-1] == "X"
    assert not link.baseline_valid


@pytest.mark.parametrize("command", ["Y", "L5", "K", "I13", "I120", "L0", "L1"])
def test_cancel_at_every_boundary_prevents_continuation(protocol_clock, command):
    link = NB2Controller()
    worker = ResetWorker(link, make_config(), make_main_window())
    finished = []
    worker.signals.finished.connect(finished.append)
    def hook(sent, replies):
        if sent.startswith(command):
            worker.cancel()
        return replies
    link.hook = hook
    worker.run()
    assert finished == [False]
    assert link.commands[-1].startswith(command)
    assert not link.baseline_valid


def test_unknown_firmware_never_receives_calibration(protocol_clock):
    link = NB2Controller()
    link.hook = lambda command, replies: [r for r in replies if not r.startswith("FIRMWARE")]
    _, finished, errors = run_reset(link)
    assert finished == [False] and errors
    assert not any(c.startswith("L") for c in link.commands)


def test_bare_done_cannot_skip_zero_echo(protocol_clock):
    link = NB2Controller()
    link.hook = lambda command, replies: ["DONE"] if command.startswith("L5") else replies
    _, finished, _ = run_reset(link)
    assert finished == [False]
    assert "K1450" not in link.commands
    assert link.commands.count("Y") == 2
