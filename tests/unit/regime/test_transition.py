"""Unit tests for RegimeTransitionFilter hysteresis state machine (MLD §5.2, FRD-REGIME-2)."""

from datetime import UTC, datetime

import pytest

from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RegimeClassification,
    RiskSentiment,
    TrendState,
    VolatilityLevel,
)
from src.regime.transition import RegimeTransitionFilter


def _make_classification(
    *,
    trend: TrendState = TrendState.TRENDING_UP,
    vol: VolatilityLevel = VolatilityLevel.NORMAL,
    bias: DirectionalBias = DirectionalBias.BULLISH,
    liq: LiquidityCondition = LiquidityCondition.NORMAL,
    risk: RiskSentiment = RiskSentiment.RISK_ON,
    instrument: str = "NSE:NIFTY50",
    timeframe: str = "1m",
    minute: int = 0,
) -> RegimeClassification:
    """Helper to create RegimeClassification for hysteresis testing."""
    label = f"{trend.value}_{vol.value}_{bias.value}_{liq.value}"
    return RegimeClassification(
        instrument=instrument,
        timeframe=timeframe,
        timestamp=datetime(2026, 1, 1, 9, minute, tzinfo=UTC),
        trend_state=trend,
        volatility_level=vol,
        directional_bias=bias,
        liquidity_condition=liq,
        risk_sentiment=risk,
        regime_label=label,
        metrics={"adx_14": 30.0},
    )


def test_initial_classification_establishes_baseline() -> None:
    """First classification should establish baseline with is_transition=False."""
    flt = RegimeTransitionFilter()
    c1 = _make_classification()
    res = flt.filter(c1)

    assert not res.is_transition
    assert res.previous_regime is None
    assert res.trend_state == TrendState.TRENDING_UP
    assert res.regime_label == c1.regime_label

    confirmed = flt.get_confirmed_classification("NSE:NIFTY50", "1m")
    assert confirmed is not None
    assert confirmed.regime_label == c1.regime_label
    assert flt.get_last_transition_event("NSE:NIFTY50", "1m") is None


def test_steady_state_no_transition() -> None:
    """Subsequent identical classifications maintain is_transition=False."""
    flt = RegimeTransitionFilter()
    c1 = _make_classification(minute=0)
    c2 = _make_classification(minute=1)

    flt.filter(c1)
    res = flt.filter(c2)

    assert not res.is_transition
    assert res.previous_regime is None
    assert res.regime_label == c1.regime_label


def test_oscillation_suppression_1_cycle_blip() -> None:
    """A 1-cycle blip across boundary is suppressed by 2-cycle hysteresis (FRD-REGIME-2)."""
    flt = RegimeTransitionFilter()
    base = _make_classification(vol=VolatilityLevel.NORMAL, minute=0)
    blip = _make_classification(vol=VolatilityLevel.HIGH, minute=1)
    revert = _make_classification(vol=VolatilityLevel.NORMAL, minute=2)

    # Initial baseline
    flt.filter(base)

    # Cycle 1: Blip to HIGH volatility (candidate count = 1 < 2) -> suppressed!
    res1 = flt.filter(blip)
    assert not res1.is_transition
    assert res1.previous_regime is None
    assert res1.volatility_level == VolatilityLevel.NORMAL
    assert "NORMAL" in res1.regime_label

    # Cycle 2: Revert back to NORMAL -> candidate reset, still NORMAL
    res2 = flt.filter(revert)
    assert not res2.is_transition
    assert res2.previous_regime is None
    assert res2.volatility_level == VolatilityLevel.NORMAL

    # Zero transition events emitted throughout oscillation
    assert len(flt.get_transition_events("NSE:NIFTY50", "1m")) == 0


def test_confirmed_transition_2_consecutive_cycles() -> None:
    """A sustained 2-cycle shift confirms transition and sets is_transition=True (MLD §5.2)."""
    flt = RegimeTransitionFilter()
    base = _make_classification(
        trend=TrendState.TRENDING_UP,
        bias=DirectionalBias.BULLISH,
        minute=0,
    )
    shift1 = _make_classification(
        trend=TrendState.TRENDING_DOWN,
        bias=DirectionalBias.BEARISH,
        minute=1,
    )
    shift2 = _make_classification(
        trend=TrendState.TRENDING_DOWN,
        bias=DirectionalBias.BEARISH,
        minute=2,
    )
    steady = _make_classification(
        trend=TrendState.TRENDING_DOWN,
        bias=DirectionalBias.BEARISH,
        minute=3,
    )

    # Initial
    flt.filter(base)

    # Cycle 1: candidate count = 1 -> suppressed
    res1 = flt.filter(shift1)
    assert not res1.is_transition
    assert res1.trend_state == TrendState.TRENDING_UP

    # Cycle 2: candidate count = 2 -> CONFIRMED TRANSITION!
    res2 = flt.filter(shift2)
    assert res2.is_transition
    assert res2.previous_regime == base.regime_label
    assert res2.trend_state == TrendState.TRENDING_DOWN
    assert res2.directional_bias == DirectionalBias.BEARISH

    event = flt.get_last_transition_event("NSE:NIFTY50", "1m")
    assert event is not None
    assert event.previous_regime == base.regime_label
    assert event.current_regime == res2.regime_label
    assert "trend_state" in event.transitioned_dimensions
    assert "directional_bias" in event.transitioned_dimensions

    # Cycle 3: subsequent steady-state cycle returns to is_transition=False
    res3 = flt.filter(steady)
    assert not res3.is_transition
    assert res3.previous_regime is None
    assert res3.trend_state == TrendState.TRENDING_DOWN


def test_candidate_change_resets_counter() -> None:
    """If candidate changes before reaching hysteresis threshold, counter restarts."""
    flt = RegimeTransitionFilter(hysteresis_cycles=2)
    base = _make_classification(trend=TrendState.TRENDING_UP, minute=0)
    cand_b = _make_classification(trend=TrendState.RANGING, bias=DirectionalBias.NEUTRAL, minute=1)
    cand_c = _make_classification(
        trend=TrendState.TRENDING_DOWN, bias=DirectionalBias.BEARISH, minute=2
    )
    cand_c2 = _make_classification(
        trend=TrendState.TRENDING_DOWN, bias=DirectionalBias.BEARISH, minute=3
    )

    flt.filter(base)

    # Cycle 1: candidate B (count 1) -> output base
    res1 = flt.filter(cand_b)
    assert not res1.is_transition
    assert res1.trend_state == TrendState.TRENDING_UP

    # Cycle 2: candidate changes to C (count 1 for C) -> output base
    res2 = flt.filter(cand_c)
    assert not res2.is_transition
    assert res2.trend_state == TrendState.TRENDING_UP

    # Cycle 3: candidate C repeated (count 2 for C) -> confirms C!
    res3 = flt.filter(cand_c2)
    assert res3.is_transition
    assert res3.previous_regime == base.regime_label
    assert res3.trend_state == TrendState.TRENDING_DOWN


def test_multi_instrument_stream_isolation() -> None:
    """Hysteresis states for separate instruments are strictly isolated."""
    flt = RegimeTransitionFilter(hysteresis_cycles=2)

    nifty_base = _make_classification(instrument="NSE:NIFTY50", minute=0)
    rel_base = _make_classification(instrument="NSE:RELIANCE", minute=0)

    flt.filter(nifty_base)
    flt.filter(rel_base)

    nifty_down = _make_classification(
        instrument="NSE:NIFTY50",
        trend=TrendState.TRENDING_DOWN,
        bias=DirectionalBias.BEARISH,
        minute=1,
    )
    nifty_down2 = _make_classification(
        instrument="NSE:NIFTY50",
        trend=TrendState.TRENDING_DOWN,
        bias=DirectionalBias.BEARISH,
        minute=2,
    )

    flt.filter(nifty_down)
    res_nifty = flt.filter(nifty_down2)

    # NIFTY transitioned
    assert res_nifty.is_transition

    # RELIANCE was untouched and has no transition events
    rel_confirmed = flt.get_confirmed_classification("NSE:RELIANCE", "1m")
    assert rel_confirmed is not None
    assert rel_confirmed.trend_state == TrendState.TRENDING_UP
    assert flt.get_last_transition_event("NSE:RELIANCE", "1m") is None


def test_multi_timeframe_isolation() -> None:
    """Same instrument on different timeframes maintains independent state."""
    flt = RegimeTransitionFilter(hysteresis_cycles=2)

    m1_base = _make_classification(timeframe="1m", minute=0)
    m5_base = _make_classification(timeframe="5m", minute=0)

    flt.filter(m1_base)
    flt.filter(m5_base)

    # 1m transitions
    flt.filter(_make_classification(timeframe="1m", vol=VolatilityLevel.HIGH, minute=1))
    res_1m = flt.filter(_make_classification(timeframe="1m", vol=VolatilityLevel.HIGH, minute=2))
    assert res_1m.is_transition

    # 5m still has NORMAL volatility
    conf_5m = flt.get_confirmed_classification("NSE:NIFTY50", "5m")
    assert conf_5m is not None
    assert conf_5m.volatility_level == VolatilityLevel.NORMAL


def test_ranging_neutral_bias_invariant_preserved() -> None:
    """Confirming TrendState.RANGING enforces DirectionalBias.NEUTRAL (MLD §5.1)."""
    flt = RegimeTransitionFilter(hysteresis_cycles=2)

    base = _make_classification(
        trend=TrendState.TRENDING_UP,
        bias=DirectionalBias.BULLISH,
        minute=0,
    )
    flt.filter(base)

    # Raw tries to supply RANGING with non-neutral bias (or transition triggers RANGING)
    r1 = _make_classification(
        trend=TrendState.RANGING,
        bias=DirectionalBias.BULLISH,  # intentionally non-neutral to test guard
        minute=1,
    )
    r2 = _make_classification(
        trend=TrendState.RANGING,
        bias=DirectionalBias.BULLISH,
        minute=2,
    )

    flt.filter(r1)
    res = flt.filter(r2)

    assert res.is_transition
    assert res.trend_state == TrendState.RANGING
    # DirectionalBias MUST be NEUTRAL per MLD §5.1
    assert res.directional_bias == DirectionalBias.NEUTRAL


def test_configurable_hysteresis_cycles() -> None:
    """Explicit hysteresis_cycles parameter works as expected."""
    # Cycle count = 1: immediate transition on first cycle
    flt1 = RegimeTransitionFilter(hysteresis_cycles=1)
    base = _make_classification(minute=0)
    shift = _make_classification(vol=VolatilityLevel.HIGH, minute=1)

    flt1.filter(base)
    res1 = flt1.filter(shift)
    assert res1.is_transition
    assert res1.volatility_level == VolatilityLevel.HIGH

    # Cycle count = 3: requires 3 consecutive cycles
    flt3 = RegimeTransitionFilter(hysteresis_cycles=3)
    flt3.filter(base)
    shift_b = _make_classification(vol=VolatilityLevel.HIGH, minute=1)

    assert not flt3.filter(shift_b).is_transition
    assert not flt3.filter(shift_b).is_transition
    res3 = flt3.filter(shift_b)
    assert res3.is_transition


def test_invalid_hysteresis_cycles_raises() -> None:
    """Hysteresis cycles < 1 must raise ValueError."""
    with pytest.raises(ValueError, match="hysteresis_cycles must be >= 1"):
        RegimeTransitionFilter(hysteresis_cycles=0)


def test_reset_functionality() -> None:
    """Reset clears stream states and event history."""
    flt = RegimeTransitionFilter(hysteresis_cycles=1)
    c1 = _make_classification(instrument="NSE:A", minute=0)
    c2 = _make_classification(instrument="NSE:B", minute=0)

    flt.filter(c1)
    flt.filter(c2)

    # Reset single stream
    flt.reset(instrument="NSE:A", timeframe="1m")
    assert flt.get_confirmed_classification("NSE:A", "1m") is None
    assert flt.get_confirmed_classification("NSE:B", "1m") is not None

    # Global reset
    flt.reset()
    assert flt.get_confirmed_classification("NSE:B", "1m") is None
    assert len(flt.get_transition_events()) == 0


def test_get_transition_events_queries() -> None:
    """Querying all events vs specific stream events returns proper lists."""
    flt = RegimeTransitionFilter(hysteresis_cycles=1)
    flt.filter(_make_classification(instrument="NSE:A", minute=0))
    flt.filter(_make_classification(instrument="NSE:A", vol=VolatilityLevel.HIGH, minute=1))

    flt.filter(_make_classification(instrument="NSE:B", minute=0))
    flt.filter(_make_classification(instrument="NSE:B", vol=VolatilityLevel.HIGH, minute=1))

    all_ev = flt.get_transition_events()
    assert len(all_ev) == 2

    a_ev = flt.get_transition_events(instrument="NSE:A", timeframe="1m")
    assert len(a_ev) == 1
    assert a_ev[0].instrument == "NSE:A"
