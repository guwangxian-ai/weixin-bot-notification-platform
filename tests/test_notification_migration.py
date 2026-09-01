from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest


def run_alembic(database: Path, revision: str) -> None:
    env = {**os.environ, "APP_DATABASE_URL": f"sqlite:///{database}"}
    subprocess.run(  # noqa: S603 - fixed project executable and test-owned revision
        [".venv/bin/alembic", "upgrade", revision],
        check=True,
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )


def test_notification_migration_preserves_historical_video_delivery(tmp_path: Path) -> None:
    database = tmp_path / "historical.db"
    run_alembic(database, "d19a4c6e8b27")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO companies (id, name, enabled, created_at)
            VALUES ('greenhome', '绿色家装饰', 1, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO employees
            (id, company_id, name, department, content_vertical, secondary_topics,
             target_platforms, account_name, tone, video_duration_seconds,
             publishing_frequency, status, created_at, updated_at)
            VALUES ('employee-1', 'greenhome', '历史员工', '', '', '[]', '[]', '', '',
                    60, '', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO video_assets
            (id, company_id, employee_id, title, caption, original_filename, storage_path,
             content_type, size_bytes, sha256, created_at)
            VALUES ('asset-1', 'greenhome', 'employee-1', '历史标题', '历史正文',
                    'history.mp4', '/tmp/history.mp4', 'video/mp4', 12,
                    '0000000000000000000000000000000000000000000000000000000000000000',
                    CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO video_assets
            (id, company_id, employee_id, title, caption, original_filename, storage_path,
             content_type, size_bytes, sha256, created_at)
            VALUES ('asset-2', 'greenhome', 'employee-1', '待重试标题', '待重试正文',
                    'retry.mp4', '/tmp/retry.mp4', 'video/mp4', 12,
                    '1111111111111111111111111111111111111111111111111111111111111111',
                    CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO deliveries
            (id, company_id, employee_id, video_asset_id, idempotency_key, status,
             retry_count, created_at, updated_at)
            VALUES ('delivery-1', 'greenhome', 'employee-1', 'asset-1', 'historical-1',
                    'SENT', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO deliveries
            (id, company_id, employee_id, video_asset_id, idempotency_key, status,
             retry_count, created_at, updated_at)
            VALUES ('delivery-2', 'greenhome', 'employee-1', 'asset-2', 'historical-2',
                    'FAILED', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.commit()

    run_alembic(database, "head")

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT video_asset_id, title, body, status FROM deliveries WHERE id = 'delivery-1'"
        ).fetchone()
        columns = {
            item[1]: item[3] for item in connection.execute("PRAGMA table_info(deliveries)")
        }
        historical_claim = connection.execute(
            "SELECT claimed_delivery_id, consumed_at FROM video_assets WHERE id = 'asset-2'"
        ).fetchone()
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    assert row == ("asset-1", "历史标题", "历史正文", "SENT")
    assert columns["video_asset_id"] == 0
    assert historical_claim == ("delivery-2", None)


def test_binding_notification_migration_preserves_existing_rows(tmp_path: Path) -> None:
    database = tmp_path / "binding-notifications.db"
    run_alembic(database, "e7b4c2d91a30")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO companies (id, name, enabled, created_at)
            VALUES ('tenant', '测试租户', 1, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO employees
            (id, company_id, name, department, content_vertical, secondary_topics,
             target_platforms, account_name, tone, video_duration_seconds,
             publishing_frequency, status, created_at, updated_at)
            VALUES ('employee', 'tenant', '历史员工', '', '', '[]', '[]', '', '',
                    60, '', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO deliveries
            (id, company_id, employee_id, title, body, idempotency_key, status,
             retry_count, created_at, updated_at)
            VALUES ('delivery', 'tenant', 'employee', '历史通知', '', 'historical',
                    'SENT', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.commit()

    run_alembic(database, "head")

    with sqlite3.connect(database) as connection:
        delivery = connection.execute(
            "SELECT notification_type, binding_id FROM deliveries WHERE id = 'delivery'"
        ).fetchone()
        binding_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(employee_bot_bindings)")
        }
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert delivery == ("business", None)
    assert "last_manual_test_at" in binding_columns


def test_general_platform_migration_maps_existing_employee_and_binding_once(tmp_path: Path) -> None:
    database = tmp_path / "general-platform.db"
    run_alembic(database, "f91c3a7d5e20")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO companies (id, name, enabled, created_at) "
            "VALUES ('greenhome', '绿色家装饰', 1, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            """INSERT INTO employees
            (id, company_id, name, department, content_vertical, secondary_topics,
             target_platforms, account_name, tone, video_duration_seconds,
             publishing_frequency, status, created_at, updated_at)
            VALUES ('employee-1', 'greenhome', '历史对象', '', '', '[]', '[]', '', '',
                    60, '', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO weixin_bot_accounts
            (id, account_fingerprint, account_id_encrypted, bot_token_encrypted,
             base_url_encrypted, owner_user_id_encrypted, account_id_masked,
             health_status, created_at, updated_at)
            VALUES ('bot-1', 'fingerprint', 'encrypted', 'encrypted', 'encrypted',
                    'encrypted', 'abcd***xyz', 'HEALTHY', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO employee_bot_bindings
            (id, company_id, employee_id, bot_account_id, active, bound_at)
            VALUES ('binding-1', 'greenhome', 'employee-1', 'bot-1', 1, CURRENT_TIMESTAMP)"""
        )
        connection.commit()

    run_alembic(database, "head")
    run_alembic(database, "head")

    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO companies
            (id, name, enabled, created_at, slug, deleted_at, updated_at)
            VALUES ('sanlin', '三林装饰', 1, CURRENT_TIMESTAMP, 'sanlin', NULL,
                    CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO employees
            (id, company_id, name, department, content_vertical, secondary_topics,
             target_platforms, account_name, tone, video_duration_seconds,
             publishing_frequency, status, created_at, updated_at)
            VALUES ('employee-2', 'sanlin', '另一租户', '', '', '[]', '[]', '', '',
                    60, '', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO weixin_bot_accounts
            (id, company_id, account_fingerprint, account_id_encrypted, bot_token_encrypted,
             base_url_encrypted, owner_user_id_encrypted, account_id_masked,
             health_status, created_at, updated_at)
            VALUES ('bot-2', 'sanlin', 'fingerprint-2', 'encrypted', 'encrypted', 'encrypted',
                    'encrypted', 'efgh***uvw', 'HEALTHY', CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO employee_bot_bindings
            (id, company_id, employee_id, bot_account_id, active, bound_at)
            VALUES ('binding-2', 'sanlin', 'employee-2', 'bot-2', 1, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO employees
            (id, company_id, name, department, content_vertical, secondary_topics,
             target_platforms, account_name, tone, video_duration_seconds,
             publishing_frequency, status, created_at, updated_at)
            VALUES ('employee-3', 'greenhome', '同租户另一员工', '', '', '[]', '[]', '', '',
                    60, '', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO weixin_bot_accounts
            (id, company_id, account_fingerprint, account_id_encrypted, bot_token_encrypted,
             base_url_encrypted, owner_user_id_encrypted, account_id_masked,
             health_status, created_at, updated_at)
            VALUES ('bot-3', 'greenhome', 'fingerprint-3', 'encrypted', 'encrypted', 'encrypted',
                    'encrypted', 'ijkl***rst', 'HEALTHY', CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO employee_bot_bindings
            (id, company_id, employee_id, bot_account_id, active, bound_at)
            VALUES ('binding-3', 'greenhome', 'employee-3', 'bot-3', 1,
                    CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO notification_targets
            (id, company_id, target_code, display_name, mode, enabled, employee_id,
             created_at, updated_at)
            VALUES ('target-2', 'sanlin', 'other', '另一对象', 'SINGLE', 1,
                    'employee-2', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO target_bot_members
            (id, company_id, target_id, binding_id, bot_account_id, active, created_at)
            VALUES ('member-2', 'sanlin', 'target-2', 'binding-2', 'bot-2', 1,
                    CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO notification_batches
            (id, company_id, target_id, idempotency_key, request_hash, title, body,
             notification_type, status, total_count, sent_count, failed_count,
             skipped_count, created_at)
            VALUES ('batch-1', 'greenhome', 'employee-1', 'key', 'hash', '', '',
                    'business', 'PENDING', 1, 0, 0, 0, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO deliveries
            (id, batch_id, target_id, target_member_id, company_id, employee_id,
             title, body, notification_type, binding_id, idempotency_key, status,
             retry_count, created_at, updated_at)
            VALUES ('delivery-1', 'batch-1', 'employee-1', 'binding-1', 'greenhome',
                    'employee-1', '', '', 'business', 'binding-1', 'batch-delivery',
                    'PENDING', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO notification_targets
            (id, company_id, target_code, display_name, mode, enabled, employee_id,
             created_at, updated_at)
            VALUES ('target-explicit', 'greenhome', 'explicit', '固定对象', 'MULTI', 1,
                    NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO target_bot_members
            (id, company_id, target_id, binding_id, bot_account_id, active, created_at)
            VALUES ('member-explicit', 'greenhome', 'target-explicit', 'binding-1',
                    'bot-1', 1, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO notification_batches
            (id, company_id, target_id, idempotency_key, request_hash, title, body,
             notification_type, status, total_count, sent_count, failed_count,
             skipped_count, created_at)
            VALUES ('batch-explicit', 'greenhome', 'target-explicit', 'explicit-key',
                    'explicit-hash', '', '', 'business', 'PENDING', 1, 0, 0, 0,
                    CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO deliveries
            (id, batch_id, target_id, target_member_id, company_id, employee_id,
             title, body, notification_type, binding_id, idempotency_key, status,
             retry_count, created_at, updated_at)
            VALUES ('delivery-explicit', 'batch-explicit', 'target-explicit',
                    'member-explicit', 'greenhome', 'employee-1', '', '', 'business',
                    'binding-1', 'explicit-delivery', 'PENDING', 0, CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP)"""
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="employee company is immutable"):
            connection.execute("UPDATE employees SET company_id='sanlin' WHERE id='employee-1'")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="bot binding identity is immutable"):
            connection.execute(
                "UPDATE employee_bot_bindings SET employee_id='employee-3' "
                "WHERE id='binding-1'"
            )
        connection.rollback()
        with pytest.raises(
            sqlite3.IntegrityError, match="notification target employee tenant mismatch"
        ):
            connection.execute(
                "UPDATE notification_targets SET employee_id='employee-2' "
                "WHERE id='employee-1'"
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="target member tenant mismatch"):
            connection.execute(
                "UPDATE target_bot_members SET company_id='sanlin' WHERE id='binding-1'"
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="notification batch tenant mismatch"):
            connection.execute(
                "UPDATE notification_batches SET company_id='sanlin' WHERE id='batch-1'"
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="delivery platform tenant mismatch"):
            connection.execute(
                "UPDATE deliveries SET target_id='target-2' WHERE id='delivery-1'"
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="delivery platform tenant mismatch"):
            connection.execute(
                "UPDATE deliveries SET target_member_id='member-2' WHERE id='delivery-1'"
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="delivery platform tenant mismatch"):
            connection.execute("UPDATE deliveries SET batch_id=NULL WHERE id='delivery-1'")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="delivery platform tenant mismatch"):
            connection.execute(
                """UPDATE deliveries SET employee_id='employee-3', binding_id='binding-3',
                target_member_id=NULL WHERE id='delivery-1'"""
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="delivery platform tenant mismatch"):
            connection.execute(
                "UPDATE deliveries SET target_member_id=NULL WHERE id='delivery-explicit'"
            )
        connection.rollback()

        company = connection.execute(
            "SELECT id, slug, name FROM companies WHERE id='greenhome'"
        ).fetchone()
        target = connection.execute(
            "SELECT id, company_id, employee_id, mode FROM notification_targets "
            "WHERE id='employee-1'"
        ).fetchall()
        member = connection.execute(
            "SELECT target_id, binding_id, bot_account_id, active FROM target_bot_members "
            "WHERE id='binding-1'"
        ).fetchall()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
    assert company == ("greenhome", "greenhome", "绿色家装饰")
    assert target == [("employee-1", "greenhome", "employee-1", "SINGLE")]
    assert member == [("employee-1", "binding-1", "bot-1", 1)]
    assert foreign_keys == []
    assert integrity == ("ok",)