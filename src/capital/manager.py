"""Capital manager and operator scaling authorization workflow engine.

Adheres strictly to BRD BR-2 (no silent capital scaling), FRD-CAP-1,
FRD-CAP-3, FRD-CAP-4, and RTLD §15.
"""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from pydantic import SecretStr

from src.domain.capital_event import CapitalEvent, CapitalEventType
from src.domain.capital_state import CapitalState

if TYPE_CHECKING:
    from src.domain.scaling_report import CapitalScalingReport

logger = structlog.get_logger("capital.manager")

DEFAULT_INITIAL_CAPITAL = Decimal("10000.00")
DEFAULT_OPERATOR_TOKEN = "operator-secret-token"


class CapitalError(Exception):
    """Base exception for capital management errors."""


class UnauthorizedScalingError(CapitalError):
    """Raised when operator token authorization fails during capital scaling."""


class IneligibleScalingError(CapitalError):
    """Raised when capital scaling is attempted without passing all 9 RTLD §15 criteria."""


class ScalingCapExceededError(CapitalError):
    """Raised when requested capital increase exceeds the strict +25% step cap."""


class WithdrawalError(CapitalError):
    """Raised when profit withdrawal parameters or balances are invalid."""


class CapitalManager:
    """Manages live trading capital, step-wise scaling, and profit withdrawal accounting.

    Enforces non-negotiable safety constraints:
    - Capital NEVER auto-scales without explicit human operator signature (BRD BR-2, FRD-CAP-3).
    - Step increases are bounded strictly to maximum +25% per tier (RTLD §15).
    - 50% profit withdrawal mandate before scaling (FRD-CAP-3, RTLD §15).
    - Immutable audit trail recorded for every capital event (FRD-CAP-4).
    """

    def __init__(
        self,
        initial_capital: Decimal = DEFAULT_INITIAL_CAPITAL,
        operator_token: str | SecretStr | None = None,
    ) -> None:
        self._current_capital = initial_capital
        self._peak_equity = initial_capital
        self._retained_profits = Decimal("0.00")
        self._cumulative_withdrawn = Decimal("0.00")
        self._currently_deployed = Decimal("0.00")
        self._open_position_count = 0
        self._trades_today = 0

        raw_token = (
            operator_token.get_secret_value()
            if isinstance(operator_token, SecretStr)
            else (operator_token or DEFAULT_OPERATOR_TOKEN)
        )
        self._operator_token = SecretStr(raw_token)
        self._history: list[CapitalEvent] = []
        self._log = logger.bind(component="CapitalManager")

    @property
    def current_capital(self) -> Decimal:
        """Current live trading capital allocation in INR."""
        return self._current_capital

    @property
    def retained_profits(self) -> Decimal:
        """Accumulated realized profits eligible for withdrawal in INR."""
        return self._retained_profits

    @property
    def cumulative_withdrawn(self) -> Decimal:
        """Total cumulative profits withdrawn from the trading account in INR."""
        return self._cumulative_withdrawn

    def _verify_token(self, token: str) -> None:
        """Verify operator authentication token using constant-time comparison."""
        expected = self._operator_token.get_secret_value().encode("utf-8")
        actual = token.encode("utf-8")
        if not hmac.compare_digest(expected, actual):
            self._log.warning("unauthorized_capital_action_attempted")
            msg = "Invalid or missing operator authorization token"
            raise UnauthorizedScalingError(msg)

    def record_profit(self, realized_pnl: Decimal) -> None:
        """Record realized trade P&L to track retained profits and peak equity."""
        if realized_pnl > Decimal("0.00"):
            self._retained_profits += realized_pnl
            total_equity = self._current_capital + self._retained_profits
            self._peak_equity = max(self._peak_equity, total_equity)
        elif realized_pnl < Decimal("0.00"):
            loss = abs(realized_pnl)
            if self._retained_profits >= loss:
                self._retained_profits -= loss
            else:
                remaining_loss = loss - self._retained_profits
                self._retained_profits = Decimal("0.00")
                self._current_capital = max(Decimal("0.00"), self._current_capital - remaining_loss)

    def request_scaling_authorization(
        self,
        report: CapitalScalingReport,
        operator_token: str,
        new_capital: Decimal | None = None,
        justification: str = "Operator authorized capital step increase",
    ) -> CapitalEvent:
        """Authorize and execute a step-wise capital increase up to +25%.

        Args:
            report: Validated CapitalScalingReport demonstrating all 9 criteria passed.
            operator_token: Operator secret authorization token.
            new_capital: Target capital. Must not exceed current + 25%.
            justification: Human operator rationale for scaling.

        Returns:
            CapitalEvent: Immutable audit record of the scaling transaction.

        Raises:
            UnauthorizedScalingError: If operator token is invalid.
            IneligibleScalingError: If scaling criteria report is not eligible.
            ScalingCapExceededError: If requested capital exceeds +25% ceiling.
        """
        # 1. Verify operator token authorization (FRD-CAP-3 / BRD BR-2)
        self._verify_token(operator_token)

        # 2. Verify all 9 RTLD §15 criteria passed
        if not report.eligible_for_scaling:
            msg = (
                f"Cannot scale capital: report {report.report_id} shows system is INELIGIBLE "
                f"({report.passed_count}/9 criteria passed). {report.summary_verdict}"
            )
            raise IneligibleScalingError(msg)

        # 3. Compute and enforce strict +25% step scaling cap (FRD-CAP-3, RTLD §15)
        max_permitted = (self._current_capital * Decimal("1.25")).quantize(Decimal("0.01"))
        target_capital = new_capital if new_capital is not None else max_permitted

        if target_capital > max_permitted:
            msg = (
                f"Requested capital ₹{target_capital:,.2f} exceeds strict +25% step "
                f"ceiling of ₹{max_permitted:,.2f} from current ₹{self._current_capital:,.2f}"
            )
            raise ScalingCapExceededError(msg)

        if target_capital <= self._current_capital:
            msg = (
                f"Target capital ₹{target_capital:,.2f} must be greater than "
                f"current capital ₹{self._current_capital:,.2f}"
            )
            raise ScalingCapExceededError(msg)

        # 4. Enforce 50% profit withdrawal mandate before scaling (FRD-CAP-3, RTLD §15)
        withdrawn_amount = Decimal("0.00")
        if self._retained_profits > Decimal("0.00"):
            withdrawn_amount = (self._retained_profits * Decimal("0.50")).quantize(Decimal("0.01"))
            self._retained_profits -= withdrawn_amount
            self._cumulative_withdrawn += withdrawn_amount

        prev_capital = self._current_capital
        self._current_capital = target_capital
        total_equity = self._current_capital + self._retained_profits
        self._peak_equity = max(self._peak_equity, total_equity)

        # 5. Generate cryptographic token hash for non-repudiation audit
        token_hash = hashlib.sha256(operator_token.encode("utf-8")).hexdigest()

        event = CapitalEvent(
            event_type=CapitalEventType.SCALING_INCREASE,
            previous_capital=prev_capital,
            new_capital=self._current_capital,
            withdrawn_amount=withdrawn_amount,
            operator_token_hash=token_hash,
            justification=f"{justification} (withdrew 50% profits: ₹{withdrawn_amount:,.2f})",
            scaling_report_id=report.report_id,
        )

        self._history.append(event)
        self._log.info(
            "capital_scaling_authorized_and_applied",
            event_id=event.event_id,
            previous_capital=str(prev_capital),
            new_capital=str(self._current_capital),
            withdrawn_amount=str(withdrawn_amount),
            report_id=report.report_id,
        )

        return event

    def record_withdrawal(
        self,
        amount: Decimal,
        operator_token: str,
        justification: str = "Operator profit withdrawal",
    ) -> CapitalEvent:
        """Execute a profit withdrawal transaction from retained earnings.

        Args:
            amount: Withdrawal amount in INR.
            operator_token: Operator secret authorization token.
            justification: Human operator rationale.

        Returns:
            CapitalEvent: Immutable audit record of the withdrawal.

        Raises:
            UnauthorizedScalingError: If operator token is invalid.
            WithdrawalError: If withdrawal amount exceeds retained profits.
        """
        self._verify_token(operator_token)

        if amount <= Decimal("0.00"):
            msg = f"Withdrawal amount must be positive, got ₹{amount}"
            raise WithdrawalError(msg)

        if amount > self._retained_profits:
            msg = (
                f"Requested withdrawal ₹{amount:,.2f} exceeds available retained "
                f"profits of ₹{self._retained_profits:,.2f}. Base trading capital "
                "cannot be withdrawn via this mechanism."
            )
            raise WithdrawalError(msg)

        self._retained_profits -= amount
        self._cumulative_withdrawn += amount

        token_hash = hashlib.sha256(operator_token.encode("utf-8")).hexdigest()

        event = CapitalEvent(
            event_type=CapitalEventType.PROFIT_WITHDRAWAL,
            previous_capital=self._current_capital,
            new_capital=self._current_capital,
            withdrawn_amount=amount,
            operator_token_hash=token_hash,
            justification=justification,
        )

        self._history.append(event)
        self._log.info(
            "profit_withdrawal_executed",
            amount=str(amount),
            remaining_retained=str(self._retained_profits),
            cumulative_withdrawn=str(self._cumulative_withdrawn),
        )

        return event

    def get_capital_state(self) -> CapitalState:
        """Construct the canonical CapitalState domain snapshot."""
        return CapitalState(
            current_capital=self._current_capital,
            peak_equity=self._peak_equity,
            session_start_capital=self._current_capital,
            currently_deployed=self._currently_deployed,
            open_position_count=self._open_position_count,
            trades_today=self._trades_today,
        )

    def get_history(self) -> list[CapitalEvent]:
        """Return a copy of the capital change audit history."""
        return list(self._history)
