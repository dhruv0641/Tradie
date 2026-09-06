"""Hypothesis-to-candidate generation workflow and scoping engine.

Conforms to FRD-LEARN-2, SLD §6, §8, §10, and ADD §10:
- Converts confirmed ObservedPattern hypotheses into scoped ModelVersion candidates.
- Enforces one-change-at-a-time scoping discipline (SLD §6.2).
- Enforces strict concurrency limits (max 1 candidate in validation pipeline, SLD §8).
- Enforces minimum cooldown period (30 completed trades) per agent/parameter area (SLD §8, §10).
- Purely produces candidate artifacts for Stage 3 validation; never mutates live
  parameters directly.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.domain.governance import ModelVersion
from src.domain.pattern import ObservedPattern
from src.utils.logging import get_logger

logger = get_logger(__name__)


class CandidateGenerationError(Exception):
    """Base exception for candidate generation and scoping workflow violations."""


class CandidateConcurrencyLimitError(CandidateGenerationError):
    """Raised when candidate creation exceeds maximum concurrent validation limit (SLD §8)."""


class CandidateCooldownError(CandidateGenerationError):
    """Raised when candidate creation violates the minimum cooldown period (SLD §8)."""


class MultiChangeViolationError(CandidateGenerationError):
    """Raised when candidate violates one-change-at-a-time discipline (SLD §6.2)."""


class CandidateGeneratorConfig(BaseModel):
    """Governance configuration options for candidate generation and throttled scoping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_concurrent_candidates: int = Field(
        default=1,
        ge=1,
        description="Maximum concurrent candidates permitted in validation pipeline (SLD §8)",
    )
    cooldown_trades: int = Field(
        default=30,
        ge=1,
        description="Minimum trades required before revising the same agent/parameter (SLD §8)",
    )
    require_confirmed_hypothesis: bool = Field(
        default=True,
        description="Strictly require CONFIRMED_HYPOTHESIS status before proposing candidate",
    )


class CandidateGenerationResult(BaseModel):
    """Outcome of a candidate generation attempt with structured attribution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_generated: bool = Field(description="True if candidate was successfully scoped and created")
    candidate: ModelVersion | None = Field(
        default=None,
        description="Constructed candidate ModelVersion if generated; else None",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Structured rationale explaining why candidate was throttled or rejected",
    )
    cooldown_remaining_trades: int = Field(
        default=0,
        ge=0,
        description="Number of completed trades remaining until cooldown expires for this target",
    )
    active_candidates_count: int = Field(
        default=0,
        ge=0,
        description="Number of candidates currently active in validation pipeline",
    )


class CandidateGenerator:
    """Orchestrates disciplined, scoped candidate generation from empirical trade patterns.

    Adheres strictly to SLD §6 & §8.
    """

    def __init__(self, config: CandidateGeneratorConfig | None = None) -> None:
        """Initialize CandidateGenerator with configurable throttles."""
        self.config = config or CandidateGeneratorConfig()
        self._active_candidates: dict[str, ModelVersion] = {}
        self._last_change_trade_counts: dict[str, int] = {}
        self._current_trade_count: int = 0
        self._logger = logger.bind(component="CandidateGenerator")

    @property
    def active_candidates(self) -> list[ModelVersion]:
        """Return list of active candidates currently in the validation pipeline."""
        return list(self._active_candidates.values())

    def update_trade_progress(self, total_completed_trades: int) -> None:
        """Update system completed trade count counter for cooldown tracking."""
        self._current_trade_count = max(self._current_trade_count, total_completed_trades)

    def register_pipeline_candidate(self, candidate: ModelVersion) -> None:
        """Explicitly register an externally managed candidate into active pipeline."""
        self._active_candidates[candidate.model_id] = candidate

    def release_pipeline_candidate(
        self,
        model_id: str,
        final_status: Literal["promoted", "rolled_back", "rejected"],
    ) -> None:
        """Remove candidate from active pipeline upon validation resolution.

        Args:
            model_id: Identifier of model version exiting validation.
            final_status: Final resolution status ('promoted', 'rolled_back', 'rejected').
        """
        _ = final_status
        if model_id in self._active_candidates:
            cand = self._active_candidates.pop(model_id)
            # Record last change timestamp/trade-count for cooldown on target
            if cand.targeted_change:
                dim = str(cand.targeted_change.get("target_dimension", "unknown"))
                val = str(cand.targeted_change.get("target_value", "unknown"))
                target_key = f"{dim}:{val}"
                self._last_change_trade_counts[target_key] = self._current_trade_count

    def generate_candidate(
        self,
        *,
        pattern: ObservedPattern,
        proposed_change: dict[str, Any],
        candidate_name: str | None = None,
    ) -> CandidateGenerationResult:
        """Generate a scoped ModelVersion candidate from a confirmed ObservedPattern.

        Args:
            pattern: Source ObservedPattern extracted by PatternExtractionEngine.
            proposed_change: Dictionary detailing atomic parameter/weight adjustment.
            candidate_name: Optional human-readable candidate title.

        Returns:
            CandidateGenerationResult indicating whether candidate was accepted or throttled.
        """
        target_key = f"{pattern.target_dimension}:{pattern.target_value}"

        # 1. Evidence Bar Check (SLD §5.2)
        if self.config.require_confirmed_hypothesis and pattern.status != "CONFIRMED_HYPOTHESIS":
            reason = (
                f"Pattern '{target_key}' has status='{pattern.status}'. Only CONFIRMED_HYPOTHESIS "
                "clears the evidence bar for candidate generation (SLD §5.2)."
            )
            self._logger.info("candidate_rejected_unconfirmed_pattern", reason=reason)
            return CandidateGenerationResult(
                is_generated=False,
                rejection_reason=reason,
                active_candidates_count=len(self._active_candidates),
            )

        # 2. Concurrency Limit Check (SLD §8)
        active_count = len(self._active_candidates)
        if active_count >= self.config.max_concurrent_candidates:
            reason = (
                f"Validation pipeline concurrency limit reached: {active_count}/"
                f"{self.config.max_concurrent_candidates} active candidates (SLD §8)."
            )
            self._logger.info("candidate_throttled_concurrency_limit", reason=reason)
            return CandidateGenerationResult(
                is_generated=False,
                rejection_reason=reason,
                active_candidates_count=active_count,
            )

        # 3. Cooldown Period Check (SLD §8, §10)
        if target_key in self._last_change_trade_counts:
            last_trade = self._last_change_trade_counts[target_key]
            elapsed = self._current_trade_count - last_trade
            if elapsed < self.config.cooldown_trades:
                remaining = self.config.cooldown_trades - elapsed
                reason = (
                    f"Cooldown period active for '{target_key}': {elapsed}/"
                    f"{self.config.cooldown_trades} trades elapsed ({remaining} remaining, SLD §8)."
                )
                self._logger.info("candidate_throttled_cooldown_active", reason=reason)
                return CandidateGenerationResult(
                    is_generated=False,
                    rejection_reason=reason,
                    cooldown_remaining_trades=remaining,
                    active_candidates_count=active_count,
                )

        # 4. One-Change-at-a-Time Discipline Check (SLD §6.2)
        clean_changes = {k: v for k, v in proposed_change.items() if not k.startswith("__")}
        if len(clean_changes) > 1 and not proposed_change.get("__linked_change__", False):
            reason = (
                "One-change-at-a-time discipline violated: proposed change modifies "
                f"{len(clean_changes)} unlinked parameters simultaneously without "
                "explicit causal linkage (SLD §6.2)."
            )
            self._logger.warning("candidate_rejected_multi_change_violation", reason=reason)
            return CandidateGenerationResult(
                is_generated=False,
                rejection_reason=reason,
                active_candidates_count=active_count,
            )

        # 5. Build Scoped ModelVersion Candidate
        serialized_change = json.dumps(proposed_change, sort_keys=True, default=str)
        model_hash = hashlib.sha256(serialized_change.encode("utf-8")).hexdigest()
        unique_suffix = uuid4().hex[:8]
        model_id = f"cand_{pattern.target_dimension}_{unique_suffix}"
        model_title = (
            candidate_name or f"Candidate_{pattern.target_dimension}_{pattern.target_value}"
        )

        scoped_change_payload: dict[str, Any] = {
            "target_dimension": pattern.target_dimension,
            "target_value": pattern.target_value,
            "proposed_parameters": clean_changes,
            "source_win_rate": pattern.win_rate,
            "baseline_win_rate": pattern.baseline_win_rate,
        }

        candidate = ModelVersion(
            model_id=model_id,
            model_name=model_title,
            version_tag=f"cand-v1-{unique_suffix}",
            model_hash=model_hash,
            trained_at=datetime.now(UTC),
            status="candidate",
            validation_metrics={},
            hypothesis_id=str(pattern.pattern_id),
            source_pattern_id=str(pattern.pattern_id),
            targeted_change=scoped_change_payload,
            scoping_notes=(
                f"Scoped candidate response to {pattern.pattern_type} on "
                f"{pattern.target_dimension}='{pattern.target_value}' "
                f"(Win rate {pattern.win_rate:.1%})."
            ),
        )

        # Register into active validation pipeline and set cooldown baseline
        self._active_candidates[candidate.model_id] = candidate
        self._last_change_trade_counts[target_key] = self._current_trade_count

        self._logger.info(
            "candidate_generated_successfully",
            model_id=candidate.model_id,
            target_key=target_key,
        )

        return CandidateGenerationResult(
            is_generated=True,
            candidate=candidate,
            active_candidates_count=len(self._active_candidates),
        )
