"""Dynamic multi-timeframe intelligence and timeframe selection engine.

Adheres to FRD Module 5, ADD §7.3, and LLD §8.3.
"""

from datetime import UTC, datetime

import structlog

from src.aggregation.aggregator import SignalAggregator
from src.config.models import AggregatorConfig
from src.domain.agent_signal import AgentSignalOutput
from src.domain.aggregation_result import AggregationResult

logger = structlog.get_logger(__name__)


class TimeframeSelector:
    """Dynamic timeframe selection engine evaluating candidate opportunities across timeframes.

    Performs multi-timeframe weighted scoring (ADD §7.3, FRD-AGG-3), selects the timeframe
    with the highest qualifying trade quality score, and strictly enforces NO TRADE discipline
    when no timeframe clears the quality threshold (FRD-AGG-4).
    """

    def __init__(
        self,
        aggregator: SignalAggregator | None = None,
        config: AggregatorConfig | None = None,
    ) -> None:
        """Initialize TimeframeSelector.

        Args:
            aggregator: SignalAggregator instance. If None, initialized from config.
            config: Aggregator configuration including thresholds and timeframes.
        """
        self.config = config or (aggregator.config if aggregator else AggregatorConfig())
        self.aggregator = aggregator or SignalAggregator(config=self.config)

    def select_best_timeframe(
        self,
        per_timeframe_outputs: dict[str, list[AgentSignalOutput]],
        timestamp: datetime | None = None,
    ) -> AggregationResult:
        """Evaluate opportunities across multiple candidate timeframes and select the best.

        Args:
            per_timeframe_outputs: Map of timeframe string (e.g. '5m', '15m') to agent signal lists.
            timestamp: Point-in-time calculation timestamp in UTC.

        Returns:
            Winning AggregationResult with selected_timeframe populated, or NO TRADE result.
        """
        if timestamp is not None and timestamp.tzinfo is None:
            msg = "Timestamp must be timezone-aware UTC"
            raise ValueError(msg)

        if not per_timeframe_outputs:
            calc_time = timestamp or datetime.now(tz=UTC)
            return AggregationResult(
                passed=False,
                score=0.0,
                direction=None,
                disagreement=0.0,
                weighted_score=0.0,
                contributing_agents=[],
                agent_scores={},
                agent_weights={},
                selected_timeframe=None,
                reason="no candidate timeframes provided (FRD-AGG-4)",
                timestamp=calc_time,
            )

        # 1. Run weighted aggregation independently per candidate timeframe
        results: dict[str, AggregationResult] = {
            tf: self.aggregator.aggregate(outs, timestamp=timestamp, timeframe=tf)
            for tf, outs in per_timeframe_outputs.items()
        }

        # 2. Filter candidate timeframes that cleared the quality threshold
        passing = {tf: r for tf, r in results.items() if r.passed}

        # 3. If no candidate timeframe cleared threshold, enforce strict NO TRADE (FRD-AGG-4)
        if not passing:
            best_rejected_tf = max(results, key=lambda tf: results[tf].score)
            best_score = results[best_rejected_tf].score
            calc_time = timestamp or max(r.timestamp for r in results.values())

            logger.info(
                "No candidate timeframe cleared quality threshold; outputting NO_TRADE",
                best_rejected_timeframe=best_rejected_tf,
                best_score=best_score,
                min_threshold=self.config.min_quality_threshold,
            )
            return AggregationResult(
                passed=False,
                score=0.0,
                direction=None,
                disagreement=0.0,
                weighted_score=0.0,
                contributing_agents=[],
                agent_scores={},
                agent_weights={},
                selected_timeframe=None,
                reason=(
                    f"no timeframe cleared min_quality_threshold (FRD-AGG-4) "
                    f"[best rejected: {best_rejected_tf} with score {best_score:.4f}]"
                ),
                timestamp=calc_time,
            )

        # 4. Select passing timeframe with highest quality score Q,
        # tie-broken by lowest disagreement
        best_tf = max(
            passing,
            key=lambda tf: (passing[tf].score, -passing[tf].disagreement),
        )

        winning_result = passing[best_tf]
        logger.info(
            "Selected optimal passing timeframe",
            selected_timeframe=best_tf,
            score=winning_result.score,
            direction=winning_result.direction,
            disagreement=winning_result.disagreement,
        )
        return winning_result
