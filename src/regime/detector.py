"""Multi-dimensional market regime classification engine.

Implements rule-based/statistical regime classification along 5 canonical dimensions
per MLD §5.1, ADD §5, and FRD-REGIME-1-5.
"""

from collections import deque

import pandas as pd
import structlog

from src.config.models import RegimeConfig
from src.domain.features import FeatureSet
from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RegimeClassification,
    RiskSentiment,
    TrendState,
    VolatilityLevel,
)

logger = structlog.get_logger("regime.detector")


class RegimeDetector:
    """Classifies market conditions across 5 canonical dimensions without black-box models.

    Dimensions (MLD §5.1):
    1. Trend State: TRENDING_UP, TRENDING_DOWN, RANGING, UNKNOWN (via ADX and DI/MA alignment).
    2. Volatility Level: LOW, NORMAL, HIGH, UNKNOWN (via trailing percentile rank).
    3. Directional Bias: BULLISH, BEARISH, NEUTRAL, UNKNOWN (NEUTRAL enforced when RANGING).
    4. Liquidity Condition: NORMAL, DEGRADED, UNKNOWN (via volume ratio vs 20-period baseline).
    5. Risk Sentiment: RISK_ON, RISK_OFF, UNKNOWN (default UNKNOWN pending cross-asset data).
    """

    def __init__(self, config: RegimeConfig | None = None) -> None:
        """Initialize the regime detector with configuration.

        Args:
            config: RegimeConfig parameters or defaults if None.
        """
        self.config = config or RegimeConfig()
        self._volatility_history: dict[tuple[str, str], deque[float]] = {}
        self._logger = logger.bind(component="RegimeDetector")

    def classify(
        self,
        feature_set: FeatureSet,
        history_df: pd.DataFrame | None = None,
    ) -> RegimeClassification:
        """Classify market regime for an instrument from point-in-time features.

        Args:
            feature_set: Computed point-in-time FeatureSet.
            history_df: Optional historical feature dataframe for batch warmup.

        Returns:
            RegimeClassification object containing all 5 dimensions and metrics.
        """
        feats = feature_set.features
        instrument = feature_set.instrument
        timeframe = feature_set.timeframe
        key = (instrument, timeframe)

        metrics: dict[str, float] = {}

        # Pre-populate history if dataframe provided
        if history_df is not None and not history_df.empty:
            self._warmup_from_dataframe(key, history_df)

        # 1. Trend State & Directional Strength (MLD §5.1)
        trend_state = self._classify_trend(feats, metrics)

        # 2. Volatility Level (Percentile Rank) (MLD §5.1)
        volatility_level = self._classify_volatility(key, feats, metrics)

        # 3. Directional Bias (MLD §5.1 Invariant: NEUTRAL if RANGING)
        directional_bias = self._classify_directional_bias(trend_state, feats, metrics)

        # 4. Liquidity Condition (MLD §5.1)
        liquidity_condition = self._classify_liquidity(feats, metrics)

        # 5. Risk Sentiment (MLD §5.1)
        risk_sentiment = self._classify_risk_sentiment(feats, metrics)

        # Composite canonical label
        regime_label = self._build_regime_label(trend_state, volatility_level, liquidity_condition)

        classification = RegimeClassification(
            instrument=instrument,
            timeframe=timeframe,
            timestamp=feature_set.timestamp,
            trend_state=trend_state,
            volatility_level=volatility_level,
            directional_bias=directional_bias,
            liquidity_condition=liquidity_condition,
            risk_sentiment=risk_sentiment,
            regime_label=regime_label,
            is_transition=False,
            previous_regime=None,
            metrics=metrics,
            feature_set_id=feature_set.feature_set_id,
        )

        self._logger.debug(
            "regime_classified",
            instrument=instrument,
            timeframe=timeframe,
            label=regime_label,
            trend=trend_state.value,
            volatility=volatility_level.value,
            bias=directional_bias.value,
            liquidity=liquidity_condition.value,
        )

        return classification

    def clear_history(self) -> None:
        """Clear all trailing rolling history buffers."""
        self._volatility_history.clear()

    def _warmup_from_dataframe(self, key: tuple[str, str], df: pd.DataFrame) -> None:
        """Warm up volatility trailing history buffer from historical dataframe."""
        if key not in self._volatility_history:
            self._volatility_history[key] = deque(maxlen=self.config.volatility_window)

        vol_col = None
        for col in ("atr_14", "volatility_20", "atr", "volatility"):
            if col in df.columns:
                vol_col = col
                break

        if vol_col is not None:
            valid_series = df[vol_col].dropna().astype(float)
            for val in valid_series.iloc[-self.config.volatility_window :]:
                if val > 0:
                    self._volatility_history[key].append(float(val))

    def _classify_trend(self, feats: dict[str, float], metrics: dict[str, float]) -> TrendState:
        """Classify trend state into TRENDING_UP, TRENDING_DOWN, RANGING, or UNKNOWN."""
        adx = feats.get("adx_14")
        plus_di = feats.get("plus_di_14")
        minus_di = feats.get("minus_di_14")
        sma_20 = feats.get("sma_20")
        sma_50 = feats.get("sma_50")

        if adx is None:
            return TrendState.UNKNOWN

        metrics["adx_14"] = float(adx)
        if plus_di is not None:
            metrics["plus_di_14"] = float(plus_di)
        if minus_di is not None:
            metrics["minus_di_14"] = float(minus_di)

        if adx < self.config.adx_threshold:
            return TrendState.RANGING

        trend = TrendState.UNKNOWN
        if plus_di is not None and minus_di is not None:
            if plus_di > minus_di:
                trend = TrendState.TRENDING_UP
            elif minus_di > plus_di:
                trend = TrendState.TRENDING_DOWN
        elif sma_20 is not None and sma_50 is not None:
            if sma_20 > sma_50:
                trend = TrendState.TRENDING_UP
            elif sma_20 < sma_50:
                trend = TrendState.TRENDING_DOWN

        return trend

    def _classify_volatility(
        self,
        key: tuple[str, str],
        feats: dict[str, float],
        metrics: dict[str, float],
    ) -> VolatilityLevel:
        """Classify volatility level into LOW, NORMAL, HIGH, or UNKNOWN via percentile rank."""
        vol_val = feats.get("atr_14")
        if vol_val is None or vol_val <= 0:
            vol_val = feats.get("volatility_20")

        if vol_val is None or vol_val <= 0:
            return VolatilityLevel.UNKNOWN

        metrics["volatility_value"] = float(vol_val)

        # Update trailing history
        if key not in self._volatility_history:
            self._volatility_history[key] = deque(maxlen=self.config.volatility_window)

        hist = self._volatility_history[key]
        hist.append(float(vol_val))

        # Calculate empirical percentile rank against trailing history
        if len(hist) >= 10:
            count_less = sum(1 for v in hist if v <= vol_val)
            pct = (count_less / len(hist)) * 100.0
            metrics["volatility_percentile"] = float(round(pct, 2))

            if pct <= self.config.volatility_low_percentile:
                return VolatilityLevel.LOW
            if pct >= self.config.volatility_high_percentile:
                return VolatilityLevel.HIGH
            return VolatilityLevel.NORMAL

        # Warmup heuristic if insufficient history (<10 bars)
        zscore = feats.get("zscore_20")
        if zscore is not None:
            metrics["zscore_20"] = float(zscore)
            if abs(zscore) >= 2.0:
                return VolatilityLevel.HIGH

        return VolatilityLevel.NORMAL

    def _classify_directional_bias(
        self,
        trend_state: TrendState,
        feats: dict[str, float],
        metrics: dict[str, float],
    ) -> DirectionalBias:
        """Classify directional bias. Enforces NEUTRAL when RANGING per MLD §5.1."""
        # Non-negotiable MLD §5.1 Invariant:
        # NEUTRAL applies when trend state is RANGING to prevent oscillation
        if trend_state == TrendState.RANGING:
            return DirectionalBias.NEUTRAL
        if trend_state == TrendState.TRENDING_UP:
            return DirectionalBias.BULLISH
        if trend_state == TrendState.TRENDING_DOWN:
            return DirectionalBias.BEARISH

        bias = DirectionalBias.UNKNOWN
        roc = feats.get("roc_10")
        if roc is not None:
            metrics["roc_10"] = float(roc)
            if roc > 1.0:
                bias = DirectionalBias.BULLISH
            elif roc < -1.0:
                bias = DirectionalBias.BEARISH
            else:
                bias = DirectionalBias.NEUTRAL

        return bias

    def _classify_liquidity(
        self, feats: dict[str, float], metrics: dict[str, float]
    ) -> LiquidityCondition:
        """Classify liquidity condition based on volume relative to rolling average."""
        vol_ratio = feats.get("volume_ratio_20")
        if vol_ratio is None:
            vol = feats.get("volume")
            vol_sma = feats.get("volume_sma_20")
            if vol is not None and vol_sma is not None and vol_sma > 0:
                vol_ratio = vol / vol_sma

        if vol_ratio is None:
            return LiquidityCondition.UNKNOWN

        metrics["volume_ratio"] = float(round(vol_ratio, 4))

        if vol_ratio < self.config.liquidity_volume_ratio_threshold:
            return LiquidityCondition.DEGRADED

        return LiquidityCondition.NORMAL

    def _classify_risk_sentiment(
        self, feats: dict[str, float], metrics: dict[str, float]
    ) -> RiskSentiment:
        """Classify risk sentiment. Defaults to UNKNOWN until cross-asset feeds integrated."""
        vix = feats.get("india_vix")
        if vix is not None:
            metrics["india_vix"] = float(vix)
            if vix > 22.0:
                return RiskSentiment.RISK_OFF
            if vix < 14.0:
                return RiskSentiment.RISK_ON
            return RiskSentiment.UNKNOWN

        return RiskSentiment.UNKNOWN

    def _build_regime_label(
        self,
        trend: TrendState,
        vol: VolatilityLevel,
        liq: LiquidityCondition,
    ) -> str:
        """Build canonical composite regime label string."""
        if trend == TrendState.UNKNOWN and vol == VolatilityLevel.UNKNOWN:
            return "UNKNOWN"

        base = f"{trend.value}_{vol.value}_VOL"
        if liq == LiquidityCondition.DEGRADED:
            base += "_DEGRADED_LIQ"

        return base
