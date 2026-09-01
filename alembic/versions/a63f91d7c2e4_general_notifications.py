"""support text notifications with optional video attachments

Revision ID: a63f91d7c2e4
Revises: d19a4c6e8b27
Create Date: 2026-08-19 06:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a63f91d7c2e4"
down_revision: str | Sequence[str] | None = "d19a4c6e8b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deliveries",
        sa.Column("title", sa.String(length=240), nullable=False, server_default=""),
    )
    op.add_column(
        "deliveries",
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
    )
    op.execute(
        """UPDATE deliveries
        SET title = COALESCE(
                (SELECT video_assets.title FROM video_assets
                 WHERE video_assets.id = deliveries.video_asset_id),
                ''
            ),
            body = COALESCE(
                (SELECT video_assets.caption FROM video_assets
                 WHERE video_assets.id = deliveries.video_asset_id),
                ''
            )"""
    )
    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.alter_column(
            "video_asset_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.alter_column("title", server_default=None)
        batch_op.alter_column("body", server_default=None)


def downgrade() -> None:
    connection = op.get_bind()
    text_only = connection.execute(
        sa.text("SELECT COUNT(*) FROM deliveries WHERE video_asset_id IS NULL")
    ).scalar_one()
    if text_only:
        raise RuntimeError("Cannot downgrade while text-only notifications exist")
    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.alter_column(
            "video_asset_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch_op.drop_column("body")
        batch_op.drop_column("title")