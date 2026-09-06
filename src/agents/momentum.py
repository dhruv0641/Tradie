"""Rule-based Momentum trading agent (MLD §6.2, ADD §6.2).

Implements multi-window Rate-of-Change and RSI oscillator evaluation
with neutral-band suppression and normalized midpoint distance scaling.
"""

from src.agents.base import BaseAgent
from src.domain.agent_signal import SignalDirection
from src.domain.features import FeatureSet
from src.domain.regime import RegimeClassification


class MomentumAgent(BaseAgent):
    """Rule-based momentum intelligence agent (MLD §6.2).

    Evaluates Rate-of-Change and RSI oscillator deviation from midpoint.
    Suppresses signals within a configurable neutral band.
    """

    def __init__(
        self,
        agent_id: str = "momentum_agent",
        roc_neutral_band: float = 0.50,
        rsi_neutral_band: float = 3.0,
        rsi_max_deviation: float = 25.0,
    ) -> None:
        """Initialize MomentumAgent with neutral-band parameters.

        Args:
            agent_id: Unique agent identifier.
            roc_neutral_band: Absolute percentage threshold around 0.0 defining neutral ROC.
            rsi_neutral_band: Absolute distance from 50.0 defining neutral RSI.
            rsi_max_deviation: RSI distance from 50.0 where confidence saturates to 1.0.

        Raises:
            ValueError: If parameters violate bounds.
        """
        super().__init__(agent_id=agent_id)
        if roc_neutral_band < 0:
            msg = "roc_neutral_band must be non-negative"
            raise ValueError(msg)
        if rsi_neutral_band < 0:
            msg = "rsi_neutral_band must be non-negative"
            raise ValueError(msg)
        if rsi_max_deviation <= rsi_neutral_band:
            msg = "rsi_max_deviation must be strictly greater than rsi_neutral_band"
            raise ValueError(msg)

        self.roc_neutral_band = roc_neutral_band
        self.rsi_neutral_band = rsi_neutral_band
        self.rsi_max_deviation = rsi_max_deviation

    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        """Compute directional momentum view and normalized confidence."""
        feats = features.features
        roc = feats.get("roc_10")
        rsi = feats.get("rsi_14")

        if roc is None or rsi is None:
            return SignalDirection.NO_VIEW, 0.0, {}, None

        inputs = {
            "roc_10": float(roc),
            "rsi_14": float(rsi),
        }

        # Check neutral band: both ROC and RSI inside neutral zones
        is_roc_neutral = abs(roc) <= self.roc_neutral_band
        is_rsi_neutral = abs(rsi - 50.0) <= self.rsi_neutral_band
        if is_roc_neutral and is_rsi_neutral:
            return SignalDirection.NO_VIEW, 0.0, inputs, float(roc)

        # Directional consensus: ROC and RSI must be aligned
        is_bullish = roc > self.roc_neutral_band and rsi > 50.0
        is_bearish = roc < -self.roc_neutral_band and rsi < 50.0

        if is_bullish:
            direction = SignalDirection.LONG
        elif is_bearish:
            direction = SignalDirection.SHORT
        else:
            # Conflicting signals (e.g., positive ROC but sub-50 RSI) -> NO_VIEW
            return SignalDirection.NO_VIEW, 0.0, inputs, float(roc)

        # Confidence: distance of RSI from neutral midpoint 50.0, normalized to [0, 1]
        rsi_dist = abs(rsi - 50.0)
        norm_conf = (rsi_dist - self.rsi_neutral_band) / (
            self.rsi_max_deviation - self.rsi_neutral_band
        )
        confidence = max(0.1, min(1.0, norm_conf))

        return direction, confidence, inputs, float(roc)
