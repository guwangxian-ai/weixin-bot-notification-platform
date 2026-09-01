"""add independent employee iLink bot binding lifecycle

Revision ID: b71f2b8c901d
Revises: 4ad8c89c24fc
Create Date: 2026-08-18 22:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b71f2b8c901d"
down_revision: str | Sequence[str] | None = "4ad8c89c24fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weixin_bot_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("account_id_encrypted", sa.Text(), nullable=False),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=False),
        sa.Column("base_url_encrypted", sa.Text(), nullable=False),
        sa.Column("owner_user_id_encrypted", sa.Text(), nullable=False),
        sa.Column("account_id_masked", sa.String(length=40), nullable=False),
        sa.Column(
            "health_status",
            sa.Enum("UNKNOWN", "HEALTHY", "DEGRADED", "REVOKED", name="bothealthstatus"),
            nullable=False,
        ),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_fingerprint"),
    )
    op.create_table(
        "employee_bot_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.String(length=36), nullable=False),
        sa.Column("bot_account_id", sa.String(length=36), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["bot_account_id"], ["weixin_bot_accounts.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_employee_bot_bindings_active", "employee_bot_bindings", ["active"], unique=False
    )
    op.create_index(
        "ix_employee_bot_bindings_bot_account_id",
        "employee_bot_bindings",
        ["bot_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_employee_bot_bindings_company_id",
        "employee_bot_bindings",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_employee_bot_bindings_employee_id",
        "employee_bot_bindings",
        ["employee_id"],
        unique=False,
    )
    op.create_index(
        "uq_employee_bot_bindings_active_account",
        "employee_bot_bindings",
        ["bot_account_id"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
    )
    op.create_index(
        "uq_employee_bot_bindings_active_employee",
        "employee_bot_bindings",
        ["employee_id"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
    )
    op.create_table(
        "weixin_binding_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "SCANNED",
                "CONFIRMING",
                "BOUND",
                "EXPIRED",
                "CANCELLED",
                "FAILED",
                "REVOKED",
                name="bindingsessionstatus",
            ),
            nullable=False,
        ),
        sa.Column("official_ticket_encrypted", sa.Text(), nullable=False),
        sa.Column("scan_data_encrypted", sa.Text(), nullable=False),
        sa.Column("base_url_encrypted", sa.Text(), nullable=False),
        sa.Column("current_base_url_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_weixin_binding_sessions_company_id",
        "weixin_binding_sessions",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_weixin_binding_sessions_employee_id",
        "weixin_binding_sessions",
        ["employee_id"],
        unique=False,
    )
    op.create_index(
        "ix_weixin_binding_sessions_status",
        "weixin_binding_sessions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_weixin_binding_sessions_live_employee",
        "weixin_binding_sessions",
        ["employee_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('PENDING', 'SCANNED', 'CONFIRMING')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_weixin_binding_sessions_live_employee", table_name="weixin_binding_sessions"
    )
    op.drop_index("ix_weixin_binding_sessions_status", table_name="weixin_binding_sessions")
    op.drop_index("ix_weixin_binding_sessions_employee_id", table_name="weixin_binding_sessions")
    op.drop_index("ix_weixin_binding_sessions_company_id", table_name="weixin_binding_sessions")
    op.drop_table("weixin_binding_sessions")
    op.drop_index(
        "uq_employee_bot_bindings_active_employee", table_name="employee_bot_bindings"
    )
    op.drop_index("uq_employee_bot_bindings_active_account", table_name="employee_bot_bindings")
    op.drop_index("ix_employee_bot_bindings_employee_id", table_name="employee_bot_bindings")
    op.drop_index("ix_employee_bot_bindings_company_id", table_name="employee_bot_bindings")
    op.drop_index("ix_employee_bot_bindings_bot_account_id", table_name="employee_bot_bindings")
    op.drop_index("ix_employee_bot_bindings_active", table_name="employee_bot_bindings")
    op.drop_table("employee_bot_bindings")
    op.drop_table("weixin_bot_accounts")
