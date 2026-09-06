"""Unit tests for multi-criteria capital scaling evaluation engine (Sprint S24.01).

Adheres strictly to BRD BR-2, FRD-CAP-2, FRD-CAP-5, FRD-CAP-6, and RTLD §15.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.capital.scaling_evaluator import CapitalScalingEvaluator, ScalingEvaluationInput


@pytest.fixture
def baseline_passing_metrics() -> ScalingEvaluationInput:
    """Fixture providing metrics where all 9 RTLD §15 criteria comfortably pass."""
    return ScalingEvaluationInput(
        current_capital=Decimal("10000.00"),
        live_days=95,  # Criterion 1: >= 90 days
        closed_trade_count=42,  # Criterion 1: >= 30 trades
        regime_expectancies={  # Criterion 2: >= 2 profitable regimes
            "BULL_TRENDING": Decimal("180.50"),
            "LOW_VOLATILITY": Decimal("75.20"),
            "RANGING": Decimal("-20.00"),
        },
        max_historical_drawdown_pct=4.8,  # Criterion 3: < 8.0%
        sortino_ratio=1.65,  # Criterion 4: >= 1.0
        validation_passed=True,  # Criterion 5: Passed validation
        live_paper_divergence_pct=11.5,  # Criterion 6: <= 20.0%
        automated_rollback_count=0,  # Criterion 7: 0 rollbacks
        avg_slippage_multiplier=1.12,  # Criterion 8: <= 1.5x
        duplicate_order_count=0,  # Criterion 8: 0 duplicates
        system_uptime_pct=99.85,  # Criterion 9: >= 99.5%
        unhandled_disconnect_count=0,  # Criterion 9: 0 disconnects
    )


def test_scaling_evaluator_nominal_all_pass(
    baseline_passing_metrics: ScalingEvaluationInput,
) -> None:
    """Verify that when all 9 criteria pass, scaling is recommended capped at +25%."""
    evaluator = CapitalScalingEvaluator()
    report = evaluator.evaluate(baseline_passing_metrics)

    assert report.eligible_for_scaling is True
    assert report.passed_count == 9
    assert report.total_criteria == 9
    assert report.current_capital == Decimal("10000.00")
    # Step scaling capped strictly at +25%: 10000 * 1.25 = 12500
    assert report.recommended_capital == Decimal("12500.00")
    assert "ELIGIBLE" in report.summary_verdict
    assert "+25% step-scaling" in report.summary_verdict

    # Check individual criteria results
    for crit in report.criteria_results.values():
        assert crit.passed is True


def test_criterion_1_insufficient_sample_size(
    baseline_passing_metrics: ScalingEvaluationInput,
) -> None:
    """Verify Criterion 1 fails when live trades < 30 or live days < 90."""
    evaluator = CapitalScalingEvaluator()

    # Case A: Too few trades
    input_trades = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "closed_trade_count": 22}
    )
    report_a = evaluator.evaluate(input_trades)
    assert report_a.eligible_for_scaling is False
    assert report_a.recommended_capital is None
    assert report_a.criteria_results["sample_size"].passed is False

    # Case B: Too few live days
    input_days = ScalingEvaluationInput(**{**baseline_passing_metrics.__dict__, "live_days": 45})
    report_b = evaluator.evaluate(input_days)
    assert report_b.eligible_for_scaling is False
    assert report_b.criteria_results["sample_size"].passed is False


def test_criterion_2_insufficient_regimes(baseline_passing_metrics: ScalingEvaluationInput) -> None:
    """Verify Criterion 2 fails when positive expectancy is shown in < 2 regimes."""
    evaluator = CapitalScalingEvaluator()
    bad_input = ScalingEvaluationInput(
        **{
            **baseline_passing_metrics.__dict__,
            "regime_expectancies": {
                "BULL_TRENDING": Decimal("150.00"),
                "LOW_VOLATILITY": Decimal("-10.00"),
                "RANGING": Decimal("-35.00"),
            },
        }
    )
    report = evaluator.evaluate(bad_input)
    assert report.eligible_for_scaling is False
    assert report.criteria_results["regime_consistency"].passed is False


def test_criterion_3_drawdown_breach(baseline_passing_metrics: ScalingEvaluationInput) -> None:
    """Verify Criterion 3 fails when drawdown reaches or exceeds 8.0% halt tier."""
    evaluator = CapitalScalingEvaluator()
    bad_input = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "max_historical_drawdown_pct": 8.1}
    )
    report = evaluator.evaluate(bad_input)
    assert report.eligible_for_scaling is False
    assert report.criteria_results["drawdown_adherence"].passed is False


def test_criterion_4_low_sortino_ratio(baseline_passing_metrics: ScalingEvaluationInput) -> None:
    """Verify Criterion 4 fails when Sortino ratio is below 1.0."""
    evaluator = CapitalScalingEvaluator()
    bad_input = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "sortino_ratio": 0.82}
    )
    report = evaluator.evaluate(bad_input)
    assert report.eligible_for_scaling is False
    assert report.criteria_results["sortino_ratio"].passed is False


def test_criterion_5_validation_robustness_failed(
    baseline_passing_metrics: ScalingEvaluationInput,
) -> None:
    """Verify Criterion 5 fails when active model did not pass validation."""
    evaluator = CapitalScalingEvaluator()
    bad_input = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "validation_passed": False}
    )
    report = evaluator.evaluate(bad_input)
    assert report.eligible_for_scaling is False
    assert report.criteria_results["validation_robustness"].passed is False


def test_criterion_6_excessive_live_paper_divergence(
    baseline_passing_metrics: ScalingEvaluationInput,
) -> None:
    """Verify Criterion 6 fails when live/paper divergence exceeds +/- 20%."""
    evaluator = CapitalScalingEvaluator()
    bad_input = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "live_paper_divergence_pct": 24.5}
    )
    report = evaluator.evaluate(bad_input)
    assert report.eligible_for_scaling is False
    assert report.criteria_results["live_paper_divergence"].passed is False


def test_criterion_7_automated_rollbacks_detected(
    baseline_passing_metrics: ScalingEvaluationInput,
) -> None:
    """Verify Criterion 7 fails when any automated rollback occurred."""
    evaluator = CapitalScalingEvaluator()
    bad_input = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "automated_rollback_count": 1}
    )
    report = evaluator.evaluate(bad_input)
    assert report.eligible_for_scaling is False
    assert report.criteria_results["model_stability"].passed is False


def test_criterion_8_execution_quality_slippage_or_duplicates(
    baseline_passing_metrics: ScalingEvaluationInput,
) -> None:
    """Verify Criterion 8 fails when slippage > 1.5x or duplicate orders exist."""
    evaluator = CapitalScalingEvaluator()

    # Case A: Excess slippage
    input_slip = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "avg_slippage_multiplier": 1.75}
    )
    report_a = evaluator.evaluate(input_slip)
    assert report_a.eligible_for_scaling is False
    assert report_a.criteria_results["execution_quality"].passed is False

    # Case B: Duplicate order detected
    input_dup = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "duplicate_order_count": 1}
    )
    report_b = evaluator.evaluate(input_dup)
    assert report_b.eligible_for_scaling is False
    assert report_b.criteria_results["execution_quality"].passed is False


def test_criterion_9_operational_reliability_uptime_or_disconnects(
    baseline_passing_metrics: ScalingEvaluationInput,
) -> None:
    """Verify Criterion 9 fails when uptime < 99.5% or unhandled disconnects exist."""
    evaluator = CapitalScalingEvaluator()

    # Case A: Low uptime
    input_uptime = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "system_uptime_pct": 99.1}
    )
    report_a = evaluator.evaluate(input_uptime)
    assert report_a.eligible_for_scaling is False
    assert report_a.criteria_results["operational_reliability"].passed is False

    # Case B: Unhandled disconnect
    input_disc = ScalingEvaluationInput(
        **{**baseline_passing_metrics.__dict__, "unhandled_disconnect_count": 2}
    )
    report_b = evaluator.evaluate(input_disc)
    assert report_b.eligible_for_scaling is False
    assert report_b.criteria_results["operational_reliability"].passed is False
