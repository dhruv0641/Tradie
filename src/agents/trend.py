"""Rule-based Trend trading agent (MLD §6.1, ADD §6.2).

Implements directional trend identification and percentile-based confidence
scaling while enforcing non-negotiable regime suppression invariants.
"""

from collections import deque

from src.agents.base import BaseAgent
from src.domain.agent_signal import SignalDirection
from src.domain.features import FeatureSet
from src.domain.regime import RegimeClassification, TrendState


class TrendAgent(BaseAgent):
    """Rule-based trend-following intelligence agent (MLD §6.1).

    Evaluates moving-average alignment and ADX directional strength.
    Enforces MLD §6.1 invariants:
    - Emits NO_VIEW (confidence 0.0) when regime.trend_state is RANGING or UNKNOWN.
    - Emits NO_VIEW when ADX is below min_adx_strength.
    - Normalizes confidence based on trend strength percentile.
    """

    def __init__(
        self,
        agent_id: str = "trend_agent",
        min_adx_strength: float = 25.0,
        adx_saturation: float = 50.0,
        rolling_window: int = 100,
    ) -> None:
        """Initialize TrendAgent with thresholds and rolling buffer.

        Args:
            agent_id: Unique agent identifier.
            min_adx_strength: Minimum ADX value required for a directional view.
            adx_saturation: ADX level corresponding to maximum saturation.
            rolling_window: Length of trailing buffer for percentile calculation.

        Raises:
            ValueError: If parameters violate boundary constraints.
        """
        super().__init__(agent_id=agent_id)
        if min_adx_strength <= 0:
            msg = "min_adx_strength must be positive"
            raise ValueError(msg)
        if adx_saturation <= min_adx_strength:
            msg = "adx_saturation must be greater than min_adx_strength"
            raise ValueError(msg)

        self.min_adx_strength = min_adx_strength
        self.adx_saturation = adx_saturation
        self.rolling_window = rolling_window
        self._adx_history: dict[tuple[str, str], deque[float]] = {}

    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        """Compute directional trend view and normalized confidence."""
        # Invariant 1: MLD §6.1: NO_VIEW when trend state is RANGING or UNKNOWN
        if regime.trend_state in (TrendState.RANGING, TrendState.UNKNOWN):
            return SignalDirection.NO_VIEW, 0.0, {}, None

        feats = features.features
        adx = feats.get("adx_14")
        plus_di = feats.get("plus_di_14")
        minus_di = feats.get("minus_di_14")
        sma_fast = feats.get("sma_20")
        sma_slow = feats.get("sma_50")

        if any(v is None for v in (adx, plus_di, minus_di, sma_fast, sma_slow)):
            return SignalDirection.NO_VIEW, 0.0, {}, None

        assert adx is not None and plus_di is not None and minus_di is not None
        assert sma_fast is not None and sma_slow is not None

        inputs = {
            "adx_14": float(adx),
            "plus_di_14": float(plus_di),
            "minus_di_14": float(minus_di),
            "sma_20": float(sma_fast),
            "sma_50": float(sma_slow),
        }

        # Invariant 2: ADX must satisfy minimum strength
        if adx < self.min_adx_strength:
            return SignalDirection.NO_VIEW, 0.0, inputs, float(adx)

        # Update rolling ADX history for percentile confidence calculation
        key = (instrument, timeframe)
        if key not in self._adx_history:
            self._adx_history[key] = deque(maxlen=self.rolling_window)
        self._adx_history[key].append(float(adx))

        # Directional view: alignment of fast/slow SMA and directional indicators
        is_bullish_alignment = sma_fast > sma_slow and plus_di > minus_di
        is_bearish_alignment = sma_fast < sma_slow and minus_di > plus_di

        if is_bullish_alignment:
            direction = SignalDirection.LONG
        elif is_bearish_alignment:
            direction = SignalDirection.SHORT
        else:
            return SignalDirection.NO_VIEW, 0.0, inputs, float(adx)

        # Confidence: rolling percentile rank (MLD §6.1) or linear saturation
        history = list(self._adx_history[key])
        if len(history) >= 10:
            rank = sum(1.0 for h in history if h <= adx)
            confidence = max(0.1, min(1.0, rank / len(history)))
        else:
            norm = (adx - self.min_adx_strength) / (
                self.adx_saturation - self.min_adx_strength
            )
            confidence = max(0.1, min(1.0, norm))

        return direction, confidence, inputs, float(adx)

    def clear_history(self) -> None:
        """Clear historical rolling ADX buffers."""
        self._adx_history.clear()
