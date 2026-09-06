"""Unit tests for DataValidationPipeline and physical market data sanity rules."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.data.validator import (
    DataValidationPipeline,
    InMemoryQuarantineStore,
)
from src.domain.market_data import OHLCVCandle


def make_candle(
    instrument: str = "NSE:RELIANCE",
    ts: datetime | None = None,
    *,
    open_price: str = "2500.00",
    high_price: str = "2525.00",
    low_price: str = "2490.00",
    close_price: str = "2510.00",
    volume: int = 10000,
    turnover: str = "25100000.00",
    timeframe: str = "1m",
    quality_state: str = "VALIDATED",
) -> OHLCVCandle:
    """Helper factory for valid canonical candles."""
    return OHLCVCandle(
        instrument=instrument,
        timestamp=ts or datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC),
        open=Decimal(open_price),
        high=Decimal(high_price),
        low=Decimal(low_price),
        close=Decimal(close_price),
        volume=volume,
        turnover=Decimal(turnover),
        timeframe=timeframe,
        quality_state=quality_state,  # type: ignore[arg-type]
    )


def test_validator_valid_single_candle() -> None:
    """Verify clean candle passes validation checklist with VALIDATED status."""
    pipeline = DataValidationPipeline()
    candle = make_candle(quality_state="RAW")

    res = pipeline.validate_candle(candle)
    assert res.passed is True
    assert res.status == "VALIDATED"
    assert len(res.reasons) == 0
    assert res.candle.quality_state == "VALIDATED"


def test_validator_valid_sequence_continuity() -> None:
    """Verify consecutive candles within normal return thresholds pass validation."""
    pipeline = DataValidationPipeline(max_price_jump_pct=Decimal("0.20"))
    t0 = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    c1 = make_candle(ts=t0, close_price="2500.00")
    c2 = make_candle(
        ts=t0 + timedelta(minutes=1),
        open_price="2500.00",
        high_price="2520.00",
        low_price="2495.00",
        close_price="2515.00",
    )

    res = pipeline.validate_candle(c2, previous=c1)
    assert res.passed is True
    assert res.status == "VALIDATED"


def test_validator_physical_bound_violations() -> None:
    """Verify detection and quarantine of physical candle boundary contradictions."""
    pipeline = DataValidationPipeline()
    t0 = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    # 1. High < Low
    inv_high_low = OHLCVCandle.model_construct(
        instrument="NSE:TCS",
        timestamp=t0,
        open=Decimal("3800"),
        high=Decimal("3750"),
        low=Decimal("3850"),
        close=Decimal("3800"),
        volume=100,
        turnover=Decimal("380000"),
        timeframe="1m",
        quality_state="RAW",
    )
    res1 = pipeline.validate_candle(inv_high_low)
    assert res1.passed is False
    assert res1.status == "QUARANTINED"
    assert any("less than low price" in r for r in res1.reasons)
    assert res1.candle.quality_state == "QUARANTINED"

    # 2. Open out of [Low, High]
    inv_open = OHLCVCandle.model_construct(
        instrument="NSE:TCS",
        timestamp=t0,
        open=Decimal("3900"),
        high=Decimal("3850"),
        low=Decimal("3750"),
        close=Decimal("3800"),
        volume=100,
        turnover=Decimal("380000"),
        timeframe="1m",
        quality_state="RAW",
    )
    res2 = pipeline.validate_candle(inv_open)
    assert res2.passed is False
    assert any("Open price" in r for r in res2.reasons)

    # 3. Close out of [Low, High]
    inv_close = OHLCVCandle.model_construct(
        instrument="NSE:TCS",
        timestamp=t0,
        open=Decimal("3800"),
        high=Decimal("3850"),
        low=Decimal("3750"),
        close=Decimal("3700"),
        volume=100,
        turnover=Decimal("380000"),
        timeframe="1m",
        quality_state="RAW",
    )
    res3 = pipeline.validate_candle(inv_close)
    assert res3.passed is False
    assert any("Close price" in r for r in res3.reasons)


def test_validator_non_positive_prices() -> None:
    """Verify detection and quarantine of non-positive price components."""
    pipeline = DataValidationPipeline()
    t0 = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    zero_price_candle = OHLCVCandle.model_construct(
        instrument="NSE:INFY",
        timestamp=t0,
        open=Decimal("0.00"),
        high=Decimal("10.00"),
        low=Decimal("0.00"),
        close=Decimal("5.00"),
        volume=100,
        turnover=Decimal("500"),
        timeframe="1m",
        quality_state="RAW",
    )
    res = pipeline.validate_candle(zero_price_candle)
    assert res.passed is False
    assert any("Non-positive price detected" in r for r in res.reasons)


def test_validator_negative_volume_and_turnover() -> None:
    """Verify quarantine of negative volume and negative turnover."""
    pipeline = DataValidationPipeline(allow_zero_volume=False)
    t0 = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    # Negative volume
    neg_vol = OHLCVCandle.model_construct(
        instrument="NSE:SBIN",
        timestamp=t0,
        open=Decimal("750"),
        high=Decimal("760"),
        low=Decimal("740"),
        close=Decimal("755"),
        volume=-10,
        turnover=Decimal("7550"),
        timeframe="1m",
        quality_state="RAW",
    )
    res_vol = pipeline.validate_candle(neg_vol)
    assert res_vol.passed is False
    assert any("Negative volume" in r for r in res_vol.reasons)

    # Disallowed zero volume
    zero_vol = OHLCVCandle.model_construct(
        instrument="NSE:SBIN",
        timestamp=t0,
        open=Decimal("750"),
        high=Decimal("760"),
        low=Decimal("740"),
        close=Decimal("755"),
        volume=0,
        turnover=Decimal("0"),
        timeframe="1m",
        quality_state="RAW",
    )
    res_zero = pipeline.validate_candle(zero_vol)
    assert res_zero.passed is False
    assert any("Zero volume not permitted" in r for r in res_zero.reasons)

    # Negative turnover
    neg_turnover = OHLCVCandle.model_construct(
        instrument="NSE:SBIN",
        timestamp=t0,
        open=Decimal("750"),
        high=Decimal("760"),
        low=Decimal("740"),
        close=Decimal("755"),
        volume=100,
        turnover=Decimal("-500"),
        timeframe="1m",
        quality_state="RAW",
    )
    res_turnover = pipeline.validate_candle(neg_turnover)
    assert res_turnover.passed is False
    assert any("Negative turnover" in r for r in res_turnover.reasons)


def test_validator_comparative_continuity_errors() -> None:
    """Verify detection of sequence discontinuities (symbol, timeframe, timestamp)."""
    pipeline = DataValidationPipeline()
    t0 = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    c1 = make_candle(instrument="NSE:RELIANCE", ts=t0, timeframe="1m")

    # 1. Instrument mismatch
    c_mismatched_sym = make_candle(
        instrument="NSE:TCS", ts=t0 + timedelta(minutes=1), timeframe="1m"
    )
    res_sym = pipeline.validate_candle(c_mismatched_sym, previous=c1)
    assert res_sym.passed is False
    assert any("Instrument mismatch" in r for r in res_sym.reasons)

    # 2. Timeframe mismatch
    c_mismatched_tf = make_candle(
        instrument="NSE:RELIANCE", ts=t0 + timedelta(minutes=5), timeframe="5m"
    )
    res_tf = pipeline.validate_candle(c_mismatched_tf, previous=c1)
    assert res_tf.passed is False
    assert any("Timeframe mismatch" in r for r in res_tf.reasons)

    # 3. Non-monotonic timestamp (equal or earlier)
    c_non_mono = make_candle(
        instrument="NSE:RELIANCE", ts=t0 - timedelta(minutes=1), timeframe="1m"
    )
    res_ts = pipeline.validate_candle(c_non_mono, previous=c1)
    assert res_ts.passed is False
    assert any("Non-monotonic timestamp" in r for r in res_ts.reasons)


def test_validator_extreme_price_spike_filtering() -> None:
    """Verify quarantine of extreme single-bar price jump anomalies (>20% default)."""
    pipeline = DataValidationPipeline(max_price_jump_pct=Decimal("0.20"))
    t0 = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)
    prev = make_candle(
        ts=t0,
        open_price="1000.00",
        high_price="1010.00",
        low_price="995.00",
        close_price="1000.00",
    )

    # 1. 25% upward spike (1000 -> 1250)
    spike_up = make_candle(
        ts=t0 + timedelta(minutes=1),
        open_price="1000.00",
        high_price="1260.00",
        low_price="995.00",
        close_price="1250.00",
    )
    res_up = pipeline.validate_candle(spike_up, previous=prev)
    assert res_up.passed is False
    assert res_up.status == "QUARANTINED"
    assert any("Extreme single-bar price jump" in r for r in res_up.reasons)

    # 2. 25% downward flash crash (1000 -> 750)
    spike_down = make_candle(
        ts=t0 + timedelta(minutes=1),
        open_price="1000.00",
        high_price="1005.00",
        low_price="740.00",
        close_price="750.00",
    )
    res_down = pipeline.validate_candle(spike_down, previous=prev)
    assert res_down.passed is False
    assert any("Extreme single-bar price jump" in r for r in res_down.reasons)

    # 3. Non-positive previous close bypasses percentage jump division
    prev_zero = OHLCVCandle.model_construct(
        instrument="NSE:RELIANCE",
        timestamp=t0,
        open=Decimal("0.00"),
        high=Decimal("0.00"),
        low=Decimal("0.00"),
        close=Decimal("0.00"),
        volume=0,
        turnover=Decimal("0"),
        timeframe="1m",
        quality_state="QUARANTINED",
    )
    res_zero = pipeline.validate_candle(spike_down, previous=prev_zero)
    # Passed because spike_down is valid on its own and jump check was safely bypassed
    assert res_zero.passed is True


def test_validator_sequence_batch_partitioning() -> None:
    """Verify sequence validation separates valid series and quarantined outliers."""
    store = InMemoryQuarantineStore()
    pipeline = DataValidationPipeline(quarantine_store=store, max_price_jump_pct=Decimal("0.20"))
    t0 = datetime(2025, 1, 15, 9, 15, 0, tzinfo=UTC)

    c1 = make_candle(ts=t0, close_price="2500.00")
    c2 = make_candle(ts=t0 + timedelta(minutes=1), close_price="2510.00")
    # Corrupt bar: 30% jump
    c3_corrupt = make_candle(
        ts=t0 + timedelta(minutes=2),
        open_price="2510.00",
        high_price="3300.00",
        low_price="2500.00",
        close_price="3263.00",
    )
    # Valid continuation after c2
    c4 = make_candle(ts=t0 + timedelta(minutes=3), close_price="2515.00")

    valid, quarantined = pipeline.validate_sequence([c1, c2, c3_corrupt, c4])

    assert len(valid) == 3
    assert [c.timestamp for c in valid] == [c1.timestamp, c2.timestamp, c4.timestamp]
    assert len(quarantined) == 1
    assert quarantined[0].candle.timestamp == c3_corrupt.timestamp

    # Verify quarantine store audit tracking
    assert store.count() == 1
    assert len(store.get_all()) == 1
    assert len(store.get_by_instrument("NSE:RELIANCE")) == 1
    assert len(store.get_by_instrument("NSE:TCS")) == 0

    store.clear()
    assert store.count() == 0
