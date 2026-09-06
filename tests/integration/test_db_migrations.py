"""Integration tests for SQLAlchemy 2.0 ORM models, Alembic migrations, and DatabaseManager."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from alembic.command import upgrade
from alembic.config import Config
from src.config.models import DatabaseConfig
from src.infrastructure.database import DatabaseManager
from src.infrastructure.models import (
    Base,
    DecisionRecordModel,
    ModelVersionModel,
    OHLCVCandleModel,
    OrderSubmissionModel,
    PositionModel,
    TradeEvaluationModel,
    ValidationRunModel,
)


@pytest.mark.integration
def test_orm_schema_table_names_and_columns() -> None:
    """Verify that all 7 canonical tables and primary keys match DDD §6 specifications."""
    tables = Base.metadata.tables
    expected_tables = {
        "ohlcv_candles",
        "decision_records",
        "trade_evaluations",
        "model_versions",
        "validation_runs",
        "order_submissions",
        "positions",
    }
    assert expected_tables.issubset(set(tables.keys()))

    # ohlcv_candles composite primary key
    ohlcv = tables["ohlcv_candles"]
    pk_cols = [c.name for c in ohlcv.primary_key.columns]
    assert set(pk_cols) == {"instrument", "timeframe", "timestamp"}

    # decision_records primary key
    dec = tables["decision_records"]
    assert [c.name for c in dec.primary_key.columns] == ["decision_record_id"]

    # trade_evaluations foreign key
    trade_eval = tables["trade_evaluations"]
    fk_targets = [fk.target_fullname for fk in trade_eval.foreign_keys]
    assert "decision_records.decision_record_id" in fk_targets

    # positions primary key
    pos = tables["positions"]
    assert [c.name for c in pos.primary_key.columns] == ["instrument"]


@pytest.mark.integration
def test_orm_in_memory_crud_roundtrip() -> None:
    """Verify that all 7 ORM models can be inserted, committed, and queried cleanly."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    now = datetime(2025, 1, 15, 9, 30, tzinfo=UTC)

    with Session(engine) as session:
        # 1. Insert OHLCVCandleModel
        candle = OHLCVCandleModel(
            timestamp=now,
            instrument="RELIANCE",
            timeframe="1m",
            open=Decimal("2500.0000"),
            high=Decimal("2510.0000"),
            low=Decimal("2495.0000"),
            close=Decimal("2505.0000"),
            volume=10000,
            turnover=Decimal("25050000.0000"),
            open_interest=50000,
            quality_state="VALIDATED",
        )
        session.add(candle)

        # 2. Insert ModelVersionModel
        model_version = ModelVersionModel(
            model_version_id="model_trend_v1",
            agent_id="trend_agent",
            architecture_type="statistical",
            created_at=now,
            git_commit_hash="abcdef123456",
            artifact_storage_path="/artifacts/models/trend_v1.joblib",
            artifact_sha256="hash1234",
            status="PROMOTED",
            active_in_production=True,
        )
        session.add(model_version)

        # 3. Insert ValidationRunModel
        val_run = ValidationRunModel(
            validation_run_id="val_run_001",
            model_version_id="model_trend_v1",
            stage="OUT_OF_SAMPLE",
            start_date=now,
            end_date=now,
            sharpe_ratio=2.1,
            sortino_ratio=2.8,
            max_drawdown_pct=0.03,
            profit_factor=1.8,
            walk_forward_efficiency_ratio=0.75,
            trade_count=150,
            passed_stage=True,
            evidence_payload_json={"metrics": "passed"},
        )
        session.add(val_run)

        # 4. Insert DecisionRecordModel
        decision = DecisionRecordModel(
            decision_record_id="dec_001",
            timestamp=now,
            instrument="RELIANCE",
            timeframe="1m",
            environment="live",
            data_quality_state="VALIDATED",
            regime_classification={"regime": "TRENDING_BULL"},
            agent_outputs={"trend": "BUY"},
            trade_quality_score=0.85,
            expected_value=Decimal("150.0000"),
            disagreement_metric=0.1,
            risk_check_passed=True,
            failed_check=None,
            rtld_param_id="RTLD-MAX-RISK",
            risk_config_version="v1.0",
            final_decision="BUY",
            decision_rationale="High trend alignment",
            client_order_id="ord_001",
            model_version_id="model_trend_v1",
            canonical_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        session.add(decision)

        # 5. Insert TradeEvaluationModel
        eval_record = TradeEvaluationModel(
            evaluation_id="eval_001",
            decision_record_id="dec_001",
            instrument="RELIANCE",
            entry_timestamp=now,
            exit_timestamp=now,
            entry_price=Decimal("2500.0000"),
            exit_price=Decimal("2520.0000"),
            quantity=10,
            realized_pnl=Decimal("190.0000"),
            gross_pnl=Decimal("200.0000"),
            total_cost_drag=Decimal("10.0000"),
            expected_pnl=Decimal("150.0000"),
            pnl_variance=Decimal("40.0000"),
            variance_driver="STRATEGY_EDGE",
            evaluation_notes="Executed above target",
        )
        session.add(eval_record)

        # 6. Insert OrderSubmissionModel
        order = OrderSubmissionModel(
            client_order_id="ord_001",
            broker_order_id="brk_12345",
            decision_record_id="dec_001",
            instrument="RELIANCE",
            direction="BUY",
            order_type="LIMIT",
            limit_price=Decimal("2500.0000"),
            quantity=10,
            filled_quantity=10,
            average_fill_price=Decimal("2500.0000"),
            status="FILLED",
            rejection_reason=None,
            submitted_at=now,
            updated_at=now,
        )
        session.add(order)

        # 7. Insert PositionModel
        position = PositionModel(
            instrument="RELIANCE",
            quantity=10,
            average_entry_price=Decimal("2500.0000"),
            current_market_price=Decimal("2520.0000"),
            unrealized_pnl=Decimal("200.0000"),
            realized_pnl=Decimal("0.0000"),
            peak_unrealized_pnl=Decimal("220.0000"),
            opened_at=now,
            last_updated_at=now,
        )
        session.add(position)

        session.commit()

    # Query back and verify persistence
    with Session(engine) as session:
        queried_dec = session.scalar(
            select(DecisionRecordModel).where(DecisionRecordModel.decision_record_id == "dec_001")
        )
        assert queried_dec is not None
        assert queried_dec.final_decision == "BUY"
        assert queried_dec.expected_value == Decimal("150.0000")
        assert queried_dec.regime_classification == {"regime": "TRENDING_BULL"}

        queried_pos = session.scalar(
            select(PositionModel).where(PositionModel.instrument == "RELIANCE")
        )
        assert queried_pos is not None
        assert queried_pos.quantity == 10
        assert queried_pos.unrealized_pnl == Decimal("200.0000")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_database_manager_lifecycle() -> None:
    """Verify DatabaseManager lifecycle, initialization status, and close."""
    config = DatabaseConfig(
        host="localhost",
        port=5432,
        user="test_user",
        database="test_db",
        pool_size=5,
    )
    db = DatabaseManager(config)
    init_before = db.is_initialized
    assert init_before is False

    engine = db.get_engine()
    init_after = db.is_initialized
    assert init_after is True
    assert engine.name == "postgresql"
    assert engine.driver == "asyncpg"

    # Health check returns False when database is not reachable
    health = await db.health_check()
    assert health is False

    await db.close()
    init_closed = db.is_initialized
    assert init_closed is False

    # Closing again should be a safe no-op
    await db.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_database_manager_session_context() -> None:
    """Verify DatabaseManager session commit/rollback context behavior."""
    config = DatabaseConfig()
    db = DatabaseManager(config)

    mock_session = AsyncMock()
    mock_sessionmaker = MagicMock()
    mock_sessionmaker.return_value.__aenter__.return_value = mock_session
    mock_sessionmaker.return_value.__aexit__.return_value = None

    db._sessionmaker = mock_sessionmaker
    db._engine = MagicMock()

    async with db.get_session() as session:
        assert session is mock_session

    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_awaited()

    # Test rollback on exception
    mock_session.reset_mock()
    with pytest.raises(RuntimeError, match="Simulated failure"):
        async with db.get_session():
            raise RuntimeError("Simulated failure")

    mock_session.commit.assert_not_awaited()
    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_database_manager_health_check_success() -> None:
    """Verify health_check() returns True when database SELECT 1 succeeds."""
    config = DatabaseConfig()
    db = DatabaseManager(config)

    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_conn.execute.return_value = mock_result
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn
    mock_engine.connect.return_value.__aexit__.return_value = None

    db._engine = mock_engine
    health = await db.health_check()
    assert health is True


@pytest.mark.integration
def test_alembic_offline_sql_generation(tmp_path: Any) -> None:
    """Verify that Alembic generates complete, valid DDL in offline mode."""
    alembic_cfg = Config("alembic.ini")
    sql_output_file = tmp_path / "migration.sql"

    # Set output buffer / file for offline sql generation
    with sql_output_file.open("w", encoding="utf-8") as buf:
        alembic_cfg.output_buffer = buf
        upgrade(alembic_cfg, "head", sql=True)

    assert sql_output_file.exists()
    sql_text = sql_output_file.read_text(encoding="utf-8")

    # Verify tables are present in generated SQL
    assert "CREATE TABLE ohlcv_candles" in sql_text
    assert "CREATE TABLE decision_records" in sql_text
    assert "CREATE TABLE trade_evaluations" in sql_text
    assert "CREATE TABLE model_versions" in sql_text
    assert "CREATE TABLE validation_runs" in sql_text
    assert "CREATE TABLE order_submissions" in sql_text
    assert "CREATE TABLE positions" in sql_text
    assert "CREATE EXTENSION IF NOT EXISTS timescaledb" in sql_text
    assert "create_hypertable" in sql_text
    assert "block_immutable_audit_modification" in sql_text
