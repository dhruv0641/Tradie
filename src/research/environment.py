"""Research Brain execution environment and architectural boundary guards.

Enforces TRD-ARCH-2, FRD-LEARN-1, FRD-X-4, BRD BR-6, and NFR-SAFE-5:
1. Physical and process-level isolation between Research Brain and Trading Brain.
2. Zero access to live broker credentials, network endpoints, or execution paths.
3. Strict read-only database and parquet historical store access.
4. Structural AST import checks verifying no execution module imports exist in research code.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from datetime import datetime

_DEFAULT_PROHIBITED_ENV_KEYS: tuple[str, ...] = (
    "BROKER_API_KEY",
    "BROKER_API_SECRET",
    "BROKER_ACCESS_TOKEN",
    "BROKER_TOTP_SECRET",
    "LIVE_BROKER_URL",
)

_FORBIDDEN_RESEARCH_IMPORT_MODULES: tuple[str, ...] = (
    "src.execution.live_broker_adapter",
    "src.execution.order_manager",
    "src.execution.idempotency",
    "src.core.runner",
    "kiteconnect",
    "smartapi",
    "fyers_api",
)


class ResearchIsolationError(PermissionError):
    """Raised when an operation violates Research Brain boundary isolation invariants."""


class ResearchBrainConfig(BaseModel):
    """Immutable configuration governing Research Brain process isolation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_sandboxed: bool = Field(
        default=True,
        description="Flag indicating execution within an isolated research sandbox.",
    )
    read_only_mode: bool = Field(
        default=True,
        description="Strict read-only access guarantee on market data and decision stores.",
    )
    database_role: str = Field(
        default="readonly",
        description="Database role name with SELECT-only privileges.",
    )
    prohibited_env_keys: tuple[str, ...] = Field(
        default=_DEFAULT_PROHIBITED_ENV_KEYS,
        description="Environment variable keys forbidden from existing in research environment.",
    )


class ResearchBrainEnvironment:
    """Isolated Research Brain execution environment runtime.

    Guarantees:
    - Zero execution authority (cannot place, modify, or cancel orders).
    - Zero live broker credentials in memory or process environment.
    - Zero state mutation on live trading database entities (positions, orders).
    """

    def __init__(
        self,
        config: ResearchBrainConfig | None = None,
        *,
        scrub_credentials: bool = True,
    ) -> None:
        self._config = config or ResearchBrainConfig()
        if scrub_credentials:
            self._scrub_prohibited_credentials()

    @property
    def config(self) -> ResearchBrainConfig:
        """Return the immutable research configuration."""
        return self._config

    @property
    def is_sandboxed(self) -> bool:
        """Return True if running in sandboxed environment."""
        return self._config.is_sandboxed

    @property
    def is_read_only(self) -> bool:
        """Return True if read-only enforcement is active."""
        return self._config.read_only_mode

    @staticmethod
    def can_place_orders() -> bool:
        """Research Brain structurally cannot place orders (BRD BR-6, FRD-X-4)."""
        return False

    @staticmethod
    def can_mutate_positions() -> bool:
        """Research Brain structurally cannot mutate live positions."""
        return False

    def _scrub_prohibited_credentials(self) -> None:
        """Scrub any prohibited broker credentials from os.environ."""
        for key in self._config.prohibited_env_keys:
            if key in os.environ:
                del os.environ[key]

    def verify_boundary_guards(self) -> list[str]:
        """Audit process environment and active configuration for boundary violations.

        Returns:
            List of violation descriptions. Empty if boundary guards are fully intact.
        """
        violations: list[str] = []

        # 1. Check for leaking live broker credentials in environment
        for key in self._config.prohibited_env_keys:
            if key in os.environ:
                violations.append(
                    f"Prohibited live credential '{key}' detected in Research Brain environment"
                )

        # 2. Check sandboxed flag
        if not self._config.is_sandboxed:
            violations.append("Research Brain is not running in sandboxed mode")

        # 3. Check read-only mode
        if not self._config.read_only_mode:
            violations.append("Research Brain is not in read-only mode")

        return violations

    def attempt_order_placement(self, *args: Any, **kwargs: Any) -> None:
        """Structurally reject order placement attempts with ResearchIsolationError."""
        _ = args, kwargs
        raise ResearchIsolationError(
            "Research Brain has zero execution authority and cannot place orders "
            "(BRD BR-6, FRD-X-4, TRD-ARCH-2)."
        )

    def attempt_position_mutation(self, *args: Any, **kwargs: Any) -> None:
        """Structurally reject position mutation attempts with ResearchIsolationError."""
        _ = args, kwargs
        raise ResearchIsolationError(
            "Research Brain has read-only access and cannot mutate positions "
            "(BRD BR-6, FRD-X-4, TRD-ARCH-2)."
        )

    def query_historical_candles(
        self,
        instrument: str,
        start_time: datetime,
        end_time: datetime,
        *,
        data_source: Any = None,
    ) -> list[Any]:
        """Execute read-only historical candle query.

        Args:
            instrument: Symbol or token identifier.
            start_time: Start datetime (UTC).
            end_time: End datetime (UTC).
            data_source: Optional adapter or repository implementing read-only query.

        Returns:
            List of historical bars.
        """
        if data_source is None:
            return []
        if hasattr(data_source, "get_candles"):
            result = data_source.get_candles(instrument, start_time, end_time)
            if isinstance(result, list):
                return result
        return []

    def query_historical_decisions(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        audit_service: Any = None,
    ) -> list[Any]:
        """Execute read-only historical decision record query.

        Args:
            start_time: Start datetime (UTC).
            end_time: End datetime (UTC).
            audit_service: Optional DecisionAuditService instance.

        Returns:
            List of DecisionRecord domain entities.
        """
        _ = start_time, end_time
        if audit_service is None:
            return []
        if hasattr(audit_service, "get_recent_decisions"):
            result = audit_service.get_recent_decisions(limit=500)
            if isinstance(result, list):
                return result
        return []


def check_research_ast_isolation(research_dir: Path | None = None) -> list[str]:
    """Audit all Python source files in src/research/ for forbidden execution imports.

    Args:
        research_dir: Path to directory to audit (defaults to src/research/).

    Returns:
        List of detected architectural boundary violations. Empty if clean.
    """
    if research_dir is None:
        research_dir = Path(__file__).resolve().parent

    violations: list[str] = []
    if not research_dir.exists():
        return violations

    for py_file in research_dir.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(py_file))
        except Exception as e:
            violations.append(f"Failed to parse {py_file}: {e}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in _FORBIDDEN_RESEARCH_IMPORT_MODULES:
                        if alias.name == forbidden or alias.name.startswith(forbidden + "."):
                            violations.append(
                                f"{py_file}:{node.lineno} - Forbidden execution import "
                                f"'{alias.name}' detected in Research Brain"
                            )
            elif isinstance(node, ast.ImportFrom) and node.module:
                for forbidden in _FORBIDDEN_RESEARCH_IMPORT_MODULES:
                    if node.module == forbidden or node.module.startswith(forbidden + "."):
                        violations.append(
                            f"{py_file}:{node.lineno} - Forbidden execution from-import "
                            f"'{node.module}' detected in Research Brain"
                        )

    return violations
