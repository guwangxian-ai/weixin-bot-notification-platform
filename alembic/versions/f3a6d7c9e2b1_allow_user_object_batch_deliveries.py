"""allow user-object deliveries without synthetic target members

Revision ID: f3a6d7c9e2b1
Revises: 9b72e4c1d6a0
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3a6d7c9e2b1"
down_revision: str | Sequence[str] | None = "9b72e4c1d6a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_delivery_platform_tenant_update")
    op.execute("DROP TRIGGER IF EXISTS trg_delivery_platform_tenant_insert")
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
                  (t.is_user_object = 1 OR t.mode = 'DYNAMIC_ALL'
                   OR t.employee_id = NEW.employee_id)))
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
                  (t.is_user_object = 1 OR t.mode = 'DYNAMIC_ALL'
                   OR t.employee_id = NEW.employee_id)))
          ) THEN RAISE(ABORT, 'delivery platform tenant mismatch') END;
        END"""
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_delivery_platform_tenant_update")
    op.execute("DROP TRIGGER IF EXISTS trg_delivery_platform_tenant_insert")
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
