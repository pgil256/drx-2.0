"""A push on the footplate reads negative; the sign is display only."""
import pytest

from helpers.measurement_state import is_push, signed_reading
from ui.measurements import signed_text

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("signed_lb, push", [
    (-24.5, True), (-0.5, True), (-0.49, False), (0.0, False), (24.5, False),
    (float("nan"), False), (None, False), ("-24.5", False), (True, False),
])
def test_push_needs_a_finite_sample_outside_the_deadband(signed_lb, push):
    assert is_push({"signed_lb": signed_lb}) is push


@pytest.mark.parametrize("diagnostics", [None, {}, {"valid": True, "age_ms": 0}])
def test_no_signed_sample_reads_as_a_pull(diagnostics):
    assert not is_push(diagnostics)
    assert signed_reading(24.5, diagnostics) == 24.5


def test_magnitude_takes_the_direction_of_the_signed_sample():
    push, pull = {"signed_lb": -24.4}, {"signed_lb": 24.4}
    assert signed_reading(24.5, push) == -24.5
    assert signed_reading(24.5, pull) == 24.5
    # The firmware reports the deadband as zero: it stays an unsigned zero.
    zero = signed_reading(0.0, push)
    assert zero == 0 and str(zero) == "0.0"
    assert signed_reading(None, push) is None


@pytest.mark.parametrize("value, spec, text", [
    (-24.5, ".1f", "−24.5"), (24.5, ".1f", "24.5"), (-0.04, ".1f", "0.0"),
    (0.0, ".1f", "0.0"), (-24.53, "g", "−24.53"), (-0.0, "g", "0"),
])
def test_text_uses_a_true_minus_and_never_signs_zero(value, spec, text):
    assert signed_text(value, spec) == text
