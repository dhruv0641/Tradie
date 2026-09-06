"""Unit tests for SignalAggregator (FRD Module 5, ADD §7, MLD §7, LLD §8.2)."""

from datetime import UTC, datetime

import pytest

from src.aggregation.aggregator import SignalAggregator
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


def test_aggregator_all_agree_buy() -> None:
    """Verify unanimous bullish consensus produces high quality BUY."""
    agg = SignalAggregator()
    signals = [
        _make_signal("trend_agent", SignalDirection.LONG, 0.80),
        _make_signal("momentum_agent", SignalDirection.LONG, 0.80),
        _make_signal("mean_reversion_agent", SignalDirection.LONG, 0.80),
        _make_signal("price_action_agent", SignalDirection.LONG, 0.80),
    ]

    res = agg.aggregate(signals, timeframe="15m")

    assert res.passed is True
    assert res.direction == "BUY"
    assert res.score == pytest.approx(0.80)
    assert res.weighted_score == pytest.approx(0.80)
    assert res.disagreement == pytest.approx(0.0)
    assert len(res.contributing_agents) == 4
    assert res.selected_timeframe == "15m"
    assert "cleared min_quality_threshold" in res.reason


def test_aggregator_all_agree_sell() -> None:
    """Verify unanimous bearish consensus produces high quality SELL."""
    agg = SignalAggregator()
    signals = [
        _make_signal("trend_agent", SignalDirection.SHORT, 0.90),
        _make_signal("momentum_agent", SignalDirection.SHORT, 0.70),
    ]

    res = agg.aggregate(signals)

    assert res.passed is True
    assert res.direction == "SELL"
    assert res.weighted_score == pytest.approx(-0.80)
    assert res.score == pytest.approx(0.80)
    assert res.disagreement == pytest.approx(0.10)


def test_aggregator_conflicting_signals_deadlock() -> None:
    """Verify equal conflicting signals produce net zero score (deadlock rejection)."""
    agg = SignalAggregator()
    signals = [
        _make_signal("trend_agent", SignalDirection.LONG, 0.80),
        _make_signal("momentum_agent", SignalDirection.LONG, 0.80),
        _make_signal("mean_reversion_agent", SignalDirection.SHORT, 0.80),
        _make_signal("price_action_agent", SignalDirection.SHORT, 0.80),
    ]

    res = agg.aggregate(signals)

    assert res.passed is False
    assert res.direction is None
    assert res.score == 0.0
    assert res.weighted_score == 0.0
    assert res.disagreement == pytest.approx(0.80)
    assert "conflicting conviction resulted in net zero score" in res.reason


def test_aggregator_sub_threshold_quality() -> None:
    """Verify weak signals failing min_quality_threshold produce NO_TRADE."""
    config = AggregatorConfig(min_quality_threshold=0.40)
    agg = SignalAggregator(config=config)
    signals = [
        _make_signal("trend_agent", SignalDirection.LONG, 0.30),
        _make_signal("momentum_agent", SignalDirection.LONG, 0.30),
    ]

    res = agg.aggregate(signals)

    assert res.passed is False
    assert res.direction is None
    assert res.score == pytest.approx(0.30)
    assert "below min_quality_threshold" in res.reason


def test_aggregator_missing_agent_renormalization() -> None:
    """Verify NO_VIEW agents are excluded and remaining weights sum to 1.0 (FRD-SIG-3)."""
    agg = SignalAggregator()
    signals = [
        _make_signal("trend_agent", SignalDirection.NO_VIEW, 0.0),
        _make_signal("momentum_agent", SignalDirection.LONG, 0.60),
        _make_signal("mean_reversion_agent", SignalDirection.LONG, 0.60),
        _make_signal("price_action_agent", SignalDirection.LONG, 0.60),
    ]

    res = agg.aggregate(signals)

    assert res.passed is True
    assert res.direction == "BUY"
    assert res.score == pytest.approx(0.60)
    assert res.contributing_agents == [
        "momentum_agent",
        "mean_reversion_agent",
        "price_action_agent",
    ]
    assert sum(res.agent_weights.values()) == pytest.approx(1.0)
    assert res.agent_weights["momentum_agent"] == pytest.approx(1.0 / 3.0)


def test_aggregator_single_agent_disagreement_zero() -> None:
    """Verify single responding agent yields 0.0 disagreement."""
    agg = SignalAggregator()
    signals = [_make_signal("price_action_agent", SignalDirection.LONG, 0.75)]

    res = agg.aggregate(signals)

    assert res.passed is True
    assert res.direction == "BUY"
    assert res.score == pytest.approx(0.75)
    assert res.disagreement == 0.0
    assert res.agent_weights["price_action_agent"] == 1.0


def test_aggregator_empty_or_all_no_view() -> None:
    """Verify empty or all-NO_VIEW inputs safely yield NO_TRADE."""
    agg = SignalAggregator()

    # Empty list
    res_empty = agg.aggregate([])
    assert res_empty.passed is False
    assert res_empty.direction is None
    assert res_empty.score == 0.0
    assert res_empty.contributing_agents == []

    # All NO_VIEW
    signals_noview = [
        _make_signal("trend_agent", SignalDirection.NO_VIEW, 0.0),
        _make_signal("momentum_agent", SignalDirection.NO_VIEW, 0.0),
    ]
    res_noview = agg.aggregate(signals_noview)
    assert res_noview.passed is False
    assert res_noview.direction is None
    assert res_noview.score == 0.0


def test_aggregator_custom_weights() -> None:
    """Verify custom agent weights influence aggregate score."""
    config = AggregatorConfig(
        agent_weights={
            "trend_agent": 0.80,
            "momentum_agent": 0.20,
        },
        min_quality_threshold=0.40,
    )
    agg = SignalAggregator(config=config)
    signals = [
        _make_signal("trend_agent", SignalDirection.LONG, 0.90),
        _make_signal("momentum_agent", SignalDirection.SHORT, 0.50),
    ]

    res = agg.aggregate(signals)

    # Expected: 0.80 * 0.90 - 0.20 * 0.50 = 0.72 - 0.10 = 0.62
    assert res.passed is True
    assert res.direction == "BUY"
    assert res.weighted_score == pytest.approx(0.62)
    assert res.score == pytest.approx(0.62)


def test_aggregator_zero_weights_fallback() -> None:
    """Verify fallback to equal weighting when total configured weight is zero."""
    config = AggregatorConfig(
        agent_weights={
            "trend_agent": 0.0,
            "momentum_agent": 0.0,
        }
    )
    agg = SignalAggregator(config=config)
    signals = [
        _make_signal("trend_agent", SignalDirection.LONG, 0.80),
        _make_signal("momentum_agent", SignalDirection.LONG, 0.60),
    ]

    res = agg.aggregate(signals)

    assert res.passed is True
    assert res.weighted_score == pytest.approx(0.70)
    assert res.agent_weights["trend_agent"] == 0.50
    assert res.agent_weights["momentum_agent"] == 0.50


def test_aggregator_invalid_timestamp_raises() -> None:
    """Verify naive timestamp raises ValueError."""
    agg = SignalAggregator()
    signals = [_make_signal("trend_agent", SignalDirection.LONG, 0.80)]

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        agg.aggregate(signals, timestamp=datetime(2026, 1, 1, 12, 0))


def test_aggregator_zero_confidence_filtered() -> None:
    """Verify directional signal with zero confidence is defensively filtered."""
    agg = SignalAggregator()
    # LONG with 0.0 confidence (defensively treated as NO_VIEW)
    signals = [
        _make_signal("trend_agent", SignalDirection.LONG, 0.0),
        _make_signal("momentum_agent", SignalDirection.LONG, 0.80),
    ]

    res = agg.aggregate(signals)

    assert res.passed is True
    assert res.direction == "BUY"
    assert res.contributing_agents == ["momentum_agent"]
    assert res.agent_weights["momentum_agent"] == 1.0
