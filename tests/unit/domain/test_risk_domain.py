"""Unit tests for risk domain models in src/domain/risk.py."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.risk import (
    CandidateTrade,
    CapitalState,
    MarketState,
    RiskCheckResult,
    StreakState,
)


def test_candidate_trade_valid_buy() -> None:
    """Test creating a valid BUY candidate trade."""
    now = datetime.now(UTC)
    trade = CandidateTrade(
        instrument="RELIANCE",
        direction="BUY",
        entry_price=Decimal("2500.00"),
        stop_price=Decimal("2450.00"),
        timeframe="15m",
        trade_quality_score=0.85,
        expected_value=Decimal("50.00"),
        confidence=0.75,
        timestamp=now,
    )
    assert trade.instrument == "RELIANCE"
    assert trade.direction == "BUY"
    assert trade.entry_price == Decimal("2500.00")
    assert trade.stop_price == Decimal("2450.00")


def test_candidate_trade_valid_sell() -> None:
    """Test creating a valid SELL candidate trade."""
    now = datetime.now(UTC)
    trade = CandidateTrade(
        instrument="TCS",
        direction="SELL",
        entry_price=Decimal("3500.00"),
        stop_price=Decimal("3550.00"),
        timeframe="5m",
        trade_quality_score=0.70,
        expected_value=Decimal("40.00"),
        confidence=0.65,
        timestamp=now,
    )
    assert trade.direction == "SELL"
    assert trade.stop_price > trade.entry_price


def test_candidate_trade_naive_timestamp_rejection() -> None:
    """Enforce timezone-aware UTC timestamp."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        CandidateTrade(
            instrument="INFY",
            direction="BUY",
            entry_price=Decimal("1500.00"),
            stop_price=Decimal("1480.00"),
            timeframe="15m",
            trade_quality_score=0.80,
            expected_value=Decimal("20.00"),
            confidence=0.70,
            timestamp=datetime(2026, 9, 6, 10, 0, 0),  # Naive
        )


def test_candidate_trade_invalid_stop_loss() -> None:
    """Enforce physical protective stop loss direction relative to entry."""
    now = datetime.now(UTC)
    # BUY with stop >= entry
    with pytest.raises(ValidationError, match="must be strictly below entry"):
        CandidateTrade(
            instrument="INFY",
            direction="BUY",
            entry_price=Decimal("1500.00"),
            stop_price=Decimal("1520.00"),
            timeframe="15m",
            trade_quality_score=0.80,
            expected_value=Decimal("20.00"),
            confidence=0.70,
            timestamp=now,
        )

    # SELL with stop <= entry
    with pytest.raises(ValidationError, match="must be strictly above entry"):
        CandidateTrade(
            instrument="INFY",
            direction="SELL",
            entry_price=Decimal("1500.00"),
            stop_price=Decimal("1480.00"),
            timeframe="15m",
            trade_quality_score=0.80,
            expected_value=Decimal("20.00"),
            confidence=0.70,
            timestamp=now,
        )

    # Identical prices
    with pytest.raises(ValidationError, match="cannot be identical"):
        CandidateTrade(
            instrument="INFY",
            direction="BUY",
            entry_price=Decimal("1500.00"),
            stop_price=Decimal("1500.00"),
            timeframe="15m",
            trade_quality_score=0.80,
            expected_value=Decimal("20.00"),
            confidence=0.70,
            timestamp=now,
        )


def test_capital_state_validation() -> None:
    """Test CapitalState model validation."""
    cap = CapitalState(
        current_capital=Decimal("10000.00"),
        peak_equity=Decimal("10500.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("2000.00"),
        open_position_count=1,
        trades_today=2,
    )
    assert cap.current_capital == Decimal("10000.00")

    # deployed > current_capital
    with pytest.raises(ValidationError, match="cannot exceed current capital"):
        CapitalState(
            current_capital=Decimal("10000.00"),
            peak_equity=Decimal("10500.00"),
            session_start_capital=Decimal("10000.00"),
            currently_deployed=Decimal("12000.00"),
            open_position_count=1,
            trades_today=2,
        )


def test_streak_and_market_state() -> None:
    """Test StreakState and MarketState instantiation."""
    streak = StreakState(consecutive_losses=2)
    assert streak.consecutive_losses == 2

    mkt = MarketState(
        instrument="SBIN",
        current_volatility=Decimal("12.50"),
        trailing_20session_avg_volatility=Decimal("10.00"),
        data_quality="VALIDATED",
        exchange_condition="NORMAL",
    )
    assert mkt.data_quality == "VALIDATED"


def test_risk_check_result_invariants() -> None:
    """Test invariant validation on RiskCheckResult."""
    # Valid passed result
    res_pass = RiskCheckResult(
        passed=True,
        config_version="1.0.0",
        approved_quantity=10,
        stop_loss_price=Decimal("240.00"),
        reason="all checks passed",
    )
    assert res_pass.passed is True
    assert res_pass.approved_quantity == 10

    # Passed result cannot carry failed_check
    with pytest.raises(ValidationError, match="cannot carry a failed_check"):
        RiskCheckResult(
            passed=True,
            failed_check="daily_loss",
            config_version="1.0.0",
            approved_quantity=10,
            stop_loss_price=Decimal("240.00"),
        )

    # Passed result must have approved_quantity > 0
    with pytest.raises(ValidationError, match="approved_quantity > 0"):
        RiskCheckResult(
            passed=True,
            config_version="1.0.0",
            approved_quantity=0,
            stop_loss_price=Decimal("240.00"),
        )

    # Passed result must have positive stop_loss_price
    with pytest.raises(ValidationError, match="valid positive stop_loss_price"):
        RiskCheckResult(
            passed=True,
            config_version="1.0.0",
            approved_quantity=10,
            stop_loss_price=None,
        )

    # Rejected result must have approved_quantity == 0
    with pytest.raises(ValidationError, match="approved_quantity == 0"):
        RiskCheckResult(
            passed=False,
            failed_check="daily_loss",
            rtld_param_id="RTLD-4",
            config_version="1.0.0",
            approved_quantity=5,
        )
