"""Continuous performance degradation monitor and automated production model rollback.

Conforms to FRD-LEARN-6, FRD-LEARN-7, FRD-LEARN-8, ADD §8.4, SLD §7.2, §8, and SOW §6.8.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from src.domain.evaluation import TradeEvaluation
    from src.domain.governance import ModelVersion

from src.domain.governance_event import RollbackEvent
from src.utils.logging import get_logger


class RollbackMonitorConfig(BaseModel):
    """Configuration governing degradation detection thresholds and rollback criteria."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_size: int = Field(
        default=30,
        ge=5,
        description="Rolling trade evaluation window size (SLD §7)",
    )
    max_drawdown_limit_pct: float = Field(
        default=8.0,
        gt=0.0,
        description="Maximum permitted live drawdown before triggering immediate rollback",
    )
    min_rolling_win_rate: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="Minimum win rate floor across window (SLD §7.2)",
    )
    max_consecutive_losses: int = Field(
        default=5,
        ge=2,
        description="Maximum permissible consecutive loss count before rollback trigger",
    )
    consecutive_degraded_windows: int = Field(
        default=2,
        ge=1,
        description="Number of consecutive windows with Sharpe drop before trigger",
    )
    max_rollbacks_per_90_days: int = Field(
        default=2,
        ge=1,
        description="Threshold of rollbacks in 90 days before halting future candidate promotions",
    )


class RollbackMonitor:
    """Monitors live trade stream for statistical degradation and reverts to prior baseline."""

    def __init__(self, config: RollbackMonitorConfig | None = None) -> None:
        self.config = config or RollbackMonitorConfig()
        self._logger = get_logger("RollbackMonitor")
        self._trade_history: list[TradeEvaluation] = []
        self._consecutive_losses: int = 0
        self._peak_equity: Decimal = Decimal("10000.00")
        self._current_equity: Decimal = Decimal("10000.00")
        self._degraded_sharpe_windows_count: int = 0
        self._rollback_history: list[RollbackEvent] = []
        self._promotion_halted: bool = False

    @property
    def promotion_halted(self) -> bool:
        """True if candidate promotions are currently frozen due to repeated rollbacks."""
        return self._promotion_halted

    @property
    def rollback_history(self) -> list[RollbackEvent]:
        """Audit list of all historical rollback events."""
        return list(self._rollback_history)

    def reset_for_new_promotion(self, initial_capital: Decimal = Decimal("10000.00")) -> None:
        """Reset trade-tracking state when a newly promoted model enters live service."""
        self._trade_history.clear()
        self._consecutive_losses = 0
        self._peak_equity = initial_capital
        self._current_equity = initial_capital
        self._degraded_sharpe_windows_count = 0

    def process_completed_trade(
        self,
        trade: TradeEvaluation,
        *,
        active_model: ModelVersion,
        fallback_model: ModelVersion | None = None,
    ) -> RollbackEvent | None:
        """Evaluate a completed live trade and trigger automated reversion if degraded.

        Args:
            trade: Evaluated live trade record.
            active_model: Currently deployed ModelVersion generating live orders.
            fallback_model: Immediately prior superseded ModelVersion eligible for restoration.

        Returns:
            RollbackEvent if rollback was triggered; None if model remains healthy.
        """
        self._trade_history.append(trade)
        self._current_equity += trade.net_pnl
        self._peak_equity = max(self._peak_equity, self._current_equity)

        # Track consecutive losses
        if trade.net_pnl < Decimal("0"):
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        # 1. Hard Trigger: Drawdown Breach
        dd_pct = (
            float(((self._peak_equity - self._current_equity) / self._peak_equity) * 100)
            if self._peak_equity > Decimal("0")
            else 0.0
        )

        if dd_pct >= self.config.max_drawdown_limit_pct:
            note = (
                f"Drawdown {dd_pct:.2f}% breached ceiling "
                f"{self.config.max_drawdown_limit_pct:.2f}%"
            )
            return self._execute_rollback(
                trigger_reason="DRAWDOWN_BREACH",
                evidence={
                    "current_drawdown_pct": dd_pct,
                    "drawdown_limit_pct": self.config.max_drawdown_limit_pct,
                    "peak_equity": float(self._peak_equity),
                    "current_equity": float(self._current_equity),
                },
                active_model=active_model,
                fallback_model=fallback_model,
                notes=note,
            )

        # 2. Hard Trigger: Consecutive Losses Breach
        if self._consecutive_losses >= self.config.max_consecutive_losses:
            return self._execute_rollback(
                trigger_reason="CONSECUTIVE_LOSSES",
                evidence={
                    "consecutive_losses": self._consecutive_losses,
                    "max_allowed": self.config.max_consecutive_losses,
                },
                active_model=active_model,
                fallback_model=fallback_model,
                notes=f"Consecutive losses ({self._consecutive_losses}) exceeded safety limit",
            )

        # Statistical rolling window checks (require at least 10 trades before window tests)
        if len(self._trade_history) >= 10:
            window = self._trade_history[-self.config.window_size :]
            window_wins = sum(1 for t in window if t.net_pnl > Decimal("0"))
            win_rate = window_wins / len(window)

            # 3. Trigger: Win Rate Collapse
            if win_rate < self.config.min_rolling_win_rate:
                win_note = (
                    f"Rolling win rate {win_rate:.1%} dropped below floor "
                    f"{self.config.min_rolling_win_rate:.1%}"
                )
                return self._execute_rollback(
                    trigger_reason="WIN_RATE_COLLAPSE",
                    evidence={
                        "rolling_win_rate": win_rate,
                        "min_required_win_rate": self.config.min_rolling_win_rate,
                        "window_trade_count": len(window),
                    },
                    active_model=active_model,
                    fallback_model=fallback_model,
                    notes=win_note,
                )

            # 4. Trigger: Rolling Sharpe Drop below (Expectation - 1 SE)
            rolling_sharpe = self._calculate_rolling_sharpe(window)
            vm = active_model.validation_metrics
            exp_sharpe = float(vm.get("sharpe_ratio", vm.get("sharpe", 1.2)))
            # Standard error approximation for Sharpe: sqrt((1 + 0.5 * S^2) / N)
            se_sharpe = math.sqrt((1.0 + 0.5 * (exp_sharpe**2)) / len(window))
            threshold_sharpe = exp_sharpe - se_sharpe

            if rolling_sharpe < threshold_sharpe:
                self._degraded_sharpe_windows_count += 1
                self._logger.warning(
                    "rolling_sharpe_degraded_window",
                    active_model_id=active_model.model_id,
                    rolling_sharpe=rolling_sharpe,
                    threshold_sharpe=threshold_sharpe,
                    degraded_windows=self._degraded_sharpe_windows_count,
                )
                if self._degraded_sharpe_windows_count >= self.config.consecutive_degraded_windows:
                    sharpe_note = (
                        f"Rolling Sharpe {rolling_sharpe:.2f} fell below expectation "
                        f"({threshold_sharpe:.2f}) across "
                        f"{self._degraded_sharpe_windows_count} windows"
                    )
                    return self._execute_rollback(
                        trigger_reason="ROLLING_SHARPE_DROP",
                        evidence={
                            "rolling_sharpe": rolling_sharpe,
                            "expected_sharpe": exp_sharpe,
                            "threshold_sharpe": threshold_sharpe,
                            "standard_error": se_sharpe,
                            "consecutive_degraded_windows": self._degraded_sharpe_windows_count,
                        },
                        active_model=active_model,
                        fallback_model=fallback_model,
                        notes=sharpe_note,
                    )
            else:
                self._degraded_sharpe_windows_count = 0

        return None

    def _execute_rollback(
        self,
        *,
        trigger_reason: Any,
        evidence: dict[str, Any],
        active_model: ModelVersion,
        fallback_model: ModelVersion | None,
        notes: str,
    ) -> RollbackEvent:
        """Atomically revert model status and record immutable RollbackEvent."""
        now = datetime.now(UTC)
        restored_id = fallback_model.model_id if fallback_model else "SAFE_BASELINE_FALLBACK"

        # Demote failed model
        active_model.status = "rolled_back"

        # Restore fallback model if available
        if fallback_model is not None:
            fallback_model.status = "promoted"

        event = RollbackEvent(
            failed_model_id=active_model.model_id,
            restored_model_id=restored_id,
            trigger_reason=trigger_reason,
            evidence=evidence,
            timestamp=now,
            notes=notes,
        )
        self._rollback_history.append(event)

        # Check 90-day rollback frequency throttle (SLD §8)
        ninety_days_ago = now - timedelta(days=90)
        recent_rollbacks = sum(1 for e in self._rollback_history if e.timestamp >= ninety_days_ago)
        if recent_rollbacks >= self.config.max_rollbacks_per_90_days:
            self._promotion_halted = True
            self._logger.critical(
                "candidate_promotions_halted",
                recent_rollbacks=recent_rollbacks,
                threshold=self.config.max_rollbacks_per_90_days,
            )

        self._logger.error(
            "automated_model_rollback_executed",
            failed_model_id=active_model.model_id,
            restored_model_id=restored_id,
            reason=trigger_reason,
            notes=notes,
        )
        return event

    @staticmethod
    def _calculate_rolling_sharpe(trades: list[TradeEvaluation]) -> float:
        """Calculate annualized empirical Sharpe ratio from a window of net trade returns."""
        if len(trades) < 2:
            return 0.0
        pnls = [float(t.net_pnl) for t in trades]
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        stdev = math.sqrt(variance) if variance > 0 else 0.0
        if stdev == 0.0:
            return 0.0 if mean_pnl <= 0 else 3.0
        # Annualized scaling assuming ~252 trades/year
        return (mean_pnl / stdev) * math.sqrt(252)
