"""Rule-based trend-following and momentum baseline strategies (SOW §6.2, BTD §12, MLD §8)."""

from decimal import Decimal
from typing import Any

import pandas as pd
import structlog

from src.backtesting.engine import BacktestEngine, OrderIntent
from src.domain.market_data import OHLCVCandle
from src.features.technical import compute_atr, compute_ema
from src.strategies.base import BaseStrategy

logger = structlog.get_logger(__name__)


class DualEMACrossoverStrategy(BaseStrategy):
    """Classic Dual Exponential Moving Average (EMA) crossover trend-following strategy.

    Rules:
    1. Long Entry: Fast EMA crosses strictly above Slow EMA while portfolio is flat.
    2. Protective Stop-Loss: Entry price minus (ATR * atr_multiplier).
    3. Profit Target: Entry price plus (ATR * atr_multiplier * reward_risk_ratio).
    4. Exit Signal: Fast EMA crosses strictly below Slow EMA.
    """

    def __init__(
        self,
        fast_span: int = 20,
        slow_span: int = 50,
        *,
        atr_period: int = 14,
        atr_multiplier: float = 2.0,
        risk_per_trade_pct: float = 0.01,
        reward_risk_ratio: float = 2.0,
        name: str = "dual_ema_crossover",
    ) -> None:
        """Initialize dual EMA crossover strategy with technical parameters.

        Args:
            fast_span: Span length for the fast EMA (default: 20).
            slow_span: Span length for the slow EMA (default: 50).
            atr_period: Lookback period for Average True Range volatility (default: 14).
            atr_multiplier: Multiple of ATR for trailing/initial stop-loss (default: 2.0).
            risk_per_trade_pct: Maximum portfolio equity risked per trade (default: 1%).
            reward_risk_ratio: Multiple of risk distance targeting take-profit (default: 2.0).
            name: Strategy identifier.
        """
        if fast_span >= slow_span:
            msg = f"fast_span ({fast_span}) must be strictly less than slow_span ({slow_span})"
            raise ValueError(msg)
        if atr_period < 1:
            msg = f"atr_period must be >= 1, got {atr_period}"
            raise ValueError(msg)
        if atr_multiplier <= 0:
            msg = f"atr_multiplier must be strictly positive, got {atr_multiplier}"
            raise ValueError(msg)

        params: dict[str, Any] = {
            "fast_span": fast_span,
            "slow_span": slow_span,
            "atr_period": atr_period,
            "atr_multiplier": atr_multiplier,
            "risk_per_trade_pct": risk_per_trade_pct,
            "reward_risk_ratio": reward_risk_ratio,
        }
        super().__init__(name=name, parameters=params)
        self.fast_span = fast_span
        self.slow_span = slow_span
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.risk_per_trade_pct = risk_per_trade_pct
        self.reward_risk_ratio = reward_risk_ratio

    def on_bar(
        self,
        engine: BacktestEngine,
        bar_idx: int,
        candle: OHLCVCandle,
    ) -> list[OrderIntent]:
        """Process incoming candle, evaluate EMA cross and return order intents."""
        min_bars_needed = self.slow_span + 2
        if len(self._candles) < min_bars_needed:
            return []

        # Use recent window to maintain fast vectorized calculations
        window_size = max(self.slow_span * 3, 100)
        recent_candles = self._candles[-window_size:]

        close_series = pd.Series([float(c.close) for c in recent_candles], dtype=float)
        high_series = pd.Series([float(c.high) for c in recent_candles], dtype=float)
        low_series = pd.Series([float(c.low) for c in recent_candles], dtype=float)

        fast_ema = compute_ema(close_series, span=self.fast_span)
        slow_ema = compute_ema(close_series, span=self.slow_span)

        prev_fast, curr_fast = fast_ema.iloc[-2], fast_ema.iloc[-1]
        prev_slow, curr_slow = slow_ema.iloc[-2], slow_ema.iloc[-1]

        symbol = candle.instrument
        has_pos = self.has_position(engine, symbol)

        # Bullish Crossover: Entry
        if prev_fast <= prev_slow and curr_fast > curr_slow and not has_pos:
            atr_series = compute_atr(
                high=high_series,
                low=low_series,
                close=close_series,
                period=self.atr_period,
            )
            atr_val_float = atr_series.iloc[-1]
            if pd.isna(atr_val_float) or atr_val_float <= 0.0:
                atr_val = candle.close * Decimal("0.02")
            else:
                atr_val = Decimal(str(round(atr_val_float, 4)))

            stop_distance = (atr_val * Decimal(str(self.atr_multiplier))).quantize(Decimal("0.05"))
            if stop_distance <= Decimal("0"):
                stop_distance = (candle.close * Decimal("0.02")).quantize(Decimal("0.05"))

            stop_loss = (candle.close - stop_distance).quantize(Decimal("0.05"))
            take_profit = (
                candle.close + (stop_distance * Decimal(str(self.reward_risk_ratio)))
            ).quantize(Decimal("0.05"))

            risk_budget = engine.portfolio.total_equity * Decimal(str(self.risk_per_trade_pct))
            quantity = self.calculate_position_size(
                available_cash=engine.portfolio.cash,
                price=candle.close,
                risk_amount=risk_budget,
                stop_distance=stop_distance,
            )

            if quantity > 0 and stop_loss > Decimal("0"):
                logger.debug(
                    "dual_ema_buy_signal",
                    symbol=symbol,
                    close=str(candle.close),
                    stop_loss=str(stop_loss),
                    take_profit=str(take_profit),
                    quantity=quantity,
                    bar_index=bar_idx,
                )
                return [
                    OrderIntent(
                        symbol=symbol,
                        direction="BUY",
                        quantity=quantity,
                        order_type="MARKET",
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        generated_at_bar_index=bar_idx,
                        generated_at_time=candle.timestamp,
                    )
                ]

        # Bearish Crossover: Exit open long position
        if prev_fast >= prev_slow and curr_fast < curr_slow and has_pos:
            pos = self.get_position(engine, symbol)
            if pos is not None and pos.direction == "BUY":
                logger.debug(
                    "dual_ema_exit_signal",
                    symbol=symbol,
                    close=str(candle.close),
                    quantity=pos.quantity,
                    bar_index=bar_idx,
                )
                return [
                    OrderIntent(
                        symbol=symbol,
                        direction="SELL",
                        quantity=pos.quantity,
                        order_type="MARKET",
                        generated_at_bar_index=bar_idx,
                        generated_at_time=candle.timestamp,
                    )
                ]

        return []


class DonchianBreakoutStrategy(BaseStrategy):
    """Donchian Channel breakout trend-following strategy with zero look-ahead bias.

    Rules:
    1. Channel Calculation: Upper channel = max high of previous N bars (excluding current bar).
       Lower channel = min low of previous N bars (excluding current bar).
    2. Long Entry: Candle close strictly breaks above Upper Channel while flat.
    3. Protective Stop-Loss: Entry price minus (ATR * stop_atr_multiplier).
    4. Exit Signal: Candle close breaks below Lower Channel.
    """

    def __init__(
        self,
        lookback_period: int = 20,
        *,
        atr_period: int = 14,
        stop_atr_multiplier: float = 1.5,
        risk_per_trade_pct: float = 0.01,
        name: str = "donchian_breakout",
    ) -> None:
        """Initialize Donchian breakout strategy with channel parameters.

        Args:
            lookback_period: Channel lookback period in bars (default: 20).
            atr_period: Lookback period for Average True Range volatility (default: 14).
            stop_atr_multiplier: Multiple of ATR for protective stop-loss (default: 1.5).
            risk_per_trade_pct: Maximum portfolio equity risked per trade (default: 1%).
            name: Strategy identifier.
        """
        if lookback_period < 2:
            msg = f"lookback_period must be >= 2, got {lookback_period}"
            raise ValueError(msg)
        if atr_period < 1:
            msg = f"atr_period must be >= 1, got {atr_period}"
            raise ValueError(msg)
        if stop_atr_multiplier <= 0:
            msg = f"stop_atr_multiplier must be > 0, got {stop_atr_multiplier}"
            raise ValueError(msg)

        params: dict[str, Any] = {
            "lookback_period": lookback_period,
            "atr_period": atr_period,
            "stop_atr_multiplier": stop_atr_multiplier,
            "risk_per_trade_pct": risk_per_trade_pct,
        }
        super().__init__(name=name, parameters=params)
        self.lookback_period = lookback_period
        self.atr_period = atr_period
        self.stop_atr_multiplier = stop_atr_multiplier
        self.risk_per_trade_pct = risk_per_trade_pct

    def on_bar(
        self,
        engine: BacktestEngine,
        bar_idx: int,
        candle: OHLCVCandle,
    ) -> list[OrderIntent]:
        """Process incoming candle, evaluate breakout and return order intents."""
        # Need at least lookback_period + 1 candles so that lookback bars precede current
        if len(self._candles) <= self.lookback_period:
            return []

        # Strictly shifted window: prior N bars excluding current bar (index -1)
        prior_candles = self._candles[-(self.lookback_period + 1) : -1]
        upper_channel = max(c.high for c in prior_candles)
        lower_channel = min(c.low for c in prior_candles)

        symbol = candle.instrument
        has_pos = self.has_position(engine, symbol)

        # Breakout Entry
        if candle.close > upper_channel and not has_pos:
            recent_candles = self._candles[-max(self.atr_period * 3, self.lookback_period + 10) :]
            close_series = pd.Series([float(c.close) for c in recent_candles], dtype=float)
            high_series = pd.Series([float(c.high) for c in recent_candles], dtype=float)
            low_series = pd.Series([float(c.low) for c in recent_candles], dtype=float)

            atr_series = compute_atr(
                high=high_series,
                low=low_series,
                close=close_series,
                period=self.atr_period,
            )
            atr_val_float = atr_series.iloc[-1]
            if pd.isna(atr_val_float) or atr_val_float <= 0.0:
                atr_val = candle.close * Decimal("0.02")
            else:
                atr_val = Decimal(str(round(atr_val_float, 4)))

            stop_distance = (atr_val * Decimal(str(self.stop_atr_multiplier))).quantize(
                Decimal("0.05")
            )
            if stop_distance <= Decimal("0"):
                stop_distance = (candle.close * Decimal("0.02")).quantize(Decimal("0.05"))

            stop_loss = (candle.close - stop_distance).quantize(Decimal("0.05"))
            risk_budget = engine.portfolio.total_equity * Decimal(str(self.risk_per_trade_pct))
            quantity = self.calculate_position_size(
                available_cash=engine.portfolio.cash,
                price=candle.close,
                risk_amount=risk_budget,
                stop_distance=stop_distance,
            )

            if quantity > 0 and stop_loss > Decimal("0"):
                logger.debug(
                    "donchian_breakout_buy_signal",
                    symbol=symbol,
                    close=str(candle.close),
                    upper_channel=str(upper_channel),
                    stop_loss=str(stop_loss),
                    quantity=quantity,
                    bar_index=bar_idx,
                )
                return [
                    OrderIntent(
                        symbol=symbol,
                        direction="BUY",
                        quantity=quantity,
                        order_type="MARKET",
                        stop_loss=stop_loss,
                        generated_at_bar_index=bar_idx,
                        generated_at_time=candle.timestamp,
                    )
                ]

        # Breakout Exit
        if candle.close < lower_channel and has_pos:
            pos = self.get_position(engine, symbol)
            if pos is not None and pos.direction == "BUY":
                logger.debug(
                    "donchian_breakout_exit_signal",
                    symbol=symbol,
                    close=str(candle.close),
                    lower_channel=str(lower_channel),
                    quantity=pos.quantity,
                    bar_index=bar_idx,
                )
                return [
                    OrderIntent(
                        symbol=symbol,
                        direction="SELL",
                        quantity=pos.quantity,
                        order_type="MARKET",
                        generated_at_bar_index=bar_idx,
                        generated_at_time=candle.timestamp,
                    )
                ]

        return []
