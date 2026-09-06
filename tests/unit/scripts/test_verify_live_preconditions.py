"""Unit tests for SOW §9 Preconditions Audit Verifier Script."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.verify_live_preconditions import LivePreconditionsVerifier, main


@pytest.fixture
def mock_repo_root(tmp_path: Path) -> Path:
    """Create a temporary directory structure mimicking repo compliance artifacts."""
    compliance_dir = tmp_path / "docs" / "compliance"
    compliance_dir.mkdir(parents=True)

    # 1. Valid SEBI review doc
    sebi_doc = compliance_dir / "SEBI_REVIEW.md"
    sebi_doc.write_text("# SEBI Review\nStatus: APPROVED & COMPLIANT\n", encoding="utf-8")

    # 2. Valid Gate sign-offs doc
    gates_doc = compliance_dir / "GATE_SIGNOFFS.md"
    gates_content = (
        "# Gate Signoffs\nPhase V0: PASSED\nPhase V1: PASSED\n"
        "Phase V2: PASSED\nPhase V3: PASSED\nPhase V4: PASSED\n"
    )
    gates_doc.write_text(gates_content, encoding="utf-8")

    # 3. Valid operator approval token
    token_file = compliance_dir / "operator_approval.token"
    token_file.write_text("APPROVED_BY_OPERATOR_TEST_20260906", encoding="utf-8")

    # 4. Safety test file
    safety_dir = tmp_path / "tests" / "safety"
    safety_dir.mkdir(parents=True)
    test_file = safety_dir / "test_kill_switch.py"
    test_file.write_text("# KS-TEST safety suite marker\n", encoding="utf-8")

    return tmp_path


def test_verify_all_passes_when_all_preconditions_met(mock_repo_root: Path) -> None:
    """Verify that all 5 preconditions pass cleanly with valid artifacts and env."""
    verifier = LivePreconditionsVerifier(base_dir=mock_repo_root)

    with patch.dict("os.environ", {"BROKER_API_KEY": "key123", "BROKER_API_SECRET": "sec123"}):
        all_passed, results = verifier.verify_all()
        assert all_passed is True
        assert len(results) == 5
        assert all(r.passed for r in results)


def test_missing_sebi_compliance_fails(mock_repo_root: Path) -> None:
    """Verify failure when SEBI compliance document is missing."""
    sebi_doc = mock_repo_root / "docs" / "compliance" / "SEBI_REVIEW.md"
    sebi_doc.unlink()

    verifier = LivePreconditionsVerifier(base_dir=mock_repo_root)
    with patch.dict("os.environ", {"BROKER_API_KEY": "key123", "BROKER_API_SECRET": "sec123"}):
        res = verifier.check_regulatory_compliance()
        assert res.passed is False
        assert "Missing SEBI compliance review document" in res.details


def test_unapproved_sebi_compliance_fails(mock_repo_root: Path) -> None:
    """Verify failure when SEBI document exists but lacks APPROVED status."""
    sebi_doc = mock_repo_root / "docs" / "compliance" / "SEBI_REVIEW.md"
    sebi_doc.write_text("# SEBI Review\nStatus: PENDING REVIEW\n", encoding="utf-8")

    verifier = LivePreconditionsVerifier(base_dir=mock_repo_root)
    res = verifier.check_regulatory_compliance()
    assert res.passed is False
    assert "lacks formal 'APPROVED' or 'COMPLIANT'" in res.details


def test_missing_broker_credentials_fails(mock_repo_root: Path) -> None:
    """Verify failure when broker credentials are not set in environment or .env."""
    verifier = LivePreconditionsVerifier(base_dir=mock_repo_root)
    with patch.dict("os.environ", {}, clear=True):
        res = verifier.check_broker_credentials()
        assert res.passed is False
        assert "BROKER_API_KEY and BROKER_API_SECRET must be set" in res.details


def test_missing_gate_signoffs_fails(mock_repo_root: Path) -> None:
    """Verify failure when exit gate sign-offs are missing."""
    gates_doc = mock_repo_root / "docs" / "compliance" / "GATE_SIGNOFFS.md"
    gates_doc.write_text("Phase V0: PASSED\nPhase V1: PASSED\n", encoding="utf-8")

    verifier = LivePreconditionsVerifier(base_dir=mock_repo_root)
    res = verifier.check_exit_gates()
    assert res.passed is False
    assert "missing sign-offs for: Phase V2, Phase V3, Phase V4" in res.details


def test_missing_operator_approval_token_fails(mock_repo_root: Path) -> None:
    """Verify failure when operator approval token is missing."""
    token_file = mock_repo_root / "docs" / "compliance" / "operator_approval.token"
    token_file.unlink()

    verifier = LivePreconditionsVerifier(base_dir=mock_repo_root)
    with patch.dict("os.environ", {}, clear=True):
        res = verifier.check_operator_approval()
        assert res.passed is False
        assert "Missing operator approval token" in res.details


def test_cli_json_output(mock_repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli_args = ["verify_live_preconditions.py", "--json", "--base-dir", str(mock_repo_root)]
    with (
        patch.dict("os.environ", {"BROKER_API_KEY": "k", "BROKER_API_SECRET": "s"}),
        patch("sys.argv", cli_args),
    ):
        exit_code = main()
        assert exit_code == 0
        captured = capsys.readouterr()
        json_start = captured.out.find("{")
        json_end = captured.out.rfind("}") + 1
        payload = json.loads(captured.out[json_start:json_end])
        assert payload["all_preconditions_satisfied"] is True
        assert len(payload["checks"]) == 5
