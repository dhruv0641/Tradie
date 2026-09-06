"""Rule-based Bollinger Bands and RSI mean-reversion baseline strategy (SOW §6.2, BTD §12)."""

from decimal import Decimal
from typing import Any

import pandas as pd
import structlog

from src.backtesting.engine import BacktestEngine, OrderIntent
from src.domain.market_data import OHLCVCandle
from src.features.technical import compute_bollinger_bands, compute_rsi
from src.strategies.base import BaseStrategy

logger = structlog.get_logger(__name__)


class BollingerBandsRSIMeanReversionStrategy(BaseStrategy):
    """Mean-reversion strategy trading oversold bounces within volatility envelopes.

    Rules:
    1. Long Entry: Candle close <= Lower Bollinger Band AND RSI < rsi_oversold (default: 30)
       while flat.
    2. Target Exit: Candle close >= Middle Bollinger Band (SMA 20) OR RSI >= rsi_exit (default: 50).
    3. Protective Stop-Loss: Entry price minus (entry price * stop_loss_pct).
    """

    def __init__(
        self,
        bb_window: int = 20,
        bb_std: float = 2.0,
        *,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_exit: float = 50.0,
        stop_loss_pct: float = 0.02,
        risk_per_trade_pct: float = 0.01,
        name: str = "bollinger_rsi_mean_reversion",
    ) -> None:
        """Initialize Bollinger Bands and RSI mean-reversion strategy.

        Args:
            bb_window: Moving average window for Bollinger Bands (default: 20).
            bb_std: Number of standard deviations for Bollinger Bands (default: 2.0).
            rsi_period: Wilder's RSI smoothing period (default: 14).
            rsi_oversold: RSI threshold defining oversold condition (default: 30.0).
            rsi_exit: RSI threshold defining mean reversion recovery exit (default: 50.0).
            stop_loss_pct: Fixed protective stop-loss percentage below entry (default: 2%).
            risk_per_trade_pct: Maximum portfolio equity risked per trade (default: 1%).
            name: Strategy identifier.
        """
        if bb_window < 2:
            msg = f"bb_window must be >= 2, got {bb_window}"
            raise ValueError(msg)
        if bb_std <= 0:
            msg = f"bb_std must be > 0, got {bb_std}"
            raise ValueError(msg)
        if rsi_period < 1:
            msg = f"rsi_period must be >= 1, got {rsi_period}"
            raise ValueError(msg)
        if rsi_oversold >= rsi_exit:
            msg = f"rsi_oversold ({rsi_oversold}) must be < rsi_exit ({rsi_exit})"
            raise ValueError(msg)
        if stop_loss_pct <= 0:
            msg = f"stop_loss_pct must be > 0, got {stop_loss_pct}"
            raise ValueError(msg)

        params: dict[str, Any] = {
            "bb_window": bb_window,
            "bb_std": bb_std,
            "rsi_period": rsi_period,
            "rsi_oversold": rsi_oversold,
            "rsi_exit": rsi_exit,
            "stop_loss_pct": stop_loss_pct,
            "risk_per_trade_pct": risk_per_trade_pct,
        }
        super().__init__(name=name, parameters=params)
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_exit = rsi_exit
        self.stop_loss_pct = stop_loss_pct
        self.risk_per_trade_pct = risk_per_trade_pct

    def on_bar(
        self,
        engine: BacktestEngine,
        bar_idx: int,
        candle: OHLCVCandle,
    ) -> list[OrderIntent]:
        """Process incoming candle, evaluate oversold envelope and return order intents."""
        min_bars_needed = max(self.bb_window, self.rsi_period) + 2
        if len(self._candles) < min_bars_needed:
            return []

        # Slice sufficient window for accurate rolling indicators
        window_size = max(self.bb_window * 3, 100)
        recent_candles = self._candles[-window_size:]

        close_series = pd.Series([float(c.close) for c in recent_candles], dtype=float)

        middle_band_s, _upper_band_s, lower_band_s, _, _ = compute_bollinger_bands(
            close_series,
            window=self.bb_window,
            num_std=self.bb_std,
        )
        rsi_series = compute_rsi(close_series, period=self.rsi_period)

        middle_band_float = middle_band_s.iloc[-1]
        lower_band_float = lower_band_s.iloc[-1]
        rsi_float = rsi_series.iloc[-1]

        if pd.isna(middle_band_float) or pd.isna(lower_band_float) or pd.isna(rsi_float):
            return []

        middle_band = Decimal(str(round(middle_band_float, 4)))
        lower_band = Decimal(str(round(lower_band_float, 4)))
        rsi_val = float(rsi_float)

        symbol = candle.instrument
        has_pos = self.has_position(engine, symbol)

        # Oversold Entry: Price <= Lower Band AND RSI < rsi_oversold
        if candle.close <= lower_band and rsi_val < self.rsi_oversold and not has_pos:
            stop_distance = (candle.close * Decimal(str(self.stop_loss_pct))).quantize(
                Decimal("0.05")
            )
            stop_loss = (candle.close - stop_distance).quantize(Decimal("0.05"))
            take_profit = middle_band.quantize(Decimal("0.05"))

            risk_budget = engine.portfolio.total_equity * Decimal(str(self.risk_per_trade_pct))
            quantity = self.calculate_position_size(
                available_cash=engine.portfolio.cash,
                price=candle.close,
                risk_amount=risk_budget,
                stop_distance=stop_distance,
            )

            if quantity > 0 and stop_loss > Decimal("0"):
                logger.debug(
                    "mean_reversion_buy_signal",
                    symbol=symbol,
                    close=str(candle.close),
                    lower_band=str(lower_band),
                    rsi=str(round(rsi_val, 2)),
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

        # Mean-Reversion Exit: Price >= Middle Band OR RSI >= rsi_exit
        if (candle.close >= middle_band or rsi_val >= self.rsi_exit) and has_pos:
            pos = self.get_position(engine, symbol)
            if pos is not None and pos.direction == "BUY":
                logger.debug(
                    "mean_reversion_exit_signal",
                    symbol=symbol,
                    close=str(candle.close),
                    middle_band=str(middle_band),
                    rsi=str(round(rsi_val, 2)),
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
