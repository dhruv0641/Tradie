"""Post-Trade Outcome Evaluator and Variance Driver Classifier.

Compares entry expectations against realized outcomes upon position close, attributing Indian
statutory costs and execution slippage, and classifying variance drivers per FRD-EVAL-3,
DDD §5.3, and SLD §5.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID, uuid4

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.backtesting.cost_model import CostModel, CostModelConfig
from src.domain.evaluation import TradeEvaluation
from src.infrastructure.database import DatabaseManager
from src.infrastructure.models import TradeEvaluationModel

logger = structlog.get_logger(__name__)

CanonicalVarianceDriver = Literal[
    "good_trade",
    "bad_signal",
    "bad_timing",
    "bad_sizing",
    "bad_execution",
    "unexpected_event",
    "regime_change",
    "data_problem",
    "model_problem",
]


class TradeEvaluator:
    """Post-trade performance attribution and variance classification engine."""

    def __init__(
        self,
        cost_model: CostModel | None = None,
        db: DatabaseManager | None = None,
    ) -> None:
        self.cost_model = cost_model or CostModel(CostModelConfig())
        self._db = db

    def classify_variance_driver(  # noqa: PLR0911
        self,
        *,
        gross_pnl: Decimal,
        net_pnl: Decimal,
        expected_pnl: Decimal,
        total_slippage: Decimal = Decimal("0"),
        statutory_costs: Decimal = Decimal("0"),
        rule_adherence: bool = True,
        entry_regime: str | None = None,
        exit_regime: str | None = None,
        data_quality: str = "VALIDATED",
        stopped_out_early: bool = False,
        unexpected_event: bool = False,
        model_disagreement: float = 0.0,
    ) -> CanonicalVarianceDriver:
        """Classify primary driver of variance between expectation and outcome (FRD-EVAL-3).

        Hierarchy of attribution:
        1. Rule violation / sizing bounds failure -> bad_sizing
        2. Data degradation / staleness -> data_problem
        3. Exogenous market shock / circuit breaker -> unexpected_event
        4. Regime transition between entry and exit -> regime_change
        5. Profitable outcome meeting expectations -> good_trade
        6. Cost / slippage turning win into loss or dominating shortfall -> bad_execution
        7. Premature stop-loss hit prior to favorable move -> bad_timing
        8. High agent disagreement anomaly -> model_problem
        9. Standard predictive edge / directional failure -> bad_signal
        """
        # 1. Rule adherence check
        if not rule_adherence:
            return "bad_sizing"

        # 2. Ingested data quality issues
        if data_quality.upper() in ("STALE", "QUARANTINED", "CORRUPTED"):
            return "data_problem"

        # 3. Exogenous market shocks
        if unexpected_event:
            return "unexpected_event"

        # 4. Regime change during position holding
        if (
            entry_regime is not None
            and exit_regime is not None
            and entry_regime.upper() != exit_regime.upper()
            and net_pnl < Decimal("0")
        ):
            return "regime_change"

        # 5. Winning trade meeting hypothesis
        if net_pnl >= Decimal("0") and (
            expected_pnl <= Decimal("0") or net_pnl >= (expected_pnl * Decimal("0.80"))
        ):
            return "good_trade"

        # 6. Cost or slippage drag turning trade negative or causing outsized loss
        total_drag = statutory_costs + total_slippage
        if gross_pnl > Decimal("0") and net_pnl <= Decimal("0"):
            return "bad_execution"

        if net_pnl < Decimal("0") and total_slippage > Decimal("0"):
            adverse_move = abs(gross_pnl)
            if total_drag > adverse_move or total_slippage >= (abs(net_pnl) * Decimal("0.40")):
                return "bad_execution"

        # 7. Suboptimal timing / premature stop
        if stopped_out_early:
            return "bad_timing"

        # 8. Model consensus / agent conflict failure
        if model_disagreement >= 0.50 and net_pnl < Decimal("0"):
            return "model_problem"

        # 9. Default directional edge failure
        if net_pnl < Decimal("0"):
            return "bad_signal"

        return "good_trade"

    def evaluate_trade(
        self,
        *,
        entry_decision_id: UUID,
        exit_decision_id: UUID,
        instrument: str,
        direction: Literal["BUY", "SELL"],
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: int,
        entry_timestamp: datetime,
        exit_timestamp: datetime,
        expected_pnl: Decimal = Decimal("0"),
        entry_slippage: Decimal = Decimal("0"),
        exit_slippage: Decimal = Decimal("0"),
        product_type: Literal["INTRADAY", "DELIVERY"] = "INTRADAY",
        rule_adherence: bool = True,
        entry_regime: str | None = None,
        exit_regime: str | None = None,
        data_quality: str = "VALIDATED",
        stopped_out_early: bool = False,
        unexpected_event: bool = False,
        model_disagreement: float = 0.0,
        evaluation_notes: str = "",
        trade_id: UUID | None = None,
    ) -> TradeEvaluation:
        """Construct a complete, canonical TradeEvaluation record for a completed round trip."""
        # 1. Gross P&L calculation
        if direction == "BUY":
            gross_pnl = (exit_price - entry_price) * Decimal(quantity)
        else:
            gross_pnl = (entry_price - exit_price) * Decimal(quantity)

        # 2. Statutory charges and brokerage
        costs = self.cost_model.calculate_round_trip(
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            product_type=product_type,
        )
        statutory_costs = costs.total_statutory_charges + costs.total_brokerage

        # 3. Slippage and total drag
        total_slippage = entry_slippage + exit_slippage
        total_cost_drag = statutory_costs + total_slippage

        # 4. Realized Net P&L and variance
        net_pnl = gross_pnl - total_cost_drag
        pnl_variance = net_pnl - expected_pnl

        # 5. Classify primary variance driver
        variance_driver = self.classify_variance_driver(
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            expected_pnl=expected_pnl,
            total_slippage=total_slippage,
            statutory_costs=statutory_costs,
            rule_adherence=rule_adherence,
            entry_regime=entry_regime,
            exit_regime=exit_regime,
            data_quality=data_quality,
            stopped_out_early=stopped_out_early,
            unexpected_event=unexpected_event,
            model_disagreement=model_disagreement,
        )

        now = datetime.now(UTC)
        final_notes = evaluation_notes or (
            f"Trade evaluated: realized net P&L {net_pnl:.2f} vs expected {expected_pnl:.2f}, "
            f"classified as {variance_driver}."
        )

        evaluation = TradeEvaluation(
            trade_id=trade_id or uuid4(),
            entry_decision_id=entry_decision_id,
            exit_decision_id=exit_decision_id,
            instrument=instrument.strip().upper(),
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            total_slippage=total_slippage,
            statutory_costs=statutory_costs,
            variance_driver=variance_driver,
            rule_adherence=rule_adherence,
            entry_timestamp=entry_timestamp,
            exit_timestamp=exit_timestamp,
            total_cost_drag=total_cost_drag,
            expected_pnl=expected_pnl,
            pnl_variance=pnl_variance,
            evaluation_notes=final_notes,
            evaluated_at=now,
        )

        logger.info(
            "trade_evaluated",
            trade_id=str(evaluation.trade_id),
            instrument=evaluation.instrument,
            direction=evaluation.direction,
            net_pnl=str(evaluation.net_pnl),
            variance_driver=evaluation.variance_driver,
        )
        return evaluation

    def _convert_to_model(self, eval_record: TradeEvaluation) -> TradeEvaluationModel:
        """Convert domain TradeEvaluation entity to SQLAlchemy TradeEvaluationModel."""
        entry_ts = eval_record.entry_timestamp or eval_record.evaluated_at
        exit_ts = eval_record.exit_timestamp or eval_record.evaluated_at

        return TradeEvaluationModel(
            evaluation_id=str(eval_record.trade_id),
            decision_record_id=str(eval_record.entry_decision_id),
            instrument=eval_record.instrument,
            entry_timestamp=entry_ts,
            exit_timestamp=exit_ts,
            entry_price=eval_record.entry_price,
            exit_price=eval_record.exit_price,
            quantity=eval_record.quantity,
            realized_pnl=eval_record.net_pnl,
            gross_pnl=eval_record.gross_pnl,
            total_cost_drag=eval_record.total_cost_drag,
            expected_pnl=eval_record.expected_pnl,
            pnl_variance=eval_record.pnl_variance,
            variance_driver=eval_record.variance_driver,
            evaluation_notes=eval_record.evaluation_notes,
        )

    async def record_evaluation(
        self,
        evaluation: TradeEvaluation,
        session: AsyncSession | None = None,
    ) -> TradeEvaluationModel:
        """Persist a TradeEvaluation asynchronously into the trade_evaluations table."""
        model = self._convert_to_model(evaluation)

        if session is not None:
            session.add(model)
            await session.flush()
            return model

        if self._db is not None:
            async with self._db.get_session() as managed_session:
                managed_session.add(model)
                await managed_session.flush()
            return model

        msg = "No database session or DatabaseManager provided to TradeEvaluator"
        raise RuntimeError(msg)

    def record_evaluation_sync(
        self,
        evaluation: TradeEvaluation,
        session: Session,
    ) -> TradeEvaluationModel:
        """Persist a TradeEvaluation synchronously into the provided SQLAlchemy Session."""
        model = self._convert_to_model(evaluation)
        session.add(model)
        session.flush()
        return model

    async def get_evaluation(
        self,
        evaluation_id: str | UUID,
        session: AsyncSession | None = None,
    ) -> TradeEvaluationModel | None:
        """Query a single TradeEvaluationModel by primary key."""
        eval_id = str(evaluation_id)
        stmt = select(TradeEvaluationModel).where(TradeEvaluationModel.evaluation_id == eval_id)

        if session is not None:
            return cast("TradeEvaluationModel | None", await session.scalar(stmt))
        if self._db is not None:
            async with self._db.get_session() as managed_session:
                return cast("TradeEvaluationModel | None", await managed_session.scalar(stmt))
        return None

    def get_evaluation_sync(
        self,
        evaluation_id: str | UUID,
        session: Session,
    ) -> TradeEvaluationModel | None:
        """Query a single TradeEvaluationModel synchronously by primary key."""
        eval_id = str(evaluation_id)
        stmt = select(TradeEvaluationModel).where(TradeEvaluationModel.evaluation_id == eval_id)
        return cast("TradeEvaluationModel | None", session.scalar(stmt))

    async def get_evaluations_for_instrument(
        self,
        instrument: str,
        limit: int = 50,
        session: AsyncSession | None = None,
    ) -> list[TradeEvaluationModel]:
        """Query recent trade evaluations for a given instrument."""
        stmt = (
            select(TradeEvaluationModel)
            .where(TradeEvaluationModel.instrument == instrument.strip().upper())
            .order_by(desc(TradeEvaluationModel.exit_timestamp))
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

    def get_evaluations_for_instrument_sync(
        self,
        instrument: str,
        session: Session,
        limit: int = 50,
    ) -> list[TradeEvaluationModel]:
        """Query recent trade evaluations for an instrument synchronously."""
        stmt = (
            select(TradeEvaluationModel)
            .where(TradeEvaluationModel.instrument == instrument.strip().upper())
            .order_by(desc(TradeEvaluationModel.exit_timestamp))
            .limit(limit)
        )
        return list(session.scalars(stmt).all())
