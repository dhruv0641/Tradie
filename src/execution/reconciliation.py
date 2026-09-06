"""Startup state reconciliation gate and safe-state trading lock.

Enforces:
- LLD §9.1
- TRD-DR-2, TRD-DR-3
- FRD-EXEC-7
- EDD §10
- NFR-REL-5
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from src.domain.execution import Position
from src.execution.broker_adapter import BrokerAdapter
from src.execution.order_manager import OrderManager
from src.execution.position_ledger import PositionLedgerProtocol
from src.risk.kill_switch import KillSwitchProtocol

logger = structlog.get_logger(__name__)


class PositionDiscrepancy(BaseModel):
    """Detailed position mismatch detected during startup reconciliation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    discrepancy_type: Literal[
        "QUANTITY_MISMATCH",
        "PHANTOM_BROKER_POSITION",
        "PHANTOM_LEDGER_POSITION",
        "UNEXPECTED_BROKER_ORDER",
        "MISSING_BROKER_ORDER",
        "CASH_MISMATCH",
    ]
    instrument: str
    broker_quantity: int
    ledger_quantity: int
    details: str
    severity: Literal["CRITICAL", "WARNING"] = "CRITICAL"


class ReconciliationResult(BaseModel):
    """Immutable audit outcome of a startup state reconciliation evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reconciled: bool = Field(
        description="True if broker and ledger states matched cleanly or were overridden"
    )
    reconciled_at: datetime = Field(description="Timestamp of reconciliation run in UTC")
    discrepancies: list[PositionDiscrepancy] = Field(default_factory=list)
    broker_positions_count: int = 0
    ledger_positions_count: int = 0
    open_orders_count: int = 0
    override_applied: bool = False
    override_operator_id: str | None = None
    override_reason: str | None = None


class StartupReconciliationMismatchError(Exception):
    """Raised when broker positions or open orders mismatch local ledger on startup."""

    def __init__(self, message: str, result: ReconciliationResult) -> None:
        super().__init__(message)
        self.result = result


class StartupReconciler:
    """Reconciles broker positions and open orders against local ledger on system startup.

    If any mismatch is detected:
    - System is locked in safe state (can_submit_orders() == False).
    - Critical alert is raised.
    - If configured, emergency Kill Switch is automatically activated (TRD-DR-3).
    - Requires explicit operator manual override to unlock.
    """

    def __init__(
        self,
        broker: BrokerAdapter,
        ledger: PositionLedgerProtocol,
        order_manager: OrderManager | None = None,
        kill_switch: KillSwitchProtocol | None = None,
        *,
        auto_halt_on_mismatch: bool = True,
    ) -> None:
        self.broker = broker
        self.ledger = ledger
        self.order_manager = order_manager
        self.kill_switch = kill_switch
        self.auto_halt_on_mismatch = auto_halt_on_mismatch

        self._reconciled: bool = False
        self._last_result: ReconciliationResult | None = None
        self._log = logger.bind(subsystem="startup_reconciler")

    @property
    def is_reconciled(self) -> bool:
        """Return current reconciliation status."""
        return self._reconciled

    @property
    def last_result(self) -> ReconciliationResult | None:
        """Return result of most recent reconciliation run."""
        return self._last_result

    def can_submit_orders(self) -> bool:
        """Gate check: orders may only be dispatched if startup state is fully reconciled."""
        return self._reconciled

    def _detect_position_discrepancies(
        self,
        broker_map: dict[str, int],
        ledger_map: dict[str, int],
    ) -> list[PositionDiscrepancy]:
        """Helper to compare broker vs ledger quantities and classify discrepancies."""
        all_instruments = set(broker_map.keys()) | set(ledger_map.keys())
        discrepancies: list[PositionDiscrepancy] = []

        for symbol in sorted(all_instruments):
            b_qty = broker_map.get(symbol, 0)
            l_qty = ledger_map.get(symbol, 0)

            if b_qty == l_qty:
                continue

            if l_qty == 0:
                disc_type: Any = "PHANTOM_BROKER_POSITION"
                details = f"Broker holds {b_qty} units in {symbol}, but local ledger is flat (0)"
            elif b_qty == 0:
                disc_type = "PHANTOM_LEDGER_POSITION"
                details = f"Ledger holds {l_qty} units in {symbol}, but broker is flat (0)"
            else:
                disc_type = "QUANTITY_MISMATCH"
                details = f"Quantity mismatch for {symbol}: broker={b_qty}, ledger={l_qty}"

            discrepancies.append(
                PositionDiscrepancy(
                    discrepancy_type=disc_type,
                    instrument=symbol,
                    broker_quantity=b_qty,
                    ledger_quantity=l_qty,
                    details=details,
                    severity="CRITICAL",
                )
            )
        return discrepancies

    def reconcile(self, raise_on_mismatch: bool = False) -> ReconciliationResult:
        """Query broker state, compare against local PositionLedger, and enforce safe-state gate.

        Args:
            raise_on_mismatch: If True, raises StartupReconciliationMismatchError on mismatch.

        Returns:
            ReconciliationResult: Audit summary of reconciliation.

        Raises:
            StartupReconciliationMismatchError: If discrepancies exist and flag is True.
        """
        now_utc = datetime.now(UTC)
        self._log.info("Starting startup position and order reconciliation...")

        # 1. Fetch broker open positions
        try:
            broker_positions: list[Position] = self.broker.get_positions()
        except Exception as exc:
            self._log.error("Failed to query positions from broker", error=str(exc))
            discrepancy = PositionDiscrepancy(
                discrepancy_type="QUANTITY_MISMATCH",
                instrument="ALL",
                broker_quantity=0,
                ledger_quantity=0,
                details=f"Broker position query failed: {exc}",
                severity="CRITICAL",
            )
            result = ReconciliationResult(
                reconciled=False,
                reconciled_at=now_utc,
                discrepancies=[discrepancy],
            )
            self._reconciled = False
            self._last_result = result
            if self.kill_switch and self.auto_halt_on_mismatch:
                self.kill_switch.activate(
                    source="startup_reconciler",
                    reason="Broker position query failed during startup reconciliation",
                )
            if raise_on_mismatch:
                raise StartupReconciliationMismatchError(
                    "Broker position query failed", result
                ) from exc
            return result

        # 2. Fetch local ledger open positions
        ledger_positions: list[Position] = self.ledger.get_open_positions()

        broker_map: dict[str, int] = {
            p.instrument: p.quantity for p in broker_positions if p.quantity != 0
        }
        ledger_map: dict[str, int] = {
            p.instrument: p.quantity for p in ledger_positions if p.quantity != 0
        }

        discrepancies = self._detect_position_discrepancies(broker_map, ledger_map)

        # 3. Check open working orders if OrderManager provided
        open_orders_count = 0
        if self.order_manager is not None:
            open_orders_count = self.order_manager.active_orders_count

        reconciled = len(discrepancies) == 0
        self._reconciled = reconciled

        result = ReconciliationResult(
            reconciled=reconciled,
            reconciled_at=now_utc,
            discrepancies=discrepancies,
            broker_positions_count=len(broker_map),
            ledger_positions_count=len(ledger_map),
            open_orders_count=open_orders_count,
        )
        self._last_result = result

        if not reconciled:
            self._log.error(
                "Startup reconciliation failed! Positions mismatch detected.",
                discrepancies_count=len(discrepancies),
                discrepancies=[d.model_dump() for d in discrepancies],
            )
            if self.kill_switch and self.auto_halt_on_mismatch:
                self.kill_switch.activate(
                    source="startup_reconciler",
                    reason=(f"Startup reconciliation mismatch: {len(discrepancies)} discrepancies"),
                )
            if raise_on_mismatch:
                msg = f"Startup state reconciliation failed with {len(discrepancies)} discrepancies"
                raise StartupReconciliationMismatchError(msg, result)
        else:
            self._log.info(
                "Startup positions and orders reconciled cleanly",
                broker_positions=len(broker_map),
                ledger_positions=len(ledger_map),
                open_orders=open_orders_count,
            )

        return result

    def manual_override(self, operator_token: str, reason: str) -> ReconciliationResult:
        """Allow human operator to override startup mismatch and unlock order dispatch.

        Args:
            operator_token: Operator identifier or signed token string.
            reason: Mandatory documented explanation for the override.

        Returns:
            ReconciliationResult: Updated result with override audit lineage.

        Raises:
            ValueError: If operator_token or reason is blank.
        """
        if not operator_token or len(operator_token.strip()) < 3:
            msg = "Operator token required to authorize manual reconciliation override"
            raise ValueError(msg)
        if not reason or len(reason.strip()) < 5:
            msg = "Detailed rationale required for manual reconciliation override"
            raise ValueError(msg)

        now_utc = datetime.now(UTC)
        self._reconciled = True

        prior_disc = self._last_result.discrepancies if self._last_result else []
        prior_b_count = self._last_result.broker_positions_count if self._last_result else 0
        prior_l_count = self._last_result.ledger_positions_count if self._last_result else 0
        prior_o_count = self._last_result.open_orders_count if self._last_result else 0

        override_result = ReconciliationResult(
            reconciled=True,
            reconciled_at=now_utc,
            discrepancies=prior_disc,
            broker_positions_count=prior_b_count,
            ledger_positions_count=prior_l_count,
            open_orders_count=prior_o_count,
            override_applied=True,
            override_operator_id=operator_token,
            override_reason=reason,
        )
        self._last_result = override_result

        self._log.warning(
            "MANUAL RECONCILIATION OVERRIDE APPLIED: Trading unlocked by operator",
            operator=operator_token,
            reason=reason,
            unresolved_discrepancies=len(prior_disc),
        )
        return override_result
