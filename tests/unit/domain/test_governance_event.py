"""Unit tests for governance event domain models (PromotionEvent, RollbackEvent).

Conforms to FRD-LEARN-4, FRD-LEARN-7, and ADD §8.3, §8.4.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.domain.governance_event import PromotionEvent, RollbackEvent


def test_promotion_event_success_and_immutability() -> None:
    """Test standard promotion event creation and immutability."""
    event = PromotionEvent(
        candidate_id="model_v2",
        baseline_id="model_v1",
        validation_run_id=uuid4(),
        promoted=True,
        promoted_by="OPERATOR_ALICE",
        metrics_comparison={"candidate_sharpe": 2.1, "baseline_sharpe": 1.8},
        rejection_reasons=[],
        notes="Outperforms on all out-of-sample slices",
    )
    assert event.candidate_id == "model_v2"
    assert event.baseline_id == "model_v1"
    assert event.promoted is True
    assert event.promoted_by == "OPERATOR_ALICE"

    with pytest.raises(ValidationError):
        event.promoted = False


def test_promotion_event_naive_timestamp_rejected() -> None:
    """Test naive timestamp rejection on PromotionEvent."""
    naive_dt = datetime(2026, 9, 7, 10, 0, 0)
    msg = "PromotionEvent timestamp must be timezone-aware UTC"
    with pytest.raises(ValidationError, match=msg):
        PromotionEvent(
            candidate_id="model_v2",
            validation_run_id=uuid4(),
            promoted=True,
            promoted_by="OPERATOR",
            timestamp=naive_dt,
        )


def test_rollback_event_success_and_immutability() -> None:
    """Test rollback event creation and immutability."""
    event = RollbackEvent(
        failed_model_id="model_v2",
        restored_model_id="model_v1",
        trigger_reason="DRAWDOWN_BREACH",
        evidence={"current_drawdown_pct": 8.5, "drawdown_limit_pct": 8.0},
        notes="Drawdown breach in live trading",
    )
    assert event.failed_model_id == "model_v2"
    assert event.restored_model_id == "model_v1"
    assert event.trigger_reason == "DRAWDOWN_BREACH"

    with pytest.raises(ValidationError):
        event.failed_model_id = "other"


def test_rollback_event_naive_timestamp_rejected() -> None:
    """Test naive timestamp rejection on RollbackEvent."""
    naive_dt = datetime(2026, 9, 7, 10, 0, 0)
    with pytest.raises(ValidationError, match="RollbackEvent timestamp must be timezone-aware UTC"):
        RollbackEvent(
            failed_model_id="model_v2",
            restored_model_id="model_v1",
            trigger_reason="CONSECUTIVE_LOSSES",
            timestamp=naive_dt,
        )
