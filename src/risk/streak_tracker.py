"""Consecutive loss tracking engine and behavioral circuit breakers.

Implements behavioral protection against loss accumulation per RTLD §10,
FRD-RISK-8, and RTLD §14:
- Tier-1: 3 consecutive losing trades -> 50% size reduction multiplier (RTLD-11)
- Tier-2: 5 consecutive losing trades -> session trading pause (RTLD-12)
- Winning trade (pnl > 0) resets consecutive loss streak counter
- Breakeven trade (pnl == 0) maintains streak state without incrementing
- Tier-1 persists on rolling basis; Tier-2 pause clears on session boundary
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.domain.risk import StreakState
from src.risk.config import RiskConfig

logger = structlog.get_logger(__name__)


class StreakTracker:
    """Tracks consecutive loss streaks and manages Tier-1 / Tier-2 behavioral circuit breakers."""

    def __init__(
        self,
        config: RiskConfig | None = None,
        initial_state: StreakState | None = None,
        rolling: bool = True,
    ) -> None:
        self._config = config or RiskConfig()
        self._rolling = rolling

        self._consecutive_losses = initial_state.consecutive_losses if initial_state else 0
        self._session_losses = 0
        self._session_paused = initial_state.session_paused if initial_state else False
        self._last_trade_pnl: Decimal | None = (
            initial_state.last_trade_pnl if initial_state else None
        )
        self._trade_history: list[dict[str, Any]] = []

    @property
    def config(self) -> RiskConfig:
        """Return the active risk configuration."""
        return self._config

    @property
    def rolling(self) -> bool:
        """Return whether Tier-1 consecutive losses persist across sessions."""
        return self._rolling

    @property
    def consecutive_losses(self) -> int:
        """Return current consecutive loss count."""
        return self._consecutive_losses

    @property
    def session_paused(self) -> bool:
        """Return whether session is currently paused due to Tier-2 streak trigger."""
        return self._session_paused

    @property
    def is_tier1_active(self) -> bool:
        """Return True if Tier-1 50% size reduction is currently triggered."""
        return self._consecutive_losses >= self._config.consec_loss_reduce_trigger

    @property
    def is_tier2_active(self) -> bool:
        """Return True if Tier-2 session pause is currently triggered."""
        return (
            self._session_paused
            or self._consecutive_losses >= self._config.consec_loss_pause_trigger
        )

    @property
    def size_multiplier(self) -> Decimal:
        """Return position sizing risk multiplier (0.5 if Tier-1 active, else 1.0)."""
        if self.is_tier1_active:
            return Decimal("0.5")
        return Decimal("1.0")

    def record_trade(
        self,
        pnl: Decimal | float | int,
        trade_id: str | None = None,
        exit_time: datetime | None = None,
    ) -> StreakState:
        """Record trade P&L outcome and update streak circuit breakers.

        Args:
            pnl: Realized profit and loss in INR.
            trade_id: Optional trade identifier.
            exit_time: Optional exit timestamp (enforces UTC).

        Returns:
            Updated StreakState snapshot.
        """
        pnl_decimal = Decimal(str(pnl))
        self._last_trade_pnl = pnl_decimal

        ts = exit_time or datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        self._trade_history.append(
            {
                "trade_id": trade_id,
                "pnl": float(pnl_decimal),
                "timestamp": ts.isoformat(),
            }
        )

        if pnl_decimal > Decimal("0"):
            logger.info(
                "streak_tracker_winning_trade_reset",
                trade_id=trade_id,
                pnl=float(pnl_decimal),
                prior_losses=self._consecutive_losses,
            )
            self._consecutive_losses = 0
            self._session_losses = 0

        elif pnl_decimal < Decimal("0"):
            self._consecutive_losses += 1
            self._session_losses += 1

            logger.warning(
                "streak_tracker_losing_trade_recorded",
                trade_id=trade_id,
                pnl=float(pnl_decimal),
                consecutive_losses=self._consecutive_losses,
                session_losses=self._session_losses,
            )

            # Check Tier-2 session pause trigger (RTLD-12)
            if self._consecutive_losses >= self._config.consec_loss_pause_trigger:
                self._session_paused = True
                logger.critical(
                    "streak_tracker_tier2_session_pause_triggered",
                    consecutive_losses=self._consecutive_losses,
                    trigger=self._config.consec_loss_pause_trigger,
                )
            elif self._consecutive_losses >= self._config.consec_loss_reduce_trigger:
                logger.warning(
                    "streak_tracker_tier1_size_reduction_active",
                    consecutive_losses=self._consecutive_losses,
                    trigger=self._config.consec_loss_reduce_trigger,
                )
        else:
            logger.info(
                "streak_tracker_breakeven_trade",
                trade_id=trade_id,
                pnl=float(pnl_decimal),
                consecutive_losses=self._consecutive_losses,
            )

        return self.get_state()

    def on_session_start(self, session_date: date | None = None) -> StreakState:
        """Handle session boundary transition.

        Clears Tier-2 session pause automatically per RTLD §10.
        If rolling is True, preserves Tier-1 consecutive loss count.
        If rolling is False, resets consecutive loss count to 0.

        Args:
            session_date: Optional session date for logging.

        Returns:
            Updated StreakState snapshot.
        """
        logger.info(
            "streak_tracker_session_start",
            session_date=str(session_date),
            prior_consecutive_losses=self._consecutive_losses,
            prior_session_paused=self._session_paused,
            rolling=self._rolling,
        )

        self._session_paused = False
        self._session_losses = 0

        if not self._rolling:
            self._consecutive_losses = 0

        return self.get_state()

    def get_state(self) -> StreakState:
        """Return the current immutable StreakState."""
        return StreakState(
            consecutive_losses=self._consecutive_losses,
            is_tier1_active=self.is_tier1_active,
            is_tier2_active=self.is_tier2_active,
            session_paused=self._session_paused,
            last_trade_pnl=self._last_trade_pnl,
        )

    def reset(self, auth_token: str | None = None) -> None:
        """Authorized operator manual streak reset.

        Args:
            auth_token: Operator authentication token.

        Raises:
            PermissionError: If auth_token is invalid or empty.
        """
        if not auth_token or not auth_token.strip():
            msg = "Operator authorization token required for streak reset"
            raise PermissionError(msg)

        logger.warning("streak_tracker_manual_reset_invoked")
        self._consecutive_losses = 0
        self._session_losses = 0
        self._session_paused = False
        self._last_trade_pnl = None
