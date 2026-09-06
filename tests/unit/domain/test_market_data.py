"""Unit tests for canonical market data and feature domain entities."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.features import FeatureSet
from src.domain.market_data import (
    CorporateAction,
    MarketDepthLevel,
    MarketDepthQuote,
    OHLCVCandle,
)


@pytest.mark.unit
def test_valid_ohlcv_candle_creation() -> None:
    """Verify clean instantiation of a standard valid candle."""
    candle = OHLCVCandle(
        instrument="NSE:RELIANCE",
        timestamp=datetime(2026, 9, 6, 9, 15, 0, tzinfo=UTC),
        open=Decimal("2950.00"),
        high=Decimal("2965.50"),
        low=Decimal("2945.20"),
        close=Decimal("2960.10"),
        volume=12500,
        turnover=Decimal("37000000.00"),
        timeframe="5m",
    )
    assert candle.instrument == "NSE:RELIANCE"
    assert candle.high >= candle.low
    assert candle.quality_state == "VALIDATED"


@pytest.mark.unit
def test_candle_boundary_violations() -> None:
    """Verify strict rejection of inverted or impossible candle price boundaries."""
    base_time = datetime(2026, 9, 6, 9, 15, 0, tzinfo=UTC)

    # 1. High < Low
    with pytest.raises(ValidationError, match="cannot be less than low price"):
        OHLCVCandle(
            instrument="NSE:RELIANCE",
            timestamp=base_time,
            open=Decimal("2950.00"),
            high=Decimal("2940.00"),
            low=Decimal("2950.00"),
            close=Decimal("2945.00"),
            volume=100,
            timeframe="1m",
        )

    # 2. Open < Low
    with pytest.raises(ValidationError, match="must be between low"):
        OHLCVCandle(
            instrument="NSE:RELIANCE",
            timestamp=base_time,
            open=Decimal("2930.00"),
            high=Decimal("2960.00"),
            low=Decimal("2940.00"),
            close=Decimal("2950.00"),
            volume=100,
            timeframe="1m",
        )

    # 3. Close > High
    with pytest.raises(ValidationError, match="must be between low"):
        OHLCVCandle(
            instrument="NSE:RELIANCE",
            timestamp=base_time,
            open=Decimal("2950.00"),
            high=Decimal("2960.00"),
            low=Decimal("2940.00"),
            close=Decimal("2970.00"),
            volume=100,
            timeframe="1m",
        )


@pytest.mark.unit
def test_candle_negative_values_and_naive_timestamp() -> None:
    """Verify rejection of negative prices, volume, or naive datetimes."""
    # Naive timestamp (no tzinfo)
    with pytest.raises(ValidationError, match="Timestamp must be timezone-aware UTC"):
        OHLCVCandle(
            instrument="NSE:NIFTY",
            timestamp=datetime(2026, 9, 6, 9, 15, 0),  # Naive
            open=Decimal("24500.00"),
            high=Decimal("24550.00"),
            low=Decimal("24480.00"),
            close=Decimal("24520.00"),
            volume=100,
            timeframe="1m",
        )

    # Negative volume
    with pytest.raises(ValidationError):
        OHLCVCandle(
            instrument="NSE:NIFTY",
            timestamp=datetime(2026, 9, 6, 9, 15, 0, tzinfo=UTC),
            open=Decimal("24500.00"),
            high=Decimal("24550.00"),
            low=Decimal("24480.00"),
            close=Decimal("24520.00"),
            volume=-5,
            timeframe="1m",
        )


@pytest.mark.unit
def test_market_depth_quote_validation() -> None:
    """Verify order book depth ladder creation and spread validation."""
    ts = datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC)
    bids = [
        MarketDepthLevel(price=Decimal("2950.00"), quantity=500, orders_count=3),
        MarketDepthLevel(price=Decimal("2949.50"), quantity=1200, orders_count=5),
    ]
    asks = [
        MarketDepthLevel(price=Decimal("2950.50"), quantity=800, orders_count=4),
        MarketDepthLevel(price=Decimal("2951.00"), quantity=1500, orders_count=7),
    ]

    quote = MarketDepthQuote(
        instrument="NSE:RELIANCE",
        timestamp=ts,
        bids=bids,
        asks=asks,
    )
    assert len(quote.bids) == 2
    assert len(quote.asks) == 2

    # Inverted order book (bid > ask)
    invalid_bids = [MarketDepthLevel(price=Decimal("2955.00"), quantity=100)]
    with pytest.raises(ValidationError, match="Inverted order book"):
        MarketDepthQuote(
            instrument="NSE:RELIANCE",
            timestamp=ts,
            bids=invalid_bids,
            asks=asks,
        )


@pytest.mark.unit
def test_corporate_action_model() -> None:
    """Verify corporate action model and ratio factor."""
    ca = CorporateAction(
        instrument="NSE:TCS",
        ex_date=datetime(2026, 9, 15, 0, 0, 0, tzinfo=UTC),
        action_type="BONUS",
        adjustment_factor=Decimal("0.5"),
    )
    assert ca.action_type == "BONUS"
    assert ca.adjustment_factor == Decimal("0.5")


@pytest.mark.unit
def test_feature_set_model() -> None:
    """Verify feature set immutability, quality score, and serialization."""
    ts = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    features = {
        "rsi_14": 58.4,
        "macd_hist": 1.25,
        "atr_14": 12.30,
    }
    fs = FeatureSet(
        instrument="NSE:INFY",
        timestamp=ts,
        timeframe="15m",
        features=features,
        feature_version="feat-v1.0",
        quality_score=0.98,
    )
    assert fs.features["rsi_14"] == 58.4
    assert fs.quality_score == 0.98

    # Ensure frozen
    attr_tf = "timeframe"
    with pytest.raises(ValidationError):
        setattr(fs, attr_tf, "1h")


@pytest.mark.unit
def test_market_data_naive_timestamp_rejections() -> None:
    """Verify that market data models reject naive datetimes without timezone."""
    naive_dt = datetime(2026, 9, 6, 9, 15, 0)

    # MarketDepthQuote
    with pytest.raises(ValidationError, match="Timestamp must be timezone-aware UTC"):
        MarketDepthQuote(
            instrument="NSE:RELIANCE",
            timestamp=naive_dt,
            bids=[],
            asks=[],
        )

    # CorporateAction
    with pytest.raises(ValidationError, match="Ex-date must be timezone-aware UTC"):
        CorporateAction(
            instrument="NSE:TCS",
            ex_date=naive_dt,
            action_type="SPLIT",
            adjustment_factor=Decimal("2.0"),
        )

    # FeatureSet
    with pytest.raises(ValidationError, match="Feature timestamp must be timezone-aware UTC"):
        FeatureSet(
            instrument="NSE:INFY",
            timestamp=naive_dt,
            timeframe="15m",
            features={"rsi": 50.0},
        )
