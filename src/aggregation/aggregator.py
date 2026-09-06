"""Deterministic weighted signal aggregator and trade quality scoring engine.

Adheres to FRD Module 5, ADD §7, MLD §7, and LLD §8.2.
"""

import math
from datetime import UTC, datetime
from typing import Literal

import structlog

from src.config.models import AggregatorConfig
from src.domain.agent_signal import AgentSignalOutput, SignalDirection
from src.domain.aggregation_result import AggregationResult

logger = structlog.get_logger(__name__)


class SignalAggregator:
    """Deterministic multi-agent voting aggregator and trade quality scoring engine.

    Combines heterogeneous agent signal outputs using configurable weights,
    re-normalizes weights dynamically when agents emit NO_VIEW (FRD-SIG-3),
    computes trade quality score Q = |S|, measures raw agent disagreement dispersion,
    and enforces configurable quality threshold gating (FRD-AGG-6).
    """

    def __init__(self, config: AggregatorConfig | None = None) -> None:
        """Initialize SignalAggregator with configuration.

        Args:
            config: Aggregator configuration including agent weights and thresholds.
        """
        self.config = config or AggregatorConfig()

    def _filter_usable(self, outputs: list[AgentSignalOutput]) -> list[AgentSignalOutput]:
        """Filter out non-actionable signals (NO_VIEW or invalid confidence)."""
        usable: list[AgentSignalOutput] = []
        for o in outputs:
            if o.direction == SignalDirection.NO_VIEW:
                continue
            if not (0.0 < o.confidence <= 1.0):
                logger.warning(
                    "Defensively discarding agent output with invalid confidence",
                    agent_id=o.agent_id,
                    confidence=o.confidence,
                    direction=o.direction,
                )
                continue
            usable.append(o)
        return usable

    def _calculate_weights(self, usable: list[AgentSignalOutput]) -> dict[str, float]:
        """Re-normalize weights among responding agents (MLD §7.2, LLD §8.2)."""
        raw_weights = {o.agent_id: self.config.agent_weights.get(o.agent_id, 1.0) for o in usable}
        total_weight = sum(raw_weights.values())
        if total_weight <= 0.0:
            return {o.agent_id: 1.0 / len(usable) for o in usable}
        return {agent_id: w / total_weight for agent_id, w in raw_weights.items()}

    def _resolve_decision(
        self, weighted_score: float, quality_score: float
    ) -> tuple[bool, Literal["BUY", "SELL"] | None, str]:
        """Determine passed status, trade direction, and diagnostic reason."""
        if weighted_score == 0.0:
            return False, None, "conflicting conviction resulted in net zero score (deadlock)"

        passed = quality_score >= self.config.min_quality_threshold
        if passed:
            direction: Literal["BUY", "SELL"] = "BUY" if weighted_score > 0.0 else "SELL"
            reason = (
                f"cleared min_quality_threshold ({quality_score:.4f} >= "
                f"{self.config.min_quality_threshold:.4f})"
            )
            return True, direction, reason

        reason = (
            f"trade quality score {quality_score:.4f} below min_quality_threshold "
            f"{self.config.min_quality_threshold:.4f} (FRD-AGG-6)"
        )
        return False, None, reason

    def aggregate(
        self,
        outputs: list[AgentSignalOutput],
        timestamp: datetime | None = None,
        timeframe: str | None = None,
    ) -> AggregationResult:
        """Aggregate agent signals into a single consensus decision and quality score.

        Args:
            outputs: List of signal outputs from the active trading agent roster.
            timestamp: Point-in-time calculation timestamp in UTC. If None, derived from signals.
            timeframe: Candidate timeframe under evaluation, if applicable.

        Returns:
            AggregationResult carrying consensus direction, quality score, and audit lineage.
        """
        calc_time = timestamp
        if calc_time is None:
            calc_time = max(o.timestamp for o in outputs) if outputs else datetime.now(tz=UTC)
        if calc_time.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)

        usable = self._filter_usable(outputs)
        if not usable:
            return AggregationResult(
                passed=False,
                score=0.0,
                direction=None,
                disagreement=0.0,
                weighted_score=0.0,
                contributing_agents=[],
                agent_scores={},
                agent_weights={},
                selected_timeframe=timeframe,
                reason="no agent expressed a view (FRD-AGG-4)",
                timestamp=calc_time,
            )

        norm_weights = self._calculate_weights(usable)

        agent_scores: dict[str, float] = {}
        for o in usable:
            sign = 1.0 if o.direction == SignalDirection.LONG else -1.0
            agent_scores[o.agent_id] = sign * o.confidence

        weighted_score = sum(norm_weights[o.agent_id] * agent_scores[o.agent_id] for o in usable)
        weighted_score = max(-1.0, min(1.0, weighted_score))

        # Disagreement: weighted population standard deviation (ADD §7.4, MLD §7.3)
        if len(usable) <= 1:
            disagreement = 0.0
        else:
            weighted_variance = sum(
                norm_weights[o.agent_id] * ((agent_scores[o.agent_id] - weighted_score) ** 2)
                for o in usable
            )
            disagreement = math.sqrt(max(0.0, weighted_variance))

        quality_score = abs(weighted_score)
        passed, direction, reason = self._resolve_decision(weighted_score, quality_score)
        contributing = [o.agent_id for o in usable]

        return AggregationResult(
            passed=passed,
            score=quality_score,
            direction=direction,
            disagreement=disagreement,
            weighted_score=weighted_score,
            contributing_agents=contributing,
            agent_scores=agent_scores,
            agent_weights=norm_weights,
            selected_timeframe=timeframe,
            reason=reason,
            timestamp=calc_time,
        )
