"""Unit tests for RiskEngine, RiskConfig, and KillSwitch in src/risk/."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.domain.risk import (
    CandidateTrade,
    CapitalState,
    MarketState,
    StreakState,
)
from src.risk.config import RiskConfig
from src.risk.engine import RiskEngine
from src.risk.kill_switch import InMemoryKillSwitch, TriggerSource


@pytest.fixture
def risk_config() -> RiskConfig:
    """Fixture providing default RTLD §14 RiskConfig."""
    return RiskConfig()


@pytest.fixture
def kill_switch() -> InMemoryKillSwitch:
    """Fixture providing an inactive InMemoryKillSwitch."""
    return InMemoryKillSwitch()


@pytest.fixture
def risk_engine(risk_config: RiskConfig, kill_switch: InMemoryKillSwitch) -> RiskEngine:
    """Fixture providing an initialized RiskEngine."""
    return RiskEngine(config=risk_config, kill_switch=kill_switch)


@pytest.fixture
def valid_candidate() -> CandidateTrade:
    """Fixture providing a standard valid BUY candidate trade."""
    return CandidateTrade(
        instrument="TATASTEEL",
        direction="BUY",
        entry_price=Decimal("150.00"),
        stop_price=Decimal("145.00"),  # Stop distance = 5.00
        timeframe="15m",
        trade_quality_score=0.80,
        expected_value=Decimal("10.00"),
        confidence=0.75,
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def valid_capital() -> CapitalState:
    """Fixture providing a standard healthy ₹10,000 CapitalState."""
    return CapitalState(
        current_capital=Decimal("10000.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("1000.00"),
        open_position_count=1,
        trades_today=1,
    )


@pytest.fixture
def valid_streak() -> StreakState:
    """Fixture providing a zero-loss streak state."""
    return StreakState(consecutive_losses=0)


@pytest.fixture
def valid_market() -> MarketState:
    """Fixture providing a normal market state."""
    return MarketState(
        instrument="TATASTEEL",
        current_volatility=Decimal("2.50"),
        trailing_20session_avg_volatility=Decimal("2.50"),
        data_quality="VALIDATED",
        exchange_condition="NORMAL",
    )


def test_kill_switch_state_and_reset(kill_switch: InMemoryKillSwitch) -> None:
    """Test InMemoryKillSwitch lifecycle and operator reset authentication."""
    assert kill_switch.is_active() is False

    kill_switch.activate(TriggerSource.MANUAL_OPERATOR, "Testing emergency halt")
    assert kill_switch.is_active() is True
    history = kill_switch.get_history()
    assert len(history) == 1
    assert history[0]["event"] == "kill_switch_activated"

    # Reset with empty token fails
    with pytest.raises(PermissionError, match="non-empty authenticated operator token"):
        kill_switch.reset("")

    # Valid reset succeeds
    kill_switch.reset("OP_AUTH_9999")
    assert kill_switch.is_active() is False
    assert len(kill_switch.get_history()) == 2


def test_risk_engine_all_checks_pass(
    risk_engine: RiskEngine,
    valid_candidate: CandidateTrade,
    valid_capital: CapitalState,
    valid_streak: StreakState,
    valid_market: MarketState,
) -> None:
    """Test that healthy trade passes all 8 checks and receives positive approved_quantity."""
    res = risk_engine.evaluate(valid_candidate, valid_capital, valid_streak, valid_market)
    assert res.passed is True
    assert res.failed_check is None
    assert res.rtld_param_id is None
    assert res.approved_quantity > 0
    assert res.stop_loss_price == valid_candidate.stop_price


def test_check_1_kill_switch_active(
    risk_engine: RiskEngine,
    kill_switch: InMemoryKillSwitch,
    valid_candidate: CandidateTrade,
    valid_capital: CapitalState,
    valid_streak: StreakState,
) -> None:
    """Check 1: Active kill switch must immediately fail fast (RTLD-17)."""
    kill_switch.activate(TriggerSource.MANUAL_OPERATOR, "Operator STOP button pressed")
    dummy_market = MarketState(
        instrument="TATASTEEL",
        current_volatility=Decimal("2.0"),
        trailing_20session_avg_volatility=Decimal("2.0"),
        data_quality="VALIDATED",
        exchange_condition="NORMAL",
    )
    res = risk_engine.evaluate(valid_candidate, valid_capital, valid_streak, dummy_market)
    assert res.passed is False
    assert res.failed_check == "kill_switch"
    assert res.rtld_param_id == "RTLD-17"


def test_check_2_daily_loss_limit(
    risk_engine: RiskEngine,
    valid_candidate: CandidateTrade,
    valid_streak: StreakState,
    valid_market: MarketState,
) -> None:
    """Check 2: Maximum daily session loss boundary testing (RTLD-4, 3% = ₹300)."""
    # Daily loss = ₹299 (Pass)
    cap_pass = CapitalState(
        current_capital=Decimal("9701.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=2,
    )
    res_pass = risk_engine.evaluate(valid_candidate, cap_pass, valid_streak, valid_market)
    assert res_pass.passed is True

    # Daily loss = ₹300 (Fail threshold)
    cap_fail_boundary = CapitalState(
        current_capital=Decimal("9700.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=2,
    )
    res_fail = risk_engine.evaluate(valid_candidate, cap_fail_boundary, valid_streak, valid_market)
    assert res_fail.passed is False
    assert res_fail.failed_check == "daily_loss_limit"
    assert res_fail.rtld_param_id == "RTLD-4"

    # Daily loss = ₹350 (Fail above)
    cap_fail_above = CapitalState(
        current_capital=Decimal("9650.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=2,
    )
    res_above = risk_engine.evaluate(valid_candidate, cap_fail_above, valid_streak, valid_market)
    assert res_above.passed is False
    assert res_above.failed_check == "daily_loss_limit"


def test_check_3_drawdown_tiers(
    risk_engine: RiskEngine,
    valid_candidate: CandidateTrade,
    valid_streak: StreakState,
    valid_market: MarketState,
) -> None:
    """Check 3: Hard drawdown halt (8% = ₹800) and extreme kill switch trigger (10% = ₹1,000)."""
    # Drawdown = 7.9% (₹790) -> Pass
    cap_pass = CapitalState(
        current_capital=Decimal("9210.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("9210.00"),
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=1,
    )
    res_pass = risk_engine.evaluate(valid_candidate, cap_pass, valid_streak, valid_market)
    assert res_pass.passed is True

    # Drawdown = 8.0% (₹800) -> Hard halt fail (RTLD-5)
    cap_halt = CapitalState(
        current_capital=Decimal("9200.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("9200.00"),
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=1,
    )
    res_halt = risk_engine.evaluate(valid_candidate, cap_halt, valid_streak, valid_market)
    assert res_halt.passed is False
    assert res_halt.failed_check == "hard_drawdown_halt"
    assert res_halt.rtld_param_id == "RTLD-5"

    # Drawdown = 10.0% (₹1,000) -> Extreme kill switch trigger (RTLD-6)
    cap_extreme = CapitalState(
        current_capital=Decimal("9000.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("9000.00"),
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=1,
    )
    res_extreme = risk_engine.evaluate(valid_candidate, cap_extreme, valid_streak, valid_market)
    assert res_extreme.passed is False
    assert res_extreme.failed_check == "extreme_drawdown_killswitch"
    assert res_extreme.rtld_param_id == "RTLD-6"


def test_check_4_exposure_and_position_caps(
    risk_engine: RiskEngine,
    valid_candidate: CandidateTrade,
    valid_streak: StreakState,
    valid_market: MarketState,
) -> None:
    """Check 4: Position count (3), daily trade count (5), and exposure headroom (RTLD-7-10)."""
    # Max simultaneous open positions = 3
    cap_pos = CapitalState(
        current_capital=Decimal("10000.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("3000.00"),
        open_position_count=3,
        trades_today=3,
    )
    res_pos = risk_engine.evaluate(valid_candidate, cap_pos, valid_streak, valid_market)
    assert res_pos.passed is False
    assert res_pos.failed_check == "max_simultaneous_positions"
    assert res_pos.rtld_param_id == "RTLD-9"

    # Max trades per day = 5
    cap_trades = CapitalState(
        current_capital=Decimal("10000.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("1000.00"),
        open_position_count=1,
        trades_today=5,
    )
    res_trades = risk_engine.evaluate(valid_candidate, cap_trades, valid_streak, valid_market)
    assert res_trades.passed is False
    assert res_trades.failed_check == "max_trades_per_day"
    assert res_trades.rtld_param_id == "RTLD-10"

    # Max portfolio exposure = 50% (₹5,000)
    cap_exp = CapitalState(
        current_capital=Decimal("10000.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("5000.00"),
        open_position_count=2,
        trades_today=2,
    )
    res_exp = risk_engine.evaluate(valid_candidate, cap_exp, valid_streak, valid_market)
    assert res_exp.passed is False
    assert res_exp.failed_check == "max_portfolio_exposure"
    assert res_exp.rtld_param_id == "RTLD-7"


def test_check_5_consecutive_loss_tier(
    risk_engine: RiskEngine,
    valid_candidate: CandidateTrade,
    valid_capital: CapitalState,
    valid_market: MarketState,
) -> None:
    """Check 5: Tier-2 consecutive loss session pause circuit breaker (RTLD-12, 5 losses)."""
    streak_pass = StreakState(consecutive_losses=4)
    res_pass = risk_engine.evaluate(valid_candidate, valid_capital, streak_pass, valid_market)
    assert res_pass.passed is True

    streak_fail = StreakState(consecutive_losses=5)
    res_fail = risk_engine.evaluate(valid_candidate, valid_capital, streak_fail, valid_market)
    assert res_fail.passed is False
    assert res_fail.failed_check == "consecutive_loss_pause"
    assert res_fail.rtld_param_id == "RTLD-12"


def test_check_6_per_trade_risk_and_sizing(
    risk_engine: RiskEngine,
    valid_capital: CapitalState,
    valid_streak: StreakState,
    valid_market: MarketState,
) -> None:
    """Check 6: Per-trade risk budget sizing, unsizeable trades, and modifiers (RTLD-3, 11, 13)."""
    now = datetime.now(UTC)
    # Unsizeable trade: stop distance ₹200 when budget is ₹100 -> raw_qty = 0
    candidate_wide_stop = CandidateTrade(
        instrument="TATASTEEL",
        direction="BUY",
        entry_price=Decimal("500.00"),
        stop_price=Decimal("300.00"),  # Stop distance = 200
        timeframe="15m",
        trade_quality_score=0.80,
        expected_value=Decimal("50.00"),
        confidence=0.70,
        timestamp=now,
    )
    res_unsizeable = risk_engine.evaluate(
        candidate_wide_stop, valid_capital, valid_streak, valid_market
    )
    assert res_unsizeable.passed is False
    assert res_unsizeable.failed_check == "unsizeable_trade"
    assert res_unsizeable.rtld_param_id == "RTLD-3"

    # Tier-1 consecutive loss (3 losses) halves risk budget (RTLD-11)
    streak_tier1 = StreakState(consecutive_losses=3)
    candidate_standard = CandidateTrade(
        instrument="TATASTEEL",
        direction="BUY",
        entry_price=Decimal("100.00"),
        stop_price=Decimal("90.00"),  # Stop distance = 10
        timeframe="15m",
        trade_quality_score=0.80,
        expected_value=Decimal("15.00"),
        confidence=0.70,
        timestamp=now,
    )
    # Base risk = ₹100, Tier-1 halved = ₹50 -> raw_qty = 5 shares
    res_tier1 = risk_engine.evaluate(candidate_standard, valid_capital, streak_tier1, valid_market)
    assert res_tier1.passed is True
    assert res_tier1.approved_quantity == 5

    # Abnormal volatility (>2x avg) halves risk budget (RTLD-13)
    market_vol_halved = MarketState(
        instrument="TATASTEEL",
        current_volatility=Decimal("5.50"),  # > 2x of 2.50
        trailing_20session_avg_volatility=Decimal("2.50"),
        data_quality="VALIDATED",
        exchange_condition="NORMAL",
    )
    res_vol = risk_engine.evaluate(
        candidate_standard, valid_capital, valid_streak, market_vol_halved
    )
    assert res_vol.passed is True
    assert res_vol.approved_quantity == 5

    # Exposure headroom allows 0 shares
    cap_near_full = CapitalState(
        current_capital=Decimal("10000.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("4950.00"),  # Headroom = ₹50, entry = ₹100 -> 0 shares
        open_position_count=1,
        trades_today=1,
    )
    res_headroom_zero = risk_engine.evaluate(
        candidate_standard, cap_near_full, valid_streak, valid_market
    )
    assert res_headroom_zero.passed is False
    assert res_headroom_zero.failed_check == "position_exposure_headroom_zero"
    assert res_headroom_zero.rtld_param_id == "RTLD-7"


def test_check_7_volatility_liquidity_market(
    risk_engine: RiskEngine,
    valid_candidate: CandidateTrade,
    valid_capital: CapitalState,
    valid_streak: StreakState,
) -> None:
    """Check 7: Market halted, stale data, and extreme volatility (RTLD-14, 19)."""
    # Exchange halted
    mkt_halted = MarketState(
        instrument="TATASTEEL",
        current_volatility=Decimal("2.50"),
        trailing_20session_avg_volatility=Decimal("2.50"),
        data_quality="VALIDATED",
        exchange_condition="HALTED",
    )
    res_halted = risk_engine.evaluate(valid_candidate, valid_capital, valid_streak, mkt_halted)
    assert res_halted.passed is False
    assert res_halted.failed_check == "exchange_condition_abnormal"
    assert res_halted.rtld_param_id == "RTLD-14"

    # Data stale
    mkt_stale = MarketState(
        instrument="TATASTEEL",
        current_volatility=Decimal("2.50"),
        trailing_20session_avg_volatility=Decimal("2.50"),
        data_quality="STALE",
        exchange_condition="NORMAL",
    )
    res_stale = risk_engine.evaluate(valid_candidate, valid_capital, valid_streak, mkt_stale)
    assert res_stale.passed is False
    assert res_stale.failed_check == "data_quality_unacceptable"
    assert res_stale.rtld_param_id == "RTLD-19"

    # Extreme volatility block (>= 3x)
    mkt_extreme_vol = MarketState(
        instrument="TATASTEEL",
        current_volatility=Decimal("7.60"),  # > 3x 2.50 (7.50)
        trailing_20session_avg_volatility=Decimal("2.50"),
        data_quality="VALIDATED",
        exchange_condition="NORMAL",
    )
    res_vol = risk_engine.evaluate(valid_candidate, valid_capital, valid_streak, mkt_extreme_vol)
    assert res_vol.passed is False
    assert res_vol.failed_check == "extreme_volatility_block"
    assert res_vol.rtld_param_id == "RTLD-14"


def test_check_8_model_confidence_and_ev(
    risk_engine: RiskEngine,
    valid_capital: CapitalState,
    valid_streak: StreakState,
    valid_market: MarketState,
) -> None:
    """Check 8: Model confidence gate (<0.60) and non-positive expected value (RTLD-16)."""
    now = datetime.now(UTC)
    # Low confidence (0.55 < 0.60)
    candidate_low_conf = CandidateTrade(
        instrument="TATASTEEL",
        direction="BUY",
        entry_price=Decimal("150.00"),
        stop_price=Decimal("145.00"),
        timeframe="15m",
        trade_quality_score=0.80,
        expected_value=Decimal("10.00"),
        confidence=0.55,
        timestamp=now,
    )
    res_conf = risk_engine.evaluate(candidate_low_conf, valid_capital, valid_streak, valid_market)
    assert res_conf.passed is False
    assert res_conf.failed_check == "confidence_below_threshold"
    assert res_conf.rtld_param_id == "RTLD-16"

    # Non-positive EV (<= 0)
    candidate_neg_ev = CandidateTrade(
        instrument="TATASTEEL",
        direction="BUY",
        entry_price=Decimal("150.00"),
        stop_price=Decimal("145.00"),
        timeframe="15m",
        trade_quality_score=0.80,
        expected_value=Decimal("0.00"),
        confidence=0.75,
        timestamp=now,
    )
    res_ev = risk_engine.evaluate(candidate_neg_ev, valid_capital, valid_streak, valid_market)
    assert res_ev.passed is False
    assert res_ev.failed_check == "non_positive_expected_value"
    assert res_ev.rtld_param_id == "RTLD-16"


def test_risk_engine_config_property(risk_engine: RiskEngine, risk_config: RiskConfig) -> None:
    """Test accessing config property on RiskEngine."""
    assert risk_engine.config == risk_config


def test_check_per_trade_undefined_stop(
    risk_engine: RiskEngine,
    valid_capital: CapitalState,
    valid_streak: StreakState,
    valid_market: MarketState,
) -> None:
    """Test undefined stop distance check directly."""
    mock_candidate = MagicMock()
    mock_candidate.entry_price = Decimal("100.00")
    mock_candidate.stop_price = Decimal("100.00")
    res, qty = risk_engine._check_per_trade_risk_and_sizing(
        mock_candidate, valid_capital, valid_streak, valid_market
    )
    assert res is not None
    assert res.passed is False
    assert res.failed_check == "undefined_stop"
    assert res.rtld_param_id == "RTLD-3"
    assert qty == 0


def test_risk_engine_sizer_property(risk_engine: RiskEngine) -> None:
    """Verify sizer property returns initialized PositionSizer."""
    assert risk_engine.sizer is not None
    assert risk_engine.sizer.config == risk_engine.config
