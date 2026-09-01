from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import (
    Delivery,
    DeliveryStatus,
    EmployeeBotBinding,
    NotificationTarget,
    TargetBotMember,
    TargetMode,
)
from tests.test_binding import login
from tests.test_binding_notifications import bind_and_activate
from tests.test_rbac import create_user, relogin


def auth(csrf: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf}


def create_target(
    client: TestClient,
    csrf: str,
    *,
    company_id: str,
    code: str,
    binding_ids: list[str] | None = None,
    mode: str = "single",
    description: str = "",
) -> dict:
    response = client.post(
        "/api/v1/notification-targets",
        headers=auth(csrf),
        json={
            "company_id": company_id,
            "target_code": code,
            "display_name": f"对象 {code}",
            "description": description,
            "mode": mode,
            "binding_ids": binding_ids or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_super_admin_manages_third_company_and_company_admin_is_scoped(
    client: TestClient,
) -> None:
    csrf = login(client)
    created = client.post(
        "/api/v1/companies",
        headers=auth(csrf),
        json={"company_slug": "acme", "name": "示例科技"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["company_id"] == "acme"
    assert created.json()["company_slug"] == "acme"

    listed = client.get("/api/v1/companies")
    assert {item["company_slug"] for item in listed.json()} >= {"greenhome", "sanlin", "acme"}
    renamed = client.patch(
        "/api/v1/companies/acme",
        headers=auth(csrf),
        json={"name": "示例科技（中国）"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["company_slug"] == "acme"

    create_user(client, csrf, "green-company-manager", "company_admin", "greenhome")
    company_csrf = relogin(client, "green-company-manager")
    scoped = client.get("/api/v1/companies")
    assert [item["company_id"] for item in scoped.json()] == ["greenhome"]
    assert client.patch(
        "/api/v1/companies/sanlin",
        headers=auth(company_csrf),
        json={"enabled": False},
    ).status_code == 403


def test_target_mode_and_api_client_name_are_editable(client: TestClient) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="editable-platform")
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    target = create_target(
        client,
        csrf,
        company_id="greenhome",
        code="editable-target",
        binding_ids=[detail["binding"]["binding_id"]],
        description="剪辑任务完成通知",
    )
    assert target["description"] == "剪辑任务完成通知"

    updated_target = client.patch(
        f"/api/v1/notification-targets/{target['target_id']}",
        headers=auth(csrf),
        json={
            "display_name": "更新后的对象",
            "description": "更新后的业务用途",
            "mode": "dynamic_all",
            "binding_ids": [],
        },
    )
    assert updated_target.status_code == 200, updated_target.text
    assert updated_target.json()["display_name"] == "更新后的对象"
    assert updated_target.json()["description"] == "更新后的业务用途"
    assert updated_target.json()["mode"] == "dynamic_all"
    assert updated_target.json()["member_count"] == 1

    issued = client.post(
        "/api/v1/api-clients",
        headers=auth(csrf),
        json={
            "company_id": "greenhome",
            "name": "旧客户端名称",
            "permissions": ["query"],
            "allowed_target_codes": [],
        },
    )
    assert issued.status_code == 201, issued.text
    integration = issued.json()["integration"]
    assert integration["all_user_objects"] is True
    editable_mapping = next(
        item
        for item in integration["allowed_user_objects"]
        if item["user_object_code"] == "editable-target"
    )
    assert editable_mapping == {
        "user_object_code": "editable-target",
        "account_name": "更新后的对象",
        "description": "更新后的业务用途",
        "enabled": True,
    }
    assert "允许公司全部用户对象，包括未来新增对象" in integration["guide_markdown"]
    assert "| `editable-target` | 更新后的对象 | 更新后的业务用途 | 启用 |" in integration[
        "guide_markdown"
    ]
    updated_client = client.patch(
        f"/api/v1/api-clients/{issued.json()['id']}",
        headers=auth(csrf),
        json={"name": "新客户端名称", "permissions": ["query", "status"]},
    )
    assert updated_client.status_code == 200, updated_client.text
    assert updated_client.json()["name"] == "新客户端名称"
    assert updated_client.json()["permissions"] == ["query", "status"]

    null_target = client.patch(
        f"/api/v1/notification-targets/{target['target_id']}",
        headers=auth(csrf),
        json={"mode": None},
    )
    assert null_target.status_code == 422
    null_client = client.patch(
        f"/api/v1/api-clients/{issued.json()['id']}",
        headers=auth(csrf),
        json={"name": None},
    )
    assert null_client.status_code == 422

    null_updates = [
        ("/api/v1/companies/greenhome", "name"),
        ("/api/v1/companies/greenhome", "enabled"),
        (f"/api/v1/notification-targets/{target['target_id']}", "display_name"),
        (f"/api/v1/notification-targets/{target['target_id']}", "enabled"),
        (f"/api/v1/notification-targets/{target['target_id']}", "binding_ids"),
        (f"/api/v1/api-clients/{issued.json()['id']}", "enabled"),
        (f"/api/v1/api-clients/{issued.json()['id']}", "permissions"),
        (f"/api/v1/api-clients/{issued.json()['id']}", "allowed_target_codes"),
        (f"/api/v1/employees/{employee['id']}", "department"),
        (f"/api/v1/employees/{employee['id']}", "content_vertical"),
        (f"/api/v1/employees/{employee['id']}", "status"),
        (f"/api/v1/employees/{employee['id']}", "secondary_topics"),
        (f"/api/v1/employees/{employee['id']}", "target_platforms"),
        (f"/api/v1/employees/{employee['id']}", "account_name"),
        (f"/api/v1/employees/{employee['id']}", "tone"),
        (f"/api/v1/employees/{employee['id']}", "video_duration_seconds"),
        (f"/api/v1/employees/{employee['id']}", "publishing_frequency"),
    ]
    for path, field in null_updates:
        response = client.patch(path, headers=auth(csrf), json={field: None})
        assert response.status_code == 422, (path, field, response.text)

    for path in {
        "/api/v1/companies/greenhome",
        f"/api/v1/notification-targets/{target['target_id']}",
        f"/api/v1/api-clients/{issued.json()['id']}",
        f"/api/v1/employees/{employee['id']}",
    }:
        omitted = client.patch(path, headers=auth(csrf), json={})
        assert omitted.status_code == 200, (path, omitted.text)


def test_api_client_rejects_unknown_user_object_scope(client: TestClient) -> None:
    csrf = login(client)
    response = client.post(
        "/api/v1/api-clients",
        headers=auth(csrf),
        json={
            "company_id": "greenhome",
            "name": "invalid-scope",
            "permissions": ["query", "send", "status"],
            "allowed_target_codes": ["missing-user-object"],
        },
    )
    assert response.status_code == 422
    assert "missing-user-object" in response.json()["detail"]


def test_single_multi_and_dynamic_targets_expand_unique_healthy_bots(client: TestClient) -> None:
    csrf = login(client)
    first = bind_and_activate(client, csrf, account="platform-one")
    second = bind_and_activate(client, csrf, account="platform-two")
    employees = client.get("/api/v1/employees?company_id=greenhome").json()
    bindings = {item["id"]: item["binding"]["binding_id"] for item in employees}

    single = create_target(
        client,
        csrf,
        company_id="greenhome",
        code="person-one",
        binding_ids=[bindings[first["id"]]],
    )
    assert single["member_count"] == 1
    assert single["healthy_count"] == 1

    group = create_target(
        client,
        csrf,
        company_id="greenhome",
        code="team",
        binding_ids=[bindings[first["id"]], bindings[second["id"]], bindings[first["id"]]],
        mode="multi",
    )
    assert group["member_count"] == 2

    everyone = create_target(
        client,
        csrf,
        company_id="greenhome",
        code="all",
        mode="dynamic_all",
    )
    assert everyone["member_count"] == 2

    preview = client.post(
        "/api/v1/notifications/preview",
        headers=auth(csrf),
        json={"company_slug": "greenhome", "target_code": "team"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["bot_count"] == 2
    assert all("***" in item["bot_masked"] for item in preview.json()["bots"])
    assert all("binding_id" not in item for item in preview.json()["bots"])


def test_target_modes_reject_invalid_inactive_and_cross_company_members(
    client: TestClient,
) -> None:
    csrf = login(client)
    first = bind_and_activate(client, csrf, account="rules-one")
    second = bind_and_activate(client, csrf, account="rules-two")
    foreign = bind_and_activate(client, csrf, company_id="sanlin", account="rules-foreign")
    employees = client.get("/api/v1/employees").json()
    bindings = {item["id"]: item["binding"]["binding_id"] for item in employees}

    invalid_payloads = [
        ("single-empty", "single", []),
        ("single-many", "single", [bindings[first["id"]], bindings[second["id"]]]),
        ("multi-empty", "multi", []),
        ("dynamic-fixed", "dynamic_all", [bindings[first["id"]]]),
        ("foreign", "single", [bindings[foreign["id"]]]),
    ]
    for code, mode, binding_ids in invalid_payloads:
        response = client.post(
            "/api/v1/notification-targets",
            headers=auth(csrf),
            json={
                "company_id": "greenhome",
                "target_code": code,
                "display_name": code,
                "mode": mode,
                "binding_ids": binding_ids,
            },
        )
        assert response.status_code == 422, (code, response.text)

    with client.app.state.session_factory() as database:
        corrupted = database.get(EmployeeBotBinding, bindings[foreign["id"]])
        assert corrupted is not None
        corrupted.company_id = "greenhome"
        database.commit()
    corrupted_member = client.post(
        "/api/v1/notification-targets",
        headers=auth(csrf),
        json={
            "company_id": "greenhome",
            "target_code": "corrupted-employee-tenant",
            "display_name": "corrupted-employee-tenant",
            "mode": "single",
            "binding_ids": [bindings[foreign["id"]]],
        },
    )
    assert corrupted_member.status_code == 422

    assert client.post(
        f"/api/v1/employees/{first['id']}/unbind",
        headers=auth(csrf),
        json={"confirm": True},
    ).status_code == 200
    inactive = client.post(
        "/api/v1/notification-targets",
        headers=auth(csrf),
        json={
            "company_id": "greenhome",
            "target_code": "inactive",
            "display_name": "inactive",
            "mode": "single",
            "binding_ids": [bindings[first["id"]]],
        },
    )
    assert inactive.status_code == 422


def test_database_api_client_is_one_time_scoped_rotatable_and_audited(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="client-bot")
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    create_target(
        client,
        csrf,
        company_id="greenhome",
        code="alerts",
        binding_ids=[detail["binding"]["binding_id"]],
        description="核心系统告警",
    )
    create_target(
        client,
        csrf,
        company_id="greenhome",
        code="other-alerts",
        binding_ids=[detail["binding"]["binding_id"]],
    )
    create_target(client, csrf, company_id="sanlin", code="other", mode="dynamic_all")

    allowed_batch = client.post(
        "/api/v1/notifications/send",
        headers=auth(csrf),
        json={
            "company_slug": "greenhome",
            "target_code": "alerts",
            "body": "允许对象",
            "idempotency_key": "allowlist-allowed",
        },
    ).json()
    blocked_batch = client.post(
        "/api/v1/notifications/send",
        headers=auth(csrf),
        json={
            "company_slug": "greenhome",
            "target_code": "other-alerts",
            "body": "非允许对象",
            "idempotency_key": "allowlist-blocked",
        },
    ).json()

    issued = client.post(
        "/api/v1/api-clients",
        headers=auth(csrf),
        json={
            "company_id": "greenhome",
            "name": "green-profile",
            "permissions": ["query", "send", "status"],
            "allowed_target_codes": ["alerts"],
        },
    )
    assert issued.status_code == 201, issued.text
    issued_body = issued.json()
    token = issued_body.pop("token")
    assert token
    integration = issued_body["integration"]
    assert integration["api_base_url"] == (
        "https://notify.example.com/weixin-bot-notification-platform/api/v1"
    )
    assert integration["api_address_scope"] == "configured"
    assert integration["api_address_warning"] == ""
    assert integration["company_slug"] == "greenhome"
    assert integration["permissions"] == ["query", "send", "status"]
    assert integration["all_user_objects"] is False
    assert integration["allowed_user_objects"] == [
        {
            "user_object_code": "alerts",
            "account_name": "对象 alerts",
            "description": "核心系统告警",
            "enabled": True,
        }
    ]
    assert "| `alerts` | 对象 alerts | 核心系统告警 | 启用 |" in integration[
        "guide_markdown"
    ]
    assert "EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN" in integration["guide_markdown"]
    assert token not in integration["guide_markdown"]
    assert token not in integration["curl_check"]
    guide = client.get(f"/api/v1/api-clients/{issued_body['id']}/integration-guide")
    assert guide.status_code == 200, guide.text
    assert guide.json() == integration
    listed = client.get("/api/v1/api-clients?company_id=greenhome")
    assert listed.status_code == 200
    assert "token" not in listed.json()[0]
    assert listed.json()[0]["token_prefix"] in token

    client.cookies.clear()
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get(
        f"/api/v1/api-clients/{issued_body['id']}/integration-guide", headers=bearer
    ).status_code == 403
    companies = client.get("/api/v1/authorized-companies", headers=bearer)
    assert companies.status_code == 200
    assert [item["company_slug"] for item in companies.json()] == ["greenhome"]
    cross_targets = client.get(
        "/api/v1/notification-targets?company_id=sanlin", headers=bearer
    )
    assert cross_targets.status_code == 403
    assert client.post(
        "/api/v1/notifications/preview",
        headers=bearer,
        json={"company_slug": "sanlin", "target_code": "other"},
    ).status_code == 403
    assert client.post(
        "/api/v1/notifications/preview",
        headers=bearer,
        json={"company_slug": "greenhome", "target_code": "not-allowed"},
    ).status_code == 403
    assert client.post(
        "/api/v1/notifications/send",
        headers=bearer,
        json={
            "company_slug": "sanlin",
            "target_code": "other",
            "body": "跨公司",
            "idempotency_key": "cross-company-send",
        },
    ).status_code == 403
    batches = client.get("/api/v1/notification-batches?company_id=greenhome", headers=bearer)
    assert batches.status_code == 200
    assert [item["id"] for item in batches.json()] == [allowed_batch["id"]]
    assert client.get(
        f"/api/v1/notification-batches/{blocked_batch['id']}", headers=bearer
    ).status_code == 403
    assert client.get("/api/v1/deliveries?company_id=greenhome", headers=bearer).status_code == 403
    assert client.get(
        f"/api/v1/deliveries/{allowed_batch['deliveries'][0]['delivery_id']}",
        headers=bearer,
    ).status_code == 403
    assert (
        client.get("/api/v1/video-assets?company_id=greenhome", headers=bearer).status_code
        == 403
    )
    assert client.get("/api/v1/audit-logs?company_id=greenhome", headers=bearer).status_code == 403

    csrf = client.post(
        "/api/v1/auth/login",
        json={"username": "root", "password": "Strong-Test-Password-123!"},
    ).json()["csrf_token"]
    rotated = client.post(
        f"/api/v1/api-clients/{issued.json()['id']}/rotate",
        headers=auth(csrf),
    )
    assert rotated.status_code == 200
    replacement = rotated.json()["token"]
    client.cookies.clear()
    assert client.get("/api/v1/authorized-companies", headers=bearer).status_code == 401
    assert client.get(
        "/api/v1/authorized-companies",
        headers={"Authorization": f"Bearer {replacement}"},
    ).status_code == 200


def test_api_client_delete_is_permanent_and_keeps_notification_history(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="delete-client-bot")
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    create_target(
        client,
        csrf,
        company_id="greenhome",
        code="delete-client-alerts",
        binding_ids=[detail["binding"]["binding_id"]],
    )
    issued = client.post(
        "/api/v1/api-clients",
        headers=auth(csrf),
        json={
            "company_id": "greenhome",
            "name": "temporary-integration",
            "permissions": ["query", "send", "status"],
            "allowed_target_codes": ["delete-client-alerts"],
        },
    )
    assert issued.status_code == 201, issued.text
    client_id = issued.json()["id"]
    bearer = {"Authorization": f"Bearer {issued.json()['token']}"}
    client.cookies.clear()
    sent = client.post(
        "/api/v1/notifications/send",
        headers=bearer,
        json={
            "company_slug": "greenhome",
            "target_code": "delete-client-alerts",
            "body": "删除接入后仍应保留的通知",
            "idempotency_key": "delete-client-history",
        },
    )
    assert sent.status_code == 201, sent.text
    batch_id = sent.json()["id"]

    csrf = login(client)
    rejected = client.request(
        "DELETE",
        f"/api/v1/api-clients/{client_id}",
        headers=auth(csrf),
        json={"confirm": False},
    )
    assert rejected.status_code == 422
    deleted = client.request(
        "DELETE",
        f"/api/v1/api-clients/{client_id}",
        headers=auth(csrf),
        json={"confirm": True},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {
        "ok": True,
        "deleted_id": client_id,
        "detached_notification_batches": 1,
    }
    assert all(
        item["id"] != client_id
        for item in client.get("/api/v1/api-clients?company_id=greenhome").json()
    )
    assert client.get(f"/api/v1/api-clients/{client_id}/integration-guide").status_code == 404
    assert client.get(f"/api/v1/notification-batches/{batch_id}").status_code == 200
    assert any(
        log["action"] == "api_client.delete" and log["target_id"] == client_id
        for log in client.get("/api/v1/audit-logs?company_id=greenhome").json()
    )
    client.cookies.clear()
    assert client.get("/api/v1/authorized-companies", headers=bearer).status_code == 401


def test_batch_send_is_idempotent_deduplicated_and_reports_each_bot(client: TestClient) -> None:
    csrf = login(client)
    first = bind_and_activate(client, csrf, account="batch-one")
    second = bind_and_activate(client, csrf, account="batch-two")
    employees = client.get("/api/v1/employees?company_id=greenhome").json()
    binding_ids = [
        item["binding"]["binding_id"]
        for item in employees
        if item["id"] in {first["id"], second["id"]}
    ]
    create_target(
        client,
        csrf,
        company_id="greenhome",
        code="batch-team",
        binding_ids=binding_ids + binding_ids,
        mode="multi",
    )

    payload = {
        "company_slug": "greenhome",
        "target_code": "batch-team",
        "title": "系统告警",
        "body": "请检查服务状态",
        "idempotency_key": "alert-2026-001",
    }
    first_send = client.post("/api/v1/notifications/send", headers=auth(csrf), json=payload)
    replay = client.post("/api/v1/notifications/send", headers=auth(csrf), json=payload)
    assert first_send.status_code == 201, first_send.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first_send.json()["id"]
    assert first_send.json()["total"] == 2
    assert first_send.json()["sent"] == 0
    assert first_send.json()["simulated"] == 2
    assert first_send.json()["status"] == "simulated"
    assert len(first_send.json()["deliveries"]) == 2
    assert len({item["bot_id"] for item in first_send.json()["deliveries"]}) == 2
    assert all("***" in item["bot_masked"] for item in first_send.json()["deliveries"])

    conflict = client.post(
        "/api/v1/notifications/send",
        headers=auth(csrf),
        json={**payload, "body": "不同内容"},
    )
    assert conflict.status_code == 409
    status = client.get(f"/api/v1/notification-batches/{first_send.json()['id']}")
    assert status.status_code == 200
    assert status.json()["total"] == 2


def test_idempotent_replay_recovers_unleased_pending_batch_delivery(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="pending-recovery")
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    create_target(
        client,
        csrf,
        company_id="greenhome",
        code="pending-recovery",
        binding_ids=[detail["binding"]["binding_id"]],
    )
    payload = {
        "company_slug": "greenhome",
        "target_code": "pending-recovery",
        "body": "恢复待处理投递",
        "idempotency_key": "pending-recovery-001",
    }
    created = client.post("/api/v1/notifications/send", headers=auth(csrf), json=payload)
    assert created.status_code == 201
    delivery_id = created.json()["deliveries"][0]["delivery_id"]
    with client.app.state.session_factory() as database:
        delivery = database.get(Delivery, delivery_id)
        assert delivery is not None
        delivery.status = DeliveryStatus.PENDING
        delivery.dispatch_token = None
        delivery.dispatch_lease_expires_at = None
        delivery.text_sent_at = None
        database.commit()

    replay = client.post("/api/v1/notifications/send", headers=auth(csrf), json=payload)
    assert replay.status_code == 200
    assert replay.json()["sent"] == 0
    assert replay.json()["simulated"] == 1
    assert replay.json()["status"] == "simulated"


def test_historical_delivery_without_binding_version_never_uses_current_bot(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="historical-version")
    created = client.post(
        "/api/v1/deliveries",
        headers={"X-CSRF-Token": csrf, "X-Test-Force-Failure": "true"},
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "title": "历史通知",
            "idempotency_key": "historical-version-001",
        },
    )
    assert created.status_code == 201
    with client.app.state.session_factory() as database:
        delivery = database.get(Delivery, created.json()["id"])
        assert delivery is not None and delivery.binding_id is not None
        delivery.binding_id = None
        database.commit()

    retried = client.post(
        f"/api/v1/deliveries/{created.json()['id']}/retry",
        headers=auth(csrf),
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "failed"
    assert retried.json()["failure_code"] == "binding_version_unknown"


def test_migrated_employee_target_follows_replacement_active_binding(
    client: TestClient,
) -> None:
    csrf = login(client)
    first = bind_and_activate(client, csrf, account="compatibility-old")
    second = bind_and_activate(client, csrf, account="compatibility-new")
    with client.app.state.session_factory() as database:
        old_binding = database.query(EmployeeBotBinding).filter_by(
            employee_id=first["id"], active=True
        ).one()
        replacement = database.query(EmployeeBotBinding).filter_by(
            employee_id=second["id"], active=True
        ).one()
        target = NotificationTarget(
            id=first["id"],
            company_id="greenhome",
            target_code=f"employee-{first['id']}",
            display_name="迁移兼容对象",
            mode=TargetMode.SINGLE,
            employee_id=first["id"],
        )
        database.add(target)
        database.flush()
        database.add(
            TargetBotMember(
                id=old_binding.id,
                company_id="greenhome",
                target_id=target.id,
                binding_id=old_binding.id,
                bot_account_id=old_binding.bot_account_id,
            )
        )
        old_binding.active = False
        replacement.active = False
        database.flush()
        database.add(
            EmployeeBotBinding(
                company_id="greenhome",
                employee_id=first["id"],
                bot_account_id=replacement.bot_account_id,
                context_token_encrypted=replacement.context_token_encrypted,
                chat_id_encrypted=replacement.chat_id_encrypted,
            )
        )
        database.commit()

    preview = client.post(
        "/api/v1/notifications/preview",
        headers=auth(csrf),
        json={
            "company_slug": "greenhome",
            "target_code": f"employee-{first['id']}",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["bot_count"] == 1


def test_batch_response_dynamically_aggregates_current_delivery_state(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="dynamic-aggregate")
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    create_target(
        client,
        csrf,
        company_id="greenhome",
        code="dynamic-aggregate",
        binding_ids=[detail["binding"]["binding_id"]],
    )
    created = client.post(
        "/api/v1/notifications/send",
        headers=auth(csrf),
        json={
            "company_slug": "greenhome",
            "target_code": "dynamic-aggregate",
            "body": "动态聚合",
            "idempotency_key": "dynamic-aggregate-001",
        },
    ).json()
    with client.app.state.session_factory() as database:
        delivery = database.get(Delivery, created["deliveries"][0]["delivery_id"])
        assert delivery is not None
        delivery.status = DeliveryStatus.FAILED
        delivery.failure_code = "later_failure"
        delivery.failure_message = "安全失败摘要"
        database.commit()

    detail_response = client.get(f"/api/v1/notification-batches/{created['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "failed"
    assert detail_response.json()["sent"] == 0
    assert detail_response.json()["failed"] == 1
    listed = client.get("/api/v1/notification-batches?company_id=greenhome").json()
    current = next(item for item in listed if item["id"] == created["id"])
    assert current["status"] == "failed"
    assert current["failed"] == 1
    targets = client.get("/api/v1/notification-targets?company_id=greenhome").json()
    target = next(item for item in targets if item["target_code"] == "dynamic-aggregate")
    assert target["last_send_status"] == "failed"


def test_formal_batch_send_rejects_non_weixin_mode_without_creating_rows(
    client: TestClient,
) -> None:
    csrf = login(client)
    settings = client.app.state.settings
    original_environment = settings.environment
    original_mode = settings.delivery_mode
    try:
        object.__setattr__(settings, "environment", "production")
        object.__setattr__(settings, "delivery_mode", "mock")
        response = client.post(
            "/api/v1/notifications/send",
            headers=auth(csrf),
            json={
                "company_slug": "greenhome",
                "target_code": "does-not-matter",
                "body": "不得发送",
                "idempotency_key": "non-weixin-blocked",
            },
        )
    finally:
        object.__setattr__(settings, "environment", original_environment)
        object.__setattr__(settings, "delivery_mode", original_mode)
    assert response.status_code == 409
    assert "运行模式" in response.json()["detail"]


def test_disabled_company_target_and_bot_are_rejected_with_clear_errors(client: TestClient) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="disable-bot")
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    target = create_target(
        client,
        csrf,
        company_id="greenhome",
        code="disable-target",
        binding_ids=[detail["binding"]["binding_id"]],
    )
    disabled_target = client.patch(
        f"/api/v1/notification-targets/{target['target_id']}",
        headers=auth(csrf),
        json={"enabled": False},
    )
    assert disabled_target.status_code == 200
    blocked = client.post(
        "/api/v1/notifications/send",
        headers=auth(csrf),
        json={
            "company_slug": "greenhome",
            "target_code": "disable-target",
            "body": "blocked",
            "idempotency_key": "blocked-target",
        },
    )
    assert blocked.status_code == 409
    assert "停用" in blocked.json()["detail"]

    client.patch(
        f"/api/v1/notification-targets/{target['target_id']}",
        headers=auth(csrf),
        json={"enabled": True},
    )
    client.patch(
        "/api/v1/companies/greenhome",
        headers=auth(csrf),
        json={"enabled": False},
    )
    company_blocked = client.post(
        "/api/v1/notifications/preview",
        headers=auth(csrf),
        json={"company_slug": "greenhome", "target_code": "disable-target"},
    )
    assert company_blocked.status_code == 409
    assert "公司" in company_blocked.json()["detail"]


def test_batch_partial_failure_is_recorded_per_bot(client: TestClient) -> None:
    csrf = login(client)
    first = bind_and_activate(client, csrf, account="partial-one")
    second = bind_and_activate(client, csrf, account="partial-two")
    employees = client.get("/api/v1/employees?company_id=greenhome").json()
    bindings = {
        item["id"]: item["binding"]["binding_id"]
        for item in employees
        if item["id"] in {first["id"], second["id"]}
    }
    create_target(
        client,
        csrf,
        company_id="greenhome",
        code="partial-team",
        binding_ids=list(bindings.values()),
        mode="multi",
    )
    result = client.post(
        "/api/v1/notifications/send",
        headers={
            "X-CSRF-Token": csrf,
            "X-Test-Fail-Binding-ID": bindings[first["id"]],
        },
        json={
            "company_slug": "greenhome",
            "target_code": "partial-team",
            "body": "部分失败测试",
            "idempotency_key": "partial-failure-001",
        },
    )
    assert result.status_code == 201
    assert result.json()["status"] == "partial"
    assert result.json()["sent"] == 0
    assert result.json()["simulated"] == 1
    assert result.json()["failed"] == 1
    assert {item["status"] for item in result.json()["deliveries"]} == {
        "simulated",
        "failed",
    }
    failed = next(item for item in result.json()["deliveries"] if item["status"] == "failed")
    assert failed["failure_code"] == "mock_failure"


def test_single_target_accepts_tenant_scoped_image_file_or_video_attachment(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="attachment-bot")
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    create_target(
        client,
        csrf,
        company_id="greenhome",
        code="attachment-target",
        binding_ids=[detail["binding"]["binding_id"]],
    )
    uploaded = client.post(
        "/api/v1/media-assets",
        headers={"X-CSRF-Token": csrf},
        data={"company_id": "greenhome", "employee_id": employee["id"]},
        files={"file": ("notice.txt", b"safe notification attachment", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    sent = client.post(
        "/api/v1/notifications/send",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_slug": "greenhome",
            "target_code": "attachment-target",
            "body": "附件通知",
            "media_asset_id": uploaded.json()["id"],
            "idempotency_key": "attachment-001",
        },
    )
    assert sent.status_code == 201, sent.text
    with client.app.state.session_factory() as database:
        delivery = database.get(Delivery, sent.json()["deliveries"][0]["delivery_id"])
        assert delivery is not None
        assert delivery.video_asset_id == uploaded.json()["id"]
