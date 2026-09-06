"""Authoritative internal position ledger and mark-to-market accounting engine.

Maintains the single internal source of truth for portfolio exposure, open/closed positions,
cost basis, mark-to-market valuation, realized/unrealized P&L, and capital state accounting
(FRD-EXEC-4, TRD-DATA-2, EDD §8, RTLD §8).
"""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from threading import RLock
from typing import Protocol, runtime_checkable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.capital_state import CapitalState
from src.domain.execution import OrderFill, Position
from src.infrastructure.models import PositionModel

logger = structlog.get_logger(__name__)


@runtime_checkable
class PositionLedgerProtocol(Protocol):
    """Structural protocol defining position ledger query and mutation interface."""

    def get_position(self, instrument: str) -> Position | None:
        """Get current position snapshot for an instrument."""
        ...

    def get_open_positions(self) -> list[Position]:
        """Get all currently open positions (quantity != 0)."""
        ...

    def get_all_positions(self) -> list[Position]:
        """Get all tracked positions including flat/closed ones."""
        ...

    def apply_fill(self, fill: OrderFill) -> Position:
        """Apply an order execution fill event and update portfolio state."""
        ...

    def mark_to_market(
        self,
        prices: dict[str, Decimal] | str,
        price: Decimal | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Update current market price(s) and recompute unrealized P&L and equity."""
        ...

    def get_capital_state(self) -> CapitalState:
        """Derive authoritative CapitalState snapshot for risk evaluation."""
        ...

    @property
    def total_equity(self) -> Decimal:
        """Current total portfolio equity (cash + holdings - liabilities)."""
        ...

    @property
    def cash(self) -> Decimal:
        """Current cash balance in INR."""
        ...

    @property
    def realized_pnl(self) -> Decimal:
        """Cumulative realized profit and loss."""
        ...

    @property
    def unrealized_pnl(self) -> Decimal:
        """Sum of current unrealized profit and loss across open positions."""
        ...

    @property
    def peak_equity(self) -> Decimal:
        """Peak total portfolio equity achieved."""
        ...


class PositionLedger:
    """Authoritative transactional position ledger and portfolio state tracker.

    Thread-safe in-memory ledger with optional asynchronous ACID PostgreSQL/TimescaleDB
    persistence conforming to TRD-DATA-2 and EDD §8.
    """

    def __init__(
        self,
        initial_capital: Decimal = Decimal("10000.00"),
        session_start_capital: Decimal | None = None,
    ) -> None:
        """Initialize position ledger with starting capital.

        Args:
            initial_capital: Baseline portfolio cash in INR (RTLD-1 default ₹10,000).
            session_start_capital: Session starting capital (defaults to initial_capital).
        """
        if initial_capital <= Decimal("0"):
            msg = f"Initial capital must be positive, got {initial_capital}"
            raise ValueError(msg)

        self._lock = RLock()
        self._initial_capital = initial_capital
        self._session_start_capital = session_start_capital or initial_capital
        self._cash = initial_capital
        self._peak_equity = initial_capital
        self._cumulative_realized_pnl = Decimal("0.00")
        self._cumulative_fees = Decimal("0.00")
        self._trades_today = 0

        # In-memory position store: instrument -> Position
        self._positions: dict[str, Position] = {}
        # Track when position was opened: instrument -> datetime
        self._opened_at: dict[str, datetime] = {}

    @property
    def initial_capital(self) -> Decimal:
        """Initial allocated capital in INR."""
        return self._initial_capital

    @property
    def session_start_capital(self) -> Decimal:
        """Capital at the start of current trading session in INR."""
        return self._session_start_capital

    @property
    def cash(self) -> Decimal:
        """Current cash balance in INR."""
        with self._lock:
            return self._cash

    @property
    def cumulative_fees(self) -> Decimal:
        """Total brokerage and statutory fees paid in INR."""
        with self._lock:
            return self._cumulative_fees

    @property
    def realized_pnl(self) -> Decimal:
        """Cumulative realized profit and loss in INR."""
        with self._lock:
            return self._cumulative_realized_pnl

    @property
    def unrealized_pnl(self) -> Decimal:
        """Current total unrealized profit and loss across all open positions."""
        with self._lock:
            return sum(
                (pos.unrealized_pnl for pos in self._positions.values() if pos.quantity != 0),
                Decimal("0.00"),
            )

    @property
    def total_equity(self) -> Decimal:
        """Current total portfolio equity (cash + open positions market value)."""
        with self._lock:
            return self._cash + self._calculate_holdings_net_value()

    @property
    def peak_equity(self) -> Decimal:
        """Peak total portfolio equity achieved."""
        with self._lock:
            return self._peak_equity

    @property
    def trades_today(self) -> int:
        """Number of closed/completed trade legs today."""
        with self._lock:
            return self._trades_today

    def get_position(self, instrument: str) -> Position | None:
        """Get position snapshot for given instrument symbol.

        Args:
            instrument: Traded instrument identifier.

        Returns:
            Position entity if tracked, None otherwise.
        """
        with self._lock:
            return self._positions.get(instrument)

    def get_open_positions(self) -> list[Position]:
        """Get all currently active open positions (quantity != 0)."""
        with self._lock:
            return [pos for pos in self._positions.values() if pos.quantity != 0]

    def get_all_positions(self) -> list[Position]:
        """Get all tracked positions including flat positions."""
        with self._lock:
            return list(self._positions.values())

    def apply_fill(self, fill: OrderFill) -> Position:
        """Apply an order execution fill event and synchronously update portfolio state.

        Args:
            fill: Validated OrderFill event.

        Returns:
            Updated Position entity for the instrument.
        """
        with self._lock:
            instrument = fill.instrument
            existing = self._positions.get(instrument)
            now_utc = fill.timestamp

            # Deduct commission immediately from cash
            self._cash -= fill.commission
            self._cumulative_fees += fill.commission

            if existing is None or existing.quantity == 0:
                # 1. Opening a brand-new position from flat
                updated_pos = self._handle_open_from_flat(fill, existing, now_utc)
            elif (existing.quantity > 0 and fill.direction == "BUY") or (
                existing.quantity < 0 and fill.direction == "SELL"
            ):
                # 2. Adding to existing position in the same direction (averaging)
                updated_pos = self._handle_add_to_position(existing, fill, now_utc)
            else:
                # 3. Reducing, closing, or flipping an existing position
                updated_pos = self._handle_reduce_or_flip(existing, fill, now_utc)

            self._positions[instrument] = updated_pos
            self._update_peak_equity()

            logger.info(
                "fill_applied_to_position_ledger",
                fill_id=fill.fill_id,
                instrument=instrument,
                direction=fill.direction,
                quantity=fill.quantity,
                price=str(fill.price),
                resulting_qty=updated_pos.quantity,
                average_entry=str(updated_pos.average_entry_price),
                realized_pnl=str(updated_pos.realized_pnl),
                total_equity=str(self.total_equity),
            )

            return updated_pos

    def mark_to_market(
        self,
        prices: dict[str, Decimal] | str,
        price: Decimal | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Update current market price(s) and recompute unrealized P&L and peak equity.

        Args:
            prices: Either a mapping of {symbol: price} or a single instrument symbol string.
            price: Market price when prices is passed as a symbol string.
            timestamp: Update timestamp (defaults to timezone-aware UTC now).
        """
        now_utc = timestamp or datetime.now(UTC)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)

        with self._lock:
            price_map: dict[str, Decimal] = {}
            if isinstance(prices, str):
                if price is None:
                    msg = "Price must be provided when instrument string is passed"
                    raise ValueError(msg)
                price_map[prices] = price
            else:
                price_map = prices

            for symbol, mkt_price in price_map.items():
                if mkt_price <= Decimal("0"):
                    msg = f"Market price must be positive, got {mkt_price} for {symbol}"
                    raise ValueError(msg)

                pos = self._positions.get(symbol)
                if pos is not None:
                    # Recalculate unrealized P&L with updated market price
                    unrealized = self._compute_unrealized_pnl(
                        pos.quantity, pos.average_entry_price, mkt_price
                    )
                    peak_unrealized = max(pos.peak_unrealized_pnl, unrealized)

                    self._positions[symbol] = Position(
                        instrument=pos.instrument,
                        quantity=pos.quantity,
                        average_entry_price=pos.average_entry_price,
                        current_market_price=mkt_price,
                        unrealized_pnl=unrealized,
                        realized_pnl=pos.realized_pnl,
                        peak_unrealized_pnl=peak_unrealized,
                        updated_at=now_utc,
                    )

            self._update_peak_equity()

    def get_capital_state(self) -> CapitalState:
        """Derive authoritative CapitalState snapshot for risk evaluation and sizing.

        Returns:
            Canonical, validated CapitalState entity.
        """
        with self._lock:
            open_positions = self.get_open_positions()
            current_cap = self.total_equity

            # Currently deployed capital is the total gross market exposure
            deployed = sum(
                (abs(pos.quantity) * pos.current_market_price for pos in open_positions),
                Decimal("0.00"),
            )

            # Defensive clamp: deployed cannot mathematically exceed current capital in CapitalState
            deployed = min(deployed, current_cap)

            return CapitalState(
                current_capital=current_cap,
                peak_equity=self._peak_equity,
                session_start_capital=self._session_start_capital,
                currently_deployed=deployed,
                open_position_count=len(open_positions),
                trades_today=self._trades_today,
            )

    def reset_session(self, session_start_capital: Decimal | None = None) -> None:
        """Reset session-level tracking counters for a new trading session.

        Args:
            session_start_capital: Optional baseline capital override for the new session.
        """
        with self._lock:
            current_cap = self.total_equity
            self._session_start_capital = session_start_capital or current_cap
            self._trades_today = 0
            logger.info(
                "position_ledger_session_reset",
                session_start_capital=str(self._session_start_capital),
                current_equity=str(current_cap),
            )

    async def record_fill_transactional(
        self,
        fill: OrderFill,
        session: AsyncSession,
    ) -> Position:
        """Apply an order fill atomically within an ACID database transaction (TRD-DATA-2).

        Args:
            fill: Validated OrderFill event.
            session: Active SQLAlchemy AsyncSession.

        Returns:
            Updated Position entity.

        Raises:
            Exception: If database commit fails, in-memory state is rolled back.
        """
        # Take snapshot for in-memory rollback if DB write fails
        with self._lock:
            state_snapshot = self._create_state_snapshot()

        try:
            # 1. Update in-memory state first
            updated_pos = self.apply_fill(fill)

            # 2. Persist to PostgreSQL / TimescaleDB positions table
            stmt = select(PositionModel).where(PositionModel.instrument == fill.instrument)
            res = await session.execute(stmt)
            db_pos = res.scalar_one_or_none()

            opened_at_ts = self._opened_at.get(fill.instrument, fill.timestamp)

            if db_pos is None:
                db_pos = PositionModel(
                    instrument=updated_pos.instrument,
                    quantity=updated_pos.quantity,
                    average_entry_price=updated_pos.average_entry_price,
                    current_market_price=updated_pos.current_market_price,
                    unrealized_pnl=updated_pos.unrealized_pnl,
                    realized_pnl=updated_pos.realized_pnl,
                    peak_unrealized_pnl=updated_pos.peak_unrealized_pnl,
                    opened_at=opened_at_ts,
                    last_updated_at=updated_pos.updated_at,
                )
                session.add(db_pos)
            else:
                db_pos.quantity = updated_pos.quantity
                db_pos.average_entry_price = updated_pos.average_entry_price
                db_pos.current_market_price = updated_pos.current_market_price
                db_pos.unrealized_pnl = updated_pos.unrealized_pnl
                db_pos.realized_pnl = updated_pos.realized_pnl
                db_pos.peak_unrealized_pnl = updated_pos.peak_unrealized_pnl
                db_pos.last_updated_at = updated_pos.updated_at

            await session.flush()
            return updated_pos

        except Exception as exc:
            # Atomic rollback of in-memory state upon database exception
            with self._lock:
                self._restore_state_snapshot(state_snapshot)
            logger.error(
                "position_transaction_failed_rolled_back",
                fill_id=fill.fill_id,
                instrument=fill.instrument,
                error=str(exc),
            )
            raise

    # -------------------------------------------------------------------------
    # Internal Accounting Calculation Helpers
    # -------------------------------------------------------------------------

    def _handle_open_from_flat(
        self,
        fill: OrderFill,
        existing: Position | None,
        now_utc: datetime,
    ) -> Position:
        """Open a position from flat state."""
        qty = fill.quantity if fill.direction == "BUY" else -fill.quantity
        cost = Decimal(fill.quantity) * fill.price

        if fill.direction == "BUY":
            self._cash -= cost
        else:
            self._cash += cost

        self._opened_at[fill.instrument] = now_utc
        prev_realized = existing.realized_pnl if existing is not None else Decimal("0.00")

        return Position(
            instrument=fill.instrument,
            quantity=qty,
            average_entry_price=fill.price,
            current_market_price=fill.price,
            unrealized_pnl=Decimal("0.00"),
            realized_pnl=prev_realized,
            peak_unrealized_pnl=Decimal("0.00"),
            updated_at=now_utc,
        )

    def _handle_add_to_position(
        self,
        existing: Position,
        fill: OrderFill,
        now_utc: datetime,
    ) -> Position:
        """Add to existing position in the same direction (weighted average price)."""
        current_qty = abs(existing.quantity)
        add_qty = fill.quantity
        new_total_qty = current_qty + add_qty

        # Weighted average entry price
        current_cost = Decimal(current_qty) * existing.average_entry_price
        add_cost = Decimal(add_qty) * fill.price
        new_avg_entry = (current_cost + add_cost) / Decimal(new_total_qty)

        signed_qty = new_total_qty if existing.quantity > 0 else -new_total_qty

        if fill.direction == "BUY":
            self._cash -= add_cost
        else:
            self._cash += add_cost

        unrealized = self._compute_unrealized_pnl(signed_qty, new_avg_entry, fill.price)
        peak_unrealized = max(existing.peak_unrealized_pnl, unrealized)

        return Position(
            instrument=existing.instrument,
            quantity=signed_qty,
            average_entry_price=new_avg_entry,
            current_market_price=fill.price,
            unrealized_pnl=unrealized,
            realized_pnl=existing.realized_pnl,
            peak_unrealized_pnl=peak_unrealized,
            updated_at=now_utc,
        )

    def _handle_reduce_or_flip(
        self,
        existing: Position,
        fill: OrderFill,
        now_utc: datetime,
    ) -> Position:
        """Partially close, fully close, or flip an existing position."""
        current_qty = existing.quantity
        fill_qty = fill.quantity

        is_long = current_qty > 0
        held_qty = abs(current_qty)

        if fill_qty <= held_qty:
            # Partial or exact close
            closed_qty = fill_qty
            if is_long:
                trade_pnl = Decimal(closed_qty) * (fill.price - existing.average_entry_price)
                self._cash += Decimal(closed_qty) * fill.price
            else:
                trade_pnl = Decimal(closed_qty) * (existing.average_entry_price - fill.price)
                self._cash -= Decimal(closed_qty) * fill.price

            self._cumulative_realized_pnl += trade_pnl
            new_pos_realized = existing.realized_pnl + trade_pnl
            self._trades_today += 1

            rem_qty = held_qty - closed_qty
            if rem_qty == 0:
                # Fully closed
                return Position(
                    instrument=existing.instrument,
                    quantity=0,
                    average_entry_price=Decimal("0.00"),
                    current_market_price=fill.price,
                    unrealized_pnl=Decimal("0.00"),
                    realized_pnl=new_pos_realized,
                    peak_unrealized_pnl=existing.peak_unrealized_pnl,
                    updated_at=now_utc,
                )

            # Partially closed: entry price stays the same for remaining shares
            signed_rem_qty = rem_qty if is_long else -rem_qty
            unrealized = self._compute_unrealized_pnl(
                signed_rem_qty, existing.average_entry_price, fill.price
            )
            peak_unrealized = max(existing.peak_unrealized_pnl, unrealized)

            return Position(
                instrument=existing.instrument,
                quantity=signed_rem_qty,
                average_entry_price=existing.average_entry_price,
                current_market_price=fill.price,
                unrealized_pnl=unrealized,
                realized_pnl=new_pos_realized,
                peak_unrealized_pnl=peak_unrealized,
                updated_at=now_utc,
            )

        # Oversized exit: Position Flip (e.g., Long 10 -> Sell 15 -> Short 5)
        closed_qty = held_qty
        if is_long:
            trade_pnl = Decimal(closed_qty) * (fill.price - existing.average_entry_price)
            self._cash += Decimal(closed_qty) * fill.price
        else:
            trade_pnl = Decimal(closed_qty) * (existing.average_entry_price - fill.price)
            self._cash -= Decimal(closed_qty) * fill.price

        self._cumulative_realized_pnl += trade_pnl
        new_pos_realized = existing.realized_pnl + trade_pnl
        self._trades_today += 1

        flipped_qty = fill_qty - held_qty
        if is_long:
            # Long flipped to Short
            signed_qty = -flipped_qty
            self._cash += Decimal(flipped_qty) * fill.price
        else:
            # Short flipped to Long
            signed_qty = flipped_qty
            self._cash -= Decimal(flipped_qty) * fill.price

        self._opened_at[existing.instrument] = now_utc

        return Position(
            instrument=existing.instrument,
            quantity=signed_qty,
            average_entry_price=fill.price,
            current_market_price=fill.price,
            unrealized_pnl=Decimal("0.00"),
            realized_pnl=new_pos_realized,
            peak_unrealized_pnl=Decimal("0.00"),
            updated_at=now_utc,
        )

    @staticmethod
    def _compute_unrealized_pnl(
        quantity: int,
        average_entry_price: Decimal,
        market_price: Decimal,
    ) -> Decimal:
        """Compute mark-to-market unrealized profit or loss."""
        if quantity == 0:
            return Decimal("0.00")
        if quantity > 0:
            return Decimal(quantity) * (market_price - average_entry_price)
        return Decimal(abs(quantity)) * (average_entry_price - market_price)

    def _calculate_holdings_net_value(self) -> Decimal:
        """Calculate net market value of open positions (long value - short liability)."""
        net_val = Decimal("0.00")
        for pos in self._positions.values():
            if pos.quantity > 0:
                net_val += Decimal(pos.quantity) * pos.current_market_price
            elif pos.quantity < 0:
                net_val -= Decimal(abs(pos.quantity)) * pos.current_market_price
        return net_val

    def _update_peak_equity(self) -> None:
        """Update portfolio peak equity monotonically."""
        current_eq = self.total_equity
        self._peak_equity = max(self._peak_equity, current_eq)

    def _create_state_snapshot(self) -> dict[str, object]:
        """Create deep-copy snapshot of mutable state for transaction rollback."""
        return {
            "cash": self._cash,
            "peak_equity": self._peak_equity,
            "cumulative_realized_pnl": self._cumulative_realized_pnl,
            "cumulative_fees": self._cumulative_fees,
            "trades_today": self._trades_today,
            "positions": deepcopy(self._positions),
            "opened_at": deepcopy(self._opened_at),
        }

    def _restore_state_snapshot(self, snapshot: dict[str, object]) -> None:
        """Restore in-memory state from snapshot."""
        self._cash = snapshot["cash"]  # type: ignore[assignment]
        self._peak_equity = snapshot["peak_equity"]  # type: ignore[assignment]
        self._cumulative_realized_pnl = snapshot["cumulative_realized_pnl"]  # type: ignore[assignment]
        self._cumulative_fees = snapshot["cumulative_fees"]  # type: ignore[assignment]
        self._trades_today = snapshot["trades_today"]  # type: ignore[assignment]
        self._positions = snapshot["positions"]  # type: ignore[assignment]
        self._opened_at = snapshot["opened_at"]  # type: ignore[assignment]
