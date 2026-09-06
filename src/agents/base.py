"""Base trading agent protocol and fault-tolerant execution contract.

Adheres to ADD §4, LLD §8.1, FRD-SIG-1/2/3, and subsystem-contracts.md §2.
"""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

import structlog

from src.domain.agent_signal import AgentSignalOutput, SignalDirection
from src.domain.features import FeatureSet
from src.domain.regime import RegimeClassification

logger = structlog.get_logger("agents.base")


@runtime_checkable
class TradingAgent(Protocol):
    """Uniform protocol interface for all trading intelligence agents (ADD §4, LLD §8.1)."""

    agent_id: str

    def evaluate(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> AgentSignalOutput:
        """Compute directional signal and normalized confidence."""
        ...


class BaseAgent(ABC):
    """Abstract base class for trading agents providing fault isolation and normalization.

    Implements the template method pattern:
    - Subclasses implement `_compute_signal(instrument, timeframe, features, regime)`.
    - `evaluate()` wraps computation in an exception-safety harness (FRD-SIG-3).
      If ANY exception occurs or feature inputs are invalid, it safely suppresses
      the failure, logs a structured error, and returns direction=NO_VIEW with confidence=0.0.
    - Enforces strict clamping of confidence in [0.0, 1.0].
    """

    def __init__(self, agent_id: str) -> None:
        """Initialize the trading agent.

        Args:
            agent_id: Canonical unique identifier for the agent.

        Raises:
            ValueError: If agent_id is empty or whitespace.
        """
        if not agent_id or not agent_id.strip():
            msg = "agent_id must be a non-empty string"
            raise ValueError(msg)
        self.agent_id = agent_id.strip()
        self._logger = logger.bind(agent_id=self.agent_id)

    def evaluate(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> AgentSignalOutput:
        """Safely evaluate agent view with fault isolation and validation (FRD-SIG-3).

        Args:
            instrument: Canonical symbol being analyzed.
            timeframe: Primary timeframe of features.
            features: Point-in-time calculated features.
            regime: Point-in-time confirmed market regime.

        Returns:
            AgentSignalOutput containing direction and bounded [0.0, 1.0] confidence.
        """
        try:
            direction, confidence, inputs_used, raw_score = self._compute_signal(
                instrument=instrument,
                timeframe=timeframe,
                features=features,
                regime=regime,
            )
            # Normalize and clamp confidence
            clamped_confidence = max(0.0, min(1.0, float(confidence)))
            if direction == SignalDirection.NO_VIEW:
                clamped_confidence = 0.0

            return AgentSignalOutput(
                agent_id=self.agent_id,
                direction=direction,
                confidence=clamped_confidence,
                inputs_used=inputs_used,
                timestamp=features.timestamp,
                raw_score=raw_score,
            )
        except Exception as exc:
            self._logger.warning(
                "agent_evaluation_failed_safe_fallback",
                instrument=instrument,
                timeframe=timeframe,
                error=str(exc),
                exc_info=True,
            )
            return AgentSignalOutput(
                agent_id=self.agent_id,
                direction=SignalDirection.NO_VIEW,
                confidence=0.0,
                inputs_used={},
                timestamp=features.timestamp,
                raw_score=None,
            )

    @abstractmethod
    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        """Subclass implementation of directional view and confidence calculation."""
        ...
