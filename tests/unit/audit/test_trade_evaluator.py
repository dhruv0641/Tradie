"""Unit tests for TradeEvaluator and Variance Driver Classifier (TASK-17-02-001)."""

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.audit.decision_logger import DecisionAuditService
from src.audit.trade_evaluator import TradeEvaluator
from src.domain.decision import DecisionRecord
from src.infrastructure.models import Base


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide a clean SQLite in-memory database session with parent decision record."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def setup_parent_decision(session: Session) -> DecisionRecord:
    """Insert a parent DecisionRecord to satisfy foreign key constraints."""
    audit = DecisionAuditService()
    ts = datetime(2026, 9, 7, 9, 30, tzinfo=UTC)
    record = DecisionRecord(
        decision_record_id=uuid4(),
        timestamp=ts,
        instrument="NSE:INFY",
        decision="BUY",
        regime="BULL_TREND",
        agent_scores={"trend": 0.8},
        aggregated_score=0.8,
        risk_result={"passed": True},
        approved_quantity=20,
    )
    audit.log_decision_sync(record, session=session)
    session.commit()
    return record


@pytest.mark.unit
def test_evaluate_trade_good_trade_financial_attribution(db_session: Session) -> None:
    """Verify winning trade attribution, exact cost drag, and good_trade classification."""
    parent = setup_parent_decision(db_session)
    evaluator = TradeEvaluator()

    entry_ts = datetime(2026, 9, 7, 9, 30, tzinfo=UTC)
    exit_ts = datetime(2026, 9, 7, 11, 45, tzinfo=UTC)

    # Buy 20 shares at 1500, exit at 1550 -> Gross = +1000.00
    evaluation = evaluator.evaluate_trade(
        entry_decision_id=parent.decision_record_id,
        exit_decision_id=uuid4(),
        instrument="NSE:INFY",
        direction="BUY",
        entry_price=Decimal("1500.00"),
        exit_price=Decimal("1550.00"),
        quantity=20,
        entry_timestamp=entry_ts,
        exit_timestamp=exit_ts,
        expected_pnl=Decimal("800.00"),
        entry_regime="BULL_TREND",
        exit_regime="BULL_TREND",
    )

    assert evaluation.gross_pnl == Decimal("1000.00")
    assert evaluation.statutory_costs > Decimal("0.00")
    assert evaluation.net_pnl == evaluation.gross_pnl - evaluation.total_cost_drag
    assert evaluation.variance_driver == "good_trade"
    assert evaluation.rule_adherence is True

    # Persist and query back
    evaluator.record_evaluation_sync(evaluation, session=db_session)
    db_session.commit()

    queried = evaluator.get_evaluation_sync(evaluation.trade_id, session=db_session)
    assert queried is not None
    assert queried.instrument == "NSE:INFY"
    assert queried.realized_pnl == evaluation.net_pnl
    assert queried.variance_driver == "good_trade"


@pytest.mark.unit
def test_evaluate_trade_bad_execution_from_cost_and_slippage() -> None:
    """Verify bad_execution classification when costs or slippage cause negative outcome."""
    evaluator = TradeEvaluator()

    # Case A: Gross profit +2.00, but costs + slippage total 15.00 -> Net PnL is negative
    driver_a = evaluator.classify_variance_driver(
        gross_pnl=Decimal("2.00"),
        net_pnl=Decimal("-13.00"),
        expected_pnl=Decimal("50.00"),
        total_slippage=Decimal("10.00"),
        statutory_costs=Decimal("5.00"),
    )
    assert driver_a == "bad_execution"

    # Case B: Negative trade where slippage accounts for 50% of total loss
    driver_b = evaluator.classify_variance_driver(
        gross_pnl=Decimal("-50.00"),
        net_pnl=Decimal("-100.00"),
        expected_pnl=Decimal("100.00"),
        total_slippage=Decimal("45.00"),
        statutory_costs=Decimal("5.00"),
    )
    assert driver_b == "bad_execution"


@pytest.mark.unit
def test_evaluate_trade_regime_change_classification() -> None:
    """Verify regime_change classification when market shifts against holding."""
    evaluator = TradeEvaluator()

    driver = evaluator.classify_variance_driver(
        gross_pnl=Decimal("-200.00"),
        net_pnl=Decimal("-220.00"),
        expected_pnl=Decimal("300.00"),
        entry_regime="BULL_TREND",
        exit_regime="HIGH_VOLATILITY",
    )
    assert driver == "regime_change"


@pytest.mark.unit
def test_evaluate_trade_bad_timing_classification() -> None:
    """Verify bad_timing classification when trade was prematurely stopped out."""
    evaluator = TradeEvaluator()

    driver = evaluator.classify_variance_driver(
        gross_pnl=Decimal("-150.00"),
        net_pnl=Decimal("-165.00"),
        expected_pnl=Decimal("250.00"),
        stopped_out_early=True,
    )
    assert driver == "bad_timing"


@pytest.mark.unit
def test_evaluate_trade_rule_violation_and_data_issues() -> None:
    """Verify bad_sizing and data_problem classifications."""
    evaluator = TradeEvaluator()

    # Rule adherence failure -> bad_sizing
    driver_sizing = evaluator.classify_variance_driver(
        gross_pnl=Decimal("-100.00"),
        net_pnl=Decimal("-110.00"),
        expected_pnl=Decimal("100.00"),
        rule_adherence=False,
    )
    assert driver_sizing == "bad_sizing"

    # Data staleness / quarantine issue -> data_problem
    driver_data = evaluator.classify_variance_driver(
        gross_pnl=Decimal("-100.00"),
        net_pnl=Decimal("-110.00"),
        expected_pnl=Decimal("100.00"),
        data_quality="STALE",
    )
    assert driver_data == "data_problem"

    # Unexpected shock -> unexpected_event
    driver_event = evaluator.classify_variance_driver(
        gross_pnl=Decimal("-100.00"),
        net_pnl=Decimal("-110.00"),
        expected_pnl=Decimal("100.00"),
        unexpected_event=True,
    )
    assert driver_event == "unexpected_event"


@pytest.mark.unit
def test_evaluate_trade_model_problem_and_bad_signal() -> None:
    """Verify model_problem (high disagreement) and bad_signal (predictive edge failure)."""
    evaluator = TradeEvaluator()

    # High agent conflict
    driver_model = evaluator.classify_variance_driver(
        gross_pnl=Decimal("-100.00"),
        net_pnl=Decimal("-110.00"),
        expected_pnl=Decimal("100.00"),
        model_disagreement=0.65,
    )
    assert driver_model == "model_problem"

    # Standard predictive loss
    driver_signal = evaluator.classify_variance_driver(
        gross_pnl=Decimal("-100.00"),
        net_pnl=Decimal("-110.00"),
        expected_pnl=Decimal("100.00"),
    )
    assert driver_signal == "bad_signal"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_async_trade_evaluation_persistence() -> None:
    """Verify async persistence and queries in TradeEvaluator."""
    mock_db = MagicMock()
    mock_session = AsyncMock()
    mock_db.get_session.return_value.__aenter__.return_value = mock_session

    evaluator = TradeEvaluator(db=mock_db)
    evaluation = evaluator.evaluate_trade(
        entry_decision_id=uuid4(),
        exit_decision_id=uuid4(),
        instrument="NSE:HDFCBANK",
        direction="SELL",
        entry_price=Decimal("1600.00"),
        exit_price=Decimal("1580.00"),
        quantity=10,
        entry_timestamp=datetime(2026, 9, 7, 10, 0, tzinfo=UTC),
        exit_timestamp=datetime(2026, 9, 7, 11, 0, tzinfo=UTC),
    )

    model = await evaluator.record_evaluation(evaluation)
    assert model.instrument == "NSE:HDFCBANK"
    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_trade_evaluator_queries_and_error_handling(db_session: Session) -> None:
    """Verify async queries, missing config error, and instrument queries."""
    parent = setup_parent_decision(db_session)
    evaluator = TradeEvaluator()

    evaluation = evaluator.evaluate_trade(
        entry_decision_id=parent.decision_record_id,
        exit_decision_id=uuid4(),
        instrument="NSE:INFY",
        direction="SELL",
        entry_price=Decimal("1550.00"),
        exit_price=Decimal("1500.00"),
        quantity=15,
        entry_timestamp=datetime(2026, 9, 7, 10, 0, tzinfo=UTC),
        exit_timestamp=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        product_type="DELIVERY",
    )
    assert evaluation.gross_pnl == Decimal("750.00")

    # Missing session and db
    with pytest.raises(RuntimeError, match="No database session or DatabaseManager"):
        await evaluator.record_evaluation(evaluation)

    # Record with direct async session
    mock_session = AsyncMock()
    model = await evaluator.record_evaluation(evaluation, session=mock_session)
    assert model.instrument == "NSE:INFY"
    mock_session.add.assert_called_once()

    # Queries without session or db return None / empty
    assert await evaluator.get_evaluation(evaluation.trade_id) is None
    assert await evaluator.get_evaluations_for_instrument("NSE:INFY") == []

    # Sync instrument query
    evaluator.record_evaluation_sync(evaluation, session=db_session)
    db_session.commit()

    evals = evaluator.get_evaluations_for_instrument_sync("NSE:INFY", session=db_session)
    assert len(evals) >= 1
    assert evals[0].instrument == "NSE:INFY"

    # Async query with mock session
    mock_query_session = AsyncMock()
    mock_query_session.scalar.return_value = model
    res_eval = await evaluator.get_evaluation(evaluation.trade_id, session=mock_query_session)
    assert res_eval is not None
    assert res_eval.instrument == "NSE:INFY"

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [model]
    mock_query_session.scalars.return_value = mock_scalars
    res_inst = await evaluator.get_evaluations_for_instrument(
        "NSE:INFY", limit=10, session=mock_query_session
    )
    assert len(res_inst) == 1
