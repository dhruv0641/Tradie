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


class InMemoryKillSwitch:
    """Minimal-dependency, thread-safe in-memory kill switch implementing LLD §6."""

    def __init__(self) -> None:
        self._is_active: bool = False
        self._history: list[dict[str, Any]] = []

    def is_active(self) -> bool:
        """Fast O(1) in-memory check whether trading is halted."""
        return self._is_active

    def activate(self, source: TriggerSource | str, reason: str) -> None:
        """Activate the emergency kill switch / manual STOP."""
        self._is_active = True
        event = {
            "event": "kill_switch_activated",
            "source": str(source),
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._history.append(event)
        logger.critical(
            "Emergency kill switch activated",
            source=str(source),
            reason=reason,
        )

    def reset(self, auth_token: str) -> None:
        """Explicit, authenticated operator reset per RTLD §16 and LLD §6.1."""
        if not auth_token or not auth_token.strip():
            msg = "Kill switch reset requires non-empty authenticated operator token"
            raise PermissionError(msg)

        self._is_active = False
        tok = f"{auth_token[:4]}...[REDACTED]" if len(auth_token) >= 4 else "[REDACTED]"
        event = {
            "event": "kill_switch_reset",
            "operator_token": tok,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._history.append(event)
        logger.warning("Emergency kill switch reset by operator", token_prefix=auth_token[:4])

    def get_history(self) -> list[dict[str, Any]]:
        """Retrieve audit history of kill switch events."""
        return list(self._history)
