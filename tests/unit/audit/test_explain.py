"""Unit tests for DecisionExplainer and Explainability CLI (TASK-17-02-002)."""

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scripts.explain_decision import run_cli
from src.audit.decision_logger import DecisionAuditService
from src.audit.explain import DecisionExplainer
from src.domain.decision import DecisionRecord
from src.infrastructure.models import Base


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide clean in-memory database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def seed_decision(session: Session, decision: str = "BUY") -> DecisionRecord:
    """Seed a test DecisionRecord into the database."""
    audit = DecisionAuditService()
    ts = datetime(2026, 9, 7, 11, 0, tzinfo=UTC)
    record = DecisionRecord(
        decision_record_id=uuid4(),
        timestamp=ts,
        instrument="NSE:SBIN",
        decision=decision,  # type: ignore[arg-type]
        regime="HIGH_VOLATILITY",
        agent_scores={"trend": 0.70, "momentum": 0.80, "mean_rev": -0.65},
        aggregated_score=0.68,
        risk_result={
            "passed": decision == "BUY",
            "failed_check": None if decision == "BUY" else "VOLATILITY_BAND_EXCEEDED",
            "param_id": "RTLD-VOL-01",
        },
        approved_quantity=50 if decision == "BUY" else 0,
        stop_loss_price=Decimal("790.00") if decision == "BUY" else None,
        target_price=Decimal("830.00") if decision == "BUY" else None,
        timeframe="5m",
        environment="paper",
        data_quality_state="VALIDATED",
        disagreement_metric=0.35,
        expected_value=Decimal("45.00"),
        client_order_id="ORD-SBIN-001" if decision == "BUY" else None,
        reason=(
            "Breakout confirmed with strict stop loss"
            if decision == "BUY"
            else "Volatility exceeded ceiling"
        ),
    )
    audit.log_decision_sync(record, session=session)
    session.commit()
    return record


@pytest.mark.unit
def test_explain_decision_answers_core_operator_questions(db_session: Session) -> None:
    """Verify that explanation accurately answers all 5 core operator questions."""
    record = seed_decision(db_session, decision="BUY")
    explainer = DecisionExplainer()

    report = explainer.explain_decision_sync(record.decision_record_id, session=db_session)

    # 1. Why was decision made?
    assert report.found is True
    assert report.final_decision == "BUY"
    assert "Breakout confirmed" in report.decision_rationale

    # 2. What regime was detected?
    assert report.regime_classification == {"regime": "HIGH_VOLATILITY"}

    # 3. Which signals agreed/disagreed?
    assert any("trend" in s for s in report.agreed_agents)
    assert any("momentum" in s for s in report.agreed_agents)
    assert any("mean_rev" in s for s in report.disagreed_agents)
    assert report.disagreement_metric == 0.35

    # 4. What was the confidence / trade quality?
    assert report.trade_quality_score == 0.68
    assert report.expected_value == Decimal("45.00")

    # 5. What risk checks evaluated?
    assert report.risk_check_passed is True
    assert report.rtld_param_id == "RTLD-VOL-01"
    assert report.client_order_id == "ORD-SBIN-001"

    # Verify formatted text report
    text_report = report.to_text_report()
    assert "DECISION EXPLAINABILITY REPORT" in text_report
    assert "HIGH_VOLATILITY" in text_report
    assert "RTLD-VOL-01" in text_report


@pytest.mark.unit
def test_explain_from_domain_record_directly() -> None:
    """Verify explaining an in-flight domain DecisionRecord directly."""
    explainer = DecisionExplainer()
    ts = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    record = DecisionRecord(
        decision_record_id=uuid4(),
        timestamp=ts,
        instrument="NSE:WIPRO",
        decision="NO_TRADE",
        regime="SIDEWAYS",
        agent_scores={"trend": 0.05, "momentum": -0.05},
        aggregated_score=0.00,
        risk_result={"passed": False, "failed_check": "MIN_OPPORTUNITY_THRESHOLD"},
        approved_quantity=0,
        reason="Consensus score below entry threshold",
    )

    report = explainer.explain_from_domain_record(record)
    assert report.found is True
    assert report.final_decision == "NO_TRADE"
    assert report.risk_check_passed is False
    assert report.failed_check == "MIN_OPPORTUNITY_THRESHOLD"
    assert len(report.neutral_agents) == 2


@pytest.mark.unit
def test_non_fabrication_guarantee_on_absent_record(db_session: Session) -> None:
    """Verify FRD-EVAL-6: Never synthesize or fabricate explanations for non-existent records."""
    explainer = DecisionExplainer()
    non_existent_id = uuid4()

    report = explainer.explain_decision_sync(non_existent_id, session=db_session)

    assert report.found is False
    assert report.decision_record_id == str(non_existent_id)
    text = report.to_text_report()
    assert "[STATUS]: RECORD NOT FOUND" in text
    assert "NON-FABRICATION GUARANTEE (FRD-EVAL-6)" in text


@pytest.mark.asyncio
@pytest.mark.unit
async def test_async_explain_decision(db_session: Session) -> None:
    """Verify async explain_decision with record found and not found."""
    mock_audit = MagicMock()
    mock_audit.get_decision = AsyncMock(return_value=None)

    explainer = DecisionExplainer(audit_service=mock_audit)
    not_found = await explainer.explain_decision("missing-id")
    assert not_found.found is False

    record = seed_decision(db_session)
    mock_model = MagicMock()
    mock_model.decision_record_id = str(record.decision_record_id)
    mock_model.final_decision = "SELL"
    mock_model.agent_outputs = {"scores": {"trend": -0.80, "momentum": 0.40, "neutral": 0.05}}
    mock_model.regime_classification = {"regime": "BEAR_TREND"}
    mock_model.decision_rationale = "Sell signal"
    mock_model.trade_quality_score = 0.75
    mock_model.expected_value = Decimal("50.00")
    mock_model.disagreement_metric = 0.20
    mock_model.risk_check_passed = True
    mock_model.failed_check = None
    mock_model.rtld_param_id = None
    mock_model.timestamp = record.timestamp
    mock_model.instrument = record.instrument
    mock_model.timeframe = "15m"
    mock_model.environment = "paper"
    mock_model.client_order_id = "ORD-002"
    mock_model.canonical_hash = "abc"

    mock_audit.get_decision = AsyncMock(return_value=mock_model)
    found_report = await explainer.explain_decision(record.decision_record_id)
    assert found_report.found is True
    assert found_report.final_decision == "SELL"
    assert any("trend" in a for a in found_report.agreed_agents)
    assert any("momentum" in d for d in found_report.disagreed_agents)
    assert any("neutral" in n for n in found_report.neutral_agents)


@pytest.mark.unit
def test_explain_cli_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify scripts/explain_decision.py CLI invocation."""

    # Create temporary SQLite DB and seed
    db_file = tmp_path / "cli_test.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_record = seed_decision(session, decision="BUY")

    # Test --id
    monkeypatch.setattr(
        "sys.argv",
        ["explain_decision.py", "--id", str(seed_record.decision_record_id), "--db-url", db_url],
    )
    code = run_cli()
    assert code == 0

    # Test --recent with --json
    monkeypatch.setattr(
        "sys.argv",
        ["explain_decision.py", "--recent", "5", "--db-url", db_url, "--json"],
    )
    code_recent = run_cli()
    assert code_recent == 0

    # Test --id not found
    monkeypatch.setattr(
        "sys.argv",
        ["explain_decision.py", "--id", "missing-id-123", "--db-url", db_url],
    )
    code_missing = run_cli()
    assert code_missing == 2
