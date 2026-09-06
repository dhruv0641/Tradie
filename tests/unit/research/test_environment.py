"""Unit tests for Research Brain execution environment and boundary guards."""

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.research.environment import (
    ResearchBrainConfig,
    ResearchBrainEnvironment,
    ResearchIsolationError,
    check_research_ast_isolation,
)


def test_research_environment_defaults() -> None:
    """Verify default ResearchBrainEnvironment invariants and properties."""
    env = ResearchBrainEnvironment()

    assert env.is_sandboxed is True
    assert env.is_read_only is True
    assert env.can_place_orders() is False
    assert env.can_mutate_positions() is False
    assert env.config.database_role == "readonly"
    assert env.verify_boundary_guards() == []


def test_research_environment_custom_config() -> None:
    """Verify ResearchBrainEnvironment accepts custom configuration."""
    cfg = ResearchBrainConfig(
        is_sandboxed=True,
        read_only_mode=True,
        database_role="custom_readonly",
    )
    env = ResearchBrainEnvironment(config=cfg)

    assert env.config == cfg
    assert env.config.database_role == "custom_readonly"


def test_attempt_order_placement_raises_isolation_error() -> None:
    """Verify attempt_order_placement raises ResearchIsolationError."""
    env = ResearchBrainEnvironment()

    with pytest.raises(ResearchIsolationError) as exc_info:
        env.attempt_order_placement(symbol="RELIANCE", quantity=10)

    assert "zero execution authority and cannot place orders" in str(exc_info.value)


def test_attempt_position_mutation_raises_isolation_error() -> None:
    """Verify attempt_position_mutation raises ResearchIsolationError."""
    env = ResearchBrainEnvironment()

    with pytest.raises(ResearchIsolationError) as exc_info:
        env.attempt_position_mutation(symbol="INFY", delta=5)

    assert "read-only access and cannot mutate positions" in str(exc_info.value)


def test_scrub_prohibited_credentials() -> None:
    """Verify ResearchBrainEnvironment scrubs prohibited credentials from os.environ."""
    os.environ["BROKER_API_KEY"] = "secret_to_scrub"
    os.environ["BROKER_API_SECRET"] = "secret_to_scrub"

    try:
        env = ResearchBrainEnvironment(scrub_credentials=True)
        assert "BROKER_API_KEY" not in os.environ
        assert "BROKER_API_SECRET" not in os.environ
        assert env.verify_boundary_guards() == []
    finally:
        os.environ.pop("BROKER_API_KEY", None)
        os.environ.pop("BROKER_API_SECRET", None)


def test_verify_boundary_guards_detects_credential_leak() -> None:
    """Verify verify_boundary_guards detects live credentials if scrubbing disabled."""
    os.environ["BROKER_ACCESS_TOKEN"] = "leaked_token"
    try:
        env = ResearchBrainEnvironment(scrub_credentials=False)
        violations = env.verify_boundary_guards()
        assert len(violations) >= 1
        assert any("BROKER_ACCESS_TOKEN" in v for v in violations)
    finally:
        os.environ.pop("BROKER_ACCESS_TOKEN", None)


def test_verify_boundary_guards_detects_unsandboxed_mode() -> None:
    """Verify detection of non-sandboxed or non-read-only configuration."""
    cfg = ResearchBrainConfig(is_sandboxed=False, read_only_mode=False)
    env = ResearchBrainEnvironment(config=cfg)

    violations = env.verify_boundary_guards()
    assert len(violations) == 2
    assert any("not running in sandboxed mode" in v for v in violations)
    assert any("not in read-only mode" in v for v in violations)


def test_query_historical_candles_read_only() -> None:
    """Verify query_historical_candles delegates to read-only data source."""
    env = ResearchBrainEnvironment()
    mock_source = MagicMock()
    mock_source.get_candles.return_value = [{"bar": 1}, {"bar": 2}]

    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    res = env.query_historical_candles("TCS", start, end, data_source=mock_source)

    assert len(res) == 2
    mock_source.get_candles.assert_called_once_with("TCS", start, end)

    # Empty data source fallback
    assert env.query_historical_candles("TCS", start, end, data_source=None) == []


def test_query_historical_decisions_read_only() -> None:
    """Verify query_historical_decisions delegates to audit service."""
    env = ResearchBrainEnvironment()
    mock_audit = MagicMock()
    mock_audit.get_recent_decisions.return_value = [{"decision": "BUY"}]

    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    res = env.query_historical_decisions(start, end, audit_service=mock_audit)

    assert len(res) == 1
    mock_audit.get_recent_decisions.assert_called_once_with(limit=500)

    # Empty audit service fallback
    assert env.query_historical_decisions(start, end, audit_service=None) == []


def test_check_research_ast_isolation_clean() -> None:
    """Verify src/research/ directory passes AST import isolation audit cleanly."""
    violations = check_research_ast_isolation()
    assert violations == []


def test_check_research_ast_isolation_detects_forbidden_imports(tmp_path: Path) -> None:
    """Verify AST isolation checker detects forbidden execution imports."""
    bad_file = tmp_path / "bad_research.py"
    bad_file.write_text(
        "import src.execution.live_broker_adapter\n"
        "from src.execution.order_manager import OrderManager\n",
        encoding="utf-8",
    )

    violations = check_research_ast_isolation(tmp_path)
    assert len(violations) == 2
    assert any("live_broker_adapter" in v for v in violations)
    assert any("order_manager" in v for v in violations)


def test_check_research_ast_isolation_handles_parse_error(tmp_path: Path) -> None:
    """Verify AST isolation checker safely handles syntax errors in files."""
    invalid_file = tmp_path / "syntax_error.py"
    invalid_file.write_text("def invalid_syntax(:\n", encoding="utf-8")

    violations = check_research_ast_isolation(tmp_path)
    assert len(violations) == 1
    assert "Failed to parse" in violations[0]
