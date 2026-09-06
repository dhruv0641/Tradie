"""Unit tests for Supervisor Decision Gate, Decision domain model, and precedence logic."""

import inspect
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.decision.supervisor import Supervisor
from src.domain.decision import Decision, DecisionRecord
from src.domain.risk import (
    CandidateTrade,
    CapitalState,
    MarketState,
    RiskCheckResult,
    StreakState,
)
from src.risk.config import RiskConfig
from src.risk.engine import RiskEngine
from src.risk.kill_switch import InMemoryKillSwitch, TriggerSource


@pytest.fixture
def risk_config() -> RiskConfig:
    """Fixture providing standard RiskConfig."""
    return RiskConfig()


@pytest.fixture
def kill_switch() -> InMemoryKillSwitch:
    """Fixture providing clean InMemoryKillSwitch."""
    return InMemoryKillSwitch()


@pytest.fixture
def risk_engine(risk_config: RiskConfig, kill_switch: InMemoryKillSwitch) -> RiskEngine:
    """Fixture providing initialized RiskEngine."""
    return RiskEngine(config=risk_config, kill_switch=kill_switch)


@pytest.fixture
def supervisor(risk_engine: RiskEngine, kill_switch: InMemoryKillSwitch) -> Supervisor:
    """Fixture providing initialized Supervisor."""
    return Supervisor(risk_engine=risk_engine, kill_switch=kill_switch)


@pytest.fixture
def sample_candidate_buy() -> CandidateTrade:
    """Fixture providing a valid BUY candidate trade."""
    return CandidateTrade(
        instrument="INFY",
        direction="BUY",
        entry_price=Decimal("1500.00"),
        stop_price=Decimal("1480.00"),
        timeframe="15m",
        trade_quality_score=0.85,
        expected_value=Decimal("15.00"),
        confidence=0.80,
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def sample_candidate_sell() -> CandidateTrade:
    """Fixture providing a valid SELL candidate trade."""
    return CandidateTrade(
        instrument="TATAMOTORS",
        direction="SELL",
        entry_price=Decimal("500.00"),
        stop_price=Decimal("510.00"),
        timeframe="15m",
        trade_quality_score=0.82,
        expected_value=Decimal("20.00"),
        confidence=0.78,
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def sample_capital() -> CapitalState:
    """Fixture providing healthy ₹10,000 capital state."""
    return CapitalState(
        current_capital=Decimal("10000.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=0,
    )


@pytest.fixture
def sample_streak() -> StreakState:
    """Fixture providing clean streak state."""
    return StreakState(consecutive_losses=0)


@pytest.fixture
def sample_market() -> MarketState:
    """Fixture providing normal market state."""
    return MarketState(
        instrument="INFY",
        current_volatility=Decimal("15.0"),
        trailing_20session_avg_volatility=Decimal("14.0"),
        data_quality="VALIDATED",
        exchange_condition="NORMAL",
    )


def test_supervisor_properties(
    supervisor: Supervisor,
    risk_engine: RiskEngine,
    kill_switch: InMemoryKillSwitch,
) -> None:
    """Verify Supervisor properties expose underlying risk engine and kill switch."""
    assert supervisor.risk_engine is risk_engine
    assert supervisor.kill_switch is kill_switch


def test_kill_switch_precedence_with_open_position(
    supervisor: Supervisor,
    kill_switch: InMemoryKillSwitch,
    sample_candidate_buy: CandidateTrade,
    sample_capital: CapitalState,
    sample_streak: StreakState,
    sample_market: MarketState,
) -> None:
    """KS-TEST-1 variant: When kill switch is active and position is open, outcome must be HOLD."""
    kill_switch.activate(TriggerSource.MANUAL_OPERATOR, "Emergency halt by operator")

    decision = supervisor.decide(
        candidate=sample_candidate_buy,
        capital=sample_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=True,
    )

    assert decision.outcome == "HOLD"
    assert decision.kill_switch_active is True
    assert decision.approved_quantity == 0
    assert "kill switch/STOP active" in decision.reason
    assert decision.risk_check.passed is False
    assert decision.risk_check.failed_check == "kill_switch"
    assert decision.is_trade_approved is False


def test_kill_switch_precedence_without_open_position(
    supervisor: Supervisor,
    kill_switch: InMemoryKillSwitch,
    sample_candidate_buy: CandidateTrade,
    sample_capital: CapitalState,
    sample_streak: StreakState,
    sample_market: MarketState,
) -> None:
    """When kill switch is active and no position is open, outcome must be NO_TRADE."""
    kill_switch.activate(TriggerSource.EXTREME_DRAWDOWN, "Drawdown breached limit")

    decision = supervisor.decide(
        candidate=sample_candidate_buy,
        capital=sample_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=False,
    )

    assert decision.outcome == "NO_TRADE"
    assert decision.kill_switch_active is True
    assert decision.approved_quantity == 0
    assert "kill switch/STOP active" in decision.reason
    assert decision.risk_check.passed is False
    assert decision.is_trade_approved is False


def test_candidate_none_produces_no_trade(
    supervisor: Supervisor,
    sample_capital: CapitalState,
    sample_streak: StreakState,
    sample_market: MarketState,
) -> None:
    """When candidate is None (upstream gate rejected), Supervisor must emit NO_TRADE."""
    decision = supervisor.decide(
        candidate=None,
        capital=sample_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=False,
    )

    assert decision.outcome == "NO_TRADE"
    assert decision.kill_switch_active is False
    assert decision.approved_quantity == 0
    assert "no candidate cleared confidence/EV gates" in decision.reason
    assert decision.risk_check.passed is False
    assert decision.risk_check.failed_check == "no_candidate"
    assert decision.is_trade_approved is False


def test_risk_engine_rejection_produces_no_trade_zero_override(
    supervisor: Supervisor,
    sample_candidate_buy: CandidateTrade,
    sample_streak: StreakState,
    sample_market: MarketState,
) -> None:
    """When Risk Engine rejects (e.g. daily loss exceeded), Supervisor must emit NO_TRADE."""
    breached_capital = CapitalState(
        current_capital=Decimal("9600.00"),
        peak_equity=Decimal("10000.00"),
        session_start_capital=Decimal("10000.00"),  # Daily loss = 400 >= 300 (3%)
        currently_deployed=Decimal("0.00"),
        open_position_count=0,
        trades_today=2,
    )

    decision = supervisor.decide(
        candidate=sample_candidate_buy,
        capital=breached_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=False,
    )

    assert decision.outcome == "NO_TRADE"
    assert decision.kill_switch_active is False
    assert decision.approved_quantity == 0
    assert decision.risk_check.passed is False
    assert decision.risk_check.failed_check == "daily_loss_limit"
    assert "daily_loss_limit" in decision.reason
    assert decision.is_trade_approved is False


def test_risk_engine_approved_buy(
    supervisor: Supervisor,
    sample_candidate_buy: CandidateTrade,
    sample_capital: CapitalState,
    sample_streak: StreakState,
    sample_market: MarketState,
) -> None:
    """When candidate clears all gates, Supervisor emits BUY with approved quantity."""
    decision = supervisor.decide(
        candidate=sample_candidate_buy,
        capital=sample_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=False,
    )

    assert decision.outcome == "BUY"
    assert decision.kill_switch_active is False
    assert decision.approved_quantity > 0
    assert decision.stop_loss_price == sample_candidate_buy.stop_price
    assert decision.reason == "cleared all gates"
    assert decision.risk_check.passed is True
    assert decision.is_trade_approved is True


def test_risk_engine_approved_sell(
    supervisor: Supervisor,
    sample_candidate_sell: CandidateTrade,
    sample_capital: CapitalState,
    sample_streak: StreakState,
    sample_market: MarketState,
) -> None:
    """When candidate clears all gates, Supervisor emits SELL with approved quantity."""
    decision = supervisor.decide(
        candidate=sample_candidate_sell,
        capital=sample_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=False,
    )

    assert decision.outcome == "SELL"
    assert decision.kill_switch_active is False
    assert decision.approved_quantity > 0
    assert decision.stop_loss_price == sample_candidate_sell.stop_price
    assert decision.reason == "cleared all gates"
    assert decision.risk_check.passed is True
    assert decision.is_trade_approved is True


def test_build_decision_record(
    supervisor: Supervisor,
    sample_candidate_buy: CandidateTrade,
    sample_capital: CapitalState,
    sample_streak: StreakState,
    sample_market: MarketState,
) -> None:
    """Verify build_decision_record outputs valid, hash-stamped DecisionRecord."""
    decision = supervisor.decide(
        candidate=sample_candidate_buy,
        capital=sample_capital,
        streak=sample_streak,
        market=sample_market,
        has_open_position=False,
    )

    record = supervisor.build_decision_record(
        decision=decision,
        instrument=sample_candidate_buy.instrument,
        regime="BULL_TRENDING",
        agent_scores={"trend": 0.85, "momentum": 0.80},
        aggregated_score=0.825,
        git_commit="abcdef123456",
    )

    assert isinstance(record, DecisionRecord)
    assert record.decision == "BUY"
    assert record.instrument == "INFY"
    assert record.regime == "BULL_TRENDING"
    assert record.approved_quantity == decision.approved_quantity
    assert record.git_commit == "abcdef123456"
    assert record.decision_hash is not None
    assert record.decision_hash == record.calculate_canonical_hash()


def test_decision_model_validation() -> None:
    """Verify Decision model bounds, UTC validator, and is_trade_approved logic."""
    risk_res = RiskCheckResult(
        passed=True,
        failed_check=None,
        rtld_param_id=None,
        reason=None,
        config_version="0.1.0",
        approved_quantity=10,
        stop_loss_price=Decimal("140.00"),
    )

    # Valid UTC decision
    d = Decision(
        outcome="BUY",
        reason="passed",
        risk_check=risk_res,
        kill_switch_active=False,
        approved_quantity=10,
        timestamp=datetime.now(UTC),
    )
    assert d.is_trade_approved is True

    # Naive timestamp should raise ValueError
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        Decision(
            outcome="BUY",
            reason="passed",
            risk_check=risk_res,
            timestamp=datetime(2026, 9, 6, 12, 0, 0),  # Naive!
        )

    # NO_TRADE with qty 0 is not trade approved
    d_no_trade = Decision(
        outcome="NO_TRADE",
        reason="rejected",
        risk_check=risk_res,
        approved_quantity=0,
    )
    assert d_no_trade.is_trade_approved is False

    # BUY with qty 0 is not trade approved
    d_zero_qty = Decision(
        outcome="BUY",
        reason="zero qty",
        risk_check=risk_res,
        approved_quantity=0,
    )
    assert d_zero_qty.is_trade_approved is False


def test_structural_non_bypassability_no_override_parameter() -> None:
    """Verify structurally that Supervisor.decide() has NO override/bypass parameter."""
    sig = inspect.signature(Supervisor.decide)
    params = set(sig.parameters.keys())
    forbidden_terms = {"override", "force", "bypass", "ignore_risk", "force_approve"}

    for param in params:
        assert not any(
            f in param.lower() for f in forbidden_terms
        ), f"Supervisor.decide() contains forbidden bypass parameter: '{param}'"
