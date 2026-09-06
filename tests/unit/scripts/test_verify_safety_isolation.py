"""Unit tests for scripts/verify_safety_isolation.py static AST linter."""

from pathlib import Path

import pytest

from scripts.verify_safety_isolation import (
    check_file_imports,
    check_risk_engine_signature,
    check_supervisor_precedence_and_signature,
    main,
    verify_safety_isolation,
)


@pytest.fixture
def repo_root() -> Path:
    """Return repository root path."""
    return Path(__file__).resolve().parent.parent.parent.parent


def test_positive_repo_verification(repo_root: Path) -> None:
    """Verify that the active production codebase passes all safety isolation checks."""
    violations = verify_safety_isolation(repo_root)
    assert violations == [], f"Expected zero violations, got: {violations}"


def test_negative_forbidden_import_detected(tmp_path: Path) -> None:
    """Verify that importing forbidden ML or Agent libraries is detected."""
    # 1. Direct import
    bad_file = tmp_path / "bad_risk.py"
    bad_file.write_text("import torch\nimport numpy as np\n", encoding="utf-8")
    violations = check_file_imports(bad_file)
    assert len(violations) == 1
    assert "Forbidden import 'torch'" in violations[0]

    # 2. From-import of agents
    bad_agent_file = tmp_path / "bad_decision.py"
    bad_agent_file.write_text("from src.agents.trend import TrendAgent\n", encoding="utf-8")
    violations2 = check_file_imports(bad_agent_file)
    assert len(violations2) == 1
    assert "Forbidden from-import 'src.agents.trend'" in violations2[0]

    # 3. LLM client library
    bad_llm_file = tmp_path / "bad_llm.py"
    bad_llm_file.write_text("from openai import OpenAI\n", encoding="utf-8")
    violations3 = check_file_imports(bad_llm_file)
    assert len(violations3) == 1
    assert "Forbidden from-import 'openai'" in violations3[0]


def test_negative_supervisor_reordered_first_statement(tmp_path: Path) -> None:
    """Verify that placing any other statement before kill-switch check triggers violation."""
    bad_supervisor = tmp_path / "supervisor.py"
    bad_supervisor.write_text(
        """
class Supervisor:
    def decide(self, candidate, capital, streak, market, has_open_position):
        # Oops, checking candidate BEFORE kill switch!
        if candidate is None:
            return "NO_TRADE"
        if self._kill_switch.is_active():
            return "HOLD"
        return "BUY"
""",
        encoding="utf-8",
    )
    violations = check_supervisor_precedence_and_signature(bad_supervisor)
    assert len(violations) == 1
    assert "Supervisor.decide() first statement must check kill switch" in violations[0]


def test_negative_supervisor_bypass_parameter(tmp_path: Path) -> None:
    """Verify that adding an override/force parameter to Supervisor.decide() triggers violation."""
    bad_supervisor = tmp_path / "supervisor.py"
    bad_supervisor.write_text(
        """
class Supervisor:
    def decide(self, candidate, capital, streak, market, has_open_position, override=False):
        if self._kill_switch.is_active():
            return "HOLD"
        return "BUY"
""",
        encoding="utf-8",
    )
    violations = check_supervisor_precedence_and_signature(bad_supervisor)
    assert any("Forbidden bypass parameter 'override'" in v for v in violations)


def test_negative_risk_engine_bypass_parameter(tmp_path: Path) -> None:
    """Verify that adding an override/force parameter to evaluate() triggers violation."""
    bad_engine = tmp_path / "engine.py"
    bad_engine.write_text(
        """
class RiskEngine:
    def evaluate(self, candidate, capital, streak, market, force_approve=False):
        return None
""",
        encoding="utf-8",
    )
    violations = check_risk_engine_signature(bad_engine)
    assert any("Forbidden bypass parameter 'force_approve'" in v for v in violations)


def test_missing_files_handling(tmp_path: Path) -> None:
    """Verify graceful handling when target files do not exist."""
    missing = tmp_path / "non_existent.py"
    v1 = check_supervisor_precedence_and_signature(missing)
    assert any("not found" in v for v in v1)

    v2 = check_risk_engine_signature(missing)
    assert any("not found" in v for v in v2)


def test_parse_error_handling(tmp_path: Path) -> None:
    """Verify graceful handling when encountering a syntax error file."""
    bad_syntax = tmp_path / "bad_syntax.py"
    bad_syntax.write_text("def def def invalid syntax ::::", encoding="utf-8")
    violations = check_file_imports(bad_syntax)
    assert any("Failed to parse" in v for v in violations)


def test_main_cli_entrypoint() -> None:
    """Verify main() CLI returns 0 on valid codebase."""
    exit_code = main()
    assert exit_code == 0
