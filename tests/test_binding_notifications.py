from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ilink_binding import IlinkLoginResult, IlinkStatus
from app.models import AuditLog, Delivery, DeliveryStatus, EmployeeBotBinding
from tests.test_binding import create_employee, login
from tests.test_bot_binding_sessions import qr_ticket
from tests.test_rbac import create_user, relogin


def confirmed(account: str) -> IlinkLoginResult:
    return IlinkLoginResult(
        status=IlinkStatus.CONFIRMED,
        account_id=account,
        token=f"test-secret-{account}",
        base_url="https://ilink.test",
        user_id=f"owner-{account}",
    )


def bind_and_activate(
    client: TestClient, csrf: str, *, company_id: str = "greenhome", account: str = "notice-bot"
) -> dict:
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket(account)):
        employee = create_employee(client, csrf, company_id)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed(account)):
        response = client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "bound"
    activated = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": account,
            "user_id": f"owner-{account}",
            "chat_id": f"chat-{account}",
            "text": "帮助",
            "context_token": f"context-{account}",
        },
    )
    assert activated.status_code == 200
    return employee


def test_binding_welcome_is_tenant_branded_and_once_per_binding_event(
    client: TestClient,
) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket("sanlin")):
        employee = create_employee(client, csrf, "sanlin")
    session_id = employee["binding_session"]["id"]

    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("sanlin-bot")):
        first = client.post(
            f"/api/v1/binding-sessions/{session_id}/poll",
            headers={"X-CSRF-Token": csrf},
        )
        replay = client.post(
            f"/api/v1/binding-sessions/{session_id}/poll",
            headers={"X-CSRF-Token": csrf},
        )

    assert first.json()["status"] == "bound"
    assert replay.json()["status"] == "bound"
    with client.app.state.session_factory() as database:
        notices = database.query(Delivery).filter_by(notification_type="binding_welcome").all()
        assert len(notices) == 1
        notice = notices[0]
        assert notice.employee_id == employee["id"]
        assert notice.company_id == "sanlin"
        assert notice.status == DeliveryStatus.WAITING_INTERACTION
        assert "三林装饰" in notice.body
        assert "绿色家装饰" not in notice.body
        assert "非本人操作" in notice.body

    activated = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "sanlin-bot",
            "user_id": "owner-sanlin-bot",
            "chat_id": "chat-sanlin-bot",
            "text": "帮助",
            "context_token": "sanlin-context",
        },
    )
    assert activated.status_code == 200
    log = client.get(f"/api/v1/deliveries/{notice.id}").json()
    assert log["status"] == "simulated"
    assert log["notification_type"] == "binding_welcome"


def test_welcome_failure_does_not_rollback_binding_and_manual_test_remains_available(
    client: TestClient, monkeypatch
) -> None:
    csrf = login(client)
    settings = client.app.state.settings
    object.__setattr__(settings, "delivery_mode", "weixin")

    from app.weixin_delivery import SendOutcome

    monkeypatch.setattr(
        "app.weixin_delivery.send_video",
        lambda *_args, **_kwargs: SendOutcome(
            False, error="微信发送失败，请稍后重试", error_code="weixin_send_failed"
        ),
    )
    employee = bind_and_activate(client, csrf, account="failed-welcome")

    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    assert detail["binding"]["status"] == "bound"
    assert detail["binding"]["health_status"] == "healthy"
    assert detail["binding"]["welcome_delivery"]["status"] == "failed"
    assert detail["binding"]["manual_test"]["allowed"] is True


def test_manual_test_is_fixed_purpose_audited_logged_and_cooled_down(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="manual-bot")

    first = client.post(
        f"/api/v1/employees/{employee['id']}/test-notification",
        headers={"X-CSRF-Token": csrf},
    )
    second = client.post(
        f"/api/v1/employees/{employee['id']}/test-notification",
        headers={"X-CSRF-Token": csrf},
    )

    assert first.status_code == 201
    assert first.json()["notification_type"] == "manual_test"
    assert first.json()["status"] == "simulated"
    assert "测试" in first.json()["title"]
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0
    with client.app.state.session_factory() as database:
        tests = database.query(Delivery).filter_by(notification_type="manual_test").all()
        assert len(tests) == 1
        assert tests[0].employee_id == employee["id"]
        assert database.query(AuditLog).filter_by(action="delivery.manual_test.create").count() == 1


def test_concurrent_manual_test_claims_cooldown_once(client: TestClient) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="race-manual-bot")

    def send(_index: int) -> int:
        return client.post(
            f"/api/v1/employees/{employee['id']}/test-notification",
            headers={"X-CSRF-Token": csrf},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(send, range(2)))

    assert statuses == [201, 429]
    with client.app.state.session_factory() as database:
        assert database.query(Delivery).filter_by(notification_type="manual_test").count() == 1


def test_manual_test_requires_healthy_active_binding_admin_and_tenant(client: TestClient) -> None:
    root_csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket("not-ready")):
        not_ready = create_employee(client, root_csrf, "greenhome")
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("not-ready-bot")):
        client.post(
            f"/api/v1/binding-sessions/{not_ready['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": root_csrf},
        )
    blocked = client.post(
        f"/api/v1/employees/{not_ready['id']}/test-notification",
        headers={"X-CSRF-Token": root_csrf},
    )
    assert blocked.status_code == 409
    assert "健康" in blocked.json()["detail"] or "会话" in blocked.json()["detail"]

    sanlin = bind_and_activate(client, root_csrf, company_id="sanlin", account="sanlin-admin-bot")
    create_user(client, root_csrf, "green-admin-test-send", "company_admin", "greenhome")
    green_csrf = relogin(client, "green-admin-test-send")
    cross_tenant = client.post(
        f"/api/v1/employees/{sanlin['id']}/test-notification",
        headers={"X-CSRF-Token": green_csrf},
    )
    assert cross_tenant.status_code == 403

    client.cookies.clear()
    business = client.post(
        f"/api/v1/employees/{not_ready['id']}/test-notification",
        headers={"Authorization": "Bearer greenhome-business-token-123456789"},
    )
    assert business.status_code == 403


def test_transfer_creates_a_new_welcome_version(client: TestClient) -> None:
    csrf = login(client)
    source = bind_and_activate(client, csrf, account="transfer-welcome-bot")
    target = create_employee(client, csrf)
    moved = client.post(
        "/api/v1/binding-transfers",
        headers={"X-CSRF-Token": csrf},
        json={"source_employee_id": source["id"], "target_employee_id": target["id"]},
    )
    assert moved.status_code == 200
    with client.app.state.session_factory() as database:
        bindings = database.query(EmployeeBotBinding).order_by(EmployeeBotBinding.bound_at).all()
        welcomes = database.query(Delivery).filter_by(notification_type="binding_welcome").all()
        assert len(bindings) == 2
        assert len(welcomes) == 2
        assert {item.binding_id for item in welcomes} == {item.id for item in bindings}
        transferred = next(item for item in welcomes if item.employee_id == target["id"])
        transferred.status = DeliveryStatus.PENDING
        transferred.dispatch_token = None
        transferred.dispatch_lease_expires_at = None
        database.commit()

    activated = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "transfer-welcome-bot",
            "user_id": "owner-transfer-welcome-bot",
            "chat_id": "target-transfer-chat",
            "text": "帮助",
            "context_token": "target-transfer-context",
        },
    )
    assert activated.status_code == 200
    assert client.get(f"/api/v1/deliveries/{transferred.id}").json()["status"] == "simulated"


def test_old_waiting_welcome_cannot_send_through_a_rebound_bot(client: TestClient) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket("old")):
        employee = create_employee(client, csrf)
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("old-bot")):
        client.post(
            f"/api/v1/binding-sessions/{employee['binding_session']['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    client.post(
        f"/api/v1/employees/{employee['id']}/unbind",
        headers={"X-CSRF-Token": csrf},
        json={"confirm": True},
    )
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket("new")):
        session = client.post(
            f"/api/v1/employees/{employee['id']}/binding-sessions",
            headers={"X-CSRF-Token": csrf},
        ).json()
    with patch("app.ilink_binding.IlinkQrAdapter.poll", return_value=confirmed("new-bot")):
        client.post(
            f"/api/v1/binding-sessions/{session['id']}/poll",
            headers={"X-CSRF-Token": csrf},
        )
    client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "new-bot",
            "user_id": "owner-new-bot",
            "chat_id": "chat-new-bot",
            "text": "帮助",
            "context_token": "new-context",
        },
    )

    with client.app.state.session_factory() as database:
        welcomes = (
            database.query(Delivery)
            .filter_by(notification_type="binding_welcome")
            .order_by(Delivery.created_at)
            .all()
        )
        assert [item.status for item in welcomes] == [
            DeliveryStatus.FAILED,
            DeliveryStatus.SIMULATED,
        ]
        assert welcomes[0].failure_code == "binding_version_changed"