"""Unit tests for AgentSignalOutput and SignalDirection domain entities (ADD §4, LLD §8.1)."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.domain.agent_signal import AgentSignalOutput, SignalDirection


def test_signal_direction_enum() -> None:
    """Verify SignalDirection enum members and string representations."""
    assert str(SignalDirection.LONG) == "LONG"
    assert str(SignalDirection.SHORT) == "SHORT"
    assert str(SignalDirection.NO_VIEW) == "NO_VIEW"


def test_agent_signal_output_valid() -> None:
    """Verify standard creation of AgentSignalOutput."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    out = AgentSignalOutput(
        agent_id="trend_agent",
        direction=SignalDirection.LONG,
        confidence=0.85,
        inputs_used={"adx_14": 32.0, "sma_20": 100.0},
        timestamp=now,
        raw_score=1.5,
    )

    assert out.agent_id == "trend_agent"
    assert out.direction == SignalDirection.LONG
    assert out.confidence == 0.85
    assert out.inputs_used["adx_14"] == 32.0
    assert out.timestamp == now
    assert out.raw_score == 1.5


def test_agent_signal_output_confidence_bounds() -> None:
    """Verify confidence must be strictly bounded in [0.0, 1.0]."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    # > 1.0 rejected
    with pytest.raises(ValidationError, match="less than or equal to 1"):
        AgentSignalOutput(
            agent_id="test_agent",
            direction=SignalDirection.LONG,
            confidence=1.05,
            timestamp=now,
        )

    # < 0.0 rejected
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        AgentSignalOutput(
            agent_id="test_agent",
            direction=SignalDirection.SHORT,
            confidence=-0.1,
            timestamp=now,
        )


def test_agent_signal_output_no_view_requires_zero_confidence() -> None:
    """Verify NO_VIEW direction strictly requires confidence=0.0 (FRD-SIG-3)."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    # Valid NO_VIEW with 0.0 confidence
    valid = AgentSignalOutput(
        agent_id="test_agent",
        direction=SignalDirection.NO_VIEW,
        confidence=0.0,
        timestamp=now,
    )
    assert valid.direction == SignalDirection.NO_VIEW
    assert valid.confidence == 0.0

    # Invalid NO_VIEW with non-zero confidence rejected
    with pytest.raises(ValidationError, match=r"NO_VIEW direction must carry confidence=0\.0"):
        AgentSignalOutput(
            agent_id="test_agent",
            direction=SignalDirection.NO_VIEW,
            confidence=0.5,
            timestamp=now,
        )


def test_agent_signal_output_naive_timestamp_rejected() -> None:
    """Verify naive timestamp raises ValidationError."""
    naive = datetime(2026, 1, 1, 12, 0)
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        AgentSignalOutput(
            agent_id="test_agent",
            direction=SignalDirection.LONG,
            confidence=0.7,
            timestamp=naive,
        )


def test_agent_signal_output_immutability() -> None:
    """Verify AgentSignalOutput is frozen and mutation raises error."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    out = AgentSignalOutput(
        agent_id="test_agent",
        direction=SignalDirection.LONG,
        confidence=0.7,
        timestamp=now,
    )
    with pytest.raises(ValidationError):
        out.confidence = 0.9


def test_agent_signal_output_extra_fields_forbidden() -> None:
    """Verify extra attributes are forbidden."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        AgentSignalOutput(
            agent_id="test_agent",
            direction=SignalDirection.LONG,
            confidence=0.7,
            timestamp=now,
            unknown_arg="invalid",  # type: ignore[call-arg]
        )


def test_agent_signal_output_json_serialization() -> None:
    """Verify JSON export and deserialization round-trip."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    out = AgentSignalOutput(
        agent_id="momentum_agent",
        direction=SignalDirection.SHORT,
        confidence=0.62,
        inputs_used={"roc_10": -2.4, "rsi_14": 42.1},
        timestamp=now,
        raw_score=-2.4,
    )

    dumped = out.model_dump_json()
    data = json.loads(dumped)

    assert data["agent_id"] == "momentum_agent"
    assert data["direction"] == "SHORT"
    assert data["confidence"] == 0.62
    assert data["raw_score"] == -2.4

    loaded = AgentSignalOutput.model_validate_json(dumped)
    assert loaded == out
