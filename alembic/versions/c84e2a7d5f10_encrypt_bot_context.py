"""encrypt independent Bot conversation context

Revision ID: c84e2a7d5f10
Revises: b71f2b8c901d
Create Date: 2026-08-19 00:55:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c84e2a7d5f10"
down_revision: str | Sequence[str] | None = "b71f2b8c901d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "employee_bot_bindings",
        sa.Column("context_token_encrypted", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("employee_bot_bindings", "context_token_encrypted")
