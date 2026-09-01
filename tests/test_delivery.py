from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from tests.test_binding import create_employee, login

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"test-video-payload"
FAKE_LEGACY_MOV = b"\x00\x00\x00\x14moov" + b"legacy-quicktime"


def bind_employee(client: TestClient, csrf: str, employee_id: str) -> None:
    code = client.post(
        f"/api/v1/employees/{employee_id}/binding-code", headers={"X-CSRF-Token": csrf}
    ).json()["code"]
    response = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "bot",
            "user_id": f"user-{employee_id}",
            "chat_id": f"chat-{employee_id}",
            "text": f"绑定 {code}",
            "context_token": "ctx-valid",
        },
    )
    assert response.status_code == 200


def create_asset(client: TestClient, csrf: str, employee_id: str) -> dict:
    response = client.post(
        "/api/v1/video-assets",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("site.mp4", FAKE_MP4, "video/mp4")},
        data={
            "company_id": "greenhome",
            "employee_id": employee_id,
            "title": "今日工地",
            "caption": "施工节点说明",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_text_notification_does_not_require_video_asset(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])

    response = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "title": "施工提醒",
            "body": "明天上午九点进行水电验收，请提前准备。",
            "idempotency_key": "text-notification-001",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "simulated"
    assert response.json()["title"] == "施工提醒"
    assert response.json()["body"] == "明天上午九点进行水电验收，请提前准备。"
    assert response.json()["video_asset_id"] is None


def test_notification_requires_text_or_video(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])

    response = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "idempotency_key": "empty-notification-001",
        },
    )

    assert response.status_code == 422


def test_video_upload_rejects_invalid_signature(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    response = client.post(
        "/api/v1/video-assets",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("not-video.mp4", b"not-a-video", "video/mp4")},
        data={"company_id": "greenhome", "employee_id": employee["id"]},
    )
    assert response.status_code == 415
    assert client.get("/api/v1/video-assets?company_id=greenhome").json() == []


def test_video_upload_accepts_legacy_quicktime_mov(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    response = client.post(
        "/api/v1/video-assets",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("legacy.mov", FAKE_LEGACY_MOV, "video/quicktime")},
        data={"company_id": "greenhome", "employee_id": employee["id"]},
    )
    assert response.status_code == 201
    assert response.json()["content_type"] == "video/quicktime"


def test_video_upload_rejects_invalid_content_length(client: TestClient) -> None:
    response = client.post(
        "/api/v1/video-assets",
        headers={"Content-Length": "not-a-number"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid Content-Length"}


def test_video_upload_rejects_declared_oversized_request(client: TestClient) -> None:
    settings = client.app.state.settings
    response = client.post(
        "/api/v1/video-assets",
        headers={"Content-Length": str(settings.upload_max_bytes + 1024 * 1024 + 1)},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Video exceeds the upload size limit"}


def test_video_upload_limit_leaves_no_file_or_record(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    settings = client.app.state.settings
    object.__setattr__(settings, "upload_max_bytes", len(FAKE_MP4) - 1)
    response = client.post(
        "/api/v1/video-assets",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("large.mp4", FAKE_MP4, "video/mp4")},
        data={"company_id": "greenhome", "employee_id": employee["id"]},
    )
    assert response.status_code == 413
    assert client.get("/api/v1/video-assets?company_id=greenhome").json() == []
    employee_upload_dir = settings.upload_dir / "greenhome" / employee["id"]
    assert not employee_upload_dir.exists() or not list(employee_upload_dir.iterdir())


def test_video_upload_rejects_file_above_direct_send_limit(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    settings = client.app.state.settings
    object.__setattr__(settings, "native_video_max_bytes", len(FAKE_MP4) - 1)

    response = client.post(
        "/api/v1/video-assets",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("large.mp4", FAKE_MP4, "video/mp4")},
        data={"company_id": "greenhome", "employee_id": employee["id"]},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Video exceeds the direct-send size limit"}
    assert client.get("/api/v1/video-assets?company_id=greenhome").json() == []


def test_delivery_rejects_existing_video_above_direct_send_limit(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    asset = create_asset(client, csrf, employee["id"])
    object.__setattr__(client.app.state.settings, "native_video_max_bytes", len(FAKE_MP4) - 1)

    response = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "video_asset_id": asset["id"],
            "idempotency_key": "oversized-existing-001",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Video cannot be sent directly"}
    assert client.get("/api/v1/deliveries?company_id=greenhome").json() == []


def test_unbound_notification_rejection_is_explicit_and_audited(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)

    response = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "title": "测试通知",
            "idempotency_key": "unbound-notification-001",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Employee has no active Weixin notification binding"
    logs = client.get("/api/v1/audit-logs?company_id=greenhome").json()
    assert any(log["action"] == "delivery.rejected.unbound" for log in logs)


def test_delivery_is_idempotent_and_confirmation_is_explicit(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    asset = create_asset(client, csrf, employee["id"])
    payload = {
        "company_id": "greenhome",
        "employee_id": employee["id"],
        "video_asset_id": asset["id"],
        "idempotency_key": "daily-001",
    }
    first = client.post("/api/v1/deliveries", headers={"X-CSRF-Token": csrf}, json=payload)
    second = client.post("/api/v1/deliveries", headers={"X-CSRF-Token": csrf}, json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "simulated"
    assert first.json()["title"] == "今日工地"
    assert first.json()["body"] == "施工节点说明"
    assert first.json()["video_asset_id"] == asset["id"]

    confirmed = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "bot",
            "user_id": f"user-{employee['id']}",
            "chat_id": f"chat-{employee['id']}",
            "text": "已收到",
            "context_token": "ctx-fresh",
        },
    )
    assert confirmed.status_code == 200
    assert client.get(f"/api/v1/deliveries/{first.json()['id']}").json()["status"] == "simulated"


def test_concurrent_delivery_creation_returns_one_idempotent_record(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    payload = {
        "company_id": "greenhome",
        "employee_id": employee["id"],
        "title": "并发幂等通知",
        "idempotency_key": "concurrent-create-001",
    }
    barrier = Barrier(2)

    def create() -> tuple[int, str]:
        barrier.wait()
        response = client.post(
            "/api/v1/deliveries",
            headers={"X-CSRF-Token": csrf},
            json=payload,
        )
        return response.status_code, response.json()["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: create(), range(2)))

    assert sorted(status for status, _delivery_id in results) == [200, 201]
    assert len({delivery_id for _status, delivery_id in results}) == 1


def test_idempotent_replay_recovers_unleased_pending_delivery(
    client: TestClient, tmp_path: Path
) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    payload = {
        "company_id": "greenhome",
        "employee_id": employee["id"],
        "title": "恢复待发送通知",
        "idempotency_key": "pending-recovery-001",
    }
    created = client.post("/api/v1/deliveries", headers={"X-CSRF-Token": csrf}, json=payload).json()
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute(
            """UPDATE deliveries
            SET status = 'PENDING', external_message_id = NULL, text_sent_at = NULL,
                dispatch_token = NULL, dispatch_lease_expires_at = NULL
            WHERE id = ?""",
            (created["id"],),
        )
        connection.commit()

    recovered = client.post("/api/v1/deliveries", headers={"X-CSRF-Token": csrf}, json=payload)

    assert recovered.status_code == 200
    assert recovered.json()["id"] == created["id"]
    assert recovered.json()["status"] == "simulated"
    logs = client.get("/api/v1/audit-logs?company_id=greenhome").json()
    assert any(log["action"] == "delivery.idempotent_recovery" for log in logs)


def test_video_asset_can_only_be_claimed_by_one_delivery(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    asset = create_asset(client, csrf, employee["id"])

    first = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "video_asset_id": asset["id"],
            "idempotency_key": "claim-video-first",
        },
    )
    second = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "video_asset_id": asset["id"],
            "idempotency_key": "claim-video-second",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {"detail": "Video is already assigned to a delivery"}


def test_legacy_binding_missing_context_waits_and_next_interaction_redelivers(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    asset = create_asset(client, csrf, employee["id"])
    client.post(
        f"/api/v1/employees/{employee['id']}/binding/context-expire",
        headers={"X-CSRF-Token": csrf},
    )
    delivery = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "video_asset_id": asset["id"],
            "idempotency_key": "wait-001",
        },
    ).json()
    assert delivery["status"] == "waiting_interaction"

    client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "bot",
            "user_id": f"user-{employee['id']}",
            "chat_id": f"chat-{employee['id']}",
            "text": "今日视频",
            "context_token": "ctx-new",
        },
    )
    assert client.get(f"/api/v1/deliveries/{delivery['id']}").json()["status"] == "simulated"


def test_disabled_and_departed_employee_cannot_receive(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    asset = create_asset(client, csrf, employee["id"])
    client.patch(
        f"/api/v1/employees/{employee['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"status": "departed"},
    )
    response = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "video_asset_id": asset["id"],
            "idempotency_key": "blocked-001",
        },
    )
    assert response.status_code == 409
    logs = client.get("/api/v1/audit-logs?company_id=greenhome").json()
    assert any(log["action"] == "delivery.rejected.employee_inactive" for log in logs)


def test_openapi_describes_general_notifications(client: TestClient) -> None:
    document = client.get("/api/openapi.json").json()
    assert document["info"]["title"] == "Weixin Bot Notification System API"
    schema = document["components"]["schemas"]["DeliveryCreate"]
    assert {"title", "body", "video_asset_id"} <= schema["properties"].keys()
    assert "video_asset_id" not in schema["required"]


def test_failed_delivery_can_retry_without_duplicate_record(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    asset = create_asset(client, csrf, employee["id"])
    created = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf, "X-Test-Force-Failure": "true"},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "video_asset_id": asset["id"],
            "idempotency_key": "retry-001",
        },
    ).json()
    assert created["status"] == "failed"
    retried = client.post(
        f"/api/v1/deliveries/{created['id']}/retry", headers={"X-CSRF-Token": csrf}
    )
    assert retried.status_code == 200
    assert retried.json()["id"] == created["id"]
    assert retried.json()["status"] == "simulated"
    assert retried.json()["retry_count"] == 1


def test_concurrent_manual_retry_claims_failed_delivery_once(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    created = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf, "X-Test-Force-Failure": "true"},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "title": "并发重试",
            "idempotency_key": "concurrent-retry-001",
        },
    ).json()

    def retry() -> int:
        return client.post(
            f"/api/v1/deliveries/{created['id']}/retry",
            headers={"X-CSRF-Token": csrf},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _index: retry(), range(2)))

    assert statuses == [200, 409]
    stored = client.get(f"/api/v1/deliveries/{created['id']}").json()
    assert stored["retry_count"] == 1


def test_stale_inflight_delivery_can_be_recovered(client: TestClient, tmp_path: Path) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    created = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf, "X-Test-Force-Failure": "true"},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "title": "中断恢复",
            "idempotency_key": "stale-recovery-001",
        },
    ).json()
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute(
            """UPDATE deliveries
            SET status = 'SENDING', dispatch_token = 'stale-worker',
                dispatch_lease_expires_at = '2000-01-01 00:00:00'
            WHERE id = ?""",
            (created["id"],),
        )
        connection.commit()

    recovered = client.post(
        f"/api/v1/deliveries/{created['id']}/retry",
        headers={"X-CSRF-Token": csrf},
    )

    assert recovered.status_code == 200
    assert recovered.json()["status"] == "simulated"
    assert recovered.json()["retry_count"] == 1


def test_active_inflight_delivery_cannot_be_retried_or_cancelled(
    client: TestClient, tmp_path: Path
) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    bind_employee(client, csrf, employee["id"])
    created = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf, "X-Test-Force-Failure": "true"},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "title": "活动租约",
            "idempotency_key": "active-lease-001",
        },
    ).json()
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute(
            """UPDATE deliveries
            SET status = 'SENDING', dispatch_token = 'active-worker',
                dispatch_lease_expires_at = '2999-01-01 00:00:00'
            WHERE id = ?""",
            (created["id"],),
        )
        connection.commit()

    retried = client.post(
        f"/api/v1/deliveries/{created['id']}/retry",
        headers={"X-CSRF-Token": csrf},
    )
    cancelled = client.post(
        f"/api/v1/deliveries/{created['id']}/cancel",
        headers={"X-CSRF-Token": csrf},
    )

    assert retried.status_code == 409
    assert cancelled.status_code == 409
    stored = client.get(f"/api/v1/deliveries/{created['id']}").json()
    assert stored["status"] == "sending"
    assert "dispatch_token" not in stored
    assert "dispatch_lease_expires_at" not in stored


def test_download_link_uses_complete_public_prefix(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    asset = create_asset(client, csrf, employee["id"])
    response = client.post(
        f"/api/v1/video-assets/{asset['id']}/download-link",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["url"].startswith(
        "https://notify.example.com/weixin-bot-notification-platform/api/v1/downloads/"
    )


def test_successful_video_delivery_deletes_file_and_keeps_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{tmp_path / 'large.db'}")
    monkeypatch.setenv("APP_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-that-is-long-enough-123")
    monkeypatch.setenv("APP_IDENTIFIER_HMAC_KEY", "test-hmac-key-that-is-long-enough-123")
    monkeypatch.setenv(
        "APP_IDENTIFIER_ENCRYPTION_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    monkeypatch.setenv("APP_BOOTSTRAP_ADMIN_USERNAME", "root")
    monkeypatch.setenv("APP_BOOTSTRAP_ADMIN_PASSWORD", "Strong-Test-Password-123!")
    monkeypatch.setenv("APP_DELIVERY_MODE", "weixin")
    monkeypatch.setenv("APP_NATIVE_VIDEO_MAX_BYTES", "1024")
    monkeypatch.setenv("APP_BOT_WEBHOOK_SECRET", "test-bot-webhook-secret-123456789")
    monkeypatch.setenv("APP_SERVICE_API_TOKEN", "test-service-api-token-123456789")
    monkeypatch.setenv("EMPLOYEE_WEIXIN_ACCOUNT_ID", "dedicated-test-bot")
    monkeypatch.setenv("EMPLOYEE_WEIXIN_TOKEN", "dedicated-test-token")

    captured: dict[str, object] = {}

    def fake_send(
        _settings,
        _account_id: str,
        _bot_token: str,
        _base_url: str,
        _chat_id: str,
        message: str,
        video_path: str | None,
        _context_token: str | None = None,
        skip_text: bool = False,
        skip_media: bool = False,
    ):
        from app.weixin_delivery import SendOutcome

        del skip_text, skip_media

        if message == "限流测试":
            captured["rate_calls"] = int(captured.get("rate_calls", 0)) + 1
            return SendOutcome(
                False,
                error="微信发送频率受限，请30秒后重试",
                error_code="weixin_rate_limited",
                retry_after_seconds=30,
            )
        with sqlite3.connect(tmp_path / "large.db") as observer:
            phase = observer.execute(
                "SELECT status, media_sent_at FROM deliveries WHERE idempotency_key = ?",
                ("oversized-001",),
            ).fetchone()
        if video_path:
            captured["status_before_media"] = phase
            captured["video_path"] = video_path
            captured["file_existed_during_send"] = Path(video_path).is_file()
            return SendOutcome(True, "media-message", True, media_sent=True)
        captured["phase_before_text"] = phase
        captured.setdefault("message", message)
        captured.setdefault("video_path", video_path)
        captured.setdefault(
            "file_existed_during_send", bool(video_path and Path(video_path).is_file())
        )
        return SendOutcome(True, "text-message", True, text_sent=True, media_sent=True)

    monkeypatch.setattr("app.weixin_delivery.send_video", fake_send)
    from datetime import UTC, datetime, timedelta

    from app.ilink_binding import IlinkLoginResult, IlinkQrAdapter, IlinkQrTicket, IlinkStatus

    monkeypatch.setattr(
        IlinkQrAdapter,
        "create",
        staticmethod(
            lambda *, ttl_seconds: IlinkQrTicket(
                ticket="large-video-ticket",
                scan_data="https://weixin.test/large-video",
                base_url="https://ilink.test",
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )
        ),
    )
    monkeypatch.setattr(
        IlinkQrAdapter,
        "poll",
        staticmethod(
            lambda **_kwargs: IlinkLoginResult(
                status=IlinkStatus.CONFIRMED,
                account_id="large-video-bot",
                token="large-video-secret",  # noqa: S106 - simulated adapter credential
                base_url="https://ilink.test",
                user_id="large-video-owner",
            )
        ),
    )
    from app.main import create_app

    with TestClient(create_app()) as large_client:
        csrf = login(large_client)
        employee = create_employee(large_client, csrf)
        bound = large_client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
        assert bound.json()["status"] == "bound"
        activated = large_client.post(
            "/api/v1/bot/inbound",
            headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
            json={
                "account_id": "large-video-bot",
                "user_id": "large-video-owner",
                "chat_id": "large-video-owner",
                "text": "帮助",
                "context_token": "large-video-context",
            },
        )
        assert activated.status_code == 200
        asset = create_asset(large_client, csrf, employee["id"])
        response = large_client.post(
            "/api/v1/deliveries",
            headers={"X-CSRF-Token": csrf},
            json={
                "company_id": "greenhome",
                "employee_id": employee["id"],
                "video_asset_id": asset["id"],
                "idempotency_key": "oversized-001",
            },
        )
        logs = large_client.get("/api/v1/audit-logs?company_id=greenhome").json()
        persisted = large_client.get(f"/api/v1/deliveries/{response.json()['id']}")
        reused = large_client.post(
            "/api/v1/deliveries",
            headers={"X-CSRF-Token": csrf},
            json={
                "company_id": "greenhome",
                "employee_id": employee["id"],
                "video_asset_id": asset["id"],
                "idempotency_key": "reused-video-001",
            },
        )
        rate_limited = large_client.post(
            "/api/v1/deliveries",
            headers={"X-CSRF-Token": csrf},
            json={
                "company_id": "greenhome",
                "employee_id": employee["id"],
                "title": "限流测试",
                "idempotency_key": "rate-limited-001",
            },
        )
        premature_retry = large_client.post(
            f"/api/v1/deliveries/{rate_limited.json()['id']}/retry",
            headers={"X-CSRF-Token": csrf},
        )
        health_after_rate_limit = large_client.get(f"/api/v1/employees/{employee['id']}").json()[
            "binding"
        ]["health_status"]
    assert response.status_code == 201
    assert response.json()["status"] == "sent"
    assert captured["status_before_media"] == ("SENDING", None)
    assert captured["phase_before_text"][0] in {"SENDING", "RETRYING"}
    assert captured["phase_before_text"][1] is not None
    assert captured["file_existed_during_send"] is True
    assert captured["video_path"] is not None
    assert not Path(str(captured["video_path"])).exists()
    assert any(log["action"] == "delivery.video_file_deleted" for log in logs)
    assert persisted.status_code == 200
    assert reused.status_code == 409
    assert reused.json() == {"detail": "Video is no longer available"}
    assert rate_limited.status_code == 201
    assert rate_limited.json()["status"] == "failed"
    assert rate_limited.json()["failure_code"] == "weixin_rate_limited"
    assert rate_limited.json()["next_retry_at"] is not None
    assert health_after_rate_limit == "healthy"
    assert premature_retry.status_code == 409
    assert premature_retry.json() == {"detail": "Delivery retry is not due yet"}
