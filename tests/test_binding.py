from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "root", "password": "Strong-Test-Password-123!"},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def create_employee(client: TestClient, csrf: str, company_id: str = "greenhome") -> dict:
    response = client.post(
        "/api/v1/employees",
        headers={"X-CSRF-Token": csrf},
        json={
            "company_id": company_id,
            "name": "张工",
            "department": "工程部",
            "content_vertical": "施工工艺",
            "secondary_topics": ["工地实拍"],
            "target_platforms": ["douyin"],
            "account_name": "张工讲施工",
            "tone": "专业直接",
            "video_duration_seconds": 60,
            "publishing_frequency": "每周3条",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_binding_code_is_single_use_and_identifiers_are_masked(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    code_response = client.post(
        f"/api/v1/employees/{employee['id']}/binding-code",
        headers={"X-CSRF-Token": csrf},
    )
    assert code_response.status_code == 201
    code = code_response.json()["code"]

    inbound = {
        "account_id": "dedicated-employee-bot",
        "user_id": "wx-user-sensitive-123456",
        "chat_id": "wx-chat-sensitive-654321",
        "text": f"绑定 {code}",
        "context_token": "context-secret-value",
    }
    first = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json=inbound,
    )
    assert first.status_code == 200
    assert first.json()["command"] == "bind"

    second = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={**inbound, "user_id": "other-user", "chat_id": "other-chat"},
    )
    assert second.status_code == 409

    detail = client.get(f"/api/v1/employees/{employee['id']}")
    assert detail.status_code == 200
    text = detail.text
    assert "wx-user-sensitive-123456" not in text
    assert "wx-chat-sensitive-654321" not in text
    assert "context-secret-value" not in text
    assert detail.json()["binding"]["user_id_masked"].startswith("wx-u")


def test_expired_binding_code_is_rejected(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    response = client.post(
        f"/api/v1/employees/{employee['id']}/binding-code",
        headers={
            "X-CSRF-Token": csrf,
            "X-Test-Expires-At": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        },
    )
    code = response.json()["code"]
    bound = client.post(
        "/api/v1/bot/inbound",
        headers={"X-Bot-Secret": "test-bot-webhook-secret-123456789"},
        json={
            "account_id": "bot",
            "user_id": "u",
            "chat_id": "c",
            "text": f"绑定 {code}",
            "context_token": "ctx",
        },
    )
    assert bound.status_code == 410


def test_unbind_revokes_authorization_and_allows_rebind(client: TestClient) -> None:
    csrf = login(client)
    employee = create_employee(client, csrf)
    code = client.post(
        f"/api/v1/employees/{employee['id']}/binding-code", headers={"X-CSRF-Token": csrf}
    ).json()["code"]
    headers = {"X-Bot-Secret": "test-bot-webhook-secret-123456789"}
    client.post(
        "/api/v1/bot/inbound",
        headers=headers,
        json={
            "account_id": "bot",
            "user_id": "stable-user",
            "chat_id": "stable-chat",
            "text": f"绑定 {code}",
            "context_token": "ctx1",
        },
    )
    assert (
        client.post(
            f"/api/v1/employees/{employee['id']}/unbind",
            headers={"X-CSRF-Token": csrf},
            json={"confirm": True},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/employees/{employee['id']}").json()["binding"] is None
    new_code = client.post(
        f"/api/v1/employees/{employee['id']}/binding-code", headers={"X-CSRF-Token": csrf}
    ).json()["code"]
    rebound = client.post(
        "/api/v1/bot/inbound",
        headers=headers,
        json={
            "account_id": "bot",
            "user_id": "stable-user",
            "chat_id": "stable-chat",
            "text": f"绑定 {new_code}",
            "context_token": "ctx2",
        },
    )
    assert rebound.status_code == 200
