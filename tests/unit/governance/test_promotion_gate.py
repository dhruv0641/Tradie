"""Unit tests for ModelPromotionGate.

Conforms to FRD-LEARN-4, FRD-LEARN-5, ADD §8.3, §8.4, and MLD §9.2:
- Multi-dimensional comparative promotion gates
- Mandatory human operator sign-off enforcement
- Atomic state transitions (promoted / superseded)
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.domain.governance import ModelVersion
from src.domain.validation_record import (
    ValidationRunRecord,
    ValidationStageResult,
)
from src.governance.promotion_gate import (
    ModelPromotionGate,
    PromotionGateConfig,
)


def _make_model(
    model_id: str,
    *,
    status: str = "candidate",
    metrics: dict[str, Any] | None = None,
) -> ModelVersion:
    """Create a ModelVersion for testing."""
    default_metrics = {
        "sharpe_ratio": 1.8,
        "max_drawdown_pct": 5.0,
    }
    if metrics:
        default_metrics.update(metrics)

    return ModelVersion(
        model_id=model_id,
        model_name=f"Model_{model_id}",
        version_tag="v1.0.0",
        model_hash="a" * 64,
        trained_at=datetime.now(UTC),
        status=status,  # type: ignore[arg-type]
        validation_metrics=default_metrics,
    )


def _make_passed_run(model_id: str) -> ValidationRunRecord:
    """Create a passing ValidationRunRecord."""
    stage = ValidationStageResult(
        stage_name="HISTORICAL_BACKTEST",
        stage_index=1,
        passed=True,
        metrics={"sharpe": 1.8},
        thresholds={"min_sharpe": 1.0},
    )
    return ValidationRunRecord(
        run_id=uuid4(),
        model_id=model_id,
        candidate_hash="a" * 64,
        stages=[stage],
        overall_passed=True,
        halted_stage_index=None,
    )


def test_successful_promotion_with_baseline() -> None:
    """Test standard successful promotion replacing an active baseline model."""
    gate = ModelPromotionGate()
    candidate = _make_model("cand_v2", metrics={"sharpe_ratio": 2.2, "max_drawdown_pct": 4.5})
    baseline = _make_model(
        "prod_v1", status="promoted", metrics={"sharpe_ratio": 1.9, "max_drawdown_pct": 5.0}
    )
    run_record = _make_passed_run("cand_v2")

    decision = gate.evaluate_and_promote(
        candidate=candidate,
        validation_record=run_record,
        baseline=baseline,
        operator_signoff="OP_BOB",
        notes="Q3 production refresh",
    )

    assert decision.promoted is True
    assert decision.candidate_id == "cand_v2"
    assert decision.baseline_id == "prod_v1"
    assert len(decision.rejection_reasons) == 0
    assert candidate.status == "promoted"
    assert candidate.promoted_by == "OP_BOB"
    assert candidate.promotion_timestamp is not None
    assert baseline.status == "superseded"
    assert decision.event is not None
    assert decision.event.promoted is True


def test_successful_promotion_initial_model_without_baseline() -> None:
    """Test initial model promotion when no production baseline exists."""
    gate = ModelPromotionGate()
    candidate = _make_model("first_model", metrics={"sharpe_ratio": 1.5})
    run_record = _make_passed_run("first_model")

    decision = gate.evaluate_and_promote(
        candidate=candidate,
        validation_record=run_record,
        baseline=None,
        operator_signoff="CHIEF_ARCHITECT",
    )

    assert decision.promoted is True
    assert candidate.status == "promoted"
    assert candidate.promoted_by == "CHIEF_ARCHITECT"


def test_promotion_rejected_when_validation_failed() -> None:
    """Test rejection when empirical validation did not pass."""
    gate = ModelPromotionGate()
    candidate = _make_model("cand_v2")
    failed_record = ValidationRunRecord(
        run_id=uuid4(),
        model_id="cand_v2",
        candidate_hash="a" * 64,
        stages=[],
        overall_passed=False,
        rejection_reason="Drawdown breach in stress test",
    )

    decision = gate.evaluate_and_promote(
        candidate=candidate,
        validation_record=failed_record,
        operator_signoff="OP",
    )

    assert decision.promoted is False
    assert any("failed empirical validation" in r for r in decision.rejection_reasons)
    assert candidate.status == "candidate"


def test_promotion_rejected_when_validation_model_id_mismatched() -> None:
    """Test rejection when validation record belongs to a different model."""
    gate = ModelPromotionGate()
    candidate = _make_model("cand_v2")
    run_record = _make_passed_run("cand_v1_other")

    decision = gate.evaluate_and_promote(
        candidate=candidate,
        validation_record=run_record,
        operator_signoff="OP",
    )

    assert decision.promoted is False
    assert candidate.status == "candidate"


def test_promotion_rejected_missing_operator_signoff() -> None:
    """Test rejection when mandatory human operator sign-off is missing."""
    gate = ModelPromotionGate()
    candidate = _make_model("cand_v2")
    run_record = _make_passed_run("cand_v2")

    decision = gate.evaluate_and_promote(
        candidate=candidate,
        validation_record=run_record,
        operator_signoff=None,
    )

    assert decision.promoted is False
    assert any("Missing mandatory operator sign-off" in r for r in decision.rejection_reasons)
    assert candidate.status == "candidate"


def test_promotion_rejected_sharpe_underperforms_baseline() -> None:
    """Test rejection when candidate Sharpe is lower than baseline Sharpe."""
    gate = ModelPromotionGate()
    candidate = _make_model("cand_v2", metrics={"sharpe_ratio": 1.4})
    baseline = _make_model("prod_v1", status="promoted", metrics={"sharpe_ratio": 1.9})
    run_record = _make_passed_run("cand_v2")

    decision = gate.evaluate_and_promote(
        candidate=candidate,
        validation_record=run_record,
        baseline=baseline,
        operator_signoff="OP",
    )

    assert decision.promoted is False
    expected_msg = "Candidate Sharpe (1.40) does not meet baseline"
    assert any(expected_msg in r for r in decision.rejection_reasons)
    assert candidate.status == "candidate"
    assert baseline.status == "promoted"


def test_promotion_rejected_drawdown_exceeds_baseline_tolerance() -> None:
    """Test rejection when candidate MaxDD exceeds baseline * tolerance ratio."""
    gate = ModelPromotionGate(PromotionGateConfig(max_drawdown_tolerance_ratio=1.10))
    # Baseline DD: 5.0%, ceiling: 5.5%. Candidate DD: 6.2% -> should be rejected
    candidate = _make_model("cand_v2", metrics={"sharpe_ratio": 2.2, "max_drawdown_pct": 6.2})
    baseline = _make_model(
        "prod_v1",
        status="promoted",
        metrics={"sharpe_ratio": 1.8, "max_drawdown_pct": 5.0},
    )
    run_record = _make_passed_run("cand_v2")

    decision = gate.evaluate_and_promote(
        candidate=candidate,
        validation_record=run_record,
        baseline=baseline,
        operator_signoff="OP",
    )

    assert decision.promoted is False
    assert any("exceeds baseline tolerance" in r for r in decision.rejection_reasons)
    assert candidate.status == "candidate"
    assert baseline.status == "promoted"


def test_promotion_rejected_negative_initial_sharpe() -> None:
    """Test rejection when initial candidate has negative Sharpe."""
    gate = ModelPromotionGate()
    candidate = _make_model("cand_v2", metrics={"sharpe_ratio": -0.5})
    run_record = _make_passed_run("cand_v2")

    decision = gate.evaluate_and_promote(
        candidate=candidate,
        validation_record=run_record,
        baseline=None,
        operator_signoff="OP",
    )

    assert decision.promoted is False
    assert any("must be non-negative" in r for r in decision.rejection_reasons)


def test_custom_gate_config_relaxed_signoff() -> None:
    """Test promotion gate with relaxed configuration options."""
    config = PromotionGateConfig(
        require_operator_signoff=False,
        require_validation_pass=False,
    )
    gate = ModelPromotionGate(config=config)
    candidate = _make_model("cand_v2", metrics={"sharpe_ratio": 1.5})
    failed_record = ValidationRunRecord(
        run_id=uuid4(),
        model_id="cand_v2",
        candidate_hash="a" * 64,
        stages=[],
        overall_passed=False,
    )

    decision = gate.evaluate_and_promote(
        candidate=candidate,
        validation_record=failed_record,
        operator_signoff=None,
    )

    assert decision.promoted is True
    assert candidate.status == "promoted"
