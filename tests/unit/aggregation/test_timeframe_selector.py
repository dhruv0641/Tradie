"""Unit tests for TimeframeSelector (FRD Module 5, ADD §7.3, LLD §8.3)."""

from datetime import UTC, datetime

import pytest

from src.aggregation.aggregator import SignalAggregator
from src.aggregation.timeframe_selector import TimeframeSelector
from src.config.models import AggregatorConfig
from src.domain.agent_signal import AgentSignalOutput, SignalDirection


def _make_signal(
    agent_id: str,
    direction: SignalDirection,
    confidence: float,
    timestamp: datetime | None = None,
) -> AgentSignalOutput:
    """Helper to instantiate AgentSignalOutput."""
    ts = timestamp or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return AgentSignalOutput(
        agent_id=agent_id,
        direction=direction,
        confidence=confidence,
        timestamp=ts,
    )


def test_timeframe_selector_optimal_timeframe_selection() -> None:
    """Verify timeframe with highest trade quality score is selected."""
    selector = TimeframeSelector()
    per_tf = {
        "5m": [
            _make_signal("trend_agent", SignalDirection.LONG, 0.50),
            _make_signal("momentum_agent", SignalDirection.LONG, 0.50),
        ],
        "15m": [
            _make_signal("trend_agent", SignalDirection.LONG, 0.85),
            _make_signal("momentum_agent", SignalDirection.LONG, 0.85),
        ],
        "1h": [
            _make_signal("trend_agent", SignalDirection.LONG, 0.65),
            _make_signal("momentum_agent", SignalDirection.LONG, 0.65),
        ],
    }

    res = selector.select_best_timeframe(per_tf)

    assert res.passed is True
    assert res.selected_timeframe == "15m"
    assert res.score == pytest.approx(0.85)
    assert res.direction == "BUY"


def test_timeframe_selector_no_timeframe_clears_threshold() -> None:
    """Verify all-rejected timeframes strictly outputs NO_TRADE (FRD-AGG-4)."""
    config = AggregatorConfig(min_quality_threshold=0.50)
    selector = TimeframeSelector(config=config)
    per_tf = {
        "5m": [_make_signal("trend_agent", SignalDirection.LONG, 0.20)],
        "15m": [_make_signal("trend_agent", SignalDirection.LONG, 0.35)],
        "1h": [_make_signal("trend_agent", SignalDirection.LONG, 0.25)],
    }

    res = selector.select_best_timeframe(per_tf)

    assert res.passed is False
    assert res.direction is None
    assert res.score == 0.0
    assert res.selected_timeframe is None
    assert "no timeframe cleared min_quality_threshold" in res.reason
    assert "best rejected: 15m with score 0.3500" in res.reason


def test_timeframe_selector_single_passing_timeframe() -> None:
    """Verify only candidate clearing threshold is selected."""
    config = AggregatorConfig(min_quality_threshold=0.50)
    selector = TimeframeSelector(config=config)
    per_tf = {
        "5m": [_make_signal("trend_agent", SignalDirection.LONG, 0.30)],  # fails
        "15m": [_make_signal("trend_agent", SignalDirection.SHORT, 0.70)],  # passes
    }

    res = selector.select_best_timeframe(per_tf)

    assert res.passed is True
    assert res.selected_timeframe == "15m"
    assert res.direction == "SELL"
    assert res.score == pytest.approx(0.70)


def test_timeframe_selector_tie_breaker_lower_disagreement() -> None:
    """Verify when quality scores tie, timeframe with lower disagreement is chosen."""
    selector = TimeframeSelector()
    per_tf = {
        "5m": [
            # Mean score = (0.90 + 0.50) / 2 = 0.70, Disagreement = 0.20
            _make_signal("trend_agent", SignalDirection.LONG, 0.90),
            _make_signal("momentum_agent", SignalDirection.LONG, 0.50),
        ],
        "15m": [
            # Mean score = (0.70 + 0.70) / 2 = 0.70, Disagreement = 0.00
            _make_signal("trend_agent", SignalDirection.LONG, 0.70),
            _make_signal("momentum_agent", SignalDirection.LONG, 0.70),
        ],
    }

    res = selector.select_best_timeframe(per_tf)

    assert res.passed is True
    assert res.score == pytest.approx(0.70)
    assert res.selected_timeframe == "15m"
    assert res.disagreement == pytest.approx(0.0)


def test_timeframe_selector_empty_inputs() -> None:
    """Verify empty dictionary gracefully outputs NO_TRADE."""
    selector = TimeframeSelector()
    res = selector.select_best_timeframe({})

    assert res.passed is False
    assert res.direction is None
    assert res.score == 0.0
    assert "no candidate timeframes provided" in res.reason


def test_timeframe_selector_custom_aggregator_injection() -> None:
    """Verify dependency injection of custom SignalAggregator."""
    config = AggregatorConfig(min_quality_threshold=0.60)
    aggregator = SignalAggregator(config=config)
    selector = TimeframeSelector(aggregator=aggregator)

    assert selector.config.min_quality_threshold == 0.60
    assert selector.aggregator is aggregator


def test_timeframe_selector_naive_timestamp_raises() -> None:
    """Verify naive timestamp raises ValueError."""
    selector = TimeframeSelector()
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        selector.select_best_timeframe({}, timestamp=datetime(2026, 1, 1, 12, 0))

    per_tf = {"5m": [_make_signal("trend_agent", SignalDirection.LONG, 0.20)]}
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        selector.select_best_timeframe(per_tf, timestamp=datetime(2026, 1, 1, 12, 0))
