"""Unit tests for canonical market regime domain entities (MLD §5.1, DDD §5.1)."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RegimeClassification,
    RegimeTransitionEvent,
    RiskSentiment,
    TrendState,
    VolatilityLevel,
)


def test_regime_enums() -> None:
    """Verify enum members and string values."""
    assert str(TrendState.TRENDING_UP) == "TRENDING_UP"
    assert str(TrendState.TRENDING_DOWN) == "TRENDING_DOWN"
    assert str(TrendState.RANGING) == "RANGING"
    assert str(TrendState.UNKNOWN) == "UNKNOWN"

    assert str(VolatilityLevel.LOW) == "LOW"
    assert str(VolatilityLevel.NORMAL) == "NORMAL"
    assert str(VolatilityLevel.HIGH) == "HIGH"
    assert str(VolatilityLevel.UNKNOWN) == "UNKNOWN"

    assert str(DirectionalBias.BULLISH) == "BULLISH"
    assert str(DirectionalBias.BEARISH) == "BEARISH"
    assert str(DirectionalBias.NEUTRAL) == "NEUTRAL"
    assert str(DirectionalBias.UNKNOWN) == "UNKNOWN"

    assert str(LiquidityCondition.NORMAL) == "NORMAL"
    assert str(LiquidityCondition.DEGRADED) == "DEGRADED"

    assert str(RiskSentiment.RISK_ON) == "RISK_ON"
    assert str(RiskSentiment.RISK_OFF) == "RISK_OFF"
    assert str(RiskSentiment.UNKNOWN) == "UNKNOWN"


def test_regime_classification_instantiation_and_defaults() -> None:
    """Verify valid creation of RegimeClassification with UTC timestamp."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    feat_id = uuid4()
    classification = RegimeClassification(
        instrument="NSE:TCS",
        timeframe="15m",
        timestamp=now,
        trend_state=TrendState.TRENDING_UP,
        volatility_level=VolatilityLevel.NORMAL,
        directional_bias=DirectionalBias.BULLISH,
        liquidity_condition=LiquidityCondition.NORMAL,
        regime_label="TRENDING_UP_NORMAL_VOL",
        metrics={"adx_14": 28.5, "volatility_percentile": 52.0},
        feature_set_id=feat_id,
    )

    assert classification.instrument == "NSE:TCS"
    assert classification.timeframe == "15m"
    assert classification.timestamp == now
    assert classification.trend_state == TrendState.TRENDING_UP
    assert classification.volatility_level == VolatilityLevel.NORMAL
    assert classification.directional_bias == DirectionalBias.BULLISH
    assert classification.liquidity_condition == LiquidityCondition.NORMAL
    assert classification.risk_sentiment == RiskSentiment.UNKNOWN
    assert classification.is_transition is False
    assert classification.previous_regime is None
    assert classification.metrics["adx_14"] == 28.5
    assert classification.feature_set_id == feat_id


def test_regime_classification_immutability() -> None:
    """Verify RegimeClassification is frozen and rejects mutation."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    classification = RegimeClassification(
        instrument="NSE:TCS",
        timeframe="15m",
        timestamp=now,
        trend_state=TrendState.RANGING,
        volatility_level=VolatilityLevel.LOW,
        directional_bias=DirectionalBias.NEUTRAL,
        liquidity_condition=LiquidityCondition.NORMAL,
        regime_label="RANGING_LOW_VOL",
    )

    with pytest.raises(ValidationError):
        classification.trend_state = TrendState.TRENDING_UP


def test_regime_classification_extra_fields_forbidden() -> None:
    """Verify extra attributes are strictly forbidden."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        RegimeClassification(
            instrument="NSE:TCS",
            timeframe="15m",
            timestamp=now,
            trend_state=TrendState.RANGING,
            volatility_level=VolatilityLevel.LOW,
            directional_bias=DirectionalBias.NEUTRAL,
            liquidity_condition=LiquidityCondition.NORMAL,
            regime_label="RANGING_LOW_VOL",
            extra_field="invalid",  # type: ignore[call-arg]
        )


def test_regime_classification_naive_timestamp_rejected() -> None:
    """Verify naive timestamp without timezone raises validation error."""
    naive_time = datetime(2026, 1, 1, 12, 0)
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        RegimeClassification(
            instrument="NSE:TCS",
            timeframe="15m",
            timestamp=naive_time,
            trend_state=TrendState.RANGING,
            volatility_level=VolatilityLevel.LOW,
            directional_bias=DirectionalBias.NEUTRAL,
            liquidity_condition=LiquidityCondition.NORMAL,
            regime_label="RANGING_LOW_VOL",
        )


def test_regime_classification_json_serialization() -> None:
    """Verify JSON export and deserialization round-trip."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    classification = RegimeClassification(
        instrument="NSE:INFY",
        timeframe="5m",
        timestamp=now,
        trend_state=TrendState.TRENDING_DOWN,
        volatility_level=VolatilityLevel.HIGH,
        directional_bias=DirectionalBias.BEARISH,
        liquidity_condition=LiquidityCondition.DEGRADED,
        risk_sentiment=RiskSentiment.RISK_OFF,
        regime_label="TRENDING_DOWN_HIGH_VOL_DEGRADED_LIQ",
        is_transition=True,
        previous_regime="RANGING_NORMAL_VOL",
    )

    json_str = classification.model_dump_json()
    data = json.loads(json_str)

    assert data["instrument"] == "NSE:INFY"
    assert data["trend_state"] == "TRENDING_DOWN"
    assert data["volatility_level"] == "HIGH"
    assert data["directional_bias"] == "BEARISH"
    assert data["liquidity_condition"] == "DEGRADED"
    assert data["risk_sentiment"] == "RISK_OFF"
    assert data["is_transition"] is True
    assert data["previous_regime"] == "RANGING_NORMAL_VOL"

    reconstructed = RegimeClassification.model_validate_json(json_str)
    assert reconstructed == classification


def test_regime_transition_event_instantiation_and_serialization() -> None:
    """Verify RegimeTransitionEvent creation, UTC check, and JSON serialization."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    classification = RegimeClassification(
        instrument="NSE:INFY",
        timeframe="5m",
        timestamp=now,
        trend_state=TrendState.TRENDING_DOWN,
        volatility_level=VolatilityLevel.HIGH,
        directional_bias=DirectionalBias.BEARISH,
        liquidity_condition=LiquidityCondition.DEGRADED,
        risk_sentiment=RiskSentiment.RISK_OFF,
        regime_label="TRENDING_DOWN_HIGH_VOL_DEGRADED_LIQ",
        is_transition=True,
        previous_regime="RANGING_NORMAL_VOL",
    )

    event = RegimeTransitionEvent(
        instrument="NSE:INFY",
        timeframe="5m",
        timestamp=now,
        previous_regime="RANGING_NORMAL_VOL",
        current_regime="TRENDING_DOWN_HIGH_VOL_DEGRADED_LIQ",
        transitioned_dimensions=["trend_state", "directional_bias"],
        classification=classification,
    )

    assert event.instrument == "NSE:INFY"
    assert event.previous_regime == "RANGING_NORMAL_VOL"
    assert event.current_regime == "TRENDING_DOWN_HIGH_VOL_DEGRADED_LIQ"
    assert event.transitioned_dimensions == ["trend_state", "directional_bias"]
    assert event.classification == classification

    # Immutability check
    with pytest.raises(ValidationError):
        event.previous_regime = "ANOTHER_REGIME"

    # JSON round-trip
    dumped = event.model_dump_json()
    loaded = RegimeTransitionEvent.model_validate_json(dumped)
    assert loaded == event


def test_regime_transition_event_naive_timestamp_rejected() -> None:
    """Verify naive timestamp without timezone raises validation error."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    naive = datetime(2026, 1, 1, 12, 0)
    classification = RegimeClassification(
        instrument="NSE:INFY",
        timeframe="5m",
        timestamp=now,
        trend_state=TrendState.TRENDING_DOWN,
        volatility_level=VolatilityLevel.HIGH,
        directional_bias=DirectionalBias.BEARISH,
        liquidity_condition=LiquidityCondition.DEGRADED,
        risk_sentiment=RiskSentiment.RISK_OFF,
        regime_label="TRENDING_DOWN_HIGH_VOL_DEGRADED_LIQ",
    )

    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        RegimeTransitionEvent(
            instrument="NSE:INFY",
            timeframe="5m",
            timestamp=naive,
            previous_regime="RANGING_NORMAL_VOL",
            current_regime="TRENDING_DOWN_HIGH_VOL_DEGRADED_LIQ",
            transitioned_dimensions=["trend_state"],
            classification=classification,
        )
