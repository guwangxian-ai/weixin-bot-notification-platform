import warnings

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SAWarning


def test_health_reports_mock_mode_without_secrets(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "delivery_mode": "mock", "bot_configured": False}
    assert "token" not in response.text.lower()


def test_login_required_for_business_api(client: TestClient) -> None:
    response = client.get("/api/v1/employees")
    assert response.status_code == 401


def test_invalid_bearer_is_rejected_without_sqlalchemy_warning(
    client: TestClient,
) -> None:
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        response = client.get(
            "/api/v1/authorized-companies",
            headers={"Authorization": "Bearer invalid-acceptance-token"},
        )
    assert response.status_code == 401
    assert not [warning for warning in recorded if issubclass(warning.category, SAWarning)]


@pytest.mark.parametrize(
    "company_tokens",
    [
        '{"greenhome":"test-service-api-token-123456789"}',
        (
            '{"greenhome":"shared-business-token-123456789",'
            '"sanlin":"shared-business-token-123456789"}'
        ),
    ],
)
def test_service_tokens_must_be_pairwise_distinct(monkeypatch, company_tokens: str) -> None:
    from app.config import Settings

    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-that-is-long-enough-123")
    monkeypatch.setenv("APP_BOT_WEBHOOK_SECRET", "test-bot-webhook-secret-123456789")
    monkeypatch.setenv("APP_SERVICE_API_TOKEN", "test-service-api-token-123456789")
    monkeypatch.setenv("APP_COMPANY_SERVICE_TOKENS_JSON", company_tokens)
    with pytest.raises(RuntimeError, match="token"):
        Settings.from_env().validate()
