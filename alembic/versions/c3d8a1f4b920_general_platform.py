"""general multi-company notification platform

Revision ID: c3d8a1f4b920
Revises: f91c3a7d5e20
Create Date: 2026-08-20 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d8a1f4b920"
down_revision: str | Sequence[str] | None = "f91c3a7d5e20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("slug", sa.String(length=64), nullable=True))
    op.add_column("companies", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("companies", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE companies SET slug = id, updated_at = created_at")
    with op.batch_alter_table("companies") as batch_op:
        batch_op.alter_column("slug", existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column(
            "updated_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )
    op.create_index("ix_companies_slug", "companies", ["slug"], unique=True)

    op.create_table(
        "notification_targets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=64), nullable=False),
        sa.Column("target_code", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=11), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("employee_id", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.UniqueConstraint("company_id", "target_code", name="uq_target_company_code"),
    )
    op.create_index("ix_notification_targets_company_id", "notification_targets", ["company_id"])
    op.create_index("ix_notification_targets_employee_id", "notification_targets", ["employee_id"])
    op.create_index("ix_notification_targets_enabled", "notification_targets", ["enabled"])

    op.create_table(
        "target_bot_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("bot_account_id", sa.String(length=36), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["notification_targets.id"]),
        sa.ForeignKeyConstraint(["binding_id"], ["employee_bot_bindings.id"]),
        sa.ForeignKeyConstraint(["bot_account_id"], ["weixin_bot_accounts.id"]),
    )
    for column in ("company_id", "target_id", "binding_id", "bot_account_id", "active"):
        op.create_index(f"ix_target_bot_members_{column}", "target_bot_members", [column])
    op.create_index(
        "uq_target_bot_members_active_binding",
        "target_bot_members",
        ["target_id", "binding_id"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
    )

    op.create_table(
        "api_clients",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=24), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("allowed_target_codes", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
    )
    op.create_index("ix_api_clients_company_id", "api_clients", ["company_id"])
    op.create_index("ix_api_clients_token_hash", "api_clients", ["token_hash"], unique=True)
    op.create_index("ix_api_clients_token_prefix", "api_clients", ["token_prefix"])
    op.create_index("ix_api_clients_enabled", "api_clients", ["enabled"])

    op.create_table(
        "notification_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("api_client_id", sa.String(length=36), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("notification_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["notification_targets.id"]),
        sa.ForeignKeyConstraint(["api_client_id"], ["api_clients.id"]),
        sa.UniqueConstraint(
            "company_id", "target_id", "idempotency_key", name="uq_batch_target_key"
        ),
    )
    for column in ("company_id", "target_id", "api_client_id", "status"):
        op.create_index(f"ix_notification_batches_{column}", "notification_batches", [column])

    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.add_column(sa.Column("batch_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("target_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("target_member_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_delivery_batch", "notification_batches", ["batch_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_delivery_target", "notification_targets", ["target_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_delivery_target_member",
            "target_bot_members",
            ["target_member_id"],
            ["id"],
        )
    op.create_index("ix_deliveries_batch_id", "deliveries", ["batch_id"])
    op.create_index("ix_deliveries_target_id", "deliveries", ["target_id"])
    op.create_index("ix_deliveries_target_member_id", "deliveries", ["target_member_id"])

    # Deterministic compatibility targets preserve every existing employee and binding.
    op.execute(
        """INSERT INTO notification_targets
        (id, company_id, target_code, display_name, mode, enabled, employee_id,
         created_at, updated_at)
        SELECT id, company_id, 'employee-' || id, name, 'SINGLE',
               CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END, id, created_at, updated_at
        FROM employees"""
    )
    op.execute(
        """INSERT INTO target_bot_members
        (id, company_id, target_id, binding_id, bot_account_id, active, created_at, removed_at)
        SELECT id, company_id, employee_id, id, bot_account_id, active, bound_at, revoked_at
        FROM employee_bot_bindings"""
    )
    op.execute(
        """UPDATE deliveries SET target_id = employee_id,
        target_member_id = binding_id WHERE employee_id IS NOT NULL"""
    )
    op.execute(
        """CREATE TRIGGER trg_employee_company_immutable
        BEFORE UPDATE OF company_id ON employees
        WHEN NEW.company_id <> OLD.company_id BEGIN
          SELECT RAISE(ABORT, 'employee company is immutable');
        END"""
    )
    op.execute(
        """CREATE TRIGGER trg_bot_binding_identity_immutable
        BEFORE UPDATE OF company_id, employee_id, bot_account_id ON employee_bot_bindings
        WHEN NEW.company_id <> OLD.company_id OR NEW.employee_id <> OLD.employee_id
          OR NEW.bot_account_id <> OLD.bot_account_id BEGIN
          SELECT RAISE(ABORT, 'bot binding identity is immutable');
        END"""
    )
    op.execute(
        """CREATE TRIGGER trg_notification_target_employee_tenant_insert
        BEFORE INSERT ON notification_targets WHEN NEW.employee_id IS NOT NULL BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM employees e
            WHERE e.id = NEW.employee_id AND e.company_id = NEW.company_id
          ) THEN RAISE(ABORT, 'notification target employee tenant mismatch') END;
        END"""
    )
    op.execute(
        """CREATE TRIGGER trg_notification_target_employee_tenant_update
        BEFORE UPDATE ON notification_targets WHEN NEW.employee_id IS NOT NULL BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM employees e
            WHERE e.id = NEW.employee_id AND e.company_id = NEW.company_id
          ) THEN RAISE(ABORT, 'notification target employee tenant mismatch') END;
        END"""
    )
    op.execute(
        """CREATE TRIGGER trg_target_member_tenant_insert
        BEFORE INSERT ON target_bot_members BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM notification_targets t
            JOIN employee_bot_bindings b ON b.id = NEW.binding_id
            JOIN employees e ON e.id = b.employee_id
            WHERE t.id = NEW.target_id AND t.company_id = NEW.company_id
              AND b.company_id = NEW.company_id AND b.bot_account_id = NEW.bot_account_id
              AND e.company_id = NEW.company_id
          ) THEN RAISE(ABORT, 'target member tenant mismatch') END;
        END"""
    )
    op.execute(
        """CREATE TRIGGER trg_target_member_tenant_update
        BEFORE UPDATE ON target_bot_members BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM notification_targets t
            JOIN employee_bot_bindings b ON b.id = NEW.binding_id
            JOIN employees e ON e.id = b.employee_id
            WHERE t.id = NEW.target_id AND t.company_id = NEW.company_id
              AND b.company_id = NEW.company_id AND b.bot_account_id = NEW.bot_account_id
              AND e.company_id = NEW.company_id
          ) THEN RAISE(ABORT, 'target member tenant mismatch') END;
        END"""
    )
    op.execute(
        """CREATE TRIGGER trg_notification_batch_tenant_insert
        BEFORE INSERT ON notification_batches BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM notification_targets t
            WHERE t.id = NEW.target_id AND t.company_id = NEW.company_id
          ) OR (NEW.api_client_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM api_clients c
            WHERE c.id = NEW.api_client_id AND c.company_id = NEW.company_id
          )) THEN RAISE(ABORT, 'notification batch tenant mismatch') END;
        END"""
    )
    op.execute(
        """CREATE TRIGGER trg_notification_batch_tenant_update
        BEFORE UPDATE ON notification_batches BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM notification_targets t
            WHERE t.id = NEW.target_id AND t.company_id = NEW.company_id
          ) OR (NEW.api_client_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM api_clients c
            WHERE c.id = NEW.api_client_id AND c.company_id = NEW.company_id
          )) THEN RAISE(ABORT, 'notification batch tenant mismatch') END;
        END"""
    )
    op.execute(
        """CREATE TRIGGER trg_delivery_platform_tenant_insert
        BEFORE INSERT ON deliveries WHEN NEW.batch_id IS NOT NULL BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM notification_batches n
            JOIN notification_targets t ON t.id = NEW.target_id
            JOIN employee_bot_bindings b ON b.id = NEW.binding_id
            JOIN employees e ON e.id = NEW.employee_id
            WHERE n.id = NEW.batch_id AND n.company_id = NEW.company_id
              AND n.target_id = NEW.target_id AND t.company_id = NEW.company_id
              AND b.company_id = NEW.company_id AND b.employee_id = NEW.employee_id
              AND e.company_id = NEW.company_id
              AND ((NEW.target_member_id IS NOT NULL AND EXISTS (
                  SELECT 1 FROM target_bot_members m
                  WHERE m.id = NEW.target_member_id AND m.company_id = NEW.company_id
                    AND m.target_id = NEW.target_id AND m.binding_id = NEW.binding_id
                )) OR (NEW.target_member_id IS NULL AND
                  (t.mode = 'DYNAMIC_ALL' OR t.employee_id = NEW.employee_id)))
          ) THEN RAISE(ABORT, 'delivery platform tenant mismatch') END;
        END"""
    )
    op.execute(
        """CREATE TRIGGER trg_delivery_platform_tenant_update
        BEFORE UPDATE ON deliveries
        WHEN OLD.batch_id IS NOT NULL OR NEW.batch_id IS NOT NULL BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM notification_batches n
            JOIN notification_targets t ON t.id = NEW.target_id
            JOIN employee_bot_bindings b ON b.id = NEW.binding_id
            JOIN employees e ON e.id = NEW.employee_id
            WHERE n.id = NEW.batch_id AND n.company_id = NEW.company_id
              AND n.target_id = NEW.target_id AND t.company_id = NEW.company_id
              AND b.company_id = NEW.company_id AND b.employee_id = NEW.employee_id
              AND e.company_id = NEW.company_id
              AND ((NEW.target_member_id IS NOT NULL AND EXISTS (
                  SELECT 1 FROM target_bot_members m
                  WHERE m.id = NEW.target_member_id AND m.company_id = NEW.company_id
                    AND m.target_id = NEW.target_id AND m.binding_id = NEW.binding_id
                )) OR (NEW.target_member_id IS NULL AND
                  (t.mode = 'DYNAMIC_ALL' OR t.employee_id = NEW.employee_id)))
          ) THEN RAISE(ABORT, 'delivery platform tenant mismatch') END;
        END"""
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_delivery_platform_tenant_update")
    op.execute("DROP TRIGGER IF EXISTS trg_delivery_platform_tenant_insert")
    op.execute("DROP TRIGGER IF EXISTS trg_notification_batch_tenant_update")
    op.execute("DROP TRIGGER IF EXISTS trg_notification_batch_tenant_insert")
    op.execute("DROP TRIGGER IF EXISTS trg_target_member_tenant_update")
    op.execute("DROP TRIGGER IF EXISTS trg_target_member_tenant_insert")
    op.execute("DROP TRIGGER IF EXISTS trg_notification_target_employee_tenant_update")
    op.execute("DROP TRIGGER IF EXISTS trg_notification_target_employee_tenant_insert")
    op.execute("DROP TRIGGER IF EXISTS trg_bot_binding_identity_immutable")
    op.execute("DROP TRIGGER IF EXISTS trg_employee_company_immutable")
    op.drop_index("ix_deliveries_target_member_id", table_name="deliveries")
    op.drop_index("ix_deliveries_target_id", table_name="deliveries")
    op.drop_index("ix_deliveries_batch_id", table_name="deliveries")
    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.drop_constraint("fk_delivery_target_member", type_="foreignkey")
        batch_op.drop_constraint("fk_delivery_target", type_="foreignkey")
        batch_op.drop_constraint("fk_delivery_batch", type_="foreignkey")
        batch_op.drop_column("target_member_id")
        batch_op.drop_column("target_id")
        batch_op.drop_column("batch_id")
    op.drop_table("notification_batches")
    op.drop_table("api_clients")
    op.drop_table("target_bot_members")
    op.drop_table("notification_targets")
    op.drop_index("ix_companies_slug", table_name="companies")
    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("slug")
