"""Multi-trade variance driver and failure pattern extraction engine.

Conforms to FRD-LEARN-2, SLD §5.2, §10, and MLD §8:
- Aggregates TradeEvaluation records alongside entry DecisionRecords.
- Enforces minimum sample size threshold (>= 30 trades) to avoid chasing statistical noise.
- Evaluates one-tailed statistical significance tests for underperformance clusters.
- Distinguishes CONFIRMED_HYPOTHESIS from OBSERVED_UNCONFIRMED evidence.
- Structurally read-only; never mutates live parameters or executes orders directly.
"""

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.domain.decision import DecisionRecord
from src.domain.evaluation import TradeEvaluation
from src.domain.pattern import ObservedPattern
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _normal_cdf(x: float) -> float:
    """Compute standard normal cumulative distribution function using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


class PatternExtractionConfig(BaseModel):
    """Configuration options for statistical pattern extraction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_sample_size: int = Field(
        default=30,
        ge=5,
        description="Minimum sample size for a pattern to clear evidence bar (SLD §10)",
    )
    significance_level: float = Field(
        default=0.05,
        gt=0.0,
        le=0.20,
        description="P-value significance threshold for one-tailed test (alpha=0.05)",
    )
    min_batch_size: int = Field(
        default=30,
        ge=10,
        description="Minimum evaluated trade count required before extraction (SLD §9)",
    )
    underperformance_margin: float = Field(
        default=0.05,
        ge=0.0,
        description="Minimum absolute win-rate deficit below baseline for consideration",
    )


class PatternExtractionEngine:
    """Statistical pattern detector aggregating post-trade evaluations into actionable hypotheses.

    Adheres to SLD §5.2 and FRD-LEARN-2.
    """

    def __init__(self, config: PatternExtractionConfig | None = None) -> None:
        """Initialize PatternExtractionEngine with configurable thresholds."""
        self.config = config or PatternExtractionConfig()
        self._logger = logger.bind(component="PatternExtractionEngine")

    def extract_patterns(
        self,
        trades: Sequence[TradeEvaluation],
        decisions: Sequence[DecisionRecord] | Mapping[UUID, DecisionRecord],
    ) -> list[ObservedPattern]:
        """Extract statistically significant underperformance clusters from trade evaluations.

        Args:
            trades: Completed round-trip TradeEvaluation records.
            decisions: Linked DecisionRecords (as sequence or UUID-keyed mapping).

        Returns:
            List of ObservedPattern entities (both CONFIRMED_HYPOTHESIS and OBSERVED_UNCONFIRMED).
        """
        n_total = len(trades)
        if n_total < self.config.min_batch_size:
            self._logger.info(
                "hypothesis_starvation_insufficient_sample",
                trades_count=n_total,
                min_required=self.config.min_batch_size,
            )
            return []

        # Index decision records by decision_record_id
        decision_map: dict[UUID, DecisionRecord]
        if isinstance(decisions, Mapping):
            decision_map = dict(decisions)
        else:
            decision_map = {d.decision_record_id: d for d in decisions}

        # Compute baseline population statistics
        winning_trades = [t for t in trades if t.net_pnl > Decimal("0")]
        baseline_win_rate = len(winning_trades) / n_total
        baseline_mean_pnl = sum((t.net_pnl for t in trades), Decimal("0")) / Decimal(n_total)

        # 1. Bucket trades by Regime
        regime_buckets: dict[str, list[TradeEvaluation]] = defaultdict(list)
        # 2. Bucket trades by Contributing Agent
        agent_buckets: dict[str, list[TradeEvaluation]] = defaultdict(list)
        # 3. Bucket trades by Variance Driver
        variance_buckets: dict[str, list[TradeEvaluation]] = defaultdict(list)
        # 4. Bucket trades by Disagreement Level
        disagreement_buckets: dict[str, list[TradeEvaluation]] = defaultdict(list)

        for trade in trades:
            # Group by variance driver
            variance_buckets[trade.variance_driver].append(trade)

            entry_dec = decision_map.get(trade.entry_decision_id)
            if entry_dec:
                # Group by regime
                regime_buckets[entry_dec.regime].append(trade)

                # Identify primary contributing agent
                if entry_dec.agent_scores:
                    primary_agent = max(entry_dec.agent_scores.items(), key=lambda item: item[1])[0]
                    agent_buckets[primary_agent].append(trade)

                # Group by high disagreement
                if entry_dec.disagreement_metric >= 0.35:
                    disagreement_buckets["HIGH_DISAGREEMENT"].append(trade)
                else:
                    disagreement_buckets["LOW_DISAGREEMENT"].append(trade)

        patterns: list[ObservedPattern] = []

        # Evaluate Regime Clusters
        patterns.extend(
            self._evaluate_clusters(
                buckets=regime_buckets,
                pattern_type="REGIME_FAILURE",
                dimension_name="regime",
                n_total=n_total,
                baseline_win_rate=baseline_win_rate,
                baseline_mean_pnl=baseline_mean_pnl,
            )
        )

        # Evaluate Agent Clusters
        patterns.extend(
            self._evaluate_clusters(
                buckets=agent_buckets,
                pattern_type="AGENT_UNDERPERFORMANCE",
                dimension_name="agent_id",
                n_total=n_total,
                baseline_win_rate=baseline_win_rate,
                baseline_mean_pnl=baseline_mean_pnl,
            )
        )

        # Evaluate Variance Driver Clusters
        patterns.extend(
            self._evaluate_clusters(
                buckets=variance_buckets,
                pattern_type="VARIANCE_CLUSTER",
                dimension_name="variance_driver",
                n_total=n_total,
                baseline_win_rate=baseline_win_rate,
                baseline_mean_pnl=baseline_mean_pnl,
            )
        )

        # Evaluate Disagreement Clusters
        patterns.extend(
            self._evaluate_clusters(
                buckets=disagreement_buckets,
                pattern_type="DISAGREEMENT_FAILURE",
                dimension_name="disagreement_level",
                n_total=n_total,
                baseline_win_rate=baseline_win_rate,
                baseline_mean_pnl=baseline_mean_pnl,
            )
        )

        # Sort: CONFIRMED_HYPOTHESIS first, then lowest p_value
        patterns.sort(key=lambda p: (0 if p.status == "CONFIRMED_HYPOTHESIS" else 1, p.p_value))
        return patterns

    def _evaluate_clusters(
        self,
        *,
        buckets: Mapping[str, Sequence[TradeEvaluation]],
        pattern_type: Any,
        dimension_name: str,
        n_total: int,
        baseline_win_rate: float,
        baseline_mean_pnl: Decimal,
    ) -> list[ObservedPattern]:
        """Evaluate statistical underperformance across candidate buckets for a given dimension."""
        results: list[ObservedPattern] = []

        for val, cluster_trades in buckets.items():
            n_cluster = len(cluster_trades)
            if n_cluster < 3:
                # Sub-sample noise below minimal evaluation count
                continue

            wins = sum(1 for t in cluster_trades if t.net_pnl > Decimal("0"))
            cluster_win_rate = wins / n_cluster
            total_net_pnl = sum((t.net_pnl for t in cluster_trades), Decimal("0"))
            cluster_mean_pnl = total_net_pnl / Decimal(n_cluster)

            # Check for underperformance
            if cluster_win_rate > baseline_win_rate - self.config.underperformance_margin:
                # Not an underperforming cluster
                continue

            failure_count = n_cluster - wins

            # Calculate one-tailed two-proportion z-statistic:
            # H0: cluster_win_rate == baseline_win_rate vs Ha: cluster_win_rate < baseline_win_rate
            p0 = max(0.01, min(0.99, baseline_win_rate))
            std_err = math.sqrt((p0 * (1.0 - p0)) / n_cluster)
            z_stat = (cluster_win_rate - p0) / max(std_err, 1e-6)
            p_value = _normal_cdf(z_stat)
            confidence = max(0.0, min(1.0, 1.0 - p_value))

            is_significant = (
                n_cluster >= self.config.min_sample_size
                and p_value <= self.config.significance_level
            )

            status: Literal["CONFIRMED_HYPOTHESIS", "OBSERVED_UNCONFIRMED"] = (
                "CONFIRMED_HYPOTHESIS" if is_significant else "OBSERVED_UNCONFIRMED"
            )

            desc = (
                f"{pattern_type} detected on {dimension_name}='{val}': "
                f"Win rate {cluster_win_rate:.1%} vs baseline {baseline_win_rate:.1%} "
                f"(Sample N={n_cluster}, p={p_value:.4f}, status={status})."
            )

            pattern = ObservedPattern(
                pattern_type=pattern_type,
                target_dimension=dimension_name,
                target_value=str(val),
                sample_size=n_cluster,
                total_trades_analyzed=n_total,
                failure_count=failure_count,
                win_rate=cluster_win_rate,
                baseline_win_rate=baseline_win_rate,
                mean_pnl=cluster_mean_pnl,
                baseline_mean_pnl=baseline_mean_pnl,
                p_value=p_value,
                confidence=confidence,
                is_statistically_significant=is_significant,
                status=status,
                description=desc,
            )
            results.append(pattern)

        return results
