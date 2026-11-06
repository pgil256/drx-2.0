"""S2: the post-STOP re-home prompt counts time but never acts on it."""

import pytest

from ui.modals.rehome_prompt import RehomePrompt, format_elapsed
from ui.theme import load_fonts

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def prompt(qtbot, monkeypatch):
    load_fonts()
    monkeypatch.setattr(RehomePrompt, "TICK_MS", 10)
    clock = FakeClock()
    box = RehomePrompt(clock=clock)
    qtbot.addWidget(box)
    box.clock = clock
    return box


@pytest.mark.parametrize("seconds, text", [
    (0, "0:00"), (7.9, "0:07"), (61, "1:01"), (750, "12:30"), (-3, "0:00"),
])
def test_format_elapsed(seconds, text):
    assert format_elapsed(seconds) == text


def test_elapsed_time_is_shown(prompt):
    assert prompt.elapsed_label.text() == "Waiting to re-home: 0:00"
    prompt.clock.now += 95
    prompt.refresh_elapsed()
    assert prompt.elapsed_label.text() == "Waiting to re-home: 1:35"


def test_nothing_happens_when_time_passes(prompt, qtbot):
    requests = []
    prompt.rehome_requested.connect(lambda: requests.append(True))
    prompt.show()
    prompt.clock.now += 3600
    qtbot.waitUntil(lambda: prompt.elapsed_label.text().endswith("60:00"), timeout=1000)
    qtbot.wait(50)
    assert requests == []
    assert prompt.isVisible()


def test_rehome_button_asks_once_and_closes(prompt, qtbot):
    prompt.show()
    with qtbot.waitSignal(prompt.rehome_requested, timeout=1000):
        prompt.rehome_button.click()
    assert not prompt.isVisible()


def test_not_now_closes_without_asking(prompt):
    requests = []
    prompt.rehome_requested.connect(lambda: requests.append(True))
    prompt.show()
    prompt.later_button.click()
    assert requests == [] and not prompt.isVisible()


def test_remaining_load_is_called_out(qtbot):
    load_fonts()
    box = RehomePrompt(load_cleared=False)
    qtbot.addWidget(box)
    texts = [label.text() for label in box.findChildren(type(box.elapsed_label))]
    assert any("did not drop fully" in text for text in texts)
    assert not any("traction was released" in text for text in texts)
    # The dialog grows to fit the extra warning instead of clipping it.
    assert box.minimumHeight() >= box.layout().heightForWidth(box.width())
