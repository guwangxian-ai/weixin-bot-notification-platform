"""encrypt independent Bot chat identity

Revision ID: d19a4c6e8b27
Revises: c84e2a7d5f10
Create Date: 2026-08-19 01:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d19a4c6e8b27"
down_revision: str | Sequence[str] | None = "c84e2a7d5f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "employee_bot_bindings",
        sa.Column("chat_id_encrypted", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("employee_bot_bindings", "chat_id_encrypted")
