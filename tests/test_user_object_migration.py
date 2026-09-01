from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest


def run_alembic(database: Path, revision: str, *, action: str = "upgrade") -> None:
    env = {
        **os.environ,
        "APP_DATABASE_URL": f"sqlite:///{database}",
        "APP_IDENTIFIER_HMAC_KEY": "migration-test-hmac-key-long-enough",
        "APP_IDENTIFIER_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    }
    subprocess.run(  # noqa: S603 - fixed executable and test-owned revision
        [".venv/bin/alembic", action, revision],
        check=True,
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )


def seed_predecessor_bot_history(
    database: Path, companies: list[str], *, orphan: bool = False
) -> None:
    with sqlite3.connect(database) as connection:
        for company_id in set(companies):
            connection.execute(
                "INSERT INTO companies (id, slug, name, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (company_id, company_id, company_id.upper()),
            )
        connection.execute(
            """INSERT INTO weixin_bot_accounts
            (id, account_fingerprint, account_id_encrypted, bot_token_encrypted,
             base_url_encrypted, owner_user_id_encrypted, account_id_masked,
             health_status, created_at, updated_at)
            VALUES ('bot', 'fingerprint', 'encrypted', 'encrypted', 'encrypted',
                    'encrypted', 'bot***', 'UNKNOWN', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        if orphan:
            return
        for index, company_id in enumerate(companies):
            employee_id = f"employee-{index}"
            connection.execute(
                """INSERT INTO employees
                (id, company_id, name, department, content_vertical, secondary_topics,
                 target_platforms, account_name, tone, video_duration_seconds,
                 publishing_frequency, status, created_at, updated_at)
                VALUES (?, ?, 'Contact', '', '', '[]', '[]', '', '', 60, '', 'ACTIVE',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (employee_id, company_id),
            )
            connection.execute(
                """INSERT INTO employee_bot_bindings
                (id, company_id, employee_id, bot_account_id, active, bound_at)
                VALUES (?, ?, ?, 'bot', ?, CURRENT_TIMESTAMP)""",
                (f"binding-{index}", company_id, employee_id, index == len(companies) - 1),
            )


def test_user_object_migration_adds_private_contact_storage_and_tenant_guards(
    tmp_path: Path,
) -> None:
    database = tmp_path / "user-objects.db"
    run_alembic(database, "c3d8a1f4b920")
    run_alembic(database, "head")

    with sqlite3.connect(database) as connection:
        employee_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(employees)")
        }
        target_columns = {
            row[1]: row[4]
            for row in connection.execute("PRAGMA table_info(notification_targets)")
        }
        contact_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(user_object_contacts)")
        }
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    assert {"phone_encrypted", "phone_fingerprint", "phone_masked"} <= employee_columns
    assert target_columns["is_user_object"] == "0"
    assert {
        "id",
        "company_id",
        "target_id",
        "employee_id",
        "active",
        "created_at",
        "removed_at",
    } <= contact_columns
    assert {
        "trg_user_object_contact_tenant_insert",
        "trg_user_object_contact_tenant_update",
        "trg_bot_binding_tenant_insert",
        "trg_bot_binding_tenant_update",
        "trg_bot_account_company_immutable",
    } <= triggers


def test_user_object_contact_trigger_rejects_cross_tenant_rows(tmp_path: Path) -> None:
    database = tmp_path / "tenant-guard.db"
    run_alembic(database, "head")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO companies (id, slug, name, enabled, created_at, updated_at) "
            "VALUES ('a', 'a', 'A', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('b', 'b', 'B', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        for company_id, employee_id in (("a", "ea"), ("b", "eb")):
            connection.execute(
                """INSERT INTO employees
                (id, company_id, name, department, content_vertical, secondary_topics,
                 target_platforms, account_name, tone, video_duration_seconds,
                 publishing_frequency, status, created_at, updated_at)
                VALUES (?, ?, 'Contact', '', '', '[]', '[]', '', '', 60, '', 'ACTIVE',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (employee_id, company_id),
            )
        connection.execute(
            """INSERT INTO notification_targets
            (id, company_id, target_code, display_name, mode, enabled, employee_id,
             deleted_at, created_at, updated_at, is_user_object)
            VALUES ('target-a', 'a', 'object-a', 'Object A', 'MULTI', 1, NULL, NULL,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"""
        )
        with pytest.raises(sqlite3.IntegrityError, match="user object contact tenant mismatch"):
            connection.execute(
                """INSERT INTO user_object_contacts
                (id, company_id, target_id, employee_id, active, created_at)
                VALUES ('bad', 'a', 'target-a', 'eb', 1, CURRENT_TIMESTAMP)"""
            )
        connection.execute(
            """INSERT INTO weixin_bot_accounts
            (id, company_id, account_fingerprint, account_id_encrypted,
             bot_token_encrypted, base_url_encrypted, owner_user_id_encrypted,
             account_id_masked, health_status, created_at, updated_at)
            VALUES ('bot-a', 'a', 'fingerprint-a', 'encrypted', 'encrypted',
                    'encrypted', 'encrypted', 'bot***a', 'UNKNOWN',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        with pytest.raises(sqlite3.IntegrityError, match="bot binding tenant mismatch"):
            connection.execute(
                """INSERT INTO employee_bot_bindings
                (id, company_id, employee_id, bot_account_id, active, bound_at)
                VALUES ('bad-binding', 'b', 'eb', 'bot-a', 1, CURRENT_TIMESTAMP)"""
            )
        with pytest.raises(sqlite3.IntegrityError, match="bot account company is immutable"):
            connection.execute(
                "UPDATE weixin_bot_accounts SET company_id = 'b' WHERE id = 'bot-a'"
            )


def test_user_object_delivery_trigger_allows_membership_backed_delivery(
    tmp_path: Path,
) -> None:
    database = tmp_path / "user-object-delivery.db"
    run_alembic(database, "head")

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO companies (id, slug, name, enabled, created_at, updated_at) "
            "VALUES ('a', 'a', 'A', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            """INSERT INTO employees
            (id, company_id, name, department, content_vertical, secondary_topics,
             target_platforms, account_name, tone, video_duration_seconds,
             publishing_frequency, status, created_at, updated_at)
            VALUES ('employee-a', 'a', 'Contact', '', '', '[]', '[]', '', '', 60, '',
                    'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO weixin_bot_accounts
            (id, company_id, account_fingerprint, account_id_encrypted,
             bot_token_encrypted, base_url_encrypted, owner_user_id_encrypted,
             account_id_masked, health_status, created_at, updated_at)
            VALUES ('bot-a', 'a', 'fingerprint-a', 'encrypted', 'encrypted',
                    'encrypted', 'encrypted', 'bot***a', 'HEALTHY',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO employee_bot_bindings
            (id, company_id, employee_id, bot_account_id, active, bound_at)
            VALUES ('binding-a', 'a', 'employee-a', 'bot-a', 1, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO notification_targets
            (id, company_id, target_code, display_name, mode, enabled, employee_id,
             deleted_at, created_at, updated_at, is_user_object)
            VALUES ('target-a', 'a', 'user-object-a', 'User object', 'MULTI', 1, NULL,
                    NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"""
        )
        connection.execute(
            """INSERT INTO user_object_contacts
            (id, company_id, target_id, employee_id, active, created_at)
            VALUES ('contact-a', 'a', 'target-a', 'employee-a', 1, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO api_clients
            (id, company_id, name, token_hash, token_prefix, permissions,
             allowed_target_codes, enabled, created_at, updated_at)
            VALUES ('client-a', 'a', 'API client', 'hash', 'prefix', '["send"]',
                    '["user-object-a"]', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO notification_batches
            (id, company_id, target_id, api_client_id, idempotency_key, request_hash,
             title, body, notification_type, status, total_count, sent_count,
             failed_count, skipped_count, created_at)
            VALUES ('batch-a', 'a', 'target-a', 'client-a', 'user-object-delivery',
                    'request-hash', 'Test', 'Body', 'business', 'PENDING', 1, 0, 0, 0,
                    CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """INSERT INTO deliveries
            (id, batch_id, target_id, target_member_id, company_id, employee_id,
             title, body, notification_type, binding_id, idempotency_key, status,
             retry_count, created_at, updated_at)
            VALUES ('delivery-a', 'batch-a', 'target-a', NULL, 'a', 'employee-a',
                    'Test', 'Body', 'business', 'binding-a', 'delivery-a', 'PENDING',
                    0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        connection.commit()

        assert connection.execute(
            "SELECT target_member_id FROM deliveries WHERE id = 'delivery-a'"
        ).fetchone() == (None,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


@pytest.mark.parametrize("orphan,companies", [(True, []), (False, ["a", "b"])])
def test_user_object_migration_fails_closed_without_unique_bot_company(
    tmp_path: Path, orphan: bool, companies: list[str]
) -> None:
    database = tmp_path / f"fail-closed-{orphan}.db"
    run_alembic(database, "c3d8a1f4b920")
    seed_predecessor_bot_history(database, companies, orphan=orphan)
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(database, "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM weixin_bot_accounts WHERE id = 'bot'"
        ).fetchone() == (1,)
        assert "company_id" not in {
            row[1] for row in connection.execute("PRAGMA table_info(weixin_bot_accounts)")
        }
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "c3d8a1f4b920",
        )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_user_object_migration_backfills_consistent_history_and_company_is_immutable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "consistent-history.db"
    run_alembic(database, "c3d8a1f4b920")
    seed_predecessor_bot_history(database, ["a", "a"])
    run_alembic(database, "head")
    run_alembic(database, "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT company_id FROM weixin_bot_accounts WHERE id = 'bot'"
        ).fetchone() == ("a",)
        with pytest.raises(sqlite3.IntegrityError, match="bot account company is immutable"):
            connection.execute("UPDATE weixin_bot_accounts SET company_id = 'b' WHERE id = 'bot'")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    run_alembic(database, "c3d8a1f4b920", action="downgrade")
    with sqlite3.connect(database) as connection:
        assert "company_id" not in {
            row[1] for row in connection.execute("PRAGMA table_info(weixin_bot_accounts)")
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
