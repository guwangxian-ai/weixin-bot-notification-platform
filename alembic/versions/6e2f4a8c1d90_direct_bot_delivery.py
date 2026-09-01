"""backfill preliminary Weixin Bot owner targets

Revision ID: 6e2f4a8c1d90
Revises: 2c4e6a8b0d12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6e2f4a8c1d90"
down_revision: str | Sequence[str] | None = "2c4e6a8b0d12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # QR confirmation stores the owner's encrypted iLink user id on the account. Copy it
    # to the binding as the preliminary DM target. The channel still needs an inbound
    # context token before iLink permits the Bot's first outbound message.
    op.execute(
        sa.text(
            """
            UPDATE employee_bot_bindings
            SET chat_id_encrypted = (
                SELECT weixin_bot_accounts.owner_user_id_encrypted
                FROM weixin_bot_accounts
                WHERE weixin_bot_accounts.id = employee_bot_bindings.bot_account_id
            )
            WHERE active = 1
              AND chat_id_encrypted IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM weixin_bot_accounts
                  WHERE weixin_bot_accounts.id = employee_bot_bindings.bot_account_id
                    AND weixin_bot_accounts.owner_user_id_encrypted IS NOT NULL
              )
            """
        )
    )


def downgrade() -> None:
    # The copied encrypted target is indistinguishable from a target later refreshed by
    # an inbound event. Removing it would break existing binding metadata.
    pass
