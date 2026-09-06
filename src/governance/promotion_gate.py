"""Model promotion gate enforcing multi-dimensional criteria and operator sign-off.

Conforms to FRD-LEARN-4, FRD-LEARN-5, FRD-LEARN-8, ADD §8.3, §8.4, MLD §9.2, and BRD BR-6.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from src.domain.governance import ModelVersion
    from src.domain.validation_record import ValidationRunRecord

from src.domain.governance_event import PromotionEvent
from src.utils.logging import get_logger


class PromotionGateConfig(BaseModel):
    """Configuration governing model promotion evaluation criteria."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_sharpe_delta: float = Field(
        default=0.0,
        description="Candidate Sharpe must meet or exceed production baseline (delta >= 0)",
    )
    max_drawdown_tolerance_ratio: float = Field(
        default=1.10,
        description="Candidate MaxDD must not exceed baseline MaxDD * 1.10 (MLD §9.2)",
    )
    require_validation_pass: bool = Field(
        default=True,
        description="Require passing ValidationRunRecord (overall_passed=True)",
    )
    require_operator_signoff: bool = Field(
        default=True,
        description="Require operator manual sign-off identity/token (BRD §11, ADD §8.4)",
    )


class PromotionDecision(BaseModel):
    """Structured result of a promotion gate evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    promoted: bool = Field(description="True if all promotion criteria and sign-off passed")
    candidate_id: str = Field(description="Evaluated candidate model ID")
    baseline_id: str | None = Field(default=None, description="Current baseline model ID if any")
    checks: dict[str, bool] = Field(
        default_factory=dict, description="Status of each individual gate check"
    )
    metrics_comparison: dict[str, Any] = Field(
        default_factory=dict, description="Comparative metrics between candidate and baseline"
    )
    rejection_reasons: list[str] = Field(
        default_factory=list, description="List of reasons if promotion was rejected"
    )
    event: PromotionEvent | None = Field(
        default=None, description="Generated immutable audit event"
    )


class ModelPromotionGate:
    """Evaluates candidates against production baselines and enforces operator sign-off."""

    def __init__(self, config: PromotionGateConfig | None = None) -> None:
        self.config = config or PromotionGateConfig()
        self._logger = get_logger("ModelPromotionGate")

    def evaluate_and_promote(
        self,
        *,
        candidate: ModelVersion,
        validation_record: ValidationRunRecord,
        baseline: ModelVersion | None = None,
        operator_signoff: str | None = None,
        notes: str = "",
    ) -> PromotionDecision:
        """Evaluate candidate vs baseline and atomically promote if all criteria pass."""
        checks: dict[str, bool] = {}
        rejection_reasons: list[str] = []
        metrics_comp: dict[str, Any] = {}

        # 1. Empirical validation pass check
        val_passed = (
            validation_record.overall_passed and validation_record.model_id == candidate.model_id
        )
        checks["validation_passed"] = val_passed
        if self.config.require_validation_pass and not val_passed:
            rejection_reasons.append(
                f"Candidate {candidate.model_id} failed empirical validation pipeline "
                f"(overall_passed={validation_record.overall_passed})"
            )

        # 2. Operator sign-off check
        has_signoff = bool(operator_signoff and operator_signoff.strip())
        checks["operator_signoff"] = has_signoff
        if self.config.require_operator_signoff and not has_signoff:
            rejection_reasons.append(
                "Missing mandatory operator sign-off token (BRD §11 item 6, ADD §8.4)"
            )

        # 3. Metric extraction & multi-dimensional baseline comparison
        self._evaluate_metrics_comparison(
            candidate=candidate,
            baseline=baseline,
            checks=checks,
            rejection_reasons=rejection_reasons,
            metrics_comp=metrics_comp,
        )

        promoted = len(rejection_reasons) == 0
        now = datetime.now(UTC)
        signoff_author = operator_signoff if operator_signoff else "SYSTEM_AUTOMATION"

        if promoted:
            if baseline is not None:
                baseline.status = "superseded"
                self._logger.info(
                    "model_superseded",
                    baseline_id=baseline.model_id,
                    superseded_by=candidate.model_id,
                )

            candidate.status = "promoted"
            candidate.promoted_by = signoff_author
            candidate.promotion_timestamp = now
            self._logger.info(
                "model_promoted",
                candidate_id=candidate.model_id,
                promoted_by=signoff_author,
                baseline_id=baseline.model_id if baseline else None,
            )
        else:
            self._logger.warning(
                "model_promotion_rejected",
                candidate_id=candidate.model_id,
                reasons=rejection_reasons,
            )

        event = PromotionEvent(
            candidate_id=candidate.model_id,
            baseline_id=baseline.model_id if baseline else None,
            validation_run_id=validation_record.run_id,
            promoted=promoted,
            promoted_by=signoff_author,
            metrics_comparison=metrics_comp,
            rejection_reasons=rejection_reasons,
            notes=notes,
            timestamp=now,
        )

        return PromotionDecision(
            promoted=promoted,
            candidate_id=candidate.model_id,
            baseline_id=baseline.model_id if baseline else None,
            checks=checks,
            metrics_comparison=metrics_comp,
            rejection_reasons=rejection_reasons,
            event=event,
        )

    def _evaluate_metrics_comparison(
        self,
        *,
        candidate: ModelVersion,
        baseline: ModelVersion | None,
        checks: dict[str, bool],
        rejection_reasons: list[str],
        metrics_comp: dict[str, Any],
    ) -> None:
        """Helper to compare candidate metrics against baseline model."""
        c_sharpe, c_dd = self._extract_sharpe_and_dd(candidate)
        metrics_comp["candidate_sharpe"] = c_sharpe
        metrics_comp["candidate_drawdown_pct"] = c_dd

        if baseline is not None:
            b_sharpe, b_dd = self._extract_sharpe_and_dd(baseline)
            metrics_comp["baseline_sharpe"] = b_sharpe
            metrics_comp["baseline_drawdown_pct"] = b_dd

            sharpe_passed = c_sharpe >= (b_sharpe + self.config.min_sharpe_delta)
            checks["sharpe_superiority"] = sharpe_passed
            if not sharpe_passed:
                rejection_reasons.append(
                    f"Candidate Sharpe ({c_sharpe:.2f}) does not meet baseline expectation "
                    f"({b_sharpe:.2f} + delta {self.config.min_sharpe_delta:.2f})"
                )

            max_allowed_dd = b_dd * self.config.max_drawdown_tolerance_ratio
            dd_passed = c_dd <= max_allowed_dd
            checks["drawdown_tolerance"] = dd_passed
            if not dd_passed:
                rejection_reasons.append(
                    f"Candidate MaxDD ({c_dd:.2f}%) exceeds baseline tolerance "
                    f"ceiling ({max_allowed_dd:.2f}%)"
                )
        else:
            checks["sharpe_superiority"] = c_sharpe >= 0.0
            checks["drawdown_tolerance"] = True
            if c_sharpe < 0.0:
                rejection_reasons.append(
                    f"Candidate initial Sharpe must be non-negative ({c_sharpe:.2f})"
                )

    @staticmethod
    def _extract_sharpe_and_dd(model: ModelVersion) -> tuple[float, float]:
        """Extract Sharpe ratio and Drawdown percentage from model validation metrics."""
        vm = model.validation_metrics
        sharpe = float(vm.get("sharpe_ratio", vm.get("sharpe", 1.0)))
        raw_dd = float(vm.get("max_drawdown_pct", vm.get("max_drawdown", 5.0)))
        dd = raw_dd * 100.0 if raw_dd <= 1.0 else raw_dd
        return sharpe, dd
