from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ilink_binding import IlinkLoginResult, IlinkQrTicket, IlinkStatus
from app.models import AuditLog, Delivery, DeliveryStatus, EmployeeBotBinding, WeixinBinding
from tests.test_binding import create_employee, login
from tests.test_delivery import create_asset

QR_SCAN_DATA = "https://weixin.example.invalid/official-login-ticket"


def qr_ticket(ticket: str = "official-ticket") -> IlinkQrTicket:
    return IlinkQrTicket(
        ticket=ticket,
        scan_data=QR_SCAN_DATA,
        base_url="https://ilink.example.invalid",
        expires_at=datetime.now(UTC) + timedelta(minutes=8),
    )


def confirmed(account: str = "bot-account-1") -> IlinkLoginResult:
    return IlinkLoginResult(
        status=IlinkStatus.CONFIRMED,
        account_id=account,
        token=f"secret-{account}",
        base_url="https://ilink.example.invalid",
        user_id=f"owner-{account}",
    )


def activate_independent_bot(client: TestClient, csrf: str, employee: dict, account: str) -> None:
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed(account)):
        bound = client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    assert bound.json()["status"] == "bound"
    activated = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": account,
            "user_id": f"owner-{account}",
            "chat_id": f"owner-{account}",
            "text": "帮助",
            "context_token": f"context-{account}",
        },
    )
    assert activated.status_code == 200


def test_unbound_bot_account_cannot_be_claimed_by_another_company(
    client: TestClient,
) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket("owner-a")):
        owner_a = create_employee(client, csrf, "greenhome")
    activate_independent_bot(client, csrf, owner_a, "tenant-owned-bot")
    assert (
        client.post(
            f"/api/v1/employees/{owner_a['id']}/unbind",
            headers={"X-CSRF-Token": csrf},
            json={"confirm": True},
        ).status_code
        == 200
    )

    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket("owner-b")):
        owner_b = create_employee(client, csrf, "sanlin")
    with patch(
        "app.ilink_binding.IlinkQrAdapter.poll",
        return_value=confirmed("tenant-owned-bot"),
    ):
        rejected = client.post(
            f"/api/v1/binding-sessions/{owner_b['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "failed"
    assert rejected.json()["failure_code"] == "bot_account_company_mismatch"


def test_inbound_confirmation_is_fenced_to_current_binding(client: TestClient) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket("old")):
        employee = create_employee(client, csrf)
    activate_independent_bot(client, csrf, employee, "old-confirm-bot")
    with client.app.state.session_factory() as database:
        old_binding = database.query(EmployeeBotBinding).filter_by(active=True).one()
        old_delivery = Delivery(
            company_id=employee["company_id"],
            employee_id=employee["id"],
            binding_id=old_binding.id,
            idempotency_key="old-binding-confirmation",
            status=DeliveryStatus.SENT,
        )
        database.add(old_delivery)
        database.commit()
        old_delivery_id = old_delivery.id
    assert (
        client.post(
            f"/api/v1/employees/{employee['id']}/unbind",
            headers={"X-CSRF-Token": csrf},
            json={"confirm": True},
        ).status_code
        == 200
    )
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket("new")):
        new_session = client.post(
            f"/api/v1/employees/{employee['id']}/binding-sessions",
            headers={"X-CSRF-Token": csrf},
        ).json()
    with patch(
        "app.ilink_binding.IlinkQrAdapter.poll",
        return_value=confirmed("new-confirm-bot"),
    ):
        assert (
            client.post(
                f"/api/v1/binding-sessions/{new_session['id']}/poll",
                headers={"X-CSRF-Token": csrf},
            ).json()["status"]
            == "bound"
        )
    inbound = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "new-confirm-bot",
            "user_id": "owner-new-confirm-bot",
            "chat_id": "new-confirm-chat",
            "text": "已收到",
            "context_token": "new-confirm-context",
        },
    )
    assert inbound.status_code == 200
    assert client.get(f"/api/v1/deliveries/{old_delivery_id}").json()["status"] == "sent"


def test_legacy_binding_cannot_confirm_delivery_without_immutable_binding_version(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    from tests.test_delivery import bind_employee

    bind_employee(client, csrf, employee["id"])
    with client.app.state.session_factory() as database:
        old_binding = database.query(WeixinBinding).filter_by(active=True).one()
        old_binding.active = False
        old_binding.revoked_at = datetime.now(UTC)
        old_delivery = Delivery(
            company_id=employee["company_id"],
            employee_id=employee["id"],
            idempotency_key="legacy-binding-confirmation-fence",
            status=DeliveryStatus.SENT,
        )
        database.add(old_delivery)
        database.commit()
        old_delivery_id = old_delivery.id

    code = client.post(
        f"/api/v1/employees/{employee['id']}/binding-code",
        headers={"X-CSRF-Token": csrf},
    ).json()["code"]
    inbound_payload = {
        "account_id": "replacement-legacy-account",
        "user_id": "replacement-legacy-user",
        "chat_id": "replacement-legacy-chat",
        "context_token": "replacement-legacy-context",
    }
    assert (
        client.post(
            "/api/v1/bot/inbound",
            headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
            json={**inbound_payload, "text": f"绑定 {code}"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/bot/inbound",
            headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
            json={**inbound_payload, "text": "已收到"},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/deliveries/{old_delivery_id}").json()["status"] == "sent"


def test_employee_creation_returns_pending_official_qr_session(client: TestClient) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)

    session = employee["binding_session"]
    assert session["status"] == "pending"
    assert session["qr_image_url"].endswith("/qr.png")
    assert session["expires_at"]
    serialized = str(employee)
    assert "official-ticket" not in serialized
    assert QR_SCAN_DATA not in serialized
    assert "token" not in serialized.lower()

    qr = client.get("/api/v1/" + session["qr_image_url"].split("/api/v1/", 1)[1])
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert qr.headers["cache-control"] == "no-store"


def test_official_status_progresses_to_bound_without_leaking_credentials(
    client: TestClient,
) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    session_id = employee["binding_session"]["id"]

    with patch(
        "app.ilink_binding.IlinkQrAdapter.poll",
        side_effect=[
            IlinkLoginResult(status=IlinkStatus.SCANNED),
            IlinkLoginResult(status=IlinkStatus.CONFIRMING),
            confirmed(),
        ],
    ):
        states = [
            client.post(
                f"/api/v1/binding-sessions/{session_id}/poll",
                headers={"X-CSRF-Token": csrf},
            ).json()["status"]
            for _ in range(3)
        ]

    assert states == ["scanned", "confirming", "bound"]
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    assert detail["binding"]["status"] == "bound"
    assert detail["binding"]["health_status"] in {"unknown", "healthy"}
    assert "secret-bot-account-1" not in str(detail)
    assert "official-ticket" not in str(detail)


def test_cancel_expire_refresh_and_replay_are_enforced(client: TestClient) -> None:
    csrf = login(client)
    expired = qr_ticket("expired-ticket")
    expired = IlinkQrTicket(
        ticket=expired.ticket,
        scan_data=expired.scan_data,
        base_url=expired.base_url,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=expired):
        employee = create_employee(client, csrf)
    original = employee["binding_session"]
    assert client.get(f"/api/v1/binding-sessions/{original['id']}").json()["status"] == "expired"

    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket("fresh-ticket")):
        refreshed = client.post(
            f"/api/v1/employees/{employee['id']}/binding-sessions",
            headers={"X-CSRF-Token": csrf},
        )
    assert refreshed.status_code == 201
    assert refreshed.json()["id"] != original["id"]

    cancelled = client.post(
        f"/api/v1/binding-sessions/{refreshed.json()['id']}/cancel",
        headers={"X-CSRF-Token": csrf},
    )
    assert cancelled.json()["status"] == "cancelled"
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed()):
        replay = client.get(f"/api/v1/binding-sessions/{refreshed.json()['id']}")
    assert replay.json()["status"] == "cancelled"


def test_cross_tenant_and_wrong_employee_session_access_fail(client: TestClient) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        greenhome = create_employee(client, csrf, "greenhome")
        sanlin = create_employee(client, csrf, "sanlin")
    sid = greenhome["binding_session"]["id"]

    transfer = client.post(
        "/api/v1/binding-transfers",
        headers={"X-CSRF-Token": csrf},
        json={"source_employee_id": greenhome["id"], "target_employee_id": sanlin["id"]},
    )
    assert transfer.status_code == 403

    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed()):
        assert (
            client.post(
                f"/api/v1/binding-sessions/{sid}/poll", headers={"X-CSRF-Token": csrf}
            ).status_code
            == 200
        )


def test_concurrent_confirmation_consumes_session_once(client: TestClient) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    sid = employee["binding_session"]["id"]

    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed()):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: client.post(
                        f"/api/v1/binding-sessions/{sid}/poll",
                        headers={"X-CSRF-Token": csrf},
                    ),
                    range(2),
                )
            )

    assert all(response.status_code == 200 for response in results)
    assert {response.json()["status"] for response in results} == {"bound"}
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    assert detail["binding"]["status"] == "bound"


def test_cancel_waits_for_in_flight_confirmation_without_resurrecting_session(
    client: TestClient,
) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    sid = employee["binding_session"]["id"]
    poll_started = threading.Event()
    release_poll = threading.Event()
    cancel_finished = threading.Event()

    def deferred_confirmation(**_kwargs) -> IlinkLoginResult:
        poll_started.set()
        assert release_poll.wait(2)
        return confirmed("cancel-race-bot")

    def cancel_request():
        try:
            return client.post(
                f"/api/v1/binding-sessions/{sid}/cancel",
                headers={"X-CSRF-Token": csrf},
            )
        finally:
            cancel_finished.set()

    with patch("app.ilink_binding.IlinkQrAdapter.poll", side_effect=deferred_confirmation):
        with ThreadPoolExecutor(max_workers=2) as pool:
            poll_future = pool.submit(
                client.post,
                f"/api/v1/binding-sessions/{sid}/poll",
                headers={"X-CSRF-Token": csrf},
            )
            assert poll_started.wait(1)
            cancel_future = pool.submit(cancel_request)
            assert cancel_finished.wait(1)
            cancelled = cancel_future.result(timeout=2)
            assert cancelled.json()["status"] == "cancelled"
            release_poll.set()
            polled = poll_future.result(timeout=2)

    assert polled.json()["status"] == "cancelled"
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    assert detail["binding"] is None


def test_duplicate_bot_requires_explicit_transfer_and_unbind_releases_it(
    client: TestClient,
) -> None:
    csrf = login(client)
    with patch(
        "app.ilink_binding.IlinkQrAdapter.create",
        side_effect=[qr_ticket("one"), qr_ticket("two")],
    ):
        old = create_employee(client, csrf)
        new = create_employee(client, csrf)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("shared-bot")):
        assert (
            client.post(
                f"/api/v1/binding-sessions/{old['binding_session']['id']}/poll",
                headers={"X-CSRF-Token": csrf},
            ).json()["status"]
            == "bound"
        )
        collision = client.post(
            f"/api/v1/binding-sessions/{new['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    assert collision.json()["status"] == "failed"

    activation_payload = {
        "account_id": "shared-bot",
        "user_id": "owner-shared-bot",
        "chat_id": "chat-shared-bot",
        "text": "帮助",
        "context_token": "transfer-context",  # noqa: S105 - simulated iLink context
    }
    assert (
        client.post(
            "/api/v1/bot/inbound",
            headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
            json=activation_payload,
        ).status_code
        == 200
    )

    moved = client.post(
        "/api/v1/binding-transfers",
        headers={"X-CSRF-Token": csrf},
        json={"source_employee_id": old["id"], "target_employee_id": new["id"]},
    )
    assert moved.status_code == 200
    assert client.get(f"/api/v1/employees/{old['id']}").json()["binding"] is None
    assert client.get(f"/api/v1/employees/{new['id']}").json()["binding"]["status"] == "bound"
    with client.app.state.session_factory() as database:
        old_binding = database.query(EmployeeBotBinding).filter_by(employee_id=old["id"]).one()
        assert old_binding.context_token_encrypted is None
        assert old_binding.chat_id_encrypted is None

    assert (
        client.post(
            "/api/v1/bot/inbound",
            headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
            json=activation_payload,
        ).status_code
        == 200
    )

    unbound = client.post(
        f"/api/v1/employees/{new['id']}/unbind",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": True},
    )
    assert unbound.status_code == 200
    assert client.get(f"/api/v1/employees/{new['id']}").json()["binding"] is None
    with client.app.state.session_factory() as database:
        new_binding = database.query(EmployeeBotBinding).filter_by(employee_id=new["id"]).one()
        assert new_binding.context_token_encrypted is None
        assert new_binding.chat_id_encrypted is None


def test_sensitive_fields_absent_from_openapi_and_audit(client: TestClient) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed()):
        client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )

    openapi = client.get("/api/openapi.json").text.lower()
    for forbidden in ("bot_token", "token_encrypted", "ticket_encrypted", "scan_data_encrypted"):
        assert forbidden not in openapi
    logs = client.get("/api/v1/audit-logs?company_id=greenhome").text
    assert "secret-bot-account-1" not in logs
    assert "official-ticket" not in logs


def test_bound_bot_inbound_is_owner_scoped_and_worker_can_load_active_account(
    client: TestClient,
) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("owner-bot")):
        result = client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    assert result.json()["status"] == "bound"

    headers = {"X-Bot-Secret": "test-bot-webhook-secret-123456789"}
    wrong = client.post(
        "/api/v1/bot/inbound",
        headers=headers,
        json={
            "account_id": "owner-bot",
            "user_id": "wrong-owner",
            "chat_id": "wrong-owner",
            "text": "帮助",
        },
    )
    assert wrong.status_code == 403
    accepted = client.post(
        "/api/v1/bot/inbound",
        headers=headers,
        json={
            "account_id": "owner-bot",
            "user_id": "owner-owner-bot",
            "chat_id": "owner-owner-bot",
            "text": "帮助",
        },
    )
    assert accepted.status_code == 200

    from app.bot_worker import load_active_credentials

    credentials = load_active_credentials(
        client.app.state.settings, client.app.state.session_factory
    )
    assert len(credentials) == 1
    loaded = next(iter(credentials.values()))
    assert loaded.account_id == "owner-bot"
    assert loaded.token == confirmed("owner-bot").token
    assert loaded.employee_ref != employee["id"]
    assert len(loaded.employee_ref) == 12

    from app.bot_worker import platform_extra

    extra = platform_extra(loaded)
    assert extra["dm_policy"] == "allowlist"
    assert extra["allow_from"] == ["owner-owner-bot"]
    assert extra["group_policy"] == "disabled"

    from app.bot_worker import SafeWorkerLogFilter

    log_filter = SafeWorkerLogFilter()
    assert log_filter.filter(logging.LogRecord("app.bot_worker", 20, "", 1, "ok", (), None))
    assert not log_filter.filter(
        logging.LogRecord("gateway.platforms.weixin", 40, "", 1, "raw", (), None)
    )


def test_safe_get_updates_probe_reports_only_aggregate_contract(caplog):
    from app.bot_worker import BotCredential, SafeGetUpdatesProbe

    probe_token = "test-" + "token"
    credential = BotCredential(
        record_id="record",
        employee_id="employee-secret",
        employee_ref="employee-ref",
        account_id="bot-secret@im.bot",
        owner_user_id="owner-secret",
        token=probe_token,
        base_url="https://secret.example",
    )

    async def get_updates(*_args, **_kwargs):
        return {
            "ret": 0,
            "get_updates_buf": "next-secret-cursor",
            "msgs": [
                {
                    "from_user_id": "owner-secret",
                    "to_user_id": "bot-secret@im.bot",
                    "context_token": "context-secret",
                    "item_list": [{"text_item": {"text": "message-secret"}}],
                }
            ],
        }

    probe = SafeGetUpdatesProbe(get_updates, b"correlation-key", empty_log_interval_seconds=300)
    probe.update_credentials([credential])
    with caplog.at_level(logging.INFO, logger="app.bot_worker"):
        response = asyncio.run(
            probe(
                object(),
                base_url=credential.base_url,
                token=credential.token,
                sync_buf="previous-secret-cursor",
                timeout_ms=35_000,
            )
        )

    assert response["get_updates_buf"] == "next-secret-cursor"
    text = caplog.text
    assert "message_count=1" in text
    assert "owner_match_count=1" in text
    assert "target_match_count=1" in text
    assert "context_count=1" in text
    for secret in (
        credential.employee_id,
        credential.account_id,
        credential.owner_user_id,
        credential.token,
        credential.base_url,
        "context-secret",
        "message-secret",
        "next-secret-cursor",
        "previous-secret-cursor",
    ):
        assert secret not in text


def test_safe_get_updates_probe_is_fail_closed_and_restores_lifecycle(caplog):
    from app.bot_worker import (
        BotCredential,
        SafeGetUpdatesProbe,
        installed_safe_get_updates_probe,
    )

    first = BotCredential(
        record_id="first-record",
        employee_id="first-employee-secret",
        employee_ref="first-ref",
        account_id="first-bot-secret@im.bot",
        owner_user_id="first-owner-secret",
        token="first-" + "test-token",
        base_url="https://first.secret.example",
    )
    second = BotCredential(
        record_id="second-record",
        employee_id="second-employee-secret",
        employee_ref="second-ref",
        account_id="second-bot-secret@im.bot",
        owner_user_id="second-owner-secret",
        token="second-" + "test-token",
        base_url="https://second.secret.example",
    )

    async def failing_get_updates(*_args, **_kwargs):
        raise RuntimeError("raw-upstream-secret")

    probe = SafeGetUpdatesProbe(
        failing_get_updates, b"correlation-key", empty_log_interval_seconds=0
    )
    probe.update_credentials([first, second])
    assert len(probe._identities) == 2
    with caplog.at_level(logging.INFO, logger="app.bot_worker"):
        response = asyncio.run(
            probe(
                object(),
                base_url=second.base_url,
                token=second.token,
                sync_buf="cursor-secret",
                timeout_ms=35_000,
            )
        )
    assert response == {
        "ret": -1,
        "errcode": -1,
        "errmsg": "",
        "msgs": [],
        "get_updates_buf": "cursor-secret",
    }
    assert "error_type=RuntimeError" in caplog.text
    assert "employee_ref=second-ref" in caplog.text
    assert "employee_ref=first-ref" not in caplog.text
    for secret in (
        "raw-upstream-secret",
        first.token,
        second.token,
        second.base_url,
        "cursor-secret",
    ):
        assert secret not in caplog.text
        assert secret not in probe._identities
        assert secret not in probe._last_empty_log

    probe.update_credentials([first])
    assert len(probe._identities) == 1
    assert not probe._last_empty_log
    probe.clear()
    assert not probe._identities
    assert not probe._last_empty_log

    original = failing_get_updates
    official = SimpleNamespace(_get_updates=original)
    with installed_safe_get_updates_probe(official, b"correlation-key") as outer:
        assert official._get_updates is outer
        with installed_safe_get_updates_probe(official, b"correlation-key") as inner:
            assert official._get_updates is inner
        assert official._get_updates is outer
    assert official._get_updates is original


def test_independent_bot_activates_on_first_inbound_and_delivers_waiting_tasks(
    client: TestClient,
) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("notify-bot")):
        bound = client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    assert bound.json()["status"] == "bound"
    assert bound.json()["delivery_ready"] is False
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    assert detail["binding"]["delivery_ready"] is False
    assert detail["binding"]["manual_test"]["allowed"] is False
    assert detail["binding"]["welcome_delivery"]["status"] == "waiting_interaction"

    asset = create_asset(client, csrf, employee["id"])
    delivery = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "video_asset_id": asset["id"],
            "idempotency_key": "await-first-interaction",
        },
    )
    assert delivery.status_code == 201
    assert delivery.json()["status"] == "waiting_interaction"
    assert delivery.json()["failure_code"] == "context_required"

    context_token = "fresh-context"  # noqa: S105 - simulated iLink conversation context
    inbound = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "notify-bot",
            "user_id": "owner-notify-bot",
            "chat_id": "chat-notify-bot",
            "text": "帮助",
            "context_token": context_token,
        },
    )
    assert inbound.status_code == 200
    assert inbound.json()["message"] == "指令已处理"
    assert inbound.json()["reply"] is False
    assert client.get(f"/api/v1/deliveries/{delivery.json()['id']}").json()["status"] == "simulated"
    refreshed_session = client.post(
        f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
        headers={"X-CSRF-Token": csrf},
    ).json()
    assert refreshed_session["delivery_ready"] is True

    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    assert detail["binding"]["health_status"] == "healthy"
    assert detail["binding"]["delivery_ready"] is True

    from cryptography.fernet import Fernet

    with client.app.state.session_factory() as database:
        stored = database.query(EmployeeBotBinding).filter_by(employee_id=employee["id"]).one()
        assert stored.context_token_encrypted is not None
        assert stored.chat_id_encrypted is not None
        assert stored.context_token_encrypted != context_token
        cipher = Fernet(client.app.state.settings.identifier_encryption_key.encode())
        assert cipher.decrypt(stored.context_token_encrypted.encode()).decode() == context_token
        assert cipher.decrypt(stored.chat_id_encrypted.encode()).decode() == "chat-notify-bot"


def test_concurrent_first_inbound_claims_waiting_delivery_once(client: TestClient) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("race-bot")):
        client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    with client.app.state.session_factory() as database:
        binding = database.query(EmployeeBotBinding).filter_by(employee_id=employee["id"]).one()
        binding.context_token_encrypted = None
        binding.chat_id_encrypted = None
        database.commit()
    asset = create_asset(client, csrf, employee["id"])
    delivery = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "video_asset_id": asset["id"],
            "idempotency_key": "concurrent-first-inbound",
        },
    ).json()
    assert delivery["status"] == "waiting_interaction"

    payload = {
        "account_id": "race-bot",
        "user_id": "owner-race-bot",
        "chat_id": "chat-race-bot",
        "text": "帮助",
        "context_token": "race-context",  # noqa: S105 - simulated iLink context
    }

    def activate(_index: int):
        return client.post(
            "/api/v1/bot/inbound",
            headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
            json=payload,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(activate, range(2)))
    assert all(response.status_code == 200 for response in responses)

    stored_delivery = client.get(f"/api/v1/deliveries/{delivery['id']}").json()
    assert stored_delivery["status"] == "simulated"
    assert stored_delivery["retry_count"] == 1
    with client.app.state.session_factory() as database:
        auto_retries = (
            database.query(AuditLog)
            .filter_by(action="delivery.auto_retry", target_id=delivery["id"])
            .count()
        )
        assert auto_retries == 1


def test_partial_auto_retry_failure_keeps_activation_and_prior_result(
    client: TestClient, monkeypatch
) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("partial-bot")):
        client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    with client.app.state.session_factory() as database:
        binding = database.query(EmployeeBotBinding).filter_by(employee_id=employee["id"]).one()
        binding.context_token_encrypted = None
        binding.chat_id_encrypted = None
        database.commit()

    settings = client.app.state.settings
    object.__setattr__(settings, "delivery_mode", "weixin")
    attempts = 0

    def fake_send(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("simulated transport failure")
        from app.weixin_delivery import SendOutcome

        return SendOutcome(True, f"message-{attempts}", True)

    monkeypatch.setattr("app.weixin_delivery.send_video", fake_send)
    delivery_ids = []
    for index in range(2):
        asset = create_asset(client, csrf, employee["id"])
        delivery = client.post(
            "/api/v1/deliveries",
            headers={"X-CSRF-Token": csrf},
            json={
                "company_id": "greenhome",
                "employee_id": employee["id"],
                "video_asset_id": asset["id"],
                "idempotency_key": f"partial-auto-retry-{index}",
            },
        ).json()
        assert delivery["status"] == "waiting_interaction"
        delivery_ids.append(delivery["id"])

    inbound = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "partial-bot",
            "user_id": "owner-partial-bot",
            "chat_id": "chat-partial-bot",
            "text": "帮助",
            "context_token": "partial-context",  # noqa: S105 - simulated iLink context
        },
    )
    assert inbound.status_code == 200
    statuses = {
        client.get(f"/api/v1/deliveries/{delivery_id}").json()["status"]
        for delivery_id in delivery_ids
    }
    assert statuses == {"sent", "failed"}
    assert (
        client.get(f"/api/v1/employees/{employee['id']}").json()["binding"]["delivery_ready"]
        is True
    )


def test_first_inbound_unsubscribe_does_not_activate_or_retain_context(
    client: TestClient,
) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("quit-bot")):
        client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )

    response = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "quit-bot",
            "user_id": "owner-quit-bot",
            "chat_id": "chat-quit-bot",
            "text": "退订",
            "context_token": "quit-context",  # noqa: S105 - simulated iLink context
        },
    )
    assert response.status_code == 200
    assert response.json()["message"] == "指令已处理"
    assert client.get(f"/api/v1/employees/{employee['id']}").json()["binding"] is None
    with client.app.state.session_factory() as database:
        binding = database.query(EmployeeBotBinding).filter_by(employee_id=employee["id"]).one()
        assert binding.active is False
        assert binding.context_token_encrypted is None
        assert binding.chat_id_encrypted is None


def test_concurrent_unbind_and_inbound_cannot_restore_revoked_context(
    client: TestClient,
) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("revoke-race-bot")):
        client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )

    def unbind(_index: int):
        return client.post(
            f"/api/v1/employees/{employee['id']}/unbind",
            headers={"X-CSRF-Token": csrf},
            json={"confirm": True},
        )

    def inbound(_index: int):
        return client.post(
            "/api/v1/bot/inbound",
            headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
            json={
                "account_id": "revoke-race-bot",
                "user_id": "owner-revoke-race-bot",
                "chat_id": "chat-revoke-race-bot",
                "text": "帮助",
                "context_token": "race-context",  # noqa: S105 - simulated iLink context
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(unbind, 0), pool.submit(inbound, 0)]
        responses = [future.result() for future in futures]
    assert responses[0].status_code == 200
    assert responses[1].status_code in {200, 403, 409}
    with client.app.state.session_factory() as database:
        binding = database.query(EmployeeBotBinding).filter_by(employee_id=employee["id"]).one()
        assert binding.active is False
        assert binding.context_token_encrypted is None
        assert binding.chat_id_encrypted is None
