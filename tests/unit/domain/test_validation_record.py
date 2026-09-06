"""Unit tests for validation record domain models.

Conforms to FRD-LEARN-3, ADD §8.2, and MLD §9, §10:
- Validates immutability (frozen=True)
- Verifies UTC timestamp enforcement
"""

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.domain.validation_record import (
    ValidationRunRecord,
    ValidationStageResult,
)


def test_validation_stage_result_success_and_immutability() -> None:
    """Test valid stage result creation and frozen immutability."""
    stage = ValidationStageResult(
        stage_name="HISTORICAL_BACKTEST",
        stage_index=1,
        passed=True,
        metrics={"sharpe": 1.5, "max_drawdown_pct": 5.0},
        thresholds={"min_sharpe": 1.0, "max_drawdown_pct": 15.0},
        failure_reason=None,
    )
    assert stage.stage_name == "HISTORICAL_BACKTEST"
    assert stage.stage_index == 1
    assert stage.passed is True
    assert stage.metrics["sharpe"] == 1.5

    with pytest.raises(ValidationError):
        stage.passed = False


def test_validation_stage_result_naive_timestamp_rejected() -> None:
    """Test that naive timestamp is rejected by validator."""
    naive_dt = datetime(2026, 9, 7, 0, 0, 0)
    msg = "ValidationStageResult evaluated_at must be timezone-aware UTC"
    with pytest.raises(ValidationError, match=msg):
        ValidationStageResult(
            stage_name="HISTORICAL_BACKTEST",
            stage_index=1,
            passed=True,
            metrics={"sharpe": 1.5},
            thresholds={"min_sharpe": 1.0},
            evaluated_at=naive_dt,
        )


def test_validation_run_record_success_and_immutability() -> None:
    """Test valid validation run record creation and frozen immutability."""
    run_id = uuid4()
    stage = ValidationStageResult(
        stage_name="HISTORICAL_BACKTEST",
        stage_index=1,
        passed=True,
        metrics={"sharpe": 1.5},
        thresholds={"min_sharpe": 1.0},
    )
    run_record = ValidationRunRecord(
        run_id=run_id,
        model_id="test_model_v1",
        candidate_hash="a" * 64,
        stages=[stage],
        overall_passed=True,
        halted_stage_index=None,
        rejection_reason=None,
    )
    assert run_record.run_id == run_id
    assert run_record.overall_passed is True
    assert len(run_record.stages) == 1

    with pytest.raises(ValidationError):
        run_record.overall_passed = False


def test_validation_run_record_naive_timestamp_rejected() -> None:
    """Test that naive created_at timestamp is rejected by validator."""
    naive_dt = datetime(2026, 9, 7, 0, 0, 0)
    msg = "ValidationRunRecord created_at must be timezone-aware UTC"
    with pytest.raises(ValidationError, match=msg):
        ValidationRunRecord(
            run_id=uuid4(),
            model_id="test_model_v1",
            candidate_hash="a" * 64,
            stages=[],
            overall_passed=False,
            created_at=naive_dt,
        )
