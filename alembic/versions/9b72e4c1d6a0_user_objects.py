"""user objects and encrypted employee contact phones

Revision ID: 9b72e4c1d6a0
Revises: c3d8a1f4b920
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9b72e4c1d6a0"
down_revision: str | Sequence[str] | None = "c3d8a1f4b920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    ambiguous = connection.execute(
        sa.text(
            """SELECT a.id FROM weixin_bot_accounts a
            JOIN employee_bot_bindings b ON b.bot_account_id = a.id
            GROUP BY a.id HAVING COUNT(DISTINCT b.company_id) > 1"""
        )
    ).first()
    if ambiguous is not None:
        raise RuntimeError("Bot account has historical bindings across multiple companies")
    orphan = connection.execute(
        sa.text(
            """SELECT a.id FROM weixin_bot_accounts a
            LEFT JOIN employee_bot_bindings b ON b.bot_account_id = a.id
            GROUP BY a.id HAVING COUNT(b.id) = 0 LIMIT 1"""
        )
    ).first()
    if orphan is not None:
        raise RuntimeError("Bot account has no company ownership source")
    op.add_column(
        "weixin_bot_accounts", sa.Column("company_id", sa.String(length=64), nullable=True)
    )
    op.execute(
        """UPDATE weixin_bot_accounts
        SET company_id = (
          SELECT MIN(b.company_id) FROM employee_bot_bindings b
          WHERE b.bot_account_id = weixin_bot_accounts.id
        )"""
    )
    with op.batch_alter_table("weixin_bot_accounts") as batch_op:
        batch_op.alter_column("company_id", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_foreign_key(
            "fk_weixin_bot_accounts_company_id", "companies", ["company_id"], ["id"]
        )
    op.create_index(
        "ix_weixin_bot_accounts_company_id", "weixin_bot_accounts", ["company_id"]
    )
    binding_guard = """BEGIN
      SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM employees e JOIN weixin_bot_accounts a ON a.id = NEW.bot_account_id
        WHERE e.id = NEW.employee_id AND e.company_id = NEW.company_id
          AND a.company_id = NEW.company_id
      ) THEN RAISE(ABORT, 'bot binding tenant mismatch') END;
    END"""
    op.execute(
        "CREATE TRIGGER trg_bot_binding_tenant_insert "
        "BEFORE INSERT ON employee_bot_bindings " + binding_guard
    )
    op.execute(
        "CREATE TRIGGER trg_bot_binding_tenant_update "
        "BEFORE UPDATE ON employee_bot_bindings " + binding_guard
    )
    op.execute(
        """CREATE TRIGGER trg_bot_account_company_immutable
        BEFORE UPDATE OF company_id ON weixin_bot_accounts
        WHEN NEW.company_id IS NOT OLD.company_id
        BEGIN
          SELECT RAISE(ABORT, 'bot account company is immutable');
        END"""
    )
    op.add_column("employees", sa.Column("phone_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "employees", sa.Column("phone_fingerprint", sa.String(length=64), nullable=True)
    )
    op.add_column("employees", sa.Column("phone_masked", sa.String(length=40), nullable=True))
    op.create_index("ix_employees_phone_fingerprint", "employees", ["phone_fingerprint"])
    op.add_column(
        "notification_targets",
        sa.Column("is_user_object", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index(
        "ix_notification_targets_is_user_object",
        "notification_targets",
        ["is_user_object"],
    )
    op.create_table(
        "user_object_contacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("employee_id", sa.String(length=36), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["notification_targets.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
    )
    for column in ("company_id", "target_id", "employee_id", "active"):
        op.create_index(
            f"ix_user_object_contacts_{column}", "user_object_contacts", [column]
        )
    op.create_index(
        "uq_user_object_contacts_active_employee",
        "user_object_contacts",
        ["target_id", "employee_id"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
    )
    trigger_body = """BEGIN
      SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM notification_targets t
        JOIN employees e ON e.id = NEW.employee_id
        WHERE t.id = NEW.target_id AND t.company_id = NEW.company_id
          AND t.is_user_object = 1 AND e.company_id = NEW.company_id
      ) THEN RAISE(ABORT, 'user object contact tenant mismatch') END;
    END"""
    op.execute(
        "CREATE TRIGGER trg_user_object_contact_tenant_insert "
        "BEFORE INSERT ON user_object_contacts " + trigger_body
    )
    op.execute(
        "CREATE TRIGGER trg_user_object_contact_tenant_update "
        "BEFORE UPDATE ON user_object_contacts " + trigger_body
    )


def downgrade() -> None:
    # SQLite otherwise rejects Alembic's copy-and-rename batches while predecessor
    # triggers temporarily reference the table name being rebuilt.
    op.execute("PRAGMA legacy_alter_table=ON")
    op.execute("DROP TRIGGER IF EXISTS trg_bot_account_company_immutable")
    op.execute("DROP TRIGGER IF EXISTS trg_bot_binding_tenant_update")
    op.execute("DROP TRIGGER IF EXISTS trg_bot_binding_tenant_insert")
    op.execute("DROP TRIGGER IF EXISTS trg_user_object_contact_tenant_update")
    op.execute("DROP TRIGGER IF EXISTS trg_user_object_contact_tenant_insert")
    op.drop_table("user_object_contacts")
    op.drop_index("ix_notification_targets_is_user_object", table_name="notification_targets")
    with op.batch_alter_table("notification_targets") as batch_op:
        batch_op.drop_column("is_user_object")
    op.drop_index("ix_employees_phone_fingerprint", table_name="employees")
    with op.batch_alter_table("employees") as batch_op:
        batch_op.drop_column("phone_masked")
        batch_op.drop_column("phone_fingerprint")
        batch_op.drop_column("phone_encrypted")
    op.drop_index("ix_weixin_bot_accounts_company_id", table_name="weixin_bot_accounts")
    with op.batch_alter_table("weixin_bot_accounts") as batch_op:
        batch_op.drop_constraint("fk_weixin_bot_accounts_company_id", type_="foreignkey")
        batch_op.drop_column("company_id")
    op.execute("PRAGMA legacy_alter_table=OFF")
