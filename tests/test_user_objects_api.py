from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AuditLog, Employee, NotificationTarget, UserObjectContact
from tests.test_binding import login
from tests.test_binding_notifications import bind_and_activate
from tests.test_platform_api import auth, create_target


def create_user_object(client: TestClient, csrf: str, account_name: str = "客户通知组") -> dict:
    response = client.post(
        "/api/v1/companies/greenhome/user-objects",
        headers=auth(csrf),
        json={"account_name": account_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_user_object_can_start_empty_and_contact_phone_is_encrypted_and_redacted(
    client: TestClient,
) -> None:
    csrf = login(client)
    created = create_user_object(client, csrf)
    code = created["user_object_code"]
    assert re.fullmatch(r"uo_[a-z0-9]{20}", code)
    assert created["mode"] == "multi"
    assert created["contacts"] == []
    assert created["all_available"] is False
    assert created["bound_count"] == 0
    assert created["pending_count"] == 0
    assert created["unhealthy_count"] == 0

    added = client.post(
        f"/api/v1/companies/greenhome/user-objects/{code}/contacts",
        headers=auth(csrf),
        json={"name": "张三", "phone": "138 0013 8000"},
    )
    assert added.status_code == 201, added.text
    contact = added.json()
    assert contact["name"] == "张三"
    assert contact["phone"] == "+8613800138000"
    assert contact["masked_phone"] == "138****8000"
    assert contact["binding"] is None
    assert not ({"phone_encrypted", "phone_fingerprint"} & contact.keys())

    factory = client.app.state.session_factory
    with factory() as session:
        employee = session.get(Employee, contact["employee_id"])
        assert employee is not None
        assert employee.phone_encrypted and "13800138000" not in employee.phone_encrypted
        assert employee.phone_fingerprint and employee.phone_fingerprint != "+8613800138000"
        assert session.scalar(
            select(AuditLog).where(AuditLog.action == "user_object.contact.add")
        )

    business = client.get(
        f"/api/v1/companies/greenhome/user-objects/{code}",
        headers={"Authorization": "Bearer greenhome-business-token-123456789"},
    )
    assert business.status_code == 200, business.text
    business_contact = business.json()["contacts"][0]
    assert "phone" not in business_contact
    assert business_contact["masked_phone"] == "138****8000"
    assert "binding_session" not in business_contact
    assert not ({"phone_encrypted", "phone_fingerprint"} & business_contact.keys())


def test_contact_memberships_are_idempotent_and_soft_removed(client: TestClient) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="stable-contact")
    obj = create_user_object(client, csrf, "稳定关系")
    path = (
        f"/api/v1/companies/greenhome/user-objects/{obj['user_object_code']}/contacts"
    )
    first = client.post(path, headers=auth(csrf), json={"employee_id": employee["id"]})
    second = client.post(path, headers=auth(csrf), json={"employee_id": employee["id"]})
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text

    detail = client.get(
        f"/api/v1/companies/greenhome/user-objects/{obj['user_object_code']}"
    ).json()
    assert [item["employee_id"] for item in detail["contacts"]] == [employee["id"]]

    rejected = client.request(
        "DELETE", f"{path}/{employee['id']}", headers=auth(csrf), json={"confirm": False}
    )
    assert rejected.status_code == 422
    removed = client.request(
        "DELETE", f"{path}/{employee['id']}", headers=auth(csrf), json={"confirm": True}
    )
    assert removed.status_code == 200, removed.text
    assert client.get(
        f"/api/v1/companies/greenhome/user-objects/{obj['user_object_code']}"
    ).json()["contacts"] == []
    factory = client.app.state.session_factory
    with factory() as session:
        history = session.scalars(
            select(UserObjectContact).where(
                UserObjectContact.target_id == obj["target_id"],
                UserObjectContact.employee_id == employee["id"],
            )
        ).all()
        assert len(history) == 1
        assert history[0].active is False
        assert history[0].removed_at is not None


def test_user_object_deletion_requires_server_confirmation(client: TestClient) -> None:
    csrf = login(client)
    obj = create_user_object(client, csrf, "待删除对象")
    path = f"/api/v1/companies/greenhome/user-objects/{obj['user_object_code']}"
    rejected = client.request(
        "DELETE", path, headers=auth(csrf), json={"confirm": False}
    )
    assert rejected.status_code == 422
    assert client.get(path).status_code == 200
    accepted = client.request(
        "DELETE", path, headers=auth(csrf), json={"confirm": True}
    )
    assert accepted.status_code == 200
    assert client.get(path).status_code == 404


def test_user_object_deactivation_requires_confirmation_and_old_route_cannot_bypass(
    client: TestClient,
) -> None:
    csrf = login(client)
    obj = create_user_object(client, csrf, "待停用对象")
    path = f"/api/v1/companies/greenhome/user-objects/{obj['user_object_code']}"

    rejected = client.patch(
        path, headers=auth(csrf), json={"enabled": False, "confirm": False}
    )
    assert rejected.status_code == 422
    assert client.get(path).json()["enabled"] is True

    bypass = client.patch(
        f"/api/v1/notification-targets/{obj['target_id']}",
        headers=auth(csrf),
        json={"enabled": False, "mode": "dynamic_all", "binding_ids": []},
    )
    assert bypass.status_code == 409
    with client.app.state.session_factory() as session:
        persisted = session.get(NotificationTarget, obj["target_id"])
        assert persisted is not None
        assert persisted.enabled is True
        assert persisted.mode.value == "multi"

    accepted = client.patch(
        path, headers=auth(csrf), json={"enabled": False, "confirm": True}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["enabled"] is False


def test_database_api_client_user_object_queries_enforce_permission_tenant_and_allowlist(
    client: TestClient,
) -> None:
    csrf = login(client)
    allowed = create_user_object(client, csrf, "允许对象")
    blocked = create_user_object(client, csrf, "禁止对象")
    issued = client.post(
        "/api/v1/api-clients",
        headers=auth(csrf),
        json={
            "company_id": "greenhome",
            "name": "user-object-query",
            "permissions": ["query"],
            "allowed_target_codes": [allowed["user_object_code"]],
        },
    )
    assert issued.status_code == 201, issued.text
    bearer = {"Authorization": f"Bearer {issued.json()['token']}"}
    client.cookies.clear()

    listed = client.get("/api/v1/companies/greenhome/user-objects", headers=bearer)
    assert listed.status_code == 200, listed.text
    assert [item["user_object_code"] for item in listed.json()] == [
        allowed["user_object_code"]
    ]
    assert client.get(
        f"/api/v1/companies/greenhome/user-objects/{allowed['user_object_code']}",
        headers=bearer,
    ).status_code == 200
    assert client.get(
        f"/api/v1/companies/greenhome/user-objects/{blocked['user_object_code']}",
        headers=bearer,
    ).status_code == 403
    assert client.get("/api/v1/companies/sanlin/user-objects", headers=bearer).status_code == 403

    csrf = login(client)
    denied = client.post(
        "/api/v1/api-clients",
        headers=auth(csrf),
        json={
            "company_id": "greenhome",
            "name": "user-object-no-query",
            "permissions": ["status"],
            "allowed_target_codes": [],
        },
    )
    denied_bearer = {"Authorization": f"Bearer {denied.json()['token']}"}
    client.cookies.clear()
    assert client.get(
        "/api/v1/companies/greenhome/user-objects", headers=denied_bearer
    ).status_code == 403


def test_database_api_client_can_send_to_a_user_object(client: TestClient) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="user-object-api-send")
    obj = create_user_object(client, csrf, "API 发送对象")
    added = client.post(
        f"/api/v1/companies/greenhome/user-objects/{obj['user_object_code']}/contacts",
        headers=auth(csrf),
        json={"employee_id": employee["id"]},
    )
    assert added.status_code == 201, added.text
    issued = client.post(
        "/api/v1/api-clients",
        headers=auth(csrf),
        json={
            "company_id": "greenhome",
            "name": "user-object-api-send",
            "permissions": ["query", "send", "status"],
            "allowed_target_codes": [obj["user_object_code"]],
        },
    )
    assert issued.status_code == 201, issued.text
    client.cookies.clear()
    bearer = {"Authorization": f"Bearer {issued.json()['token']}"}
    sent = client.post(
        "/api/v1/notifications/send",
        headers=bearer,
        json={
            "company_slug": "greenhome",
            "target_code": obj["user_object_code"],
            "body": "用户对象 API 发送测试",
            "idempotency_key": "user-object-api-send-001",
        },
    )
    assert sent.status_code == 201, sent.text
    body = sent.json()
    assert body["total"] == 1
    assert body["simulated"] == 1
    assert body["status"] == "simulated"
    assert client.get(
        f"/api/v1/notification-batches/{body['id']}", headers=bearer
    ).status_code == 200


def test_user_object_binding_alias_reuses_confirmation_and_qr_lifecycle(
    client: TestClient,
) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="alias-binding")
    obj = create_user_object(client, csrf, "绑定入口")
    contacts = (
        f"/api/v1/companies/greenhome/user-objects/{obj['user_object_code']}"
        f"/contacts/{employee['id']}"
    )
    assert client.post(
        contacts.rsplit("/", 1)[0],
        headers=auth(csrf),
        json={"employee_id": employee["id"]},
    ).status_code == 201
    preview_payload = {
        "company_slug": "greenhome",
        "target_code": obj["user_object_code"],
    }
    assert client.post(
        "/api/v1/notifications/preview", headers=auth(csrf), json=preview_payload
    ).json()["bot_count"] == 1

    rejected = client.post(
        f"{contacts}/unbind", headers=auth(csrf), json={"confirm": False}
    )
    assert rejected.status_code == 422
    assert client.get(f"/api/v1/employees/{employee['id']}").json()["binding"] is not None

    accepted = client.post(
        f"{contacts}/unbind", headers=auth(csrf), json={"confirm": True}
    )
    assert accepted.status_code == 200, accepted.text
    assert client.get(f"/api/v1/employees/{employee['id']}").json()["binding"] is None

    qr = client.post(f"{contacts}/binding-sessions", headers=auth(csrf))
    assert qr.status_code == 201, qr.text
    assert qr.json()["qr_image_url"].endswith("/qr.png")


def test_contact_deactivation_requires_confirmation_and_preserves_membership_history(
    client: TestClient,
) -> None:
    csrf = login(client)
    obj = create_user_object(client, csrf, "停用语义")
    code = obj["user_object_code"]
    added = client.post(
        f"/api/v1/companies/greenhome/user-objects/{code}/contacts",
        headers=auth(csrf),
        json={"name": "待停用联系人", "phone": "010-88886666"},
    ).json()
    path = (
        f"/api/v1/companies/greenhome/user-objects/{code}/contacts/"
        f"{added['employee_id']}/deactivate"
    )
    rejected = client.post(path, headers=auth(csrf), json={"confirm": False})
    assert rejected.status_code == 422
    assert client.get(
        f"/api/v1/companies/greenhome/user-objects/{code}"
    ).json()["contacts"][0]["status"] == "active"

    accepted = client.post(path, headers=auth(csrf), json={"confirm": True})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "disabled"
    factory = client.app.state.session_factory
    with factory() as session:
        employee = session.get(Employee, added["employee_id"])
        relation = session.scalar(
            select(UserObjectContact).where(
                UserObjectContact.target_id == obj["target_id"],
                UserObjectContact.employee_id == added["employee_id"],
            )
        )
        assert employee is not None and employee.status.value == "disabled"
        assert relation is not None and relation.active is True


def test_legacy_employee_patch_requires_confirmation_for_user_object_contact(
    client: TestClient,
) -> None:
    csrf = login(client)
    obj = create_user_object(client, csrf, "旧接口停用保护")
    added = client.post(
        f"/api/v1/companies/greenhome/user-objects/{obj['user_object_code']}/contacts",
        headers=auth(csrf),
        json={"name": "受保护联系人", "phone": "010-88886666"},
    ).json()
    path = f"/api/v1/employees/{added['employee_id']}"

    rejected = client.patch(path, headers=auth(csrf), json={"status": "disabled"})
    assert rejected.status_code == 422
    assert client.get(path).json()["status"] == "active"

    accepted = client.patch(
        path,
        headers=auth(csrf),
        json={"status": "disabled", "confirm": True},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "disabled"


def test_legacy_employee_delete_requires_confirmation_for_user_object_contact(
    client: TestClient,
) -> None:
    csrf = login(client)
    obj = create_user_object(client, csrf, "旧接口删除保护")
    added = client.post(
        f"/api/v1/companies/greenhome/user-objects/{obj['user_object_code']}/contacts",
        headers=auth(csrf),
        json={"name": "受保护联系人", "phone": "010-88886666"},
    ).json()
    path = f"/api/v1/employees/{added['employee_id']}"

    rejected = client.delete(path, headers=auth(csrf))
    assert rejected.status_code == 422
    assert client.get(path).status_code == 200

    accepted = client.request(
        "DELETE", path, headers=auth(csrf), json={"confirm": True}
    )
    assert accepted.status_code == 200, accepted.text
    assert client.get(path).status_code == 404


def test_alias_preserves_legacy_single_and_dynamic_all_semantics(client: TestClient) -> None:
    csrf = login(client)
    employee = bind_and_activate(client, csrf, account="legacy-alias")
    detail = client.get(f"/api/v1/employees/{employee['id']}").json()
    create_target(
        client,
        csrf,
        company_id="greenhome",
        code="legacy-single-alias",
        binding_ids=[detail["binding"]["binding_id"]],
    )
    legacy = client.get(
        "/api/v1/companies/greenhome/user-objects/legacy-single-alias"
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["is_user_object"] is False
    assert [item["employee_id"] for item in legacy.json()["contacts"]] == [employee["id"]]
    assert legacy.json()["all_available"] is False

    dynamic = create_target(
        client,
        csrf,
        company_id="greenhome",
        code="everyone-alias",
        mode="dynamic_all",
    )
    dynamic_alias = client.get(
        "/api/v1/companies/greenhome/user-objects/everyone-alias"
    )
    assert dynamic_alias.status_code == 200, dynamic_alias.text
    assert dynamic_alias.json()["target_id"] == dynamic["target_id"]
    assert dynamic_alias.json()["all_available"] is True
    assert [item["employee_id"] for item in dynamic_alias.json()["contacts"]] == [
        employee["id"]
    ]
