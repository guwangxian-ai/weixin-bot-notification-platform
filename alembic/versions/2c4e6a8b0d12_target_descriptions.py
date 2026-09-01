"""add notification target descriptions

Revision ID: 2c4e6a8b0d12
Revises: f3a6d7c9e2b1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2c4e6a8b0d12"
down_revision: str | Sequence[str] | None = "f3a6d7c9e2b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_targets",
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )


def downgrade() -> None:
    op.drop_column("notification_targets", "description")
