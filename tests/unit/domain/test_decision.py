"""Unit tests for master DecisionRecord and TradeEvaluation domain models."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.domain.decision import DecisionRecord
from src.domain.evaluation import TradeEvaluation


@pytest.mark.unit
def test_decision_record_lifecycle_and_hash() -> None:
    """Verify decision record creation, fields, and deterministic SHA-256 hash."""
    ts = datetime(2026, 9, 6, 11, 30, 0, tzinfo=UTC)
    record = DecisionRecord(
        instrument="NSE:RELIANCE",
        timestamp=ts,
        decision="BUY",
        regime="BULL_TREND",
        agent_scores={"momentum": 0.85, "trend": 0.78, "mean_rev": -0.10},
        aggregated_score=0.74,
        risk_result={"passed": True, "failed_check": None, "approved_qty": 25},
        approved_quantity=25,
        stop_loss_price=Decimal("2920.00"),
        target_price=Decimal("3020.00"),
        config_version="v1.0.0",
        git_commit="c435356",
    )
    assert record.decision == "BUY"
    assert record.approved_quantity == 25

    # Compute deterministic hash
    h1 = record.calculate_canonical_hash()
    assert isinstance(h1, str)
    assert len(h1) == 64  # SHA-256 hex length
    h2 = record.calculate_canonical_hash()
    assert h1 == h2


@pytest.mark.unit
def test_no_trade_decision_validity() -> None:
    """Verify NO_TRADE is handled as a first-class valid decision outcome."""
    ts = datetime(2026, 9, 6, 14, 0, 0, tzinfo=UTC)
    no_trade_record = DecisionRecord(
        instrument="NSE:NIFTY",
        timestamp=ts,
        decision="NO_TRADE",
        regime="HIGH_VOLATILITY",
        agent_scores={"momentum": 0.10, "trend": 0.05},
        aggregated_score=0.08,
        risk_result={"passed": False, "failed_check": "MAX_DAILY_LOSS_LIMIT", "approved_qty": 0},
        approved_quantity=0,
        config_version="v1.0.0",
        git_commit="c435356",
    )
    assert no_trade_record.decision == "NO_TRADE"
    assert no_trade_record.approved_quantity == 0


@pytest.mark.unit
def test_trade_evaluation_financial_attribution() -> None:
    """Verify trade evaluation model with gross/net P&L, slippage, and variance drivers."""
    eval_ts = datetime(2026, 9, 6, 15, 30, 0, tzinfo=UTC)
    entry_id = uuid4()
    exit_id = uuid4()

    evaluation = TradeEvaluation(
        entry_decision_id=entry_id,
        exit_decision_id=exit_id,
        instrument="NSE:TCS",
        direction="BUY",
        entry_price=Decimal("4200.00"),
        exit_price=Decimal("4260.00"),
        quantity=50,
        gross_pnl=Decimal("3000.00"),
        net_pnl=Decimal("2895.50"),
        total_slippage=Decimal("25.00"),
        statutory_costs=Decimal("79.50"),
        variance_driver="STRATEGY_EDGE",
        rule_adherence=True,
        evaluated_at=eval_ts,
    )
    assert evaluation.gross_pnl == Decimal("3000.00")
    assert evaluation.net_pnl == Decimal("2895.50")
    assert evaluation.variance_driver == "STRATEGY_EDGE"
    assert evaluation.rule_adherence is True


@pytest.mark.unit
def test_decision_record_immutability() -> None:
    """Verify DecisionRecord is strictly immutable."""
    ts = datetime(2026, 9, 6, 11, 30, 0, tzinfo=UTC)
    record = DecisionRecord(
        instrument="NSE:RELIANCE",
        timestamp=ts,
        decision="HOLD",
        regime="SIDEWAYS",
        agent_scores={},
        aggregated_score=0.0,
        risk_result={"passed": True},
        approved_quantity=0,
    )
    attr_name = "decision"
    with pytest.raises(ValidationError):
        setattr(record, attr_name, "BUY")


@pytest.mark.unit
def test_naive_timestamp_rejections() -> None:
    """Verify that naive datetimes without UTC timezone are rejected."""
    naive_dt = datetime(2026, 9, 6, 12, 0, 0)

    with pytest.raises(ValidationError, match="Decision timestamp must be timezone-aware UTC"):
        DecisionRecord(
            instrument="NSE:RELIANCE",
            timestamp=naive_dt,
            decision="HOLD",
            regime="SIDEWAYS",
            agent_scores={},
            aggregated_score=0.0,
            risk_result={"passed": True},
            approved_quantity=0,
        )

    with pytest.raises(ValidationError, match="Evaluation timestamp must be timezone-aware UTC"):
        TradeEvaluation(
            entry_decision_id=uuid4(),
            exit_decision_id=uuid4(),
            instrument="NSE:TCS",
            direction="BUY",
            entry_price=Decimal("100"),
            exit_price=Decimal("105"),
            quantity=10,
            gross_pnl=Decimal("50"),
            net_pnl=Decimal("45"),
            variance_driver="STRATEGY_EDGE",
            evaluated_at=naive_dt,
        )
