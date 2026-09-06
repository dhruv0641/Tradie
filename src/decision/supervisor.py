"""Authoritative Supervisor Decision Gate enforcing precedence and non-bypassable risk gates."""

from typing import Literal

import structlog

from src.domain.decision import Decision, DecisionRecord
from src.domain.risk import (
    CandidateTrade,
    CapitalState,
    MarketState,
    RiskCheckResult,
    StreakState,
)
from src.risk.engine import RiskEngineProtocol
from src.risk.kill_switch import KillSwitchProtocol

logger = structlog.get_logger()


class Supervisor:
    """Authoritative decision gate forming the single gateway for all trading actions.

    Adheres strictly to LLD §7, FRD Module 7 (FRD-SUP-1-6), BRD BR-4, and RTLD §16.
    Zero override pathways exist by construction: no parameter on decide() can grant one.
    """

    def __init__(
        self,
        risk_engine: RiskEngineProtocol,
        kill_switch: KillSwitchProtocol,
    ) -> None:
        self._risk_engine = risk_engine
        self._kill_switch = kill_switch

    @property
    def risk_engine(self) -> RiskEngineProtocol:
        """Return attached RiskEngine protocol instance."""
        return self._risk_engine

    @property
    def kill_switch(self) -> KillSwitchProtocol:
        """Return attached KillSwitch protocol instance."""
        return self._kill_switch

    def decide(
        self,
        candidate: CandidateTrade | None,
        capital: CapitalState,
        streak: StreakState,
        market: MarketState,
        has_open_position: bool,
    ) -> Decision:
        """Evaluate candidate opportunity through strict deterministic precedence hierarchy.

        Precedence rules (LLD §7, FRD-X-5, HLD §8):
        1. Kill Switch state checked FIRST: forces HOLD (if position open) or NO_TRADE.
        2. Candidate availability: if None (upstream rejected), emit NO_TRADE.
        3. Risk Engine evaluation: if Risk Engine rejects, emit NO_TRADE.
           Supervisor CANNOT override Risk Engine blocks (FRD-SUP-6).
        4. Approved trade: emit BUY or SELL with risk-approved quantity and parameters.
        """
        # 1. First statement: Kill switch state checked structurally first (HLD §8, FRD-X-5)
        if self._kill_switch.is_active():
            outcome: Literal["BUY", "SELL", "HOLD", "NO_TRADE"] = (
                "HOLD" if has_open_position else "NO_TRADE"
            )
            logger.warning(
                "Decision gate intercepted by active kill switch",
                outcome=outcome,
                has_open_position=has_open_position,
            )
            return Decision(
                outcome=outcome,
                reason="kill switch/STOP active",
                risk_check=RiskCheckResult(
                    passed=False,
                    failed_check="kill_switch",
                    rtld_param_id="RTLD-01",
                    reason="kill switch/STOP is active",
                    config_version=self._risk_engine.config.version,
                    approved_quantity=0,
                ),
                kill_switch_active=True,
                approved_quantity=0,
            )

        # 2. Second check: Candidate availability from upstream Aggregator/Agents
        if candidate is None:
            logger.info("No candidate trade provided to Supervisor, emitting NO_TRADE")
            return Decision(
                outcome="NO_TRADE",
                reason="no candidate cleared confidence/EV gates upstream",
                risk_check=RiskCheckResult(
                    passed=False,
                    failed_check="no_candidate",
                    rtld_param_id=None,
                    reason="no candidate trade proposed",
                    config_version=self._risk_engine.config.version,
                    approved_quantity=0,
                ),
                kill_switch_active=False,
                approved_quantity=0,
            )

        # 3. Third check: Consult Risk Engine (no override path exists by construction)
        risk_result = self._risk_engine.evaluate(candidate, capital, streak, market)
        if not risk_result.passed:
            fail_reason = (
                f"risk check failed: {risk_result.failed_check}"
                if risk_result.failed_check
                else "risk check failed"
            )
            logger.info(
                "Risk Engine rejected candidate trade",
                instrument=candidate.instrument,
                direction=candidate.direction,
                failed_check=risk_result.failed_check,
                rtld_param_id=risk_result.rtld_param_id,
            )
            return Decision(
                outcome="NO_TRADE",
                reason=fail_reason,
                risk_check=risk_result,
                kill_switch_active=False,
                approved_quantity=0,
            )

        # 4. Fourth check: Cleared all gates -> Actionable BUY or SELL
        logger.info(
            "Candidate trade cleared all gates",
            instrument=candidate.instrument,
            direction=candidate.direction,
            approved_quantity=risk_result.approved_quantity,
        )
        return Decision(
            outcome=candidate.direction,
            reason="cleared all gates",
            risk_check=risk_result,
            kill_switch_active=False,
            approved_quantity=risk_result.approved_quantity,
            stop_loss_price=candidate.stop_price,
            target_price=getattr(candidate, "target_price", None),
        )

    def build_decision_record(
        self,
        decision: Decision,
        instrument: str,
        *,
        regime: str,
        agent_scores: dict[str, float] | None = None,
        aggregated_score: float = 0.0,
        git_commit: str = "unknown",
    ) -> DecisionRecord:
        """Create a strongly-typed DecisionRecord with canonical SHA-256 hash stamp."""
        record = DecisionRecord(
            timestamp=decision.timestamp,
            instrument=instrument,
            decision=decision.outcome,
            regime=regime,
            agent_scores=agent_scores or {},
            aggregated_score=aggregated_score,
            risk_result=decision.risk_check.model_dump(),
            approved_quantity=decision.approved_quantity,
            stop_loss_price=decision.stop_loss_price,
            target_price=decision.target_price,
            config_version=decision.risk_check.config_version,
            git_commit=git_commit,
        )
        h = record.calculate_canonical_hash()
        return record.model_copy(update={"decision_hash": h})
