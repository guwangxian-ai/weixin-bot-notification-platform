"""add binding welcome and manual test notification metadata

Revision ID: f91c3a7d5e20
Revises: e7b4c2d91a30
Create Date: 2026-08-20 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f91c3a7d5e20"
down_revision: str | Sequence[str] | None = "e7b4c2d91a30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "employee_bot_bindings",
        sa.Column("last_manual_test_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.add_column(
            sa.Column(
            "notification_type",
            sa.String(length=40),
            nullable=False,
            server_default="business",
            )
        )
        batch_op.add_column(sa.Column("binding_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_deliveries_binding_id_employee_bot_bindings",
            "employee_bot_bindings",
            ["binding_id"],
            ["id"],
        )
    op.create_index(
        "ix_deliveries_notification_type",
        "deliveries",
        ["notification_type"],
        unique=False,
    )
    op.create_index("ix_deliveries_binding_id", "deliveries", ["binding_id"], unique=False)
    op.create_index(
        "uq_deliveries_binding_welcome",
        "deliveries",
        ["binding_id"],
        unique=True,
        sqlite_where=sa.text("notification_type = 'binding_welcome'"),
    )


def downgrade() -> None:
    op.drop_index("uq_deliveries_binding_welcome", table_name="deliveries")
    op.drop_index("ix_deliveries_binding_id", table_name="deliveries")
    op.drop_index("ix_deliveries_notification_type", table_name="deliveries")
    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.drop_constraint(
            "fk_deliveries_binding_id_employee_bot_bindings", type_="foreignkey"
        )
        batch_op.drop_column("binding_id")
        batch_op.drop_column("notification_type")
    op.drop_column("employee_bot_bindings", "last_manual_test_at")