from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_binding import create_employee, login
from tests.test_delivery import FAKE_MP4, bind_employee


def create_user(
    client: TestClient, csrf: str, username: str, role: str, company_id: str | None
) -> None:
    response = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": csrf},
        json={
            "username": username,
            "password": "Other-Strong-Password-123!",
            "role": role,
            "company_id": company_id,
        },
    )
    assert response.status_code == 201, response.text


def relogin(client: TestClient, username: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "Other-Strong-Password-123!"},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def test_company_admin_cannot_read_or_mutate_other_company(client: TestClient) -> None:
    root_csrf = login(client)
    create_employee(client, root_csrf, "greenhome")
    sanlin_employee = create_employee(client, root_csrf, "sanlin")
    create_user(client, root_csrf, "green-admin", "company_admin", "greenhome")
    green_csrf = relogin(client, "green-admin")

    assert client.get("/api/v1/employees?company_id=sanlin").status_code == 403
    assert client.get(f"/api/v1/employees/{sanlin_employee['id']}").status_code == 403
    assert (
        client.patch(
            f"/api/v1/employees/{sanlin_employee['id']}",
            headers={"X-CSRF-Token": green_csrf},
            json={"account_name": "越权修改"},
        ).status_code
        == 403
    )


def test_viewer_cannot_modify(client: TestClient) -> None:
    root_csrf = login(client)
    create_user(client, root_csrf, "green-viewer", "viewer", "greenhome")
    viewer_csrf = relogin(client, "green-viewer")
    response = client.post(
        "/api/v1/employees",
        headers={"X-CSRF-Token": viewer_csrf},
        json={"company_id": "greenhome", "name": "只读越权"},
    )
    assert response.status_code == 403
    send = client.post(
        "/api/v1/notifications/send",
        headers={"X-CSRF-Token": viewer_csrf},
        json={
            "company_slug": "greenhome",
            "target_code": "any",
            "body": "只读角色不得发送",
            "idempotency_key": "viewer-send",
        },
    )
    assert send.status_code == 403


def test_authenticated_session_is_recovered_and_logout_invalidates_it(
    client: TestClient,
) -> None:
    csrf = login(client)
    recovered = client.get("/api/v1/auth/session")
    assert recovered.status_code == 200
    assert recovered.json()["csrf_token"] == csrf
    assert recovered.json()["role"] == "super_admin"

    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
    ).status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401


def test_csrf_is_required_for_mutations(client: TestClient) -> None:
    login(client)
    response = client.post("/api/v1/employees", json={"company_id": "greenhome", "name": "CSRF"})
    assert response.status_code == 403


def test_company_service_token_is_tenant_scoped_and_business_only(client: TestClient) -> None:
    root_csrf = login(client)
    employee = create_employee(client, root_csrf, "greenhome")
    sanlin_employee = create_employee(client, root_csrf, "sanlin")
    bind_employee(client, root_csrf, employee["id"])
    client.cookies.clear()
    headers = {"Authorization": "Bearer greenhome-business-token-123456789"}

    employees = client.get("/api/v1/employees?company_id=greenhome", headers=headers)
    assert employees.status_code == 200
    assert {item["company_id"] for item in employees.json()} == {"greenhome"}
    assert all("binding_session" not in item for item in employees.json())
    employee_detail = client.get(f"/api/v1/employees/{employee['id']}", headers=headers)
    assert employee_detail.status_code == 200
    assert "binding_session" not in employee_detail.json()
    cross_company = client.get(
        f"/api/v1/employees/{sanlin_employee['id']}", headers=headers
    )
    assert cross_company.status_code == 403

    asset = client.post(
        "/api/v1/video-assets",
        headers=headers,
        files={"file": ("notice.mp4", FAKE_MP4, "video/mp4")},
        data={"company_id": "greenhome", "employee_id": employee["id"]},
    )
    assert asset.status_code == 201
    delivery = client.post(
        "/api/v1/deliveries",
        headers=headers,
        json={
            "company_id": "greenhome",
            "employee_id": employee["id"],
            "title": "业务通知",
            "video_asset_id": asset.json()["id"],
            "idempotency_key": "business-service-001",
        },
    )
    assert delivery.status_code == 201
    delivery_status = client.get(
        f"/api/v1/deliveries/{delivery.json()['id']}", headers=headers
    )
    assert delivery_status.status_code == 200

    assert (
        client.post(
            "/api/v1/employees",
            headers=headers,
            json={"company_id": "greenhome", "name": "越权创建"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/employees/{employee['id']}/unbind",
            headers=headers,
            json={"confirm": True},
        ).status_code
        == 403
    )
    cancel = client.post(
        f"/api/v1/deliveries/{delivery.json()['id']}/cancel", headers=headers
    )
    assert cancel.status_code == 403
    assert client.get("/api/v1/audit-logs?company_id=greenhome", headers=headers).status_code == 403


def test_legacy_platform_service_token_remains_compatible(client: TestClient) -> None:
    headers = {"Authorization": "Bearer test-service-api-token-123456789"}
    response = client.post(
        "/api/v1/employees",
        headers=headers,
        json={"company_id": "sanlin", "name": "兼容服务调用"},
    )
    assert response.status_code == 201
