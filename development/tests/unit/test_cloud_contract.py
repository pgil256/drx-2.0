"""Executable September 15 cloud handoff contract and atomic UI application."""

from datetime import datetime, timedelta, timezone
from functools import partial
from uuid import uuid4

import pytest

from fixtures.controllers import make_stub
from helpers.cloud_contract import SETTING_RULES, parse_timestamp, validate_patient
from kneespa import KneeSpa
from ui.screens.treatment import TreatmentScreen

pytestmark = pytest.mark.unit


def patient_response():
    return {"patient_id": str(uuid4()), "display_name": "Example Patient", "external_ref": None,
            "settings": {"protocol_number": 4, "duration_min": 12, "max_pressure_lb": "50.0",
                         "max_left_deg": "0.0", "max_right_deg": "20.0", "pulse_rate_hz": "2.40"}}


@pytest.mark.parametrize("protocol", [1, 2, 3, 4])
@pytest.mark.parametrize("pulse", ["0", "0.2", "2.4", "2.6", "5"])
def test_valid_cloud_plan_selects_protocol_and_preserves_zero_angles(qtbot, protocol, pulse):
    window = make_stub()
    view = TreatmentScreen()
    qtbot.addWidget(view)
    window.shell.treatment = view
    view.protocol_selected.connect(partial(KneeSpa._on_protocol_selected, window))
    response = patient_response()
    response["settings"].update(protocol_number=protocol, pulse_rate_hz=pulse)
    KneeSpa._on_cloud_lookup_done(window, 0, response)
    assert window.cloud_patient["patient_id"] == response["patient_id"]
    assert view.selected_protocol() == protocol
    assert window.protocol_value == str(protocol)
    assert view._proto_buttons[protocol].isChecked()
    values = view.settings_values()
    assert values["pulse_rate"] == float(pulse)
    assert values["max_left"] == 0 and values["max_right"] == 20
    assert values["duration"] == 12 and values["max_pressure"] == 50


@pytest.mark.parametrize("field,value", [
    ("duration_min", 4), ("duration_min", 31), ("duration_min", 12.5),
    ("max_pressure_lb", 9), ("max_pressure_lb", 81), ("max_pressure_lb", "50.5"),
    ("max_left_deg", -1), ("max_left_deg", 21), ("max_right_deg", "1.5"),
    ("pulse_rate_hz", "2.5"), ("pulse_rate_hz", "5.2"), ("pulse_rate_hz", "NaN"),
    ("pulse_rate_hz", "Infinity"), ("protocol_number", 0), ("protocol_number", 5),
    ("protocol_number", True), ("duration_min", None),
])
def test_invalid_plan_never_partially_changes_controls(field, value):
    window = make_stub()
    response = patient_response()
    response["settings"][field] = value
    KneeSpa._on_cloud_lookup_done(window, 0, response)
    assert window.cloud_patient is None
    window.shell.treatment.set_settings.assert_not_called()
    window.shell.treatment.select_protocol.assert_not_called()
    window.shell.treatment.set_patient_error.assert_called_once()


@pytest.mark.parametrize("missing", list(SETTING_RULES) + ["protocol_number"])
def test_missing_setting_rejects_whole_response(missing):
    response = patient_response()
    del response["settings"][missing]
    with pytest.raises(ValueError):
        validate_patient(response)


def test_malformed_identity_rejected_before_settings():
    response = patient_response()
    response["patient_id"] = "not-a-uuid"
    with pytest.raises(ValueError):
        validate_patient(response)


def test_new_lookup_immediately_detaches_old_patient(monkeypatch):
    window = make_stub()
    window._cloud_bridge = type("Bridge", (), {"lookup_done": None})()
    monkeypatch.setattr(
        "kneespa.threading.Thread", lambda **kw: type("Thread", (), {"start": lambda s: None})()
    )
    KneeSpa._on_patient_pin(window, "0123")
    assert window.cloud_patient is None
    assert window._patient_lookup_pending is True


def test_failed_replacement_and_cancel_leave_manual_treatment_unlinked():
    window = make_stub()
    KneeSpa._on_cloud_lookup_done(window, 0, {"error": "settings_not_supported"})
    assert window.cloud_patient is None
    assert not window._patient_lookup_pending
    window.shell.treatment.set_settings.assert_not_called()


def test_contract_matches_all_device_control_ticks():
    from ui.screens.treatment import SETTING_SPECS
    actual = {key: (low, high, str(step)) for key, _, _, low, high, step, _ in SETTING_SPECS}
    assert {key: (low, high, step) for key, low, high, step in SETTING_RULES.values()} == actual


# Python 3.7's fromisoformat rejects "Z" and every fraction width except three
# and six digits, so these would be invalid responses on the Pi without the
# parser. The expected values do not depend on the interpreter version.
@pytest.mark.parametrize("text, microsecond", [
    ("2026-09-15T12:00:00Z", 0),
    ("2026-09-15T12:00:00.5Z", 500000),
    ("2026-09-15T12:00:00.12Z", 120000),
    ("2026-09-15T12:00:00.123Z", 123000),
    ("2026-09-15T12:00:00.1234Z", 123400),
    ("2026-09-15T12:00:00.123456Z", 123456),
    ("2026-09-15T12:00:00.1234567Z", 123456),
    ("2026-09-15T12:00:00.123456789+00:00", 123456),
    ("2026-09-15 12:00:00.5+0000", 500000),
    ("2026-09-15T12:00Z", 0),
])
def test_cloud_timestamp_accepts_any_fraction_width(text, microsecond):
    assert parse_timestamp(text) == datetime(
        2026, 9, 15, 12, 0, 0, microsecond, tzinfo=timezone.utc)


def test_cloud_timestamp_keeps_a_non_utc_offset():
    stamp = parse_timestamp("2026-09-15T08:00:00.5-04:00")
    assert stamp.utcoffset() == timedelta(hours=-4)
    assert stamp == datetime(2026, 9, 15, 12, 0, 0, 500000, tzinfo=timezone.utc)


@pytest.mark.parametrize("text", [
    "2026-09-15T12:00:00", "2026-09-15T12:00:00.5", "2026-09-15", "", "yesterday",
    "2026-09-15T12:00:00.Z", "2026-13-15T12:00:00Z", "2026-09-15T12:00:00Z trailing",
])
def test_cloud_timestamp_requires_a_valid_time_with_an_offset(text):
    with pytest.raises(ValueError):
        parse_timestamp(text)


@pytest.mark.parametrize("value", [None, 1757937600, b"2026-09-15T12:00:00Z"])
def test_cloud_timestamp_rejects_non_strings(value):
    with pytest.raises(TypeError):
        parse_timestamp(value)
