from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.database import create_database
from app.hermes_runtime import install_hermes_agent_import_path
from app.models import Employee, EmployeeBotBinding, EmployeeStatus, WeixinBotAccount

logger = logging.getLogger(__name__)


class SafeWorkerLogFilter(logging.Filter):
    """Fail closed: Hermes adapter records may contain upstream response data."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("gateway.")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(SafeWorkerLogFilter())


def remove_legacy_plaintext_context_files(hermes_home: Path) -> int:
    """Delete context-token JSON left by older disk-backed worker versions."""
    removed = 0
    for path in hermes_home.rglob("*.context-tokens.json"):
        if path.is_file() and not path.is_symlink():
            path.unlink()
            removed += 1
    return removed


class InMemoryContextTokenStore:
    """Keep iLink context tokens in memory; the API persists only Fernet ciphertext."""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    @staticmethod
    def _key(account_id: str, user_id: str) -> str:
        return f"{account_id}\0{user_id}"

    def restore(self, _account_id: str) -> None:
        return

    def get(self, account_id: str, user_id: str) -> str | None:
        return self._cache.get(self._key(account_id, user_id))

    def set(self, account_id: str, user_id: str, token: str) -> None:
        self._cache[self._key(account_id, user_id)] = token


@dataclass(frozen=True)
class BotCredential:
    record_id: str
    employee_id: str
    employee_ref: str
    account_id: str
    owner_user_id: str
    token: str
    base_url: str


@dataclass(frozen=True)
class PollDiagnosticIdentity:
    employee_ref: str
    account_id: str
    owner_user_id: str


class SafeGetUpdatesProbe:
    """Log only aggregate iLink poll facts; never identifiers or response content."""

    def __init__(
        self,
        original: Any,
        correlation_key: bytes,
        *,
        empty_log_interval_seconds: float = 300,
    ) -> None:
        self._original = original
        self._correlation_key = correlation_key
        self._empty_log_interval_seconds = empty_log_interval_seconds
        self._identities: dict[str, PollDiagnosticIdentity] = {}
        self._last_empty_log: dict[str, float] = {}

    def _token_ref(self, token: str) -> str:
        return hmac.new(self._correlation_key, token.encode(), hashlib.sha256).hexdigest()

    def update_credentials(self, credentials: Any) -> None:
        self._identities = {
            self._token_ref(item.token): PollDiagnosticIdentity(
                employee_ref=item.employee_ref,
                account_id=item.account_id,
                owner_user_id=item.owner_user_id,
            )
            for item in credentials
        }
        self._last_empty_log = {
            token_ref: value
            for token_ref, value in self._last_empty_log.items()
            if token_ref in self._identities
        }

    def clear(self) -> None:
        self._identities.clear()
        self._last_empty_log.clear()

    async def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        token = str(kwargs.get("token") or "")
        token_ref = self._token_ref(token)
        sync_buf = str(kwargs.get("sync_buf") or "")
        identity = self._identities.get(token_ref)
        try:
            response = await self._original(*args, **kwargs)
        except Exception as exc:
            logger.warning(
                "Employee Bot getUpdates exception employee_ref=%s error_type=%s",
                identity.employee_ref if identity else "unknown",
                type(exc).__name__,
            )
            return {
                "ret": -1,
                "errcode": -1,
                "errmsg": "",
                "msgs": [],
                "get_updates_buf": sync_buf,
            }

        raw_messages = response.get("msgs") or []
        messages = [item for item in raw_messages if isinstance(item, dict)]
        ret_ok = response.get("ret", 0) in {0, None} and response.get("errcode", 0) in {0, None}
        now = time.monotonic()
        last_empty = self._last_empty_log.get(token_ref, 0.0)
        should_log = (
            bool(messages) or not ret_ok or (now - last_empty >= self._empty_log_interval_seconds)
        )
        if should_log:
            if not messages:
                self._last_empty_log[token_ref] = now
            owner_match_count = 0
            target_match_count = 0
            if identity:
                owner_match_count = sum(
                    hmac.compare_digest(
                        str(item.get("from_user_id") or ""),
                        identity.owner_user_id,
                    )
                    for item in messages
                )
                target_match_count = sum(
                    hmac.compare_digest(str(item.get("to_user_id") or ""), identity.account_id)
                    for item in messages
                )
            logger.info(
                "Employee Bot getUpdates employee_ref=%s ret_ok=%s "
                "message_count=%s owner_match_count=%s target_match_count=%s "
                "context_count=%s nonempty_item_count=%s cursor_changed=%s",
                identity.employee_ref if identity else "unknown",
                ret_ok,
                len(messages),
                owner_match_count,
                target_match_count,
                sum(bool(item.get("context_token")) for item in messages),
                sum(bool(item.get("item_list")) for item in messages),
                bool(response.get("get_updates_buf"))
                and str(response.get("get_updates_buf")) != sync_buf,
            )
        return response


@contextmanager
def installed_safe_get_updates_probe(official: Any, correlation_key: bytes):
    """Install one process-local probe and always restore the exact prior callable."""
    original = official._get_updates
    probe = SafeGetUpdatesProbe(original, correlation_key)
    official._get_updates = probe
    try:
        yield probe
    finally:
        if official._get_updates is probe:
            official._get_updates = original
        probe.clear()


def load_active_credentials(
    settings: Settings, factory: sessionmaker[Session]
) -> dict[str, BotCredential]:
    cipher = Fernet(settings.identifier_encryption_key.encode())
    with factory() as session:
        rows = session.execute(
            select(WeixinBotAccount, EmployeeBotBinding)
            .join(EmployeeBotBinding, EmployeeBotBinding.bot_account_id == WeixinBotAccount.id)
            .join(Employee, Employee.id == EmployeeBotBinding.employee_id)
            .where(
                EmployeeBotBinding.active.is_(True),
                Employee.status == EmployeeStatus.ACTIVE,
            )
        ).all()
        return {
            row.id: BotCredential(
                record_id=row.id,
                employee_id=binding.employee_id,
                employee_ref=hmac.new(
                    settings.identifier_hmac_key.encode(),
                    binding.employee_id.encode(),
                    hashlib.sha256,
                ).hexdigest()[:12],
                account_id=cipher.decrypt(row.account_id_encrypted.encode()).decode(),
                owner_user_id=cipher.decrypt(row.owner_user_id_encrypted.encode()).decode(),
                token=cipher.decrypt(row.bot_token_encrypted.encode()).decode(),
                base_url=cipher.decrypt(row.base_url_encrypted.encode()).decode(),
            )
            for row, binding in rows
        }


def platform_extra(credential: BotCredential) -> dict[str, object]:
    """Restrict each independent Bot to the owner identity confirmed at scan time."""
    return {
        "account_id": credential.account_id,
        "base_url": credential.base_url,
        "dm_policy": "allowlist",
        "allow_from": [credential.owner_user_id],
        "group_policy": "disabled",
        "text_batch_delay_seconds": 0,
    }


def main() -> None:
    """Poll every active per-employee iLink Bot through Hermes' official adapter."""
    configure_logging()
    settings = Settings.from_env()
    settings.validate()
    _, factory = create_database(settings.database_url)
    asyncio.run(run(settings, factory))


async def run(settings: Settings, factory: sessionmaker[Session]) -> None:
    install_hermes_agent_import_path()
    hermes_home = Path(os.environ["EMPLOYEE_BOT_HERMES_HOME"]).resolve()
    hermes_home.mkdir(parents=True, exist_ok=True)
    removed = remove_legacy_plaintext_context_files(hermes_home)
    if removed:
        logger.warning("Removed %d legacy plaintext Weixin context file(s)", removed)
    os.environ["HERMES_HOME"] = str(hermes_home)
    from gateway.platforms import weixin as official_weixin

    with installed_safe_get_updates_probe(
        official_weixin, settings.identifier_hmac_key.encode()
    ) as get_updates_probe:
        tasks: dict[str, asyncio.Task[None]] = {}
        try:
            while True:
                credentials = load_active_credentials(settings, factory)
                get_updates_probe.update_credentials(credentials.values())
                for record_id, task in list(tasks.items()):
                    if record_id not in credentials or task.done():
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        if task.done() and not task.cancelled() and task.exception() is not None:
                            logger.error(
                                "Employee Weixin Bot task stopped error_type=%s",
                                type(task.exception()).__name__,
                            )
                        tasks.pop(record_id, None)
                for record_id, credential in credentials.items():
                    if record_id not in tasks:
                        tasks[record_id] = asyncio.create_task(run_account(credential))
                await asyncio.sleep(30)
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)


async def run_account(credential: BotCredential) -> None:
    from gateway.config import PlatformConfig
    from gateway.platforms.weixin import WeixinAdapter

    class ObservableEmployeeWeixinAdapter(WeixinAdapter):
        async def _process_message(self, message: dict[str, Any]) -> None:
            sender_id = str(message.get("from_user_id") or "").strip()
            logger.info(
                "Employee Bot iLink update employee_ref=%s owner_match=%s "
                "context_present=%s item_count=%s",
                credential.employee_ref,
                bool(sender_id) and hmac.compare_digest(sender_id, credential.owner_user_id),
                bool(message.get("context_token")),
                len(message.get("item_list") or []),
            )
            await super()._process_message(message)

    api_url = os.getenv("APP_INTERNAL_URL", "http://127.0.0.1:8091")
    bot_secret = os.environ["APP_BOT_WEBHOOK_SECRET"]
    adapter = ObservableEmployeeWeixinAdapter(
        PlatformConfig(
            enabled=True,
            token=credential.token,
            extra=platform_extra(credential),
        )
    )
    adapter._token_store = InMemoryContextTokenStore()

    async def deterministic_handler(event):
        raw = event.raw_message or {}
        payload = {
            "account_id": credential.account_id,
            "user_id": event.source.user_id,
            "chat_id": event.source.chat_id,
            "text": event.text or "帮助",
            "context_token": str(raw.get("context_token") or ""),
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{api_url}/api/v1/bot/inbound",
                headers={"X-Bot-Secret": bot_secret},
                json=payload,
            )
        logger.info(
            "Employee Bot inbound handled employee_ref=%s context_present=%s api_status=%s",
            credential.employee_ref,
            bool(payload["context_token"]),
            response.status_code,
        )
        if response.status_code >= 400:
            return "操作未完成，请联系管理员检查绑定状态。"
        result = response.json()
        if result.get("reply") is False:
            return None
        return str(result.get("message") or "指令已处理")

    adapter.set_message_handler(deterministic_handler)
    logger.info(
        "Employee Bot callback registered employee_ref=%s policy=owner_allowlist",
        credential.employee_ref,
    )
    if not await adapter.connect():
        raise RuntimeError("Hermes Weixin adapter failed to connect")
    logger.info(
        "Employee Bot connected employee_ref=%s policy=owner_allowlist",
        credential.employee_ref,
    )
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await adapter.disconnect()


if __name__ == "__main__":
    main()
