"""Unit tests for AggregationResult domain model (FRD Module 5, ADD §7)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.domain.aggregation_result import AggregationResult


def test_aggregation_result_passing_buy() -> None:
    """Verify passing BUY aggregation result instantiation and properties."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    res = AggregationResult(
        passed=True,
        score=0.85,
        direction="BUY",
        disagreement=0.10,
        weighted_score=0.85,
        contributing_agents=["trend_agent", "momentum_agent"],
        agent_scores={"trend_agent": 0.80, "momentum_agent": 0.90},
        agent_weights={"trend_agent": 0.50, "momentum_agent": 0.50},
        selected_timeframe="15m",
        reason="cleared min_quality_threshold",
        timestamp=now,
    )

    assert res.passed is True
    assert res.score == 0.85
    assert res.direction == "BUY"
    assert res.disagreement == 0.10
    assert res.weighted_score == 0.85
    assert res.contributing_agents == ["trend_agent", "momentum_agent"]
    assert res.selected_timeframe == "15m"


def test_aggregation_result_passing_sell() -> None:
    """Verify passing SELL aggregation result instantiation."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    res = AggregationResult(
        passed=True,
        score=0.65,
        direction="SELL",
        disagreement=0.15,
        weighted_score=-0.65,
        reason="cleared min_quality_threshold",
        timestamp=now,
    )

    assert res.passed is True
    assert res.score == 0.65
    assert res.direction == "SELL"
    assert res.weighted_score == -0.65


def test_aggregation_result_rejected_no_trade() -> None:
    """Verify rejected opportunity requires direction=None."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    res = AggregationResult(
        passed=False,
        score=0.30,
        direction=None,
        disagreement=0.40,
        weighted_score=0.30,
        reason="below min_quality_threshold",
        timestamp=now,
    )

    assert res.passed is False
    assert res.direction is None
    assert res.score == 0.30


def test_aggregation_result_invariants() -> None:
    """Verify passed/direction consistency and score bounds."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    # passed=True but direction=None
    with pytest.raises(ValidationError, match="passed=True must specify direction"):
        AggregationResult(
            passed=True,
            score=0.70,
            direction=None,
            disagreement=0.10,
            weighted_score=0.70,
            reason="invalid",
            timestamp=now,
        )

    # passed=False but direction="BUY"
    with pytest.raises(ValidationError, match="passed=False must carry direction=None"):
        AggregationResult(
            passed=False,
            score=0.30,
            direction="BUY",
            disagreement=0.10,
            weighted_score=0.30,
            reason="invalid",
            timestamp=now,
        )

    # Score > 1.0
    with pytest.raises(ValidationError):
        AggregationResult(
            passed=True,
            score=1.1,
            direction="BUY",
            disagreement=0.10,
            weighted_score=1.0,
            reason="out of bounds",
            timestamp=now,
        )

    # Disagreement < 0.0
    with pytest.raises(ValidationError):
        AggregationResult(
            passed=True,
            score=0.5,
            direction="BUY",
            disagreement=-0.1,
            weighted_score=0.5,
            reason="negative dispersion",
            timestamp=now,
        )

    # Timestamp missing tzinfo
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        AggregationResult(
            passed=False,
            score=0.2,
            direction=None,
            disagreement=0.0,
            weighted_score=0.0,
            reason="naive timestamp",
            timestamp=datetime(2026, 1, 1, 12, 0),
        )


def test_aggregation_result_immutability() -> None:
    """Verify frozen model disallows in-place mutation."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    res = AggregationResult(
        passed=False,
        score=0.1,
        direction=None,
        disagreement=0.0,
        weighted_score=0.0,
        reason="no view",
        timestamp=now,
    )

    with pytest.raises(ValidationError):
        res.score = 0.9


def test_aggregation_result_json_roundtrip() -> None:
    """Verify JSON serialization and deserialization."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    res = AggregationResult(
        passed=True,
        score=0.75,
        direction="BUY",
        disagreement=0.12,
        weighted_score=0.75,
        contributing_agents=["trend_agent"],
        agent_scores={"trend_agent": 0.75},
        agent_weights={"trend_agent": 1.0},
        selected_timeframe="5m",
        reason="cleared",
        timestamp=now,
    )

    data = res.model_dump_json()
    loaded = AggregationResult.model_validate_json(data)

    assert loaded == res
