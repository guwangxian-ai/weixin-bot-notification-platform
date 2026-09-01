from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import WeixinBotAccount
from tests.test_binding import create_employee, login
from tests.test_bot_binding_sessions import activate_independent_bot, qr_ticket


def test_weixin_send_failure_is_explicit_and_audited(client: TestClient) -> None:
    from app.weixin_delivery import SendOutcome

    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    activate_independent_bot(client, csrf, employee, "send-failure-bot")
    settings = client.app.state.settings
    original_mode = settings.delivery_mode
    object.__setattr__(settings, "delivery_mode", "weixin")
    try:
        with patch(
            "app.weixin_delivery.send_video",
            return_value=SendOutcome(
                False,
                error="微信发送失败，请稍后重试",
                error_code="weixin_ret_-2",
            ),
        ):
            response = client.post(
                "/api/v1/deliveries",
                headers={"X-CSRF-Token": csrf},
                json={
                    "company_id": "greenhome",
                    "employee_id": employee["id"],
                    "title": "发送失败测试",
                    "idempotency_key": "send-failure-notification",
                },
            )
    finally:
        object.__setattr__(settings, "delivery_mode", original_mode)

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["failure_code"] == "weixin_ret_-2"
    assert response.json()["failure_message"] == "微信发送失败，请稍后重试"
    logs = client.get("/api/v1/audit-logs?company_id=greenhome").json()
    assert any(log["action"] == "delivery.send_failed" for log in logs)


def test_invalid_bot_credentials_are_explicit_and_audited(client: TestClient) -> None:
    csrf = login(client)
    with patch("app.ilink_binding.IlinkQrAdapter.create", return_value=qr_ticket()):
        employee = create_employee(client, csrf)
    activate_independent_bot(client, csrf, employee, "invalid-credential-bot")
    with client.app.state.session_factory() as session:
        account = session.scalar(select(WeixinBotAccount))
        assert account is not None
        account.bot_token_encrypted = (
            "invalid-fernet-ciphertext"  # noqa: S105 - deliberately corrupted test cipher
        )
        session.commit()
    settings = client.app.state.settings
    original_mode = settings.delivery_mode
    object.__setattr__(settings, "delivery_mode", "weixin")
    try:
        response = client.post(
            "/api/v1/deliveries",
            headers={"X-CSRF-Token": csrf},
            json={
                "company_id": "greenhome",
                "employee_id": employee["id"],
                "title": "凭据失效测试",
                "idempotency_key": "invalid-credential-notification",
            },
        )
    finally:
        object.__setattr__(settings, "delivery_mode", original_mode)

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["failure_code"] == "bot_credentials_invalid"
    assert response.json()["failure_message"] == "员工微信 Bot 凭据已失效，请重新绑定"
    logs = client.get("/api/v1/audit-logs?company_id=greenhome").json()
    assert any(log["action"] == "delivery.credentials_invalid" for log in logs)
