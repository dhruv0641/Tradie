"""Rule-based Mean-Reversion trading agent (MLD §6.3, ADD §6.2).

Implements statistical price deviation z-score reversion with regime-conditioned
confidence down-weighting during strongly trending market regimes.
"""

from src.agents.base import BaseAgent
from src.domain.agent_signal import SignalDirection
from src.domain.features import FeatureSet
from src.domain.regime import RegimeClassification, TrendState


class MeanReversionAgent(BaseAgent):
    """Rule-based mean-reversion intelligence agent (MLD §6.3).

    Evaluates rolling price deviation z-scores and emits contrarian reversion signals.
    Enforces MLD §6.3 invariant:
    - Deliberately down-weights confidence by trending_discount_factor (default 0.5)
      when regime.trend_state is TRENDING_UP or TRENDING_DOWN.
    """

    def __init__(
        self,
        agent_id: str = "mean_reversion_agent",
        zscore_neutral_band: float = 1.0,
        zscore_cap: float = 3.0,
        trending_discount_factor: float = 0.50,
    ) -> None:
        """Initialize MeanReversionAgent with z-score bounds and discount factor.

        Args:
            agent_id: Unique agent identifier.
            zscore_neutral_band: Absolute z-score threshold below which no signal is generated.
            zscore_cap: Z-score magnitude at which raw confidence saturates to 1.0.
            trending_discount_factor: Multiplier applied to confidence in trending regimes.

        Raises:
            ValueError: If parameters violate boundary constraints.
        """
        super().__init__(agent_id=agent_id)
        if zscore_neutral_band < 0:
            msg = "zscore_neutral_band must be non-negative"
            raise ValueError(msg)
        if zscore_cap <= zscore_neutral_band:
            msg = "zscore_cap must be strictly greater than zscore_neutral_band"
            raise ValueError(msg)
        if not (0.0 < trending_discount_factor <= 1.0):
            msg = "trending_discount_factor must be in (0.0, 1.0]"
            raise ValueError(msg)

        self.zscore_neutral_band = zscore_neutral_band
        self.zscore_cap = zscore_cap
        self.trending_discount_factor = trending_discount_factor

    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        """Compute contrarian mean-reversion view and regime-discounted confidence."""
        feats = features.features
        zscore = feats.get("zscore_20")

        if zscore is None:
            return SignalDirection.NO_VIEW, 0.0, {}, None

        inputs = {"zscore_20": float(zscore)}

        # Neutral band check: small deviations around mean do not trigger a view
        abs_z = abs(zscore)
        if abs_z <= self.zscore_neutral_band:
            return SignalDirection.NO_VIEW, 0.0, inputs, float(zscore)

        # Contrarian directional logic: buy oversold (z < 0), sell overbought (z > 0)
        if zscore < -self.zscore_neutral_band:
            direction = SignalDirection.LONG
        else:
            direction = SignalDirection.SHORT

        # Base confidence from z-score distance from neutral band
        norm_conf = (abs_z - self.zscore_neutral_band) / (
            self.zscore_cap - self.zscore_neutral_band
        )
        raw_confidence = max(0.1, min(1.0, norm_conf))

        # Enforce MLD §6.3 invariant: discount confidence in trending regimes
        is_trending = regime.trend_state in (TrendState.TRENDING_UP, TrendState.TRENDING_DOWN)
        if is_trending:
            confidence = raw_confidence * self.trending_discount_factor
        else:
            confidence = raw_confidence

        return direction, confidence, inputs, float(zscore)
