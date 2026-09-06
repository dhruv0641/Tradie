"""Unit tests for hypothesis-to-candidate generation workflow and scoping engine.

Conforms to FRD-LEARN-2, SLD §6, §8, §10, and ADD §10.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from src.domain.governance import ModelVersion
from src.domain.pattern import ObservedPattern
from src.research.candidate_generator import (
    CandidateGenerator,
    CandidateGeneratorConfig,
)


def _make_dummy_pattern(
    *,
    status: Literal["CONFIRMED_HYPOTHESIS", "OBSERVED_UNCONFIRMED"] = "CONFIRMED_HYPOTHESIS",
    target_dimension: str = "agent",
    target_value: str = "momentum_agent",
    win_rate: float = 0.25,
    baseline_win_rate: float = 0.55,
) -> ObservedPattern:
    """Create a valid mock ObservedPattern."""
    p_val = 0.0025 if status == "CONFIRMED_HYPOTHESIS" else 0.45
    return ObservedPattern(
        pattern_id=uuid4(),
        pattern_type="AGENT_UNDERPERFORMANCE",
        target_dimension=target_dimension,
        target_value=target_value,
        sample_size=35,
        total_trades_analyzed=100,
        failure_count=26,
        win_rate=win_rate,
        baseline_win_rate=baseline_win_rate,
        mean_pnl=Decimal("-120.50"),
        baseline_mean_pnl=Decimal("45.00"),
        p_value=p_val,
        confidence=1.0 - p_val,
        is_statistically_significant=(status == "CONFIRMED_HYPOTHESIS"),
        status=status,
        description=f"Persistent underperformance of {target_dimension}={target_value}",
    )


def test_successful_candidate_generation_from_confirmed_hypothesis() -> None:
    """Test standard successful candidate generation from a confirmed pattern."""
    generator = CandidateGenerator()
    pattern = _make_dummy_pattern(status="CONFIRMED_HYPOTHESIS")
    change = {"weight": 0.20}

    result = generator.generate_candidate(
        pattern=pattern,
        proposed_change=change,
        candidate_name="Momentum_DeWeight_Candidate",
    )

    assert result.is_generated is True
    assert result.rejection_reason is None
    assert result.candidate is not None
    assert result.candidate.model_name == "Momentum_DeWeight_Candidate"
    assert result.candidate.status == "candidate"
    assert result.candidate.hypothesis_id == str(pattern.pattern_id)
    assert result.candidate.source_pattern_id == str(pattern.pattern_id)
    assert result.candidate.targeted_change is not None
    assert result.candidate.targeted_change["target_dimension"] == "agent"
    assert result.candidate.targeted_change["target_value"] == "momentum_agent"
    assert result.candidate.targeted_change["proposed_parameters"] == {"weight": 0.20}
    assert len(generator.active_candidates) == 1
    assert generator.active_candidates[0].model_id == result.candidate.model_id


def test_rejection_of_unconfirmed_pattern() -> None:
    """Test candidate creation is rejected if pattern is unconfirmed (SLD §5.2)."""
    generator = CandidateGenerator()
    pattern = _make_dummy_pattern(status="OBSERVED_UNCONFIRMED")
    change = {"weight": 0.20}

    result = generator.generate_candidate(pattern=pattern, proposed_change=change)

    assert result.is_generated is False
    assert result.candidate is None
    assert result.rejection_reason is not None
    assert "CONFIRMED_HYPOTHESIS" in result.rejection_reason
    assert len(generator.active_candidates) == 0


def test_candidate_generation_when_unconfirmed_check_disabled() -> None:
    """Test unconfirmed patterns are allowed when require_confirmed_hypothesis=False."""
    cfg = CandidateGeneratorConfig(require_confirmed_hypothesis=False)
    generator = CandidateGenerator(config=cfg)
    pattern = _make_dummy_pattern(status="OBSERVED_UNCONFIRMED")
    change = {"weight": 0.20}

    result = generator.generate_candidate(pattern=pattern, proposed_change=change)

    assert result.is_generated is True
    assert result.candidate is not None
    assert len(generator.active_candidates) == 1


def test_concurrency_limit_enforcement() -> None:
    """Test that concurrency limit prevents second candidate when one is active (SLD §8)."""
    generator = CandidateGenerator(config=CandidateGeneratorConfig(max_concurrent_candidates=1))
    pattern1 = _make_dummy_pattern(target_dimension="agent", target_value="momentum_agent")
    pattern2 = _make_dummy_pattern(target_dimension="regime", target_value="HIGH_VOLATILITY")

    result1 = generator.generate_candidate(pattern=pattern1, proposed_change={"weight": 0.15})
    assert result1.is_generated is True

    result2 = generator.generate_candidate(
        pattern=pattern2,
        proposed_change={"min_confidence": 0.8},
    )
    assert result2.is_generated is False
    assert result2.candidate is None
    assert result2.rejection_reason is not None
    assert "concurrency limit reached" in result2.rejection_reason
    assert result2.active_candidates_count == 1


def test_pipeline_candidate_registration_and_release() -> None:
    """Test manual pipeline registration and release workflow."""
    generator = CandidateGenerator()
    now = datetime.now(UTC)

    dummy_cand = ModelVersion(
        model_id="cand_ext_001",
        model_name="External Candidate",
        version_tag="cand-v1-ext",
        model_hash="a" * 64,
        trained_at=now,
        status="candidate",
        validation_metrics={},
        targeted_change={"target_dimension": "agent", "target_value": "trend_agent"},
    )

    generator.register_pipeline_candidate(dummy_cand)
    assert len(generator.active_candidates) == 1

    generator.release_pipeline_candidate("cand_ext_001", "promoted")
    assert len(generator.active_candidates) == 0


def test_cooldown_period_enforcement_and_expiry() -> None:
    """Test cooldown enforcement (30 trades) on the same target dimension/value (SLD §8)."""
    generator = CandidateGenerator(config=CandidateGeneratorConfig(cooldown_trades=30))
    generator.update_trade_progress(100)

    pattern = _make_dummy_pattern(target_dimension="agent", target_value="trend_agent")

    # 1. Create candidate at trade 100
    res1 = generator.generate_candidate(pattern=pattern, proposed_change={"weight": 0.25})
    assert res1.is_generated is True
    assert res1.candidate is not None

    # 2. Release candidate after validation
    generator.release_pipeline_candidate(res1.candidate.model_id, "promoted")

    # 3. Advance trades to 115 (15 trades elapsed < 30)
    generator.update_trade_progress(115)
    res2 = generator.generate_candidate(pattern=pattern, proposed_change={"weight": 0.28})
    assert res2.is_generated is False
    assert res2.cooldown_remaining_trades == 15
    assert res2.rejection_reason is not None
    assert "Cooldown period active" in res2.rejection_reason

    # 4. Advance trades to 135 (35 trades elapsed >= 30)
    generator.update_trade_progress(135)
    res3 = generator.generate_candidate(pattern=pattern, proposed_change={"weight": 0.28})
    assert res3.is_generated is True
    assert res3.candidate is not None
    assert res3.cooldown_remaining_trades == 0


def test_different_target_dimension_not_blocked_by_cooldown() -> None:
    """Test that cooldown is target-specific and does not block other dimensions."""
    generator = CandidateGenerator(config=CandidateGeneratorConfig(cooldown_trades=30))
    generator.update_trade_progress(50)

    pattern1 = _make_dummy_pattern(target_dimension="agent", target_value="trend_agent")
    res1 = generator.generate_candidate(pattern=pattern1, proposed_change={"weight": 0.25})
    assert res1.candidate is not None
    generator.release_pipeline_candidate(res1.candidate.model_id, "rejected")

    # Target 2: regime dimension
    pattern2 = _make_dummy_pattern(target_dimension="regime", target_value="TRENDING_UP")
    res2 = generator.generate_candidate(
        pattern=pattern2,
        proposed_change={"confirmation_bars": 3},
    )
    assert res2.is_generated is True


def test_one_change_discipline_violation() -> None:
    """Test rejection when multiple parameters are changed without causal linkage (SLD §6.2)."""
    generator = CandidateGenerator()
    pattern = _make_dummy_pattern()

    multi_change = {
        "weight": 0.20,
        "stop_loss_multiplier": 1.5,
    }

    result = generator.generate_candidate(pattern=pattern, proposed_change=multi_change)
    assert result.is_generated is False
    assert result.rejection_reason is not None
    assert "One-change-at-a-time discipline violated" in result.rejection_reason


def test_causally_linked_multi_change_accepted() -> None:
    """Test multi-change is accepted when explicitly flagged as causally linked (SLD §6.2)."""
    generator = CandidateGenerator()
    pattern = _make_dummy_pattern()

    linked_change = {
        "weight": 0.20,
        "stop_loss_multiplier": 1.5,
        "__linked_change__": True,
    }

    result = generator.generate_candidate(pattern=pattern, proposed_change=linked_change)
    assert result.is_generated is True
    assert result.candidate is not None
    assert result.candidate.targeted_change is not None
    # "__linked_change__" must be cleanly stripped from proposed_parameters
    assert result.candidate.targeted_change["proposed_parameters"] == {
        "weight": 0.20,
        "stop_loss_multiplier": 1.5,
    }


def test_release_pipeline_candidate_edge_cases() -> None:
    """Test releasing non-existent candidate or candidate without targeted_change."""
    generator = CandidateGenerator()
    now = datetime.now(UTC)

    # 1. Non-existent model_id should not fail
    generator.release_pipeline_candidate("non_existent_id", "rejected")
    assert len(generator.active_candidates) == 0

    # 2. Candidate with empty targeted_change should not populate cooldown
    cand_no_change = ModelVersion(
        model_id="cand_no_change",
        model_name="No Change Candidate",
        version_tag="cand-v1-empty",
        model_hash="b" * 64,
        trained_at=now,
        status="candidate",
        validation_metrics={},
        targeted_change={},
    )
    generator.register_pipeline_candidate(cand_no_change)
    generator.release_pipeline_candidate("cand_no_change", "rolled_back")
    assert len(generator.active_candidates) == 0


def test_candidate_custom_title_and_hash_integrity() -> None:
    """Test candidate hash integrity and default vs custom title generation."""
    generator = CandidateGenerator()
    pattern = _make_dummy_pattern(target_dimension="agent", target_value="mean_reversion_agent")
    change = {"rsi_period": 14}

    # Default title
    res_default = generator.generate_candidate(pattern=pattern, proposed_change=change)
    assert res_default.is_generated is True
    assert res_default.candidate is not None
    assert "Candidate_agent_mean_reversion_agent" in res_default.candidate.model_name
    assert len(res_default.candidate.model_hash) == 64
