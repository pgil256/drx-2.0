# tests/unit/test_arduino_parse.py
import pytest
from unittest.mock import MagicMock, patch

from helpers.arduino import Arduino


@pytest.fixture
def arduino():
    """Create an Arduino instance with mocked serial connection."""
    a = Arduino()
    a.serial_com = MagicMock()
    a.serial_com.is_open = True
    a.connected = True
    return a


@pytest.mark.unit
class TestStatusParsing:
    """Tests for handle_com parsing STATUS_START messages."""

    def test_valid_status_emits_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.status_emit, timeout=1000) as blocker:
            arduino.handle_com("STATUS_START|S|1500|2000|1200|45.3|STATUS_END")
        assert blocker.args == [1500, 2000, 1200, 45.3]

    def test_truncated_status_no_crash(self, arduino):
        """Truncated status (missing STATUS_END) should not crash."""
        arduino.handle_com("STATUS_START|S|1500|2000|1200|45.3")
        # Should not raise

    def test_status_with_zero_pressure(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.status_emit, timeout=1000) as blocker:
            arduino.handle_com("STATUS_START|S|0|0|0|0.0|STATUS_END")
        assert blocker.args == [0, 0, 0, 0.0]

    def test_status_too_few_fields(self, arduino):
        """Status with fewer than 5 tokens after S should not emit."""
        # This should not crash - it just won't emit since len(tokens) < 5
        arduino.handle_com("STATUS_START|S|1500|2000|STATUS_END")


@pytest.mark.unit
class TestDoneResponse:
    """Tests for DONE response parsing."""

    def test_done_emits_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.done_emit, timeout=1000):
            arduino.handle_com("DONE")


@pytest.mark.unit
class TestOKResponse:
    """Tests for OK response parsing."""

    def test_ok_sets_event(self, arduino):
        arduino.ok_event.clear()
        arduino.handle_com("OK")
        assert arduino.ok_event.is_set()

    def test_ok_in_longer_string(self, arduino):
        arduino.ok_event.clear()
        arduino.handle_com("OK received")
        assert arduino.ok_event.is_set()


@pytest.mark.unit
class TestPositionResponse:
    """Tests for position response parsing."""

    def test_position_p_format(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.position_emit, timeout=1000) as blocker:
            arduino.handle_com("P|1500")
        assert blocker.args[0] == 1500

    def test_position_e_format(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.position_emit, timeout=1000) as blocker:
            arduino.handle_com("E|100|200|forward|14")
        assert blocker.args == [100, 200, "forward", 14]


@pytest.mark.unit
class TestPressureResponse:
    """Tests for pressure response parsing."""

    def test_pressure_response(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.pressure_emit, timeout=1000) as blocker:
            arduino.handle_com("PR|45.5")
        assert blocker.args == ["45.5"]


@pytest.mark.unit
class TestWeightResponse:
    """Tests for weight response parsing."""

    def test_weight_response(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.display_weight_emit, timeout=1000) as blocker:
            arduino.handle_com("weight|32.1")
        assert blocker.args == ["32.1"]


@pytest.mark.unit
class TestReadyToGo:
    """Tests for ready-to-go response parsing."""

    def test_ready_to_go(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.ready_to_go_emit, timeout=1000):
            arduino.handle_com("Ready to Go")


@pytest.mark.unit
class TestGarbageInput:
    """Tests for malformed/garbage input."""

    def test_empty_string(self, arduino):
        arduino.handle_com("")
        # Should not crash

    def test_random_garbage(self, arduino):
        arduino.handle_com("xyzabc123!@#")
        # Should not crash

    def test_partial_status_delimiter(self, arduino):
        arduino.handle_com("STATUS_START|")
        # Should not crash
