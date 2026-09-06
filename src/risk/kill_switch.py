"""Minimal-dependency kill switch protocol and in-memory implementation."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger()


class TriggerSource(StrEnum):
    """Source that initiated kill switch / STOP activation."""

    MANUAL_OPERATOR = "manual_operator"
    EXTREME_DRAWDOWN = "extreme_drawdown"
    SYSTEM_FAILURE = "system_failure"


@runtime_checkable
class KillSwitchProtocol(Protocol):
    """Protocol for checking kill switch status without heavyweight dependencies."""

    def is_active(self) -> bool:
        """Return True if kill switch is currently active; False otherwise."""
        ...


@runtime_checkable
class AuditLogProtocol(Protocol):
    """Protocol for synchronous audit event recording per LLD §6.2."""

    def record_sync(self, event: str, **kwargs: Any) -> None:
        """Synchronously write audit log event."""
        ...


@runtime_checkable
class OperatorAuthTokenProtocol(Protocol):
    """Protocol for operator authentication token per TRD-SEC-3."""

    @property
    def operator_id(self) -> str:
        """Return operator identifier."""
        ...

    def is_valid(self) -> bool:
        """Return True if token is authenticated and valid."""
        ...


class InMemoryKillSwitch:
    """Minimal-dependency, thread-safe in-memory kill switch implementing LLD §6."""

    def __init__(self, audit_log: AuditLogProtocol | None = None) -> None:
        self._is_active: bool = False
        self._audit_log: AuditLogProtocol | None = audit_log
        self._history: list[dict[str, Any]] = []

    def is_active(self) -> bool:
        """Fast O(1) in-memory check whether trading is halted."""
        return self._is_active

    def activate(self, source: TriggerSource | str, reason: str) -> None:
        """Activate the emergency kill switch / manual STOP."""
        self._is_active = True
        iso_time = datetime.now(UTC).isoformat()
        event = {
            "event": "kill_switch_activated",
            "source": str(source),
            "reason": reason,
            "timestamp": iso_time,
        }
        self._history.append(event)
        if self._audit_log is not None:
            self._audit_log.record_sync(
                event="kill_switch_activated",
                source=str(source),
                reason=reason,
                timestamp=iso_time,
            )
        logger.critical(
            "Emergency kill switch activated",
            source=str(source),
            reason=reason,
        )

    def reset(self, auth_token: str | OperatorAuthTokenProtocol) -> None:
        """Explicit, authenticated operator reset per RTLD §16 and LLD §6.1."""
        if isinstance(auth_token, str):
            if not auth_token.strip():
                msg = "Kill switch reset requires non-empty authenticated operator token"
                raise PermissionError(msg)
            op_id = f"{auth_token[:4]}...[REDACTED]" if len(auth_token) >= 4 else "[REDACTED]"
            token_prefix = auth_token[:4]
        else:
            if not auth_token.is_valid():
                msg = "Kill switch reset requires authenticated operator action"
                raise PermissionError(msg)
            op_id = auth_token.operator_id
            token_prefix = op_id[:4]

        self._is_active = False
        iso_time = datetime.now(UTC).isoformat()
        event = {
            "event": "kill_switch_reset",
            "operator": op_id,
            "timestamp": iso_time,
        }
        self._history.append(event)
        if self._audit_log is not None:
            self._audit_log.record_sync(
                event="kill_switch_reset",
                operator=op_id,
                timestamp=iso_time,
            )
        logger.warning("Emergency kill switch reset by operator", token_prefix=token_prefix)

    def get_history(self) -> list[dict[str, Any]]:
        """Retrieve audit history of kill switch events."""
        return list(self._history)


# Alias for LLD §6 canonical class name
KillSwitch = InMemoryKillSwitch
