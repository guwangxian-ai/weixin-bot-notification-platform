"""track one-time video claims and delivery phases

Revision ID: e7b4c2d91a30
Revises: a63f91d7c2e4
Create Date: 2026-08-20 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7b4c2d91a30"
down_revision: str | Sequence[str] | None = "a63f91d7c2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "video_assets",
        sa.Column("claimed_delivery_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "video_assets",
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "video_assets",
        sa.Column("file_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_video_assets_claimed_delivery_id",
        "video_assets",
        ["claimed_delivery_id"],
        unique=True,
    )
    op.add_column(
        "deliveries",
        sa.Column("dispatch_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "deliveries",
        sa.Column("dispatch_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_deliveries_dispatch_token",
        "deliveries",
        ["dispatch_token"],
        unique=False,
    )
    op.add_column(
        "deliveries",
        sa.Column("text_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "deliveries",
        sa.Column("media_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """UPDATE deliveries
        SET text_sent_at = updated_at
        WHERE status IN ('SENT', 'CONFIRMED')
          AND (title <> '' OR body <> '')"""
    )
    op.execute(
        """UPDATE deliveries
        SET media_sent_at = updated_at
        WHERE status IN ('SENT', 'CONFIRMED')
          AND video_asset_id IS NOT NULL"""
    )
    op.execute(
        """UPDATE video_assets
        SET consumed_at = (
            SELECT MAX(deliveries.updated_at)
            FROM deliveries
            WHERE deliveries.video_asset_id = video_assets.id
              AND deliveries.status IN ('SENT', 'CONFIRMED')
        )
        WHERE EXISTS (
            SELECT 1 FROM deliveries
            WHERE deliveries.video_asset_id = video_assets.id
              AND deliveries.status IN ('SENT', 'CONFIRMED')
        )"""
    )
    op.execute(
        """UPDATE video_assets
        SET claimed_delivery_id = (
            SELECT deliveries.id
            FROM deliveries
            WHERE deliveries.video_asset_id = video_assets.id
            ORDER BY
                CASE deliveries.status
                    WHEN 'FAILED' THEN 0
                    WHEN 'WAITING_INTERACTION' THEN 1
                    WHEN 'RETRYING' THEN 2
                    WHEN 'PENDING' THEN 3
                    WHEN 'SENDING' THEN 4
                    ELSE 5
                END,
                deliveries.created_at,
                deliveries.id
            LIMIT 1
        )
        WHERE consumed_at IS NULL
          AND EXISTS (
              SELECT 1 FROM deliveries
              WHERE deliveries.video_asset_id = video_assets.id
          )"""
    )


def downgrade() -> None:
    op.drop_column("deliveries", "media_sent_at")
    op.drop_column("deliveries", "text_sent_at")
    op.drop_index("ix_deliveries_dispatch_token", table_name="deliveries")
    op.drop_column("deliveries", "dispatch_lease_expires_at")
    op.drop_column("deliveries", "dispatch_token")
    op.drop_index("ix_video_assets_claimed_delivery_id", table_name="video_assets")
    op.drop_column("video_assets", "file_deleted_at")
    op.drop_column("video_assets", "consumed_at")
    op.drop_column("video_assets", "claimed_delivery_id")
