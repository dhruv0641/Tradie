"""Unit tests for DecisionAuditService (TASK-17-01-001, BRD BR-7, FRD-X-3, NFR-AUDIT-1)."""

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.audit.decision_logger import (
    AuditPersistenceError,
    DecisionAuditService,
    TamperEvidenceViolationError,
)
from src.domain.decision import DecisionRecord
from src.infrastructure.models import Base
from src.risk.kill_switch import InMemoryKillSwitch


@pytest.fixture
def in_memory_db() -> Generator[Session, None, None]:
    """Provide a clean SQLite in-memory database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def make_decision_record(
    decision: str = "BUY",
    instrument: str = "NSE:RELIANCE",
    approved_quantity: int = 25,
    tampered_hash: str | None = None,
) -> DecisionRecord:
    """Helper creating strongly-typed DecisionRecord with valid SHA-256 hash."""
    ts = datetime(2026, 9, 7, 10, 30, tzinfo=UTC)
    record = DecisionRecord(
        decision_record_id=uuid4(),
        timestamp=ts,
        instrument=instrument,
        decision=decision,  # type: ignore[arg-type]
        regime="BULL_TREND",
        agent_scores={"trend": 0.82, "mom": 0.74, "mr": -0.10},
        aggregated_score=0.75,
        risk_result={
            "passed": approved_quantity > 0,
            "failed_check": None if approved_quantity > 0 else "DAILY_LOSS_LIMIT",
            "param_id": "RTLD-MAX-RISK-01",
            "approved_qty": approved_quantity,
        },
        approved_quantity=approved_quantity,
        stop_loss_price=Decimal("2500.00") if approved_quantity > 0 else None,
        target_price=Decimal("2600.00") if approved_quantity > 0 else None,
        timeframe="15m",
        environment="paper",
        data_quality_state="VALIDATED",
        disagreement_metric=0.15,
        expected_value=Decimal("75.50"),
        client_order_id="ORD-12345",
        reason="Approved bullish breakout",
        inputs_used={"candle_close": 2550.0},
        features={"rsi": 62.5, "adx": 28.0},
        config_version="v1.0.0",
        git_commit="git-commit-abc",
    )
    if tampered_hash is not None:
        return record.model_copy(update={"decision_hash": tampered_hash})
    h = record.calculate_canonical_hash()
    return record.model_copy(update={"decision_hash": h})


@pytest.mark.unit
def test_log_decision_sync_persistence(in_memory_db: Session) -> None:
    """Verify synchronous decision persistence into database."""
    service = DecisionAuditService()
    record = make_decision_record(decision="BUY", instrument="NSE:TCS")

    model = service.log_decision_sync(record, session=in_memory_db)
    in_memory_db.commit()

    assert model.decision_record_id == str(record.decision_record_id)
    assert model.instrument == "NSE:TCS"
    assert model.final_decision == "BUY"
    assert model.canonical_hash == record.decision_hash
    assert model.risk_check_passed is True
    assert model.rtld_param_id == "RTLD-MAX-RISK-01"

    # Query back using get_decision_sync
    queried = service.get_decision_sync(record.decision_record_id, session=in_memory_db)
    assert queried is not None
    assert queried.final_decision == "BUY"
    assert queried.agent_outputs["scores"]["trend"] == 0.82


@pytest.mark.unit
def test_unconditional_audit_logging_all_cycle_outcomes(in_memory_db: Session) -> None:
    """Verify 100% of cycle outcomes (BUY, SELL, HOLD, NO_TRADE) are persisted unconditionally."""
    service = DecisionAuditService()
    outcomes = ["BUY", "SELL", "HOLD", "NO_TRADE"]

    for outcome in outcomes:
        qty = 10 if outcome in ("BUY", "SELL") else 0
        rec = make_decision_record(
            decision=outcome,
            instrument=f"NSE:SYM_{outcome}",
            approved_quantity=qty,
        )
        service.log_decision_sync(rec, session=in_memory_db)

    in_memory_db.commit()

    recent = service.get_recent_decisions_sync(session=in_memory_db, limit=10)
    assert len(recent) == 4
    persisted_outcomes = {m.final_decision for m in recent}
    assert persisted_outcomes == {"BUY", "SELL", "HOLD", "NO_TRADE"}


@pytest.mark.unit
def test_cryptographic_tamper_evidence_detection() -> None:
    """Verify TamperEvidenceViolationError is raised when record hash is invalid."""
    service = DecisionAuditService()
    mock_session = MagicMock()
    corrupted_hash = "deadbeef" * 8
    corrupted_record = make_decision_record(decision="BUY", tampered_hash=corrupted_hash)

    with pytest.raises(TamperEvidenceViolationError, match="Cryptographic tamper violation"):
        service.log_decision_sync(corrupted_record, session=mock_session)


@pytest.mark.unit
def test_fail_stop_and_kill_switch_on_database_failure() -> None:
    """Verify FRD-X-3 fail-stop semantics and kill-switch activation on DB write error."""
    kill_switch = InMemoryKillSwitch()
    service = DecisionAuditService(kill_switch=kill_switch)
    record = make_decision_record(decision="BUY")

    failing_session = MagicMock()
    failing_session.add.side_effect = RuntimeError("Database disk full / connection dropped")

    with pytest.raises(AuditPersistenceError, match="CRITICAL: Failed to persist DecisionRecord"):
        service.log_decision_sync(record, session=failing_session)

    assert kill_switch.is_active() is True
    history = kill_switch.get_history()
    assert len(history) > 0
    assert "database persistence failure" in history[-1]["reason"].lower()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_async_decision_logging_and_query() -> None:
    """Verify async logging, error handling, and query methods."""
    mock_db = MagicMock()
    mock_session = AsyncMock()
    mock_db.get_session.return_value.__aenter__.return_value = mock_session

    service = DecisionAuditService(db=mock_db)
    record = make_decision_record(decision="NO_TRADE", approved_quantity=0)

    res = await service.log_decision(record)
    assert res.final_decision == "NO_TRADE"
    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()

    # Test error in async path
    failing_mock_db = MagicMock()
    failing_session = AsyncMock()
    failing_session.flush.side_effect = RuntimeError("Connection timeout")
    failing_mock_db.get_session.return_value.__aenter__.return_value = failing_session

    failing_service = DecisionAuditService(db=failing_mock_db)
    with pytest.raises(AuditPersistenceError):
        await failing_service.log_decision(record)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_decision_audit_service_edge_cases(in_memory_db: Session) -> None:
    """Verify session passing, missing config error, and query filters."""
    service = DecisionAuditService()
    record = make_decision_record(decision="BUY", instrument="NSE:AXISBANK")

    # Missing session and missing db
    with pytest.raises(AuditPersistenceError, match="No database session or DatabaseManager"):
        await service.log_decision(record)

    # Async log with direct session
    mock_session = AsyncMock()
    model = await service.log_decision(record, session=mock_session)
    assert model.instrument == "NSE:AXISBANK"
    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()

    # Queries without session or db
    assert await service.get_decision(record.decision_record_id) is None
    assert await service.get_recent_decisions() == []

    # Sync recent decisions with instrument filter
    service.log_decision_sync(record, session=in_memory_db)
    in_memory_db.commit()

    filtered = service.get_recent_decisions_sync(
        session=in_memory_db, limit=10, instrument="NSE:AXISBANK"
    )
    assert len(filtered) >= 1
    assert filtered[0].instrument == "NSE:AXISBANK"

    empty_filtered = service.get_recent_decisions_sync(
        session=in_memory_db, limit=10, instrument="NSE:NONEXISTENT"
    )
    assert len(empty_filtered) == 0

    # Async query with mock session
    mock_query_session = AsyncMock()
    mock_query_session.scalar.return_value = model
    res_dec = await service.get_decision(record.decision_record_id, session=mock_query_session)
    assert res_dec is not None
    assert res_dec.instrument == "NSE:AXISBANK"

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [model]
    mock_query_session.scalars.return_value = mock_scalars
    res_recent = await service.get_recent_decisions(
        limit=5, instrument="NSE:AXISBANK", session=mock_query_session
    )
    assert len(res_recent) == 1
