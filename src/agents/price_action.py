"""Rule-based Price Action trading agent (MLD §6.4, ADD §6.2).

Implements market structure proximity detection, candlestick rejection wick
analysis, and structural support/resistance bounce/rejection signal generation.
"""

from src.agents.base import BaseAgent
from src.domain.agent_signal import SignalDirection
from src.domain.features import FeatureSet
from src.domain.regime import RegimeClassification


class PriceActionAgent(BaseAgent):
    """Rule-based price action intelligence agent (MLD §6.4).

    Evaluates proximity to support and resistance clusters alongside candlestick
    rejection wicks and reversal patterns.
    """

    def __init__(
        self,
        agent_id: str = "price_action_agent",
        proximity_threshold_pct: float = 0.50,
        min_rejection_wick_ratio: float = 0.35,
    ) -> None:
        """Initialize PriceActionAgent with proximity and wick thresholds.

        Args:
            agent_id: Unique agent identifier.
            proximity_threshold_pct: Percentage distance to support/resistance considered 'near'.
            min_rejection_wick_ratio: Minimum ratio of shadow to total range denoting rejection.

        Raises:
            ValueError: If parameters violate boundary constraints.
        """
        super().__init__(agent_id=agent_id)
        if proximity_threshold_pct <= 0:
            msg = "proximity_threshold_pct must be positive"
            raise ValueError(msg)
        if not (0.0 < min_rejection_wick_ratio < 1.0):
            msg = "min_rejection_wick_ratio must be in (0.0, 1.0)"
            raise ValueError(msg)

        self.proximity_threshold_pct = proximity_threshold_pct
        self.min_rejection_wick_ratio = min_rejection_wick_ratio

    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        """Compute price action view from level proximity and rejection patterns."""
        feats = features.features
        close = feats.get("close")
        support = feats.get("support_20")
        resistance = feats.get("resistance_20")

        if close is None or (support is None and resistance is None):
            return SignalDirection.NO_VIEW, 0.0, {}, None

        lower_shadow = float(feats.get("lower_shadow_ratio", 0.0))
        upper_shadow = float(feats.get("upper_shadow_ratio", 0.0))
        is_hammer = float(feats.get("pattern_hammer", 0.0)) == 1.0
        is_shooting_star = float(feats.get("pattern_shooting_star", 0.0)) == 1.0
        is_bull_engulf = float(feats.get("pattern_bullish_engulfing", 0.0)) == 1.0
        is_bear_engulf = float(feats.get("pattern_bearish_engulfing", 0.0)) == 1.0

        # Compute percentage distance to support and resistance
        dist_support = (
            ((close - support) / close * 100.0) if support is not None else float("inf")
        )
        dist_resistance = (
            ((resistance - close) / close * 100.0)
            if resistance is not None
            else float("inf")
        )

        is_near_support = 0.0 <= dist_support <= self.proximity_threshold_pct
        is_near_resistance = 0.0 <= dist_resistance <= self.proximity_threshold_pct

        has_bullish_rejection = (
            lower_shadow >= self.min_rejection_wick_ratio
            or is_hammer
            or is_bull_engulf
        )
        has_bearish_rejection = (
            upper_shadow >= self.min_rejection_wick_ratio
            or is_shooting_star
            or is_bear_engulf
        )

        inputs = {
            "close": float(close),
            "lower_shadow_ratio": lower_shadow,
            "upper_shadow_ratio": upper_shadow,
        }
        if support is not None:
            inputs["support_20"] = float(support)
            inputs["dist_support_pct"] = float(dist_support)
        if resistance is not None:
            inputs["resistance_20"] = float(resistance)
            inputs["dist_resistance_pct"] = float(dist_resistance)

        # Signal determination
        if is_near_support and has_bullish_rejection and not is_near_resistance:
            direction = SignalDirection.LONG
            dist = dist_support
            is_pattern = is_hammer or is_bull_engulf
        elif is_near_resistance and has_bearish_rejection and not is_near_support:
            direction = SignalDirection.SHORT
            dist = dist_resistance
            is_pattern = is_shooting_star or is_bear_engulf
        else:
            return SignalDirection.NO_VIEW, 0.0, inputs, None

        # Confidence: level proximity + pattern conviction boost
        proximity_score = 1.0 - (dist / self.proximity_threshold_pct)
        pattern_boost = 0.20 if is_pattern else 0.0
        confidence = max(0.2, min(1.0, proximity_score + pattern_boost))

        return direction, confidence, inputs, float(dist)
