from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    upload_dir: Path
    base_path: str
    public_base_url: str
    secret_key: str
    identifier_encryption_key: str
    identifier_hmac_key: str
    delivery_mode: str
    bootstrap_admin_username: str
    bootstrap_admin_password: str
    binding_ttl_seconds: int
    download_ttl_seconds: int
    native_video_max_bytes: int
    upload_max_bytes: int
    weixin_account_id: str
    weixin_token: str
    bot_webhook_secret: str
    service_api_token: str
    company_service_tokens: dict[str, str]

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            environment=os.getenv("APP_ENV", "development"),
            database_url=os.getenv("APP_DATABASE_URL", "sqlite:///./data/notification-center.db"),
            upload_dir=Path(os.getenv("APP_UPLOAD_DIR", "./uploads")).resolve(),
            base_path=os.getenv("APP_BASE_PATH", "/weixin-bot-notification-platform").rstrip(
                "/"
            ),
            public_base_url=os.getenv(
                "APP_PUBLIC_BASE_URL",
                "http://127.0.0.1:8091",
            ).rstrip("/"),
            secret_key=os.getenv("APP_SECRET_KEY", ""),
            identifier_encryption_key=os.getenv("APP_IDENTIFIER_ENCRYPTION_KEY", ""),
            identifier_hmac_key=os.getenv("APP_IDENTIFIER_HMAC_KEY", ""),
            delivery_mode=os.getenv("APP_DELIVERY_MODE", "mock"),
            bootstrap_admin_username=os.getenv("APP_BOOTSTRAP_ADMIN_USERNAME", "admin"),
            bootstrap_admin_password=os.getenv("APP_BOOTSTRAP_ADMIN_PASSWORD", ""),
            binding_ttl_seconds=int(os.getenv("APP_BINDING_TTL_SECONDS", "600")),
            download_ttl_seconds=int(os.getenv("APP_DOWNLOAD_TTL_SECONDS", "900")),
            native_video_max_bytes=int(os.getenv("APP_NATIVE_VIDEO_MAX_BYTES", "20971520")),
            upload_max_bytes=int(os.getenv("APP_UPLOAD_MAX_BYTES", "268435456")),
            weixin_account_id=os.getenv("EMPLOYEE_WEIXIN_ACCOUNT_ID", ""),
            weixin_token=os.getenv("EMPLOYEE_WEIXIN_TOKEN", ""),
            bot_webhook_secret=os.getenv("APP_BOT_WEBHOOK_SECRET", ""),
            service_api_token=os.getenv("APP_SERVICE_API_TOKEN", ""),
            company_service_tokens=_company_service_tokens_from_env(),
        )

    def validate(self) -> None:
        if len(self.secret_key) < 32:
            raise RuntimeError("APP_SECRET_KEY must contain at least 32 characters")
        if self.delivery_mode not in {"mock", "dry-run", "weixin"}:
            raise RuntimeError("APP_DELIVERY_MODE must be mock, dry-run, or weixin")
        if self.upload_max_bytes <= 0:
            raise RuntimeError("APP_UPLOAD_MAX_BYTES must be positive")

        if len(self.bot_webhook_secret) < 24:
            raise RuntimeError("APP_BOT_WEBHOOK_SECRET must contain at least 24 characters")
        if len(self.service_api_token) < 24:
            raise RuntimeError("APP_SERVICE_API_TOKEN must contain at least 24 characters")
        if any(
            not company_id or len(token) < 24
            for company_id, token in self.company_service_tokens.items()
        ):
            raise RuntimeError(
                "Company service token entries require a company_id and 24+ character token"
            )
        company_tokens = list(self.company_service_tokens.values())
        if self.service_api_token in company_tokens:
            raise RuntimeError("Company service tokens must differ from the platform service token")
        if len(company_tokens) != len(set(company_tokens)):
            raise RuntimeError("Each company service token must be unique")


def _company_service_tokens_from_env() -> dict[str, str]:
    raw = os.getenv("APP_COMPANY_SERVICE_TOKENS_JSON", "{}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("APP_COMPANY_SERVICE_TOKENS_JSON must be a JSON object") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(company_id, str) and isinstance(token, str)
        for company_id, token in parsed.items()
    ):
        raise RuntimeError("APP_COMPANY_SERVICE_TOKENS_JSON must map company IDs to tokens")
    return parsed
