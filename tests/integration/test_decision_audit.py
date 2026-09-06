"""Integration tests for DecisionAuditService, TradeEvaluator, and Explainability Engine (EPIC-17).

Verifies 100% audit logging, foreign key relationships, NFR-AUDIT-2 query latency (<5s),
and end-to-end post-trade evaluation lifecycle in an integrated database session.
"""

import time
from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.audit.decision_logger import DecisionAuditService
from src.audit.explain import DecisionExplainer
from src.audit.trade_evaluator import TradeEvaluator
from src.domain.decision import DecisionRecord
from src.infrastructure.models import Base, DecisionRecordModel, TradeEvaluationModel


@pytest.fixture
def integrated_db() -> Generator[Session, None, None]:
    """Create a fully migrated schema in SQLite in-memory for integration testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.integration
def test_full_decision_audit_lifecycle_and_foreign_key_linkage(integrated_db: Session) -> None:
    """Verify end-to-end integration: decision persistence, trade evaluation FK, and queries."""
    audit_service = DecisionAuditService()
    trade_evaluator = TradeEvaluator()
    explainer = DecisionExplainer(audit_service=audit_service)

    # 1. Simulate entry DecisionRecord for BUY
    entry_id = uuid4()
    entry_ts = datetime(2026, 9, 7, 9, 30, tzinfo=UTC)
    entry_record = DecisionRecord(
        decision_record_id=entry_id,
        timestamp=entry_ts,
        instrument="NSE:RELIANCE",
        decision="BUY",
        regime="BULL_TREND",
        agent_scores={"trend": 0.85, "momentum": 0.78, "mean_rev": -0.15},
        aggregated_score=0.76,
        risk_result={
            "passed": True,
            "approved_qty": 30,
            "failed_check": None,
            "param_id": "RTLD-MAX-EXPOSURE",
            "reason": "Breakout confirmed across multiple timeframes",
        },
        approved_quantity=30,
        stop_loss_price=Decimal("2480.00"),
        target_price=Decimal("2560.00"),
        timeframe="15m",
        environment="paper",
        data_quality_state="VALIDATED",
        disagreement_metric=0.18,
        expected_value=Decimal("120.00"),
        client_order_id="ORD-REL-ENTRY-001",
        reason="Breakout confirmed across multiple timeframes",
        config_version="v1.0.0",
        git_commit="commit-778899",
    )
    h_entry = entry_record.calculate_canonical_hash()
    entry_record = entry_record.model_copy(update={"decision_hash": h_entry})

    # Persist entry decision
    audit_service.log_decision_sync(entry_record, session=integrated_db)
    integrated_db.commit()

    # 2. Simulate exit DecisionRecord
    exit_id = uuid4()
    exit_ts = datetime(2026, 9, 7, 13, 15, tzinfo=UTC)
    exit_record = DecisionRecord(
        decision_record_id=exit_id,
        timestamp=exit_ts,
        instrument="NSE:RELIANCE",
        decision="SELL",
        regime="BULL_TREND",
        agent_scores={"trend": 0.20, "momentum": -0.10},
        aggregated_score=0.10,
        risk_result={"passed": True, "approved_qty": 30},
        approved_quantity=30,
        timeframe="15m",
        reason="Target price reached, closing position",
        client_order_id="ORD-REL-EXIT-001",
    )
    audit_service.log_decision_sync(exit_record, session=integrated_db)
    integrated_db.commit()

    # 3. Post-Trade Evaluation linking to entry_decision_id
    evaluation = trade_evaluator.evaluate_trade(
        entry_decision_id=entry_id,
        exit_decision_id=exit_id,
        instrument="NSE:RELIANCE",
        direction="BUY",
        entry_price=Decimal("2500.00"),
        exit_price=Decimal("2560.00"),
        quantity=30,
        entry_timestamp=entry_ts,
        exit_timestamp=exit_ts,
        expected_pnl=Decimal("1800.00"),
        entry_slippage=Decimal("15.00"),
        exit_slippage=Decimal("15.00"),
        rule_adherence=True,
        entry_regime="BULL_TREND",
        exit_regime="BULL_TREND",
    )
    eval_model = trade_evaluator.record_evaluation_sync(evaluation, session=integrated_db)
    integrated_db.commit()

    assert eval_model.decision_record_id == str(entry_id)
    assert eval_model.variance_driver == "good_trade"

    # 4. Verify Foreign Key relationship in DB
    queried_eval = integrated_db.scalar(
        select(TradeEvaluationModel).where(TradeEvaluationModel.decision_record_id == str(entry_id))
    )
    assert queried_eval is not None
    assert queried_eval.instrument == "NSE:RELIANCE"

    # 5. Measure Explainability Query Latency (NFR-AUDIT-2: < 5 seconds)
    start_time = time.perf_counter()
    report = explainer.explain_decision_sync(entry_id, session=integrated_db)
    elapsed_time = time.perf_counter() - start_time

    assert elapsed_time < 5.0, f"Query exceeded NFR-AUDIT-2 5s requirement: {elapsed_time:.4f}s"
    assert report.found is True
    assert report.final_decision == "BUY"
    assert report.risk_check_passed is True
    assert "Breakout confirmed" in report.decision_rationale


@pytest.mark.integration
def test_audit_logging_integrity_for_all_system_actions(integrated_db: Session) -> None:
    """Verify that multiple successive cycles create independent, immutable database rows."""
    audit_service = DecisionAuditService()
    instruments = ["NSE:RELIANCE", "NSE:TCS", "NSE:INFY", "NSE:HDFCBANK"]
    decisions = ["BUY", "NO_TRADE", "HOLD", "SELL"]

    for inst, dec in zip(instruments, decisions, strict=False):
        ts = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
        rec = DecisionRecord(
            decision_record_id=uuid4(),
            timestamp=ts,
            instrument=inst,
            decision=dec,  # type: ignore[arg-type]
            regime="TRENDING",
            agent_scores={"trend": 0.5},
            aggregated_score=0.5,
            risk_result={"passed": dec in ("BUY", "SELL")},
            approved_quantity=10 if dec in ("BUY", "SELL") else 0,
        )
        audit_service.log_decision_sync(rec, session=integrated_db)

    integrated_db.commit()

    # Query total records
    all_records = integrated_db.scalars(select(DecisionRecordModel)).all()
    assert len(all_records) == 4
    inst_set = {r.instrument for r in all_records}
    assert inst_set == set(instruments)
