"""Immutable Decision Record Audit Logging Service.

Persists 100% of Supervisor and suppression decisions unconditionally to PostgreSQL/TimescaleDB
with SHA-256 cryptographic verification and fail-stop safety semantics (BRD BR-7, FRD-EVAL-1,
FRD-EVAL-2, FRD-X-3, NFR-AUDIT-1, DDD §5.2).
"""

from typing import Protocol, cast, runtime_checkable
from uuid import UUID

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.domain.decision import DecisionRecord
from src.infrastructure.database import DatabaseManager
from src.infrastructure.models import DecisionRecordModel

logger = structlog.get_logger(__name__)


class AuditPersistenceError(RuntimeError):
    """Raised when an immutable decision record fails to persist to the database."""

    pass


class TamperEvidenceViolationError(ValueError):
    """Raised when a decision record's cryptographic hash does not match its canonical payload."""

    pass


@runtime_checkable
class KillSwitchProtocol(Protocol):
    """Protocol for activating emergency halt upon audit write failure."""

    def activate(self, source: str, reason: str) -> None:
        """Trigger emergency trading halt."""
        ...


class DecisionAuditService:
    """Synchronous and asynchronous audit service persisting 100% of trading decisions."""

    def __init__(
        self,
        db: DatabaseManager | None = None,
        kill_switch: KillSwitchProtocol | None = None,
    ) -> None:
        self._db = db
        self._kill_switch = kill_switch

    def _convert_to_model(self, record: DecisionRecord) -> DecisionRecordModel:
        """Convert a canonical domain DecisionRecord to SQLAlchemy DecisionRecordModel."""
        # 1. Tamper evidence verification
        if record.decision_hash is not None:
            canonical = record.calculate_canonical_hash()
            if record.decision_hash != canonical:
                logger.critical(
                    "decision_tamper_detected",
                    record_id=str(record.decision_record_id),
                    stored_hash=record.decision_hash,
                    canonical_hash=canonical,
                )
                msg = (
                    f"Cryptographic tamper violation on record {record.decision_record_id}: "
                    f"stored {record.decision_hash} != calculated {canonical}"
                )
                raise TamperEvidenceViolationError(msg)

        canonical_hash = record.decision_hash or record.calculate_canonical_hash()

        # 2. Extract risk flags and parameters
        risk_passed = bool(record.risk_result.get("passed", record.approved_quantity > 0))
        failed_check = record.risk_result.get("failed_check")
        rtld_param = record.risk_result.get("rtld_param_id", record.risk_result.get("param_id"))

        regime_data = {"regime": record.regime}
        agent_data = {
            "scores": record.agent_scores,
            "inputs_used": record.inputs_used,
            "features": record.features,
        }

        # 3. Decision rationale fallback
        rationale = record.reason
        if not rationale:
            rationale = str(
                record.risk_result.get("reason", f"Evaluation cycle outcome: {record.decision}")
            )

        return DecisionRecordModel(
            decision_record_id=str(record.decision_record_id),
            timestamp=record.timestamp,
            instrument=record.instrument,
            timeframe=record.timeframe,
            environment=record.environment,
            data_quality_state=record.data_quality_state,
            regime_classification=regime_data,
            agent_outputs=agent_data,
            trade_quality_score=float(record.aggregated_score),
            expected_value=record.expected_value,
            disagreement_metric=float(record.disagreement_metric),
            risk_check_passed=risk_passed,
            failed_check=failed_check,
            rtld_param_id=rtld_param,
            risk_config_version=record.config_version,
            final_decision=record.decision,
            decision_rationale=rationale,
            client_order_id=record.client_order_id,
            model_version_id=record.git_commit,
            canonical_hash=canonical_hash,
        )

    async def log_decision(
        self,
        record: DecisionRecord,
        session: AsyncSession | None = None,
    ) -> DecisionRecordModel:
        """Persist a DecisionRecord asynchronously into PostgreSQL/TimescaleDB.

        If database persistence fails, triggers kill switch (if configured) and raises
        AuditPersistenceError per FRD-X-3.
        """
        model = self._convert_to_model(record)

        try:
            if session is not None:
                session.add(model)
                await session.flush()
            elif self._db is not None:
                async with self._db.get_session() as managed_session:
                    managed_session.add(model)
                    await managed_session.flush()
            else:
                msg = "No database session or DatabaseManager provided to DecisionAuditService"
                raise RuntimeError(msg)

            logger.info(
                "decision_record_persisted",
                decision_record_id=model.decision_record_id,
                instrument=model.instrument,
                decision=model.final_decision,
                hash=model.canonical_hash,
            )
            return model

        except Exception as exc:
            logger.critical(
                "decision_audit_persistence_failure",
                decision_record_id=str(record.decision_record_id),
                instrument=record.instrument,
                decision=record.decision,
                error=str(exc),
            )
            if self._kill_switch is not None:
                self._kill_switch.activate(
                    source="DecisionAuditService",
                    reason=f"Audit log database persistence failure: {exc}",
                )
            msg = (
                f"CRITICAL: Failed to persist DecisionRecord {record.decision_record_id} "
                f"unconditionally to database: {exc}"
            )
            raise AuditPersistenceError(msg) from exc

    def log_decision_sync(
        self,
        record: DecisionRecord,
        session: Session,
    ) -> DecisionRecordModel:
        """Persist a DecisionRecord synchronously into the provided SQLAlchemy Session."""
        model = self._convert_to_model(record)

        try:
            session.add(model)
            session.flush()
            logger.info(
                "decision_record_persisted_sync",
                decision_record_id=model.decision_record_id,
                instrument=model.instrument,
                decision=model.final_decision,
                hash=model.canonical_hash,
            )
            return model
        except Exception as exc:
            logger.critical(
                "decision_audit_persistence_failure_sync",
                decision_record_id=str(record.decision_record_id),
                instrument=record.instrument,
                decision=record.decision,
                error=str(exc),
            )
            if self._kill_switch is not None:
                self._kill_switch.activate(
                    source="DecisionAuditService",
                    reason=f"Audit log database persistence failure (sync): {exc}",
                )
            msg = (
                f"CRITICAL: Failed to persist DecisionRecord {record.decision_record_id} "
                f"unconditionally to database: {exc}"
            )
            raise AuditPersistenceError(msg) from exc

    async def get_decision(
        self,
        decision_record_id: str | UUID,
        session: AsyncSession | None = None,
    ) -> DecisionRecordModel | None:
        """Query a single DecisionRecordModel by unique primary key."""
        dec_id = str(decision_record_id)
        stmt = select(DecisionRecordModel).where(DecisionRecordModel.decision_record_id == dec_id)

        if session is not None:
            return cast("DecisionRecordModel | None", await session.scalar(stmt))
        if self._db is not None:
            async with self._db.get_session() as managed_session:
                return cast("DecisionRecordModel | None", await managed_session.scalar(stmt))
        return None

    def get_decision_sync(
        self,
        decision_record_id: str | UUID,
        session: Session,
    ) -> DecisionRecordModel | None:
        """Query a single DecisionRecordModel synchronously by unique primary key."""
        dec_id = str(decision_record_id)
        stmt = select(DecisionRecordModel).where(DecisionRecordModel.decision_record_id == dec_id)
        return cast("DecisionRecordModel | None", session.scalar(stmt))

    async def get_recent_decisions(
        self,
        limit: int = 50,
        instrument: str | None = None,
        session: AsyncSession | None = None,
    ) -> list[DecisionRecordModel]:
        """Query recent decisions in reverse chronological order."""
        stmt = (
            select(DecisionRecordModel).order_by(desc(DecisionRecordModel.timestamp)).limit(limit)
        )
        if instrument:
            stmt = (
                select(DecisionRecordModel)
                .where(DecisionRecordModel.instrument == instrument.strip().upper())
                .order_by(desc(DecisionRecordModel.timestamp))
                .limit(limit)
            )

        if session is not None:
            res = await session.scalars(stmt)
            return list(res.all())
        if self._db is not None:
            async with self._db.get_session() as managed_session:
                res = await managed_session.scalars(stmt)
                return list(res.all())
        return []

    def get_recent_decisions_sync(
        self,
        session: Session,
        limit: int = 50,
        instrument: str | None = None,
    ) -> list[DecisionRecordModel]:
        """Query recent decisions synchronously in reverse chronological order."""
        stmt = (
            select(DecisionRecordModel).order_by(desc(DecisionRecordModel.timestamp)).limit(limit)
        )
        if instrument:
            stmt = (
                select(DecisionRecordModel)
                .where(DecisionRecordModel.instrument == instrument.strip().upper())
                .order_by(desc(DecisionRecordModel.timestamp))
                .limit(limit)
            )
        return list(session.scalars(stmt).all())
