"""Initial schema with TimescaleDB hypertable and immutable audit triggers.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-09-06 09:30:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = JSONB if is_postgres else sa.JSON

    # 1. Enable TimescaleDB extension if running under PostgreSQL
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

    # 2. Market Data: ohlcv_candles table
    op.create_table(
        "ohlcv_candles",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column(
            "turnover",
            sa.Numeric(precision=18, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column("open_interest", sa.BigInteger(), nullable=True),
        sa.Column(
            "quality_state",
            sa.String(length=16),
            server_default="RAW",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("instrument", "timeframe", "timestamp", name="pk_ohlcv_candles"),
    )

    # Convert to TimescaleDB hypertable if PostgreSQL
    if is_postgres:
        op.execute("SELECT create_hypertable('ohlcv_candles', 'timestamp', if_not_exists => TRUE);")

    # 3. Governance: model_versions
    op.create_table(
        "model_versions",
        sa.Column("model_version_id", sa.String(length=128), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("architecture_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("git_commit_hash", sa.String(length=64), nullable=False),
        sa.Column("artifact_storage_path", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "active_in_production",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # 4. Governance: validation_runs
    op.create_table(
        "validation_runs",
        sa.Column("validation_run_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "model_version_id",
            sa.String(length=128),
            sa.ForeignKey("model_versions.model_version_id"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sharpe_ratio", sa.Float(), nullable=False),
        sa.Column("sortino_ratio", sa.Float(), nullable=False),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=False),
        sa.Column("profit_factor", sa.Float(), nullable=False),
        sa.Column("walk_forward_efficiency_ratio", sa.Float(), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("passed_stage", sa.Boolean(), nullable=False),
        sa.Column("evidence_payload_json", json_type, nullable=False),
    )

    # 5. Core Audit: decision_records
    op.create_table(
        "decision_records",
        sa.Column("decision_record_id", sa.String(length=128), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("data_quality_state", sa.String(length=16), nullable=False),
        sa.Column("regime_classification", json_type, nullable=False),
        sa.Column("agent_outputs", json_type, nullable=False),
        sa.Column("trade_quality_score", sa.Float(), nullable=False),
        sa.Column("expected_value", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("disagreement_metric", sa.Float(), nullable=False),
        sa.Column("risk_check_passed", sa.Boolean(), nullable=False),
        sa.Column("failed_check", sa.String(length=64), nullable=True),
        sa.Column("rtld_param_id", sa.String(length=32), nullable=True),
        sa.Column("risk_config_version", sa.String(length=64), nullable=False),
        sa.Column("final_decision", sa.String(length=16), nullable=False),
        sa.Column("decision_rationale", sa.Text(), nullable=False),
        sa.Column("client_order_id", sa.String(length=128), nullable=True),
        sa.Column("model_version_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_hash", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "idx_dec_inst_time",
        "decision_records",
        ["instrument", sa.text("timestamp DESC")],
    )
    op.create_index(
        "idx_dec_decision",
        "decision_records",
        ["final_decision", sa.text("timestamp DESC")],
    )

    # 6. Evaluation: trade_evaluations
    op.create_table(
        "trade_evaluations",
        sa.Column("evaluation_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "decision_record_id",
            sa.String(length=128),
            sa.ForeignKey("decision_records.decision_record_id"),
            nullable=False,
        ),
        sa.Column("instrument", sa.String(length=64), nullable=False),
        sa.Column("entry_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("exit_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("total_cost_drag", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("expected_pnl", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("pnl_variance", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("variance_driver", sa.String(length=32), nullable=False),
        sa.Column("evaluation_notes", sa.Text(), nullable=True),
    )

    # 7. Execution: order_submissions
    op.create_table(
        "order_submissions",
        sa.Column("client_order_id", sa.String(length=128), primary_key=True),
        sa.Column("broker_order_id", sa.String(length=128), nullable=True),
        sa.Column(
            "decision_record_id",
            sa.String(length=128),
            sa.ForeignKey("decision_records.decision_record_id"),
            nullable=True,
        ),
        sa.Column("instrument", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "filled_quantity",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "average_fill_price",
            sa.Numeric(precision=18, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_order_broker_id", "order_submissions", ["broker_order_id"])
    op.create_index("idx_order_submitted_at", "order_submissions", ["submitted_at"])

    # 8. Execution: positions
    op.create_table(
        "positions",
        sa.Column("instrument", sa.String(length=64), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "average_entry_price",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "current_market_price",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column("unrealized_pnl", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column(
            "peak_unrealized_pnl",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 9. Append-Only Trigger for Immutable Audit Tables (PostgreSQL only)
    if is_postgres:
        op.execute(
            """
            CREATE OR REPLACE FUNCTION block_immutable_audit_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Modifications to immutable audit records are forbidden.';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_block_update_delete_decision_records
            BEFORE UPDATE OR DELETE ON decision_records
            FOR EACH ROW EXECUTE FUNCTION block_immutable_audit_modification();

            CREATE TRIGGER trg_block_update_delete_trade_evaluations
            BEFORE UPDATE OR DELETE ON trade_evaluations
            FOR EACH ROW EXECUTE FUNCTION block_immutable_audit_modification();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            DROP TRIGGER IF EXISTS trg_block_update_delete_trade_evaluations ON trade_evaluations;
            DROP TRIGGER IF EXISTS trg_block_update_delete_decision_records ON decision_records;
            DROP FUNCTION IF EXISTS block_immutable_audit_modification();
            """
        )

    op.drop_table("positions")
    op.drop_index("idx_order_submitted_at", table_name="order_submissions")
    op.drop_index("idx_order_broker_id", table_name="order_submissions")
    op.drop_table("order_submissions")
    op.drop_table("trade_evaluations")
    op.drop_index("idx_dec_decision", table_name="decision_records")
    op.drop_index("idx_dec_inst_time", table_name="decision_records")
    op.drop_table("decision_records")
    op.drop_table("validation_runs")
    op.drop_table("model_versions")
    op.drop_table("ohlcv_candles")
