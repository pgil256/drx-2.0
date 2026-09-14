"""Opt-in collaborators for protocol unit tests."""

import pytest

import helpers.protocols as protocols_module
from fixtures.protocol_clock import ProtocolClock


@pytest.fixture
def protocol_clock(monkeypatch: pytest.MonkeyPatch) -> ProtocolClock:
    """Replace only the protocol module's clock for tests that request it."""
    clock = ProtocolClock()
    monkeypatch.setattr(protocols_module, "time", clock)
    return clock
