"""Event-driven backtesting engine enforcing Next-Bar Open execution and friction modeling."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.backtesting.cost_model import CostModel, CostModelConfig
from src.backtesting.portfolio import SimulatedPortfolio
from src.backtesting.slippage_model import SlippageConfig, SlippageModel
from src.domain.backtest_result import BacktestResult
from src.domain.market_data import OHLCVCandle

logger = structlog.get_logger(__name__)


class OrderIntent(BaseModel):
    """Trading order intent submitted at bar close."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1, description="Instrument symbol")
    direction: Literal["BUY", "SELL"] = Field(description="Order side")
    quantity: int = Field(gt=0, description="Order quantity")
    order_type: Literal["MARKET", "LIMIT"] = Field(
        default="MARKET", description="Order execution type"
    )
    limit_price: Decimal | None = Field(
        default=None, gt=Decimal("0"), description="Limit price if LIMIT order"
    )
    stop_loss: Decimal | None = Field(
        default=None, gt=Decimal("0"), description="Stop-loss price trigger"
    )
    take_profit: Decimal | None = Field(
        default=None, gt=Decimal("0"), description="Take-profit target price trigger"
    )
    product_type: Literal["INTRADAY", "DELIVERY"] = Field(
        default="DELIVERY", description="Tax and margin product classification"
    )
    generated_at_bar_index: int = Field(
        ge=0, description="Index of bar at whose close this order was generated"
    )
    generated_at_time: datetime = Field(
        description="Timestamp of bar close when order was generated"
    )


class BacktestConfig(BaseModel):
    """Configuration settings for backtest execution engine."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str = "default_strategy"
    initial_capital: Decimal = Field(
        default=Decimal("10000.00"),
        gt=Decimal("0"),
        description="Baseline capital in INR (PRD §9, BRD BR-2)",
    )
    cost_config: CostModelConfig = Field(default_factory=CostModelConfig)
    slippage_config: SlippageConfig = Field(default_factory=SlippageConfig)
    conservative_tie_breaking: bool = Field(
        default=True,
        description="Assume stop-loss hit first if both stop and target touched (BTD §7)",
    )
    gap_threshold_pct: Decimal = Field(
        default=Decimal("0.02"),
        gt=Decimal("0"),
        description="Gap percentage threshold triggering audit logging",
    )
    force_close_at_end: bool = Field(
        default=True,
        description="Force close remaining open positions on final bar close",
    )


class BacktestEngine:
    """Event-driven backtesting execution engine enforcing Next-Bar Open fill protocol."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        """Initialize engine with cost, slippage, and portfolio trackers.

        Args:
            config: BacktestConfig settings. Defaults to standard baseline.
        """
        self.config = config or BacktestConfig()
        self.cost_model = CostModel(self.config.cost_config)
        self.slippage_model = SlippageModel(self.config.slippage_config)
        self.portfolio = SimulatedPortfolio(initial_capital=self.config.initial_capital)

        self._pending_orders: list[OrderIntent] = []
        self._current_bar_index: int = -1
        self._previous_bar: OHLCVCandle | None = None
        self._order_history: list[dict[str, object]] = []

    @property
    def current_bar_index(self) -> int:
        """Current bar index being processed."""
        return self._current_bar_index

    def submit_order(self, order: OrderIntent) -> None:
        """Queue an order generated at the current bar close.

        Args:
            order: OrderIntent specifying execution parameters.

        Raises:
            ValueError: If order was not generated at the current bar close.
        """
        if order.generated_at_bar_index != self._current_bar_index:
            msg = (
                f"Look-ahead violation: order generated at bar {order.generated_at_bar_index} "
                f"cannot be submitted during bar {self._current_bar_index}"
            )
            raise ValueError(msg)

        self._pending_orders.append(order)
        logger.debug(
            "order_queued",
            symbol=order.symbol,
            direction=order.direction,
            quantity=order.quantity,
            bar_index=self._current_bar_index,
        )

    def process_bar(self, bar: OHLCVCandle, bar_index: int) -> None:
        """Process incoming historical bar enforcing BTD §7 Next-Bar Open fill protocol.

        Execution Sequence:
        1. Fill pending orders submitted on Bar T strictly at Bar T+1 Open.
        2. Evaluate intra-bar stop-loss and take-profit triggers on Bar T+1 [Low, High].
        3. Mark portfolio to market at Bar T+1 Close.

        Args:
            bar: Current OHLCVCandle.
            bar_index: Monotonically increasing bar index.

        Raises:
            ValueError: If bar index does not advance monotonically.
        """
        if bar_index <= self._current_bar_index:
            msg = (
                f"Non-monotonic bar index: received {bar_index}, "
                f"expected > {self._current_bar_index}"
            )
            raise ValueError(msg)

        self._current_bar_index = bar_index

        # Detect and log overnight or inter-bar gap from previous bar close
        if self._previous_bar is not None and self._previous_bar.close > Decimal("0"):
            gap_pct = abs(bar.open - self._previous_bar.close) / self._previous_bar.close
            if gap_pct >= self.config.gap_threshold_pct:
                logger.info(
                    "market_gap_detected",
                    symbol=bar.instrument,
                    prev_close=str(self._previous_bar.close),
                    open=str(bar.open),
                    gap_pct=str(round(gap_pct * Decimal("100"), 2)),
                    bar_index=bar_index,
                )

        # -------------------------------------------------------------
        # STEP 1: Execute Pending Orders Strictly at Bar T+1 Open
        # -------------------------------------------------------------
        self._execute_pending_orders(bar)

        # -------------------------------------------------------------
        # STEP 2: Evaluate Intra-Bar Stop-Loss / Take-Profit Triggers
        # -------------------------------------------------------------
        self._check_intra_bar_exits(bar)

        # -------------------------------------------------------------
        # STEP 3: Mark Portfolio to Market at Bar T+1 Close
        # -------------------------------------------------------------
        self.portfolio.mark_to_market(
            timestamp=bar.timestamp,
            current_prices={bar.instrument: bar.close},
            increment_bars=True,
        )

        self._previous_bar = bar

    def _execute_pending_orders(self, bar: OHLCVCandle) -> None:
        """Execute queued orders at bar Open price with spread, slippage, and costs."""
        remaining_orders: list[OrderIntent] = []

        for order in self._pending_orders:
            # Enforce strict Next-Bar Open invariant (BTD §7)
            if order.generated_at_bar_index >= self._current_bar_index:
                msg = (
                    f"Look-ahead violation: order generated on bar {order.generated_at_bar_index} "
                    f"cannot execute on bar {self._current_bar_index}"
                )
                raise RuntimeError(msg)

            # Calculate slippage against bar open price and bar volume
            slip_res = self.slippage_model.calculate_slippage(
                requested_price=bar.open,
                quantity=order.quantity,
                side=order.direction,
                bar_volume=bar.volume,
            )

            if slip_res.rejected:
                logger.warning(
                    "order_rejected_slippage",
                    symbol=order.symbol,
                    reason=slip_res.rejection_reason,
                    bar_index=self._current_bar_index,
                )
                self._order_history.append(
                    {
                        "symbol": order.symbol,
                        "status": "REJECTED",
                        "reason": slip_res.rejection_reason,
                        "bar_index": self._current_bar_index,
                    }
                )
                continue

            exec_price = slip_res.executed_price

            # Limit order qualification check
            if order.order_type == "LIMIT" and order.limit_price is not None:
                if order.direction == "BUY" and exec_price > order.limit_price:
                    logger.debug(
                        "limit_unfilled_buy",
                        exec_price=str(exec_price),
                        limit=str(order.limit_price),
                    )
                    remaining_orders.append(order)
                    continue
                if order.direction == "SELL" and exec_price < order.limit_price:
                    logger.debug(
                        "limit_unfilled_sell",
                        exec_price=str(exec_price),
                        limit=str(order.limit_price),
                    )
                    remaining_orders.append(order)
                    continue

            # Calculate statutory charges on entry
            cost_breakdown = self.cost_model.calculate_leg(
                price=exec_price,
                quantity=order.quantity,
                side=order.direction,
                product_type=order.product_type,
            )

            try:
                self.portfolio.open_position(
                    symbol=order.symbol,
                    direction=order.direction,
                    quantity=order.quantity,
                    fill_price=exec_price,
                    timestamp=bar.timestamp,
                    entry_cost=cost_breakdown.total_cost,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                )
                self._order_history.append(
                    {
                        "symbol": order.symbol,
                        "status": "FILLED",
                        "fill_price": exec_price,
                        "bar_index": self._current_bar_index,
                    }
                )
                logger.info(
                    "order_filled",
                    symbol=order.symbol,
                    fill_price=str(exec_price),
                    quantity=order.quantity,
                    cost=str(cost_breakdown.total_cost),
                    bar_index=self._current_bar_index,
                )
            except ValueError as e:
                logger.warning(
                    "order_open_failed",
                    symbol=order.symbol,
                    error=str(e),
                    bar_index=self._current_bar_index,
                )
                self._order_history.append(
                    {
                        "symbol": order.symbol,
                        "status": "FAILED",
                        "reason": str(e),
                        "bar_index": self._current_bar_index,
                    }
                )

        self._pending_orders = remaining_orders

    def _check_intra_bar_exits(self, bar: OHLCVCandle) -> None:
        """Scan active positions against bar high/low range for stop-loss and targets."""
        symbols_to_close: list[tuple[str, Decimal, str]] = []

        for symbol, pos in self.portfolio.positions.items():
            if symbol != bar.instrument:
                continue

            stop_hit = False
            target_hit = False
            stop_price = pos.stop_loss
            target_price = pos.take_profit

            # Evaluation for LONG equity position
            if pos.direction == "BUY":
                if stop_price is not None and bar.low <= stop_price:
                    stop_hit = True
                if target_price is not None and bar.high >= target_price:
                    target_hit = True

                if stop_hit and target_hit and stop_price is not None and target_price is not None:
                    # Both touched within same bar: apply conservative tie-breaking
                    if self.config.conservative_tie_breaking:
                        # Stop-loss executed first per BTD §7 item 4
                        realized_exit = bar.open if bar.open < stop_price else stop_price
                        symbols_to_close.append((symbol, realized_exit, "STOP_LOSS"))
                    else:
                        realized_exit = bar.open if bar.open > target_price else target_price
                        symbols_to_close.append((symbol, realized_exit, "TAKE_PROFIT"))
                elif stop_hit and stop_price is not None:
                    # If bar opened gapped below stop price, fill at open
                    realized_exit = bar.open if bar.open < stop_price else stop_price
                    symbols_to_close.append((symbol, realized_exit, "STOP_LOSS"))
                elif target_hit and target_price is not None:
                    # If bar opened gapped above target price, fill at open
                    realized_exit = bar.open if bar.open > target_price else target_price
                    symbols_to_close.append((symbol, realized_exit, "TAKE_PROFIT"))

        for symbol, exit_price, reason in symbols_to_close:
            pos = self.portfolio.positions[symbol]
            slip_res = self.slippage_model.calculate_slippage(
                requested_price=exit_price,
                quantity=pos.quantity,
                side="SELL",
                bar_volume=bar.volume,
            )
            final_exit_price = slip_res.executed_price

            cost_breakdown = self.cost_model.calculate_leg(
                price=final_exit_price,
                quantity=pos.quantity,
                side="SELL",
                product_type="DELIVERY",
            )

            self.portfolio.close_position(
                symbol=symbol,
                exit_price=final_exit_price,
                timestamp=bar.timestamp,
                exit_cost=cost_breakdown.total_cost,
                exit_reason=reason,  # type: ignore[arg-type]
            )
            logger.info(
                "position_closed_intrabar",
                symbol=symbol,
                reason=reason,
                exit_price=str(final_exit_price),
                bar_index=self._current_bar_index,
            )

    def run(
        self,
        candles: list[OHLCVCandle],
        strategy_callback: Callable[["BacktestEngine", int, OHLCVCandle], list[OrderIntent]]
        | None = None,
    ) -> BacktestResult:
        """Run complete event-driven backtest simulation across candle series.

        Args:
            candles: Chronologically sorted list of historical OHLCVCandle objects.
            strategy_callback: Optional strategy function called at each bar close
                (engine, bar_index, candle) returning list of OrderIntents.

        Returns:
            BacktestResult containing trade log, equity curve, and metrics.

        Raises:
            ValueError: If candle series is empty or not chronological.
        """
        if not candles:
            msg = "Candle series cannot be empty"
            raise ValueError(msg)

        # Verify chronological ordering
        for i in range(1, len(candles)):
            if candles[i].timestamp <= candles[i - 1].timestamp:
                msg = (
                    f"Candle sequence must be strictly chronological: candle {i} "
                    f"timestamp {candles[i].timestamp} <= previous {candles[i - 1].timestamp}"
                )
                raise ValueError(msg)

        for bar_idx, candle in enumerate(candles):
            self.process_bar(candle, bar_idx)

            if strategy_callback is not None:
                new_orders = strategy_callback(self, bar_idx, candle)
                for order in new_orders:
                    self.submit_order(order)

        # Force close open positions at final bar close if configured
        if self.config.force_close_at_end and self.portfolio.positions and candles:
            last_candle = candles[-1]
            open_symbols = list(self.portfolio.positions.keys())
            for sym in open_symbols:
                pos = self.portfolio.positions[sym]
                slip_res = self.slippage_model.calculate_slippage(
                    requested_price=last_candle.close,
                    quantity=pos.quantity,
                    side="SELL",
                    bar_volume=last_candle.volume,
                )
                cost_breakdown = self.cost_model.calculate_leg(
                    price=slip_res.executed_price,
                    quantity=pos.quantity,
                    side="SELL",
                    product_type="DELIVERY",
                )
                self.portfolio.close_position(
                    symbol=sym,
                    exit_price=slip_res.executed_price,
                    timestamp=last_candle.timestamp,
                    exit_cost=cost_breakdown.total_cost,
                    exit_reason="END_OF_DATA",
                )

        metrics = self.portfolio.compute_metrics()
        return BacktestResult(
            strategy_id=self.config.strategy_id,
            initial_capital=self.config.initial_capital,
            final_equity=self.portfolio.total_equity.quantize(Decimal("0.01")),
            metrics=metrics,
            trades=self.portfolio.trades,
            equity_curve=self.portfolio.equity_curve,
            parameters={
                "conservative_tie_breaking": self.config.conservative_tie_breaking,
                "gap_threshold_pct": str(self.config.gap_threshold_pct),
                "force_close_at_end": self.config.force_close_at_end,
            },
        )
