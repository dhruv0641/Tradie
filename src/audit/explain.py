"""Decision Explainability and Audit Query Engine.

Provides non-fabricated transparency into 100% of trading decisions, answering the 5 core
operator queries strictly from stored DecisionRecord audit artifacts per FRD-EVAL-4,
FRD-EVAL-6, BRD BR-7, and NFR-AUDIT-2.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.audit.decision_logger import DecisionAuditService
from src.domain.decision import DecisionRecord
from src.infrastructure.database import DatabaseManager
from src.infrastructure.models import DecisionRecordModel


class RecordNotFoundError(LookupError):
    """Raised when an explanation is requested for a decision record that does not exist."""

    pass


class ExplanationReport(BaseModel):
    """Structured, non-fabricated breakdown of a single trading decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_record_id: str
    found: bool = True
    timestamp: datetime | None = None
    instrument: str = ""
    timeframe: str = ""
    environment: str = ""
    final_decision: str = ""
    decision_rationale: str = ""
    regime_classification: dict[str, Any] = Field(default_factory=dict)
    agent_scores: dict[str, float] = Field(default_factory=dict)
    agreed_agents: list[str] = Field(default_factory=list)
    disagreed_agents: list[str] = Field(default_factory=list)
    neutral_agents: list[str] = Field(default_factory=list)
    trade_quality_score: float = 0.0
    expected_value: Decimal = Decimal("0.0000")
    disagreement_metric: float = 0.0
    risk_check_passed: bool = False
    failed_check: str | None = None
    rtld_param_id: str | None = None
    approved_quantity: int = 0
    stop_loss_price: Decimal | None = None
    target_price: Decimal | None = None
    client_order_id: str | None = None
    canonical_hash: str = ""
    inputs_used: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, float] = Field(default_factory=dict)

    def to_text_report(self) -> str:
        """Render a formatted, human-readable terminal/dashboard summary."""
        if not self.found:
            return (
                "======================================================================\n"
                f"  DECISION EXPLAINABILITY REPORT: {self.decision_record_id}\n"
                "======================================================================\n"
                "  [STATUS]: RECORD NOT FOUND\n"
                "  [NON-FABRICATION GUARANTEE (FRD-EVAL-6)]:\n"
                "  The system refuses to synthesize or hypothesize an explanation for a\n"
                "  decision with no verifiable database audit record.\n"
                "======================================================================"
            )

        ts_str = self.timestamp.isoformat() if self.timestamp else "N/A"
        stop_str = f"₹{self.stop_loss_price}" if self.stop_loss_price else "None"
        target_str = f"₹{self.target_price}" if self.target_price else "None"

        lines = [
            "======================================================================",
            f"  DECISION EXPLAINABILITY REPORT: {self.decision_record_id}",
            "======================================================================",
            f"  Instrument:          {self.instrument} ({self.timeframe})",
            f"  Timestamp (UTC):     {ts_str}",
            f"  Environment:         {self.environment}",
            f"  FINAL ACTION:        {self.final_decision}",
            f"  Rationale:           {self.decision_rationale}",
            "----------------------------------------------------------------------",
            "  1. REGIME CONTEXT:",
            f"     Regime:           {self.regime_classification.get('regime', 'UNKNOWN')}",
            "----------------------------------------------------------------------",
            "  2. AGENT SIGNALS & CONSENSUS:",
            f"     Quality Score:    {self.trade_quality_score:.4f}",
            f"     Expected Value:   ₹{self.expected_value}",
            f"     Disagreement:     {self.disagreement_metric:.4f}",
            f"     Agreed Agents:    {', '.join(self.agreed_agents) or 'None'}",
            f"     Opposing Agents:  {', '.join(self.disagreed_agents) or 'None'}",
            f"     Neutral Agents:   {', '.join(self.neutral_agents) or 'None'}",
            f"     Detailed Scores:  {self.agent_scores}",
            "----------------------------------------------------------------------",
            "  3. DETERMINISTIC RISK EVALUATION:",
            f"     Risk Check Passed: {'YES' if self.risk_check_passed else 'NO'}",
            f"     Failed Check:      {self.failed_check or 'None'}",
            f"     RTLD Parameter:    {self.rtld_param_id or 'None'}",
            f"     Approved Quantity: {self.approved_quantity}",
            f"     Stop-Loss Price:   {stop_str}",
            f"     Profit Target:     {target_str}",
            "----------------------------------------------------------------------",
            "  4. AUDIT LINAGE & INTEGRITY:",
            f"     Client Order ID:  {self.client_order_id or 'None'}",
            f"     Canonical Hash:   {self.canonical_hash}",
            "======================================================================",
        ]
        return "\n".join(lines)


class DecisionExplainer:
    """Non-fabricated explainability query service backed by the audit trail."""

    def __init__(
        self,
        audit_service: DecisionAuditService | None = None,
        db: DatabaseManager | None = None,
    ) -> None:
        self._audit_service = audit_service or DecisionAuditService(db=db)
        self._db = db

    def explain_from_model(self, model: DecisionRecordModel) -> ExplanationReport:
        """Derive an ExplanationReport strictly from a database model without fabrication."""
        agent_data = model.agent_outputs or {}
        scores: dict[str, float] = agent_data.get("scores", {})
        inputs_used: dict[str, Any] = agent_data.get("inputs_used", {})
        features: dict[str, float] = agent_data.get("features", {})

        agreed: list[str] = []
        disagreed: list[str] = []
        neutral: list[str] = []

        is_buy = model.final_decision == "BUY"
        is_sell = model.final_decision == "SELL"

        for agent, score in scores.items():
            if abs(score) < 0.15:
                neutral.append(f"{agent} ({score:+.2f})")
            elif is_buy:
                if score > 0:
                    agreed.append(f"{agent} ({score:+.2f})")
                else:
                    disagreed.append(f"{agent} ({score:+.2f})")
            elif is_sell:
                if score < 0:
                    agreed.append(f"{agent} ({score:+.2f})")
                else:
                    disagreed.append(f"{agent} ({score:+.2f})")
            else:
                neutral.append(f"{agent} ({score:+.2f})")

        return ExplanationReport(
            decision_record_id=model.decision_record_id,
            found=True,
            timestamp=model.timestamp,
            instrument=model.instrument,
            timeframe=model.timeframe,
            environment=model.environment,
            final_decision=model.final_decision,
            decision_rationale=model.decision_rationale,
            regime_classification=model.regime_classification,
            agent_scores=scores,
            agreed_agents=agreed,
            disagreed_agents=disagreed,
            neutral_agents=neutral,
            trade_quality_score=model.trade_quality_score,
            expected_value=model.expected_value,
            disagreement_metric=model.disagreement_metric,
            risk_check_passed=model.risk_check_passed,
            failed_check=model.failed_check,
            rtld_param_id=model.rtld_param_id,
            approved_quantity=0,
            client_order_id=model.client_order_id,
            canonical_hash=model.canonical_hash,
            inputs_used=inputs_used,
            features=features,
        )

    def explain_from_domain_record(self, record: DecisionRecord) -> ExplanationReport:
        """Derive an ExplanationReport directly from a domain DecisionRecord entity."""
        agreed: list[str] = []
        disagreed: list[str] = []
        neutral: list[str] = []

        is_buy = record.decision == "BUY"
        is_sell = record.decision == "SELL"

        for agent, score in record.agent_scores.items():
            if abs(score) < 0.15:
                neutral.append(f"{agent} ({score:+.2f})")
            elif is_buy:
                if score > 0:
                    agreed.append(f"{agent} ({score:+.2f})")
                else:
                    disagreed.append(f"{agent} ({score:+.2f})")
            elif is_sell:
                if score < 0:
                    agreed.append(f"{agent} ({score:+.2f})")
                else:
                    disagreed.append(f"{agent} ({score:+.2f})")
            else:
                neutral.append(f"{agent} ({score:+.2f})")

        risk_passed = bool(record.risk_result.get("passed", record.approved_quantity > 0))
        failed_check = record.risk_result.get("failed_check")
        rtld_param = record.risk_result.get("rtld_param_id", record.risk_result.get("param_id"))

        canonical_hash = record.decision_hash or record.calculate_canonical_hash()

        return ExplanationReport(
            decision_record_id=str(record.decision_record_id),
            found=True,
            timestamp=record.timestamp,
            instrument=record.instrument,
            timeframe=record.timeframe,
            environment=record.environment,
            final_decision=record.decision,
            decision_rationale=(
                record.reason or record.risk_result.get("reason", f"Cycle: {record.decision}")
            ),
            regime_classification={"regime": record.regime},
            agent_scores=record.agent_scores,
            agreed_agents=agreed,
            disagreed_agents=disagreed,
            neutral_agents=neutral,
            trade_quality_score=float(record.aggregated_score),
            expected_value=record.expected_value,
            disagreement_metric=float(record.disagreement_metric),
            risk_check_passed=risk_passed,
            failed_check=failed_check,
            rtld_param_id=rtld_param,
            approved_quantity=record.approved_quantity,
            stop_loss_price=record.stop_loss_price,
            target_price=record.target_price,
            client_order_id=record.client_order_id,
            canonical_hash=canonical_hash,
            inputs_used=record.inputs_used,
            features=record.features,
        )

    async def explain_decision(
        self,
        decision_record_id: str | UUID,
        session: AsyncSession | None = None,
    ) -> ExplanationReport:
        """Query and explain a decision asynchronously.

        Enforces FRD-EVAL-6: Never fabricates plausibility if the record does not exist.
        """
        model = await self._audit_service.get_decision(decision_record_id, session=session)
        if model is None:
            return ExplanationReport(
                decision_record_id=str(decision_record_id),
                found=False,
            )
        return self.explain_from_model(model)

    def explain_decision_sync(
        self,
        decision_record_id: str | UUID,
        session: Session,
    ) -> ExplanationReport:
        """Query and explain a decision synchronously.

        Enforces FRD-EVAL-6: Never fabricates plausibility if the record does not exist.
        """
        model = self._audit_service.get_decision_sync(decision_record_id, session=session)
        if model is None:
            return ExplanationReport(
                decision_record_id=str(decision_record_id),
                found=False,
            )
        return self.explain_from_model(model)
