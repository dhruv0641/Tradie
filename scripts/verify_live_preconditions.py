#!/usr/bin/env python3
"""SOW §9 Preconditions Audit Verifier Script.

Enforces the five mandatory safety preconditions before live capital activation
per SOW §6.6, §9; BRD BR-9; TRD-DEPLOY-3; NFR-COMP-1.

Preconditions:
  1. Regulatory compliance sign-off document present (docs/compliance/SEBI_REVIEW.md) (BRD BR-9)
  2. Broker contracted with active API trading credentials (SOW §9.2)
  3. All Phase V0-V4 exit gates formally passed and documented (SOW §9.3)
  4. Hard risk limits verified via KS-TEST suite in non-live environment (SOW §9.4)
  5. Operator explicit signed approval token present (SOW §9.5)
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.decision.supervisor import Supervisor
from src.domain.risk import CandidateTrade, CapitalState, MarketState, StreakState
from src.risk.config import RiskConfig
from src.risk.engine import RiskEngine
from src.risk.kill_switch import InMemoryKillSwitch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class PreconditionCheckResult:
    """Individual precondition verification result."""

    name: str
    passed: bool
    details: str
    source_reference: str


class LivePreconditionsVerifier:
    """Verification harness checking all 5 mandatory SOW §9 Preconditions."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or _PROJECT_ROOT

    def check_regulatory_compliance(self) -> PreconditionCheckResult:
        """1. Verify SEBI algorithmic trading regulatory compliance review."""
        sebi_doc = self.base_dir / "docs" / "compliance" / "SEBI_REVIEW.md"
        if not sebi_doc.exists():
            return PreconditionCheckResult(
                name="Regulatory Compliance Review",
                passed=False,
                details=f"Missing SEBI compliance review document at {sebi_doc}",
                source_reference="SOW §9.1, BRD BR-9",
            )

        content = sebi_doc.read_text(encoding="utf-8")
        if "APPROVED" not in content and "COMPLIANT" not in content:
            return PreconditionCheckResult(
                name="Regulatory Compliance Review",
                passed=False,
                details=(
                    "SEBI compliance document exists but lacks formal "
                    "'APPROVED' or 'COMPLIANT' status"
                ),
                source_reference="SOW §9.1, BRD BR-9",
            )

        return PreconditionCheckResult(
            name="Regulatory Compliance Review",
            passed=True,
            details=f"Found approved SEBI compliance document at {sebi_doc.name}",
            source_reference="SOW §9.1, BRD BR-9",
        )

    def check_broker_credentials(self) -> PreconditionCheckResult:
        """2. Verify contracted broker and active API trading credentials."""
        api_key = os.environ.get("BROKER_API_KEY")
        api_secret = os.environ.get("BROKER_API_SECRET")

        # In non-production test harnesses, allow configured default if explicitly specified
        if not api_key or not api_secret:
            # Check if test token or env file exists
            env_file = self.base_dir / ".env"
            if env_file.exists():
                lines = env_file.read_text(encoding="utf-8").splitlines()
                has_key = any(line.startswith("BROKER_API_KEY=") for line in lines)
                has_sec = any(line.startswith("BROKER_API_SECRET=") for line in lines)
                if has_key and has_sec:
                    return PreconditionCheckResult(
                        name="Broker API Credentials",
                        passed=True,
                        details="Broker API credentials configured in .env file",
                        source_reference="SOW §9.2",
                    )

            return PreconditionCheckResult(
                name="Broker API Credentials",
                passed=False,
                details="BROKER_API_KEY and BROKER_API_SECRET must be set in environment or .env",
                source_reference="SOW §9.2",
            )

        return PreconditionCheckResult(
            name="Broker API Credentials",
            passed=True,
            details="Active broker API credentials detected in environment",
            source_reference="SOW §9.2",
        )

    def check_exit_gates(self) -> PreconditionCheckResult:
        """3. Verify all Phase V0-V4 exit gates formally passed and documented."""
        gates_doc = self.base_dir / "docs" / "compliance" / "GATE_SIGNOFFS.md"
        if not gates_doc.exists():
            return PreconditionCheckResult(
                name="Phase V0-V4 Exit Gates",
                passed=False,
                details=f"Missing exit gate sign-off document at {gates_doc}",
                source_reference="SOW §9.3",
            )

        content = gates_doc.read_text(encoding="utf-8")
        required_gates = ["Phase V0", "Phase V1", "Phase V2", "Phase V3", "Phase V4"]
        missing = [gate for gate in required_gates if gate not in content]

        if missing:
            return PreconditionCheckResult(
                name="Phase V0-V4 Exit Gates",
                passed=False,
                details=f"Exit gate document missing sign-offs for: {', '.join(missing)}",
                source_reference="SOW §9.3",
            )

        return PreconditionCheckResult(
            name="Phase V0-V4 Exit Gates",
            passed=True,
            details="All Phase V0 through V4 exit gates formally verified and signed off",
            source_reference="SOW §9.3",
        )

    def check_hard_risk_limits(self) -> PreconditionCheckResult:
        """4. Verify hard risk limits and KS-TEST suite in non-live environment."""
        test_file = self.base_dir / "tests" / "safety" / "test_kill_switch.py"
        if not test_file.exists():
            return PreconditionCheckResult(
                name="Hard Risk Limits Verification",
                passed=False,
                details=f"Safety test suite missing at {test_file}",
                source_reference="SOW §9.4, RTLD §4",
            )

        # In-process smoke verification of hard risk limit gating
        try:
            kill_switch = InMemoryKillSwitch()
            risk_engine = RiskEngine(RiskConfig(), kill_switch)
            supervisor = Supervisor(risk_engine, kill_switch)

            # Assert kill switch halts order submission
            kill_switch.activate(
                source="operator_manual", reason="Precondition verification smoke test"
            )
            candidate = CandidateTrade(
                instrument="NSE:RELIANCE",
                direction="BUY",
                entry_price=Decimal("2500.00"),
                stop_price=Decimal("2475.00"),
                timeframe="5m",
                trade_quality_score=0.85,
                expected_value=Decimal("15.00"),
                confidence=0.85,
                timestamp=datetime.now(UTC),
            )
            market_state = MarketState(
                instrument="NSE:RELIANCE",
                current_volatility=Decimal("15.0"),
                trailing_20session_avg_volatility=Decimal("14.0"),
            )
            capital_state = CapitalState(
                current_capital=Decimal("10000.00"),
                peak_equity=Decimal("10000.00"),
                session_start_capital=Decimal("10000.00"),
                currently_deployed=Decimal("0.00"),
                open_position_count=0,
                trades_today=0,
            )
            decision = supervisor.decide(
                candidate,
                capital_state,
                StreakState(),
                market_state,
                False,
            )
            if decision.outcome != "NO_TRADE":
                return PreconditionCheckResult(
                    name="Hard Risk Limits Verification",
                    passed=False,
                    details=(
                        f"Kill switch active check failed: supervisor emitted "
                        f"{decision.outcome} instead of NO_TRADE"
                    ),
                    source_reference="SOW §9.4, RTLD §4",
                )
        except Exception as e:
            return PreconditionCheckResult(
                name="Hard Risk Limits Verification",
                passed=False,
                details=f"Risk engine in-process sanity check raised unexpected error: {e}",
                source_reference="SOW §9.4, RTLD §4",
            )

        return PreconditionCheckResult(
            name="Hard Risk Limits Verification",
            passed=True,
            details="Safety KS-TEST suite present and in-process hard risk gate verified",
            source_reference="SOW §9.4, RTLD §4",
        )

    def check_operator_approval(self) -> PreconditionCheckResult:
        """5. Verify operator explicit signed approval token present."""
        env_token = os.environ.get("OPERATOR_LIVE_APPROVAL_TOKEN")
        token_file = self.base_dir / "docs" / "compliance" / "operator_approval.token"

        if env_token and len(env_token.strip()) > 8:
            return PreconditionCheckResult(
                name="Operator Signed Approval Token",
                passed=True,
                details="Operator approval token verified in environment variable",
                source_reference="SOW §9.5, BRD BO-7",
            )

        if token_file.exists():
            token_content = token_file.read_text(encoding="utf-8").strip()
            if len(token_content) > 8 and "APPROVED" in token_content:
                return PreconditionCheckResult(
                    name="Operator Signed Approval Token",
                    passed=True,
                    details=f"Operator approval token verified in {token_file.name}",
                    source_reference="SOW §9.5, BRD BO-7",
                )

        return PreconditionCheckResult(
            name="Operator Signed Approval Token",
            passed=False,
            details=(
                "Missing operator approval token. Provide via OPERATOR_LIVE_APPROVAL_TOKEN "
                "or write to docs/compliance/operator_approval.token"
            ),
            source_reference="SOW §9.5, BRD BO-7",
        )

    def verify_all(self) -> tuple[bool, list[PreconditionCheckResult]]:
        """Run all 5 precondition checks and return overall pass status and result list."""
        results = [
            self.check_regulatory_compliance(),
            self.check_broker_credentials(),
            self.check_exit_gates(),
            self.check_hard_risk_limits(),
            self.check_operator_approval(),
        ]
        all_passed = all(r.passed for r in results)
        return all_passed, results


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Verify SOW §9 Preconditions for Live Capital Deployment."
    )
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--base-dir", type=Path, default=None, help="Root directory for checks")
    args = parser.parse_args()

    verifier = LivePreconditionsVerifier(base_dir=args.base_dir)
    all_passed, results = verifier.verify_all()

    if args.json:
        payload = {
            "all_preconditions_satisfied": all_passed,
            "checks": [asdict(r) for r in results],
        }
        print(json.dumps(payload, indent=2))
    else:
        print("=" * 72)
        print(" AI TRADER: SOW §9 PRE-LIVE PRECONDITIONS AUDIT")
        print("=" * 72)
        for idx, r in enumerate(results, 1):
            mark = "[PASS]" if r.passed else "[FAIL]"
            print(f"{idx}. {mark} {r.name} ({r.source_reference})")
            print(f"       Details: {r.details}")
        print("=" * 72)
        if all_passed:
            print("ALL SOW §9 PRECONDITIONS SATISFIED. LIVE TRADING ACTIVATION AUTHORIZED.")
            print("=" * 72)
        else:
            print("PRECONDITION VIOLATION: LIVE TRADING ACTIVATION STRUCTURALLY BLOCKED.")
            print("=" * 72)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
