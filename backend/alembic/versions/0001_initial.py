"""Initial schema — all tables, enums, triggers, and seed data.

Revision ID: 0001
Revises:
Create Date: 2026-05-16 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # PostgreSQL ENUM types
    # -------------------------------------------------------------------------
    op.execute("CREATE TYPE direction_t AS ENUM ('LONG', 'SHORT')")
    op.execute("CREATE TYPE outcome_t AS ENUM ('WIN', 'LOSS', 'BE', 'OPEN')")
    op.execute("CREATE TYPE trade_status_t AS ENUM ('OPEN', 'CLOSED', 'CANCELLED')")
    op.execute(
        "CREATE TYPE alert_type_t AS ENUM "
        "('ENTRY_SIGNAL','EXIT_MGMT','RISK_WARNING','PATTERN','PSYCHOLOGY')"
    )
    op.execute(
        "CREATE TYPE alert_priority_t AS ENUM ('INFO','SUGGESTION','WARNING','CRITICAL')"
    )
    op.execute(
        "CREATE TYPE alert_status_t AS ENUM "
        "('PENDING','APPROVED','REJECTED','EDITED','EXECUTING','EXECUTED',"
        "'FAILED','EXPIRED','SUPERSEDED')"
    )
    op.execute(
        "CREATE TYPE ict_type_t AS ENUM "
        "('OB','FVG','BOS','CHOCH','LIQ','SFP','BREAKER','SD_ZONE')"
    )
    op.execute("CREATE TYPE ict_dir_t AS ENUM ('BULL','BEAR')")
    op.execute("CREATE TYPE ict_status_t AS ENUM ('ACTIVE','MITIGATED','EXPIRED')")
    op.execute(
        "CREATE TYPE screenshot_trig_t AS ENUM "
        "('TRADE_OPEN','INTERVAL','KEY_LEVEL','NEWS','STRUCTURE','MANUAL')"
    )
    op.execute("CREATE TYPE actor_t AS ENUM ('SYSTEM','AI','TRADER')")
    op.execute(
        "CREATE TYPE compliance_t AS ENUM "
        "('ACTIVE','AT_RISK','CRITICAL','HALTED','COOLDOWN','BREACHED')"
    )
    op.execute("CREATE TYPE order_type_t AS ENUM ('MARKET','LIMIT','STOP')")
    op.execute(
        "CREATE TYPE order_status_t AS ENUM "
        "('PENDING','FILLED','CANCELLED','REJECTED','EXPIRED')"
    )

    # -------------------------------------------------------------------------
    # trades
    # -------------------------------------------------------------------------
    op.create_table(
        "trades",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column("broker_id", sa.String(), nullable=False),
        sa.Column("broker", sa.String(), nullable=False),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("LONG", "SHORT", name="direction_t", create_type=False),
            nullable=False,
        ),
        sa.Column("entry_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("exit_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("sl", sa.Numeric(18, 6), nullable=True),
        sa.Column("tp", sa.Numeric(18, 6), nullable=True),
        sa.Column("lot_size", sa.Numeric(18, 6), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("r_multiple", sa.Numeric(8, 2), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum("WIN", "LOSS", "BE", "OPEN", name="outcome_t", create_type=False),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column("session", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("OPEN", "CLOSED", "CANCELLED", name="trade_status_t", create_type=False),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column("pnl_dollars", sa.Numeric(14, 2), nullable=True),
        sa.Column("pnl_pips", sa.Numeric(10, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("setup_tag", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_trades_user_id", "trades", ["user_id"])
    op.create_index("ix_trades_pair", "trades", ["pair"])
    op.create_index("ix_trades_status", "trades", ["status"])
    op.create_index("ix_trades_entry_time", "trades", ["entry_time"])

    # -------------------------------------------------------------------------
    # candles
    # -------------------------------------------------------------------------
    op.create_table(
        "candles",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("open", sa.Numeric(18, 6), nullable=False),
        sa.Column("high", sa.Numeric(18, 6), nullable=False),
        sa.Column("low", sa.Numeric(18, 6), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("user_id", "pair", "timeframe", "time"),
    )
    op.create_index("ix_candles_pair_tf_time", "candles", ["pair", "timeframe", "time"])

    # -------------------------------------------------------------------------
    # ict_detections
    # -------------------------------------------------------------------------
    op.create_table(
        "ict_detections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column(
            "detection_type",
            sa.Enum(
                "OB", "FVG", "BOS", "CHOCH", "LIQ", "SFP", "BREAKER", "SD_ZONE",
                name="ict_type_t",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "direction",
            sa.Enum("BULL", "BEAR", name="ict_dir_t", create_type=False),
            nullable=False,
        ),
        sa.Column("price_high", sa.Numeric(18, 6), nullable=False),
        sa.Column("price_low", sa.Numeric(18, 6), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("strength", sa.Numeric(4, 3), nullable=False),
        sa.Column("candle_index", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "MITIGATED", "EXPIRED", name="ict_status_t", create_type=False),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("mitigated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ict_user_pair_tf", "ict_detections", ["user_id", "pair", "timeframe"])
    op.create_index("ix_ict_status", "ict_detections", ["status"])

    # -------------------------------------------------------------------------
    # screenshots
    # -------------------------------------------------------------------------
    op.create_table(
        "screenshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column(
            "trade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trades.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column(
            "trigger_type",
            sa.Enum(
                "TRADE_OPEN", "INTERVAL", "KEY_LEVEL", "NEWS", "STRUCTURE", "MANUAL",
                name="screenshot_trig_t",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("image_path", sa.String(), nullable=False),
        sa.Column("image_hash", sa.String(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_screenshots_trade_id", "screenshots", ["trade_id"])
    op.create_index("ix_screenshots_user_id", "screenshots", ["user_id"])

    # -------------------------------------------------------------------------
    # ai_analyses
    # -------------------------------------------------------------------------
    op.create_table(
        "ai_analyses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column(
            "screenshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("screenshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("analysis_json", postgresql.JSONB(), nullable=False),
        sa.Column("trend_assessment", sa.String(), nullable=True),
        sa.Column("trade_bias", sa.String(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 5), nullable=False, server_default="0"),
        sa.Column("downgraded", sa.Boolean(), nullable=False, server_default="FALSE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_ai_analyses_screenshot_id", "ai_analyses", ["screenshot_id"])

    # -------------------------------------------------------------------------
    # alerts
    # -------------------------------------------------------------------------
    op.create_table(
        "alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column(
            "type",
            sa.Enum(
                "ENTRY_SIGNAL", "EXIT_MGMT", "RISK_WARNING", "PATTERN", "PSYCHOLOGY",
                name="alert_type_t",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "INFO", "SUGGESTION", "WARNING", "CRITICAL",
                name="alert_priority_t",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("pair", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("suggested_action", postgresql.JSONB(), nullable=True),
        sa.Column(
            "context_json",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "APPROVED", "REJECTED", "EDITED", "EXECUTING",
                "EXECUTED", "FAILED", "EXPIRED", "SUPERSEDED",
                name="alert_status_t",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("ai_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW() + INTERVAL '15 minutes'"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(), nullable=True),
    )
    op.create_index("ix_alerts_user_status", "alerts", ["user_id", "status"])
    op.create_index("ix_alerts_expires_at", "alerts", ["expires_at"])

    # -------------------------------------------------------------------------
    # audit_log
    # -------------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "actor",
            sa.Enum("SYSTEM", "AI", "TRADER", name="actor_t", create_type=False),
            nullable=False,
        ),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("result", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_audit_log_user_entity", "audit_log", ["user_id", "entity_type"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    # -------------------------------------------------------------------------
    # edit_diffs
    # -------------------------------------------------------------------------
    op.create_table(
        "edit_diffs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column(
            "alert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_path", sa.String(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_edit_diffs_alert_id", "edit_diffs", ["alert_id"])

    # -------------------------------------------------------------------------
    # checklists
    # -------------------------------------------------------------------------
    op.create_table(
        "checklists",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column(
            "trade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trades.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("template_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("steps_json", postgresql.JSONB(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default="FALSE"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_checklists_trade_id", "checklists", ["trade_id"])

    # -------------------------------------------------------------------------
    # prop_firm_profiles
    # -------------------------------------------------------------------------
    op.create_table(
        "prop_firm_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column("firm_name", sa.String(), nullable=False),
        sa.Column("challenge_type", sa.String(), nullable=True),
        sa.Column("rules_json", postgresql.JSONB(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_prop_firm_profiles_user_id", "prop_firm_profiles", ["user_id"])

    # -------------------------------------------------------------------------
    # prop_firm_snapshots
    # -------------------------------------------------------------------------
    op.create_table(
        "prop_firm_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prop_firm_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("equity", sa.Numeric(14, 2), nullable=False),
        sa.Column("balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("daily_loss", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_loss", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "ACTIVE", "AT_RISK", "CRITICAL", "HALTED", "COOLDOWN", "BREACHED",
                name="compliance_t",
                create_type=False,
            ),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_prop_firm_snapshots_profile_ts",
        "prop_firm_snapshots",
        ["profile_id", "timestamp"],
    )

    # -------------------------------------------------------------------------
    # scoring_profiles
    # -------------------------------------------------------------------------
    op.create_table(
        "scoring_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column("profile_name", sa.String(), nullable=False),
        sa.Column("ict_weight", sa.Numeric(4, 3), nullable=False),
        sa.Column("ta_weight", sa.Numeric(4, 3), nullable=False),
        sa.Column("price_action_weight", sa.Numeric(4, 3), nullable=False),
        sa.Column("mtf_bonus", sa.Numeric(4, 3), nullable=False),
        sa.Column(
            "min_score_entry", sa.Numeric(5, 2), nullable=False, server_default="65"
        ),
        sa.Column("weights_json", postgresql.JSONB(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="FALSE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # -------------------------------------------------------------------------
    # orders
    # -------------------------------------------------------------------------
    op.create_table(
        "orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column("broker_order_id", sa.String(), nullable=False),
        sa.Column("broker", sa.String(), nullable=False),
        sa.Column("pair", sa.String(), nullable=False),
        sa.Column(
            "order_type",
            sa.Enum("MARKET", "LIMIT", "STOP", name="order_type_t", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "direction",
            sa.Enum("LONG", "SHORT", name="direction_t", create_type=False),
            nullable=False,
        ),
        sa.Column("lot_size", sa.Numeric(18, 6), nullable=False),
        sa.Column("requested_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("filled_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("filled_volume", sa.Numeric(18, 6), nullable=True),
        sa.Column("sl", sa.Numeric(18, 6), nullable=True),
        sa.Column("tp", sa.Numeric(18, 6), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "FILLED", "CANCELLED", "REJECTED", "EXPIRED",
                name="order_status_t",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "alert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "trade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trades.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_orders_trade_id", "orders", ["trade_id"])
    op.create_index("ix_orders_alert_id", "orders", ["alert_id"])
    op.create_index("ix_orders_user_status", "orders", ["user_id", "status"])

    # -------------------------------------------------------------------------
    # settings
    # -------------------------------------------------------------------------
    op.create_table(
        "settings",
        sa.Column("user_id", sa.String(), primary_key=True, server_default="system"),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column(
            "ai_primary_model",
            sa.String(),
            nullable=False,
            server_default="claude-sonnet-4-6",
        ),
        sa.Column(
            "ai_screening_model",
            sa.String(),
            nullable=False,
            server_default="claude-haiku-4-5",
        ),
        sa.Column(
            "ai_monthly_budget_usd",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="30.00",
        ),
        sa.Column(
            "ai_used_current_month_usd",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("alert_sound", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column(
            "desktop_notifications", sa.Boolean(), nullable=False, server_default="TRUE"
        ),
        sa.Column(
            "auto_screenshot_on_open", sa.Boolean(), nullable=False, server_default="TRUE"
        ),
        sa.Column(
            "auto_screenshot_interval", sa.Integer(), nullable=False, server_default="15"
        ),
        sa.Column(
            "max_risk_pct", sa.Numeric(5, 2), nullable=False, server_default="1.00"
        ),
        sa.Column(
            "max_daily_loss_pct", sa.Numeric(5, 2), nullable=False, server_default="3.00"
        ),
        sa.Column(
            "max_concurrent_positions", sa.Integer(), nullable=False, server_default="3"
        ),
        sa.Column(
            "require_checklist", sa.Boolean(), nullable=False, server_default="FALSE"
        ),
        sa.Column("timezone", sa.String(), nullable=False, server_default="UTC"),
        sa.Column("theme", sa.String(), nullable=False, server_default="dark"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Seed default settings row for 'system' user
    op.execute(
        "INSERT INTO settings (user_id) VALUES ('system') ON CONFLICT DO NOTHING"
    )

    # -------------------------------------------------------------------------
    # broker_connections
    # -------------------------------------------------------------------------
    op.create_table(
        "broker_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False, server_default="system"),
        sa.Column("broker", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("encrypted_creds", sa.LargeBinary(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("environment", sa.String(), nullable=True),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default="FALSE"),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_broker_connections_user_id", "broker_connections", ["user_id"])

    # -------------------------------------------------------------------------
    # updated_at trigger function (auto-update on row modification)
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    for table in ("trades", "prop_firm_profiles", "orders"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )

    # -------------------------------------------------------------------------
    # TimescaleDB hypertable for candles (best-effort — skip if extension absent)
    # -------------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'
            ) THEN
                PERFORM create_hypertable(
                    'candles', 'time',
                    partitioning_column => 'pair',
                    number_partitions => 4,
                    if_not_exists => TRUE
                );
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Drop triggers
    for table in ("orders", "prop_firm_profiles", "trades"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

    # Drop tables in reverse dependency order
    op.drop_table("broker_connections")
    op.drop_table("settings")
    op.drop_table("orders")
    op.drop_table("scoring_profiles")
    op.drop_table("prop_firm_snapshots")
    op.drop_table("prop_firm_profiles")
    op.drop_table("checklists")
    op.drop_table("edit_diffs")
    op.drop_table("audit_log")
    op.drop_table("alerts")
    op.drop_table("ai_analyses")
    op.drop_table("screenshots")
    op.drop_table("ict_detections")
    op.drop_table("candles")
    op.drop_table("trades")

    # Drop enum types
    for enum_name in (
        "order_status_t",
        "order_type_t",
        "compliance_t",
        "actor_t",
        "screenshot_trig_t",
        "ict_status_t",
        "ict_dir_t",
        "ict_type_t",
        "alert_status_t",
        "alert_priority_t",
        "alert_type_t",
        "trade_status_t",
        "outcome_t",
        "direction_t",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
