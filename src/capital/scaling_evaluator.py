"""Multi-criteria capital scaling evaluation engine adhering strictly to RTLD §15.

Evaluates all 9 statistical and operational criteria before recommending capital step increases.
Adheres to BRD BR-2, FRD-CAP-2, FRD-CAP-5, FRD-CAP-6, and RTLD §15.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

import structlog

from src.domain.scaling_report import CapitalScalingReport, CriterionResult

logger = structlog.get_logger("capital.scaling_evaluator")


@dataclass(frozen=True)
class ScalingEvaluationInput:
    """Consolidated historical and operational metrics for capital scaling evaluation."""

    current_capital: Decimal
    live_days: int
    closed_trade_count: int
    regime_expectancies: dict[str, Decimal]
    max_historical_drawdown_pct: float
    sortino_ratio: float
    validation_passed: bool
    live_paper_divergence_pct: float
    automated_rollback_count: int
    avg_slippage_multiplier: float
    duplicate_order_count: int
    system_uptime_pct: float
    unhandled_disconnect_count: int


class CapitalScalingEvaluator:
    """Evaluates whether the trading system has earned the right to scale capital.

    Strictly enforces all 9 criteria defined in RTLD §15 and SOW §6.9 (Phase V8).
    This engine only emits recommendations; it CANNOT scale capital autonomously (BRD BR-2).
    """

    def __init__(
        self,
        min_live_days: int = 90,
        min_closed_trades: int = 30,
        min_profitable_regimes: int = 2,
        max_permitted_drawdown_pct: float = 8.0,
        min_sortino_ratio: float = 1.0,
        max_live_paper_divergence_pct: float = 20.0,
        max_slippage_multiplier: float = 1.5,
        min_uptime_pct: float = 99.5,
    ) -> None:
        self.min_live_days = min_live_days
        self.min_closed_trades = min_closed_trades
        self.min_profitable_regimes = min_profitable_regimes
        self.max_permitted_drawdown_pct = max_permitted_drawdown_pct
        self.min_sortino_ratio = min_sortino_ratio
        self.max_live_paper_divergence_pct = max_live_paper_divergence_pct
        self.max_slippage_multiplier = max_slippage_multiplier
        self.min_uptime_pct = min_uptime_pct
        self._log = logger.bind(component="CapitalScalingEvaluator")

    def evaluate(self, metrics: ScalingEvaluationInput) -> CapitalScalingReport:
        """Evaluate all 9 RTLD §15 criteria and return a comprehensive audit report."""
        results: dict[str, CriterionResult] = {}

        # Criterion 1: Minimum Sample Size (>= 30 closed live trades over >= 90 days)
        c1_passed = (
            metrics.closed_trade_count >= self.min_closed_trades
            and metrics.live_days >= self.min_live_days
        )
        results["sample_size"] = CriterionResult(
            criterion_number=1,
            name="Minimum Sample Size",
            passed=c1_passed,
            threshold=f">={self.min_closed_trades} trades over >={self.min_live_days} days",
            actual=f"{metrics.closed_trade_count} trades over {metrics.live_days} days",
            evidence={"trades": metrics.closed_trade_count, "days": metrics.live_days},
        )

        # Criterion 2: Consistency across Regimes (Positive expectancy in >= 2 distinct regimes)
        profitable_regimes = [
            r for r, exp in metrics.regime_expectancies.items() if exp > Decimal("0.00")
        ]
        c2_passed = len(profitable_regimes) >= self.min_profitable_regimes
        regime_names_str = ", ".join(profitable_regimes) or "none"
        results["regime_consistency"] = CriterionResult(
            criterion_number=2,
            name="Regime Consistency",
            passed=c2_passed,
            threshold=f"Positive expectancy across >={self.min_profitable_regimes} regimes",
            actual=f"{len(profitable_regimes)} profitable regimes ({regime_names_str})",
            evidence={
                "profitable_regimes": profitable_regimes,
                "all": {k: str(v) for k, v in metrics.regime_expectancies.items()},
            },
        )

        # Criterion 3: Drawdown Adherence (Zero breaches of 8% hard halt tier)
        c3_passed = metrics.max_historical_drawdown_pct < self.max_permitted_drawdown_pct
        results["drawdown_adherence"] = CriterionResult(
            criterion_number=3,
            name="Drawdown Adherence",
            passed=c3_passed,
            threshold=f"Max drawdown < {self.max_permitted_drawdown_pct:.1f}%",
            actual=f"{metrics.max_historical_drawdown_pct:.2f}%",
            evidence={"max_drawdown_pct": metrics.max_historical_drawdown_pct},
        )

        # Criterion 4: Risk-Adjusted Return (Sortino ratio >= 1.0)
        c4_passed = metrics.sortino_ratio >= self.min_sortino_ratio
        results["sortino_ratio"] = CriterionResult(
            criterion_number=4,
            name="Risk-Adjusted Return",
            passed=c4_passed,
            threshold=f"Sortino ratio >= {self.min_sortino_ratio:.2f}",
            actual=f"{metrics.sortino_ratio:.2f}",
            evidence={"sortino_ratio": metrics.sortino_ratio},
        )

        # Criterion 5: Robustness (Active model passed all validation stages without degradation)
        c5_passed = metrics.validation_passed
        results["validation_robustness"] = CriterionResult(
            criterion_number=5,
            name="Validation Robustness",
            passed=c5_passed,
            threshold="Active model passed all validation stages without degradation",
            actual="Passed" if c5_passed else "Failed",
            evidence={"validation_passed": metrics.validation_passed},
        )

        # Criterion 6: Live/Paper Divergence (Within <= 20% tolerance band)
        c6_passed = abs(metrics.live_paper_divergence_pct) <= self.max_live_paper_divergence_pct
        results["live_paper_divergence"] = CriterionResult(
            criterion_number=6,
            name="Live/Paper Divergence",
            passed=c6_passed,
            threshold=f"Divergence within +/-{self.max_live_paper_divergence_pct:.1f}%",
            actual=f"{metrics.live_paper_divergence_pct:.2f}%",
            evidence={"divergence_pct": metrics.live_paper_divergence_pct},
        )

        # Criterion 7: Model Stability (Zero automated rollbacks during evaluation window)
        c7_passed = metrics.automated_rollback_count == 0
        results["model_stability"] = CriterionResult(
            criterion_number=7,
            name="Model Stability",
            passed=c7_passed,
            threshold="Zero automated rollbacks during evaluation window",
            actual=f"{metrics.automated_rollback_count} rollbacks",
            evidence={"automated_rollback_count": metrics.automated_rollback_count},
        )

        # Criterion 8: Execution Quality (Slippage <= 1.5x and zero duplicate orders)
        c8_passed = (
            metrics.avg_slippage_multiplier <= self.max_slippage_multiplier
            and metrics.duplicate_order_count == 0
        )
        results["execution_quality"] = CriterionResult(
            criterion_number=8,
            name="Execution Quality",
            passed=c8_passed,
            threshold=f"Slippage <= {self.max_slippage_multiplier:.1f}x and zero duplicate orders",
            actual=(
                f"{metrics.avg_slippage_multiplier:.2f}x slippage, "
                f"{metrics.duplicate_order_count} duplicates"
            ),
            evidence={
                "avg_slippage_multiplier": metrics.avg_slippage_multiplier,
                "duplicate_order_count": metrics.duplicate_order_count,
            },
        )

        # Criterion 9: Operational Reliability (Uptime >= 99.5% and zero unhandled disconnects)
        c9_passed = (
            metrics.system_uptime_pct >= self.min_uptime_pct
            and metrics.unhandled_disconnect_count == 0
        )
        results["operational_reliability"] = CriterionResult(
            criterion_number=9,
            name="Operational Reliability",
            passed=c9_passed,
            threshold=f"Uptime >= {self.min_uptime_pct:.1f}% and zero unhandled disconnects",
            actual=(
                f"{metrics.system_uptime_pct:.2f}% uptime, "
                f"{metrics.unhandled_disconnect_count} disconnects"
            ),
            evidence={
                "system_uptime_pct": metrics.system_uptime_pct,
                "unhandled_disconnect_count": metrics.unhandled_disconnect_count,
            },
        )

        passed_count = sum(1 for res in results.values() if res.passed)
        eligible = passed_count == 9

        if eligible:
            # Step-wise scaling recommendation is capped strictly at +25% (FRD-CAP-3, RTLD §15)
            recommended_capital = (metrics.current_capital * Decimal("1.25")).quantize(
                Decimal("0.01")
            )
            verdict = (
                "ELIGIBLE: All 9 RTLD §15 capital scaling criteria satisfied. "
                f"+25% step-scaling (₹{metrics.current_capital:,.2f} -> "
                f"₹{recommended_capital:,.2f}) recommended pending operator authorization."
            )
        else:
            recommended_capital = None
            failed_criteria = [res.name for res in results.values() if not res.passed]
            verdict = (
                f"INELIGIBLE: {9 - passed_count} criteria failed ({', '.join(failed_criteria)}). "
                "Capital scaling blocked per BRD BR-2 and RTLD §15."
            )

        report = CapitalScalingReport(
            report_id=f"cap_eval_{uuid.uuid4().hex[:12]}",
            current_capital=metrics.current_capital,
            recommended_capital=recommended_capital,
            eligible_for_scaling=eligible,
            criteria_results=results,
            passed_count=passed_count,
            total_criteria=9,
            summary_verdict=verdict,
            evaluation_window_days=metrics.live_days,
        )

        self._log.info(
            "capital_scaling_evaluation_completed",
            eligible=eligible,
            passed_count=passed_count,
            current_capital=str(metrics.current_capital),
            recommended_capital=str(recommended_capital) if recommended_capital else "NONE",
        )

        return report
