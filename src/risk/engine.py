"""Deterministic Risk Engine enforcing fail-fast safety boundary checklist per RTLD §4-§14."""

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from src.domain.risk import (
    CandidateTrade,
    CapitalState,
    MarketState,
    RiskCheckResult,
    StreakState,
)
from src.risk.config import RiskConfig
from src.risk.kill_switch import KillSwitchProtocol
from src.risk.sizer import PositionSizer

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger()


class RiskEngine:
    """Deterministic, pure fail-fast risk engine adhering to RTLD §4-§14 and LLD §5."""

    def __init__(
        self,
        config: RiskConfig,
        kill_switch: KillSwitchProtocol,
        sizer: PositionSizer | None = None,
    ) -> None:
        self._config = config
        self._kill_switch = kill_switch
        self._sizer = sizer or PositionSizer(config)

    @property
    def sizer(self) -> PositionSizer:
        """Return position sizer instance."""
        return self._sizer

    @property
    def config(self) -> RiskConfig:
        """Return active risk configuration."""
        return self._config

    def evaluate(
        self,
        candidate: CandidateTrade,
        capital: CapitalState,
        streak: StreakState,
        market: MarketState,
    ) -> RiskCheckResult:
        """Evaluate candidate trade against fail-fast risk checklist in deterministic order."""
        pre_checks: list[Callable[[], RiskCheckResult | None]] = [
            self._check_kill_switch,
            lambda: self._check_daily_loss(capital),
            lambda: self._check_drawdown_tiers(capital),
            lambda: self._check_exposure_position_caps(capital),
            lambda: self._check_consecutive_loss_tier(streak),
        ]
        for check_fn in pre_checks:
            res = check_fn()
            if res is not None:
                return res

        sizing_res, calculated_qty = self._check_per_trade_risk_and_sizing(
            candidate, capital, streak, market
        )
        if sizing_res is not None:
            return sizing_res

        post_checks: list[Callable[[], RiskCheckResult | None]] = [
            lambda: self._check_volatility_liquidity_market(market),
            lambda: self._check_model_confidence(candidate),
        ]
        for post_fn in post_checks:
            res = post_fn()
            if res is not None:
                return res

        logger.info(
            "RiskEngine approved candidate trade",
            instrument=candidate.instrument,
            direction=candidate.direction,
            approved_quantity=calculated_qty,
            stop_price=str(candidate.stop_price),
        )
        return RiskCheckResult(
            passed=True,
            failed_check=None,
            rtld_param_id=None,
            reason="all checks passed",
            config_version=self._config.version,
            approved_quantity=calculated_qty,
            stop_loss_price=candidate.stop_price,
            target_price=None,
        )

    def _check_kill_switch(self) -> RiskCheckResult | None:
        """Check 1: Fast O(1) kill switch / manual STOP status check (RTLD-17)."""
        if self._kill_switch.is_active():
            return RiskCheckResult(
                passed=False,
                failed_check="kill_switch",
                rtld_param_id="RTLD-17",
                reason="kill switch/STOP is active",
                config_version=self._config.version,
                approved_quantity=0,
            )
        return None

    def _check_daily_loss(self, capital: CapitalState) -> RiskCheckResult | None:
        """Check 2: Maximum daily session loss check (RTLD-4)."""
        loss = capital.session_start_capital - capital.current_capital
        limit = capital.session_start_capital * self._config.max_daily_loss_pct
        if loss >= limit:
            return RiskCheckResult(
                passed=False,
                failed_check="daily_loss_limit",
                rtld_param_id="RTLD-4",
                reason=f"daily loss ₹{loss:.2f} >= limit ₹{limit:.2f}",
                config_version=self._config.version,
                approved_quantity=0,
            )
        return None

    def _check_drawdown_tiers(self, capital: CapitalState) -> RiskCheckResult | None:
        """Check 3: Peak-to-trough account equity drawdown tiers (RTLD-5, RTLD-6)."""
        drawdown = capital.peak_equity - capital.current_capital

        extreme_limit = capital.peak_equity * self._config.extreme_loss_killswitch_pct
        if drawdown >= extreme_limit:
            msg = f"extreme drawdown ₹{drawdown:.2f} >= circuit breaker limit ₹{extreme_limit:.2f}"
            return RiskCheckResult(
                passed=False,
                failed_check="extreme_drawdown_killswitch",
                rtld_param_id="RTLD-6",
                reason=msg,
                config_version=self._config.version,
                approved_quantity=0,
            )

        halt_limit = capital.peak_equity * self._config.hard_drawdown_halt_pct
        if drawdown >= halt_limit:
            return RiskCheckResult(
                passed=False,
                failed_check="hard_drawdown_halt",
                rtld_param_id="RTLD-5",
                reason=f"hard drawdown ₹{drawdown:.2f} >= halt limit ₹{halt_limit:.2f}",
                config_version=self._config.version,
                approved_quantity=0,
            )
        return None

    def _check_exposure_position_caps(self, capital: CapitalState) -> RiskCheckResult | None:
        """Check 4: Position count, daily trade count, and exposure headroom (RTLD-7-10)."""
        if capital.open_position_count >= self._config.max_simultaneous_positions:
            msg = (
                f"open position count {capital.open_position_count} >= "
                f"max {self._config.max_simultaneous_positions}"
            )
            return RiskCheckResult(
                passed=False,
                failed_check="max_simultaneous_positions",
                rtld_param_id="RTLD-9",
                reason=msg,
                config_version=self._config.version,
                approved_quantity=0,
            )

        if capital.trades_today >= self._config.max_trades_per_day:
            msg = f"trades today {capital.trades_today} >= max {self._config.max_trades_per_day}"
            return RiskCheckResult(
                passed=False,
                failed_check="max_trades_per_day",
                rtld_param_id="RTLD-10",
                reason=msg,
                config_version=self._config.version,
                approved_quantity=0,
            )

        max_exposure = capital.current_capital * self._config.max_portfolio_exposure_pct
        if capital.currently_deployed >= max_exposure:
            msg = (
                f"currently deployed ₹{capital.currently_deployed:.2f} >= "
                f"max exposure ₹{max_exposure:.2f}"
            )
            return RiskCheckResult(
                passed=False,
                failed_check="max_portfolio_exposure",
                rtld_param_id="RTLD-7",
                reason=msg,
                config_version=self._config.version,
                approved_quantity=0,
            )
        return None

    def _check_consecutive_loss_tier(self, streak: StreakState) -> RiskCheckResult | None:
        """Check 5: Tier-2 consecutive loss session pause circuit breaker (RTLD-12)."""
        if streak.consecutive_losses >= self._config.consec_loss_pause_trigger:
            msg = (
                f"consecutive losses {streak.consecutive_losses} >= "
                f"pause trigger {self._config.consec_loss_pause_trigger}"
            )
            return RiskCheckResult(
                passed=False,
                failed_check="consecutive_loss_pause",
                rtld_param_id="RTLD-12",
                reason=msg,
                config_version=self._config.version,
                approved_quantity=0,
            )
        return None

    def _check_per_trade_risk_and_sizing(
        self,
        candidate: CandidateTrade,
        capital: CapitalState,
        streak: StreakState,
        market: MarketState,
    ) -> tuple[RiskCheckResult | None, int]:
        """Check 6: Per-trade risk budget and fixed-fractional sizing (RTLD-3, RTLD-11, RTLD-13)."""
        stop_distance = abs(candidate.entry_price - candidate.stop_price)
        if stop_distance <= Decimal("0"):
            return (
                RiskCheckResult(
                    passed=False,
                    failed_check="undefined_stop",
                    rtld_param_id="RTLD-3",
                    reason="stop distance must be strictly positive",
                    config_version=self._config.version,
                    approved_quantity=0,
                ),
                0,
            )

        sizing = self._sizer.calculate(candidate, capital, streak, market)
        if not sizing.approved:
            if sizing.binding_constraint == "unsizeable":
                failed_check = "unsizeable_trade"
                rtld_id = "RTLD-3"
            else:
                failed_check = "position_exposure_headroom_zero"
                rtld_id = "RTLD-7"
            return (
                RiskCheckResult(
                    passed=False,
                    failed_check=failed_check,
                    rtld_param_id=rtld_id,
                    reason=sizing.reason.lower(),
                    config_version=self._config.version,
                    approved_quantity=0,
                ),
                0,
            )

        return None, sizing.final_quantity

    def _check_volatility_liquidity_market(self, market: MarketState) -> RiskCheckResult | None:
        """Check 7: Market condition, data staleness, and volatility (RTLD-14, RTLD-19)."""
        if market.exchange_condition != "NORMAL":
            return RiskCheckResult(
                passed=False,
                failed_check="exchange_condition_abnormal",
                rtld_param_id="RTLD-14",
                reason=f"exchange condition is {market.exchange_condition}",
                config_version=self._config.version,
                approved_quantity=0,
            )

        if market.data_quality in ("STALE", "QUARANTINED"):
            return RiskCheckResult(
                passed=False,
                failed_check="data_quality_unacceptable",
                rtld_param_id="RTLD-19",
                reason=f"market data quality is {market.data_quality}",
                config_version=self._config.version,
                approved_quantity=0,
            )

        if (
            market.trailing_20session_avg_volatility > Decimal("0")
            and market.current_volatility
            >= market.trailing_20session_avg_volatility * self._config.vol_block_multiple
        ):
            mult = self._config.vol_block_multiple
            avg = market.trailing_20session_avg_volatility
            msg = f"volatility {market.current_volatility} >= {mult}x average {avg}"
            return RiskCheckResult(
                passed=False,
                failed_check="extreme_volatility_block",
                rtld_param_id="RTLD-14",
                reason=msg,
                config_version=self._config.version,
                approved_quantity=0,
            )
        return None

    def _check_model_confidence(self, candidate: CandidateTrade) -> RiskCheckResult | None:
        """Check 8: Model confidence gate and non-negative expected value (RTLD-16)."""
        if candidate.confidence < self._config.min_confidence_threshold:
            thresh = self._config.min_confidence_threshold
            msg = f"model confidence {candidate.confidence:.2f} < threshold {thresh:.2f}"
            return RiskCheckResult(
                passed=False,
                failed_check="confidence_below_threshold",
                rtld_param_id="RTLD-16",
                reason=msg,
                config_version=self._config.version,
                approved_quantity=0,
            )

        if candidate.expected_value <= Decimal("0"):
            return RiskCheckResult(
                passed=False,
                failed_check="non_positive_expected_value",
                rtld_param_id="RTLD-16",
                reason=f"expected value {candidate.expected_value} <= 0 post-friction",
                config_version=self._config.version,
                approved_quantity=0,
            )
        return None
