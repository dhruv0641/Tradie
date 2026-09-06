"""Base quantitative trading strategy interface (SOW §6.2, BTD §12, MLD §8)."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

import structlog

from src.backtesting.engine import BacktestEngine, OrderIntent
from src.backtesting.portfolio import SimulatedPosition
from src.domain.market_data import OHLCVCandle

logger = structlog.get_logger(__name__)


class BaseStrategy(ABC):
    """Abstract base class for all rule-based and quantitative trading strategies."""

    def __init__(self, name: str, parameters: dict[str, Any] | None = None) -> None:
        """Initialize base strategy with unique name and parameter configuration.

        Args:
            name: Identifier for the strategy.
            parameters: Configuration dictionary for strategy hyperparameters.
        """
        self.name = name
        self.parameters = parameters or {}
        self._candles: list[OHLCVCandle] = []

    @abstractmethod
    def on_bar(
        self,
        engine: BacktestEngine,
        bar_idx: int,
        candle: OHLCVCandle,
    ) -> list[OrderIntent]:
        """Evaluate strategy logic on incoming candle close and return generated order intents.

        Args:
            engine: Active backtesting engine instance.
            bar_idx: Monotonically increasing index of the current bar.
            candle: Current OHLCVCandle.

        Returns:
            List of OrderIntent instances to be submitted for execution on Next-Bar Open.
        """
        ...

    def reset(self) -> None:
        """Reset internal indicator state and historical candle cache for fresh evaluation."""
        self._candles.clear()

    def has_position(self, engine: BacktestEngine, symbol: str) -> bool:
        """Check if portfolio currently holds an open position for given instrument."""
        return symbol in engine.portfolio.positions

    def get_position(self, engine: BacktestEngine, symbol: str) -> SimulatedPosition | None:
        """Retrieve active simulated position for instrument if open."""
        return engine.portfolio.positions.get(symbol)

    def calculate_position_size(
        self,
        available_cash: Decimal,
        price: Decimal,
        risk_amount: Decimal,
        stop_distance: Decimal,
    ) -> int:
        """Calculate position quantity constrained by risk budget and cash margin.

        Args:
            available_cash: Liquid cash currently available in portfolio.
            price: Approximate entry price.
            risk_amount: Maximum currency risk willing to be lost (e.g. 1% of equity).
            stop_distance: Absolute difference between entry price and stop loss (> 0).

        Returns:
            Computed integer quantity (>= 0).
        """
        if price <= Decimal("0") or available_cash <= Decimal("0"):
            return 0

        # Maintain cash buffer for statutory fees and slippage (~2%)
        usable_cash = available_cash * Decimal("0.98")
        cash_qty = int(usable_cash // price)

        if stop_distance > Decimal("0") and risk_amount > Decimal("0"):
            risk_qty = int(risk_amount // stop_distance)
            qty = min(risk_qty, cash_qty)
        else:
            qty = cash_qty

        return max(0, qty)

    def __call__(
        self,
        engine: BacktestEngine,
        bar_idx: int,
        candle: OHLCVCandle,
    ) -> list[OrderIntent]:
        """Callable protocol adapter allowing direct use as BacktestEngine callback."""
        self._candles.append(candle)
        return self.on_bar(engine, bar_idx, candle)
