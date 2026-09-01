from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("APP_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("APP_BASE_PATH", "/weixin-bot-notification-platform")
    monkeypatch.setenv(
        "APP_PUBLIC_BASE_URL", "https://notify.example.com/weixin-bot-notification-platform"
    )
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-that-is-long-enough-123")
    monkeypatch.setenv("APP_IDENTIFIER_HMAC_KEY", "test-hmac-key-that-is-long-enough-123")
    monkeypatch.setenv(
        "APP_IDENTIFIER_ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
    )
    monkeypatch.setenv("APP_BOOTSTRAP_ADMIN_USERNAME", "root")
    monkeypatch.setenv("APP_BOOTSTRAP_ADMIN_PASSWORD", "Strong-Test-Password-123!")
    monkeypatch.setenv("APP_DELIVERY_MODE", "mock")
    monkeypatch.setenv("APP_BOT_WEBHOOK_SECRET", "test-bot-webhook-secret-123456789")
    monkeypatch.setenv("APP_SERVICE_API_TOKEN", "test-service-api-token-123456789")
    monkeypatch.setenv(
        "APP_COMPANY_SERVICE_TOKENS_JSON",
        '{"greenhome":"greenhome-business-token-123456789"}',
    )

    from app.ilink_binding import IlinkQrAdapter, IlinkQrTicket

    counter = {"value": 0}

    def fake_qr(*, ttl_seconds: int) -> IlinkQrTicket:
        counter["value"] += 1
        return IlinkQrTicket(
            ticket=f"test-official-ticket-{counter['value']}",
            scan_data=f"https://weixin.test/qr/{counter['value']}",
            base_url="https://ilink.test",
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )

    monkeypatch.setattr(IlinkQrAdapter, "create", staticmethod(fake_qr))

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
