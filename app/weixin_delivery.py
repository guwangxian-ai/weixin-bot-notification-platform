from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass

from app.config import Settings
from app.hermes_runtime import install_hermes_agent_import_path


@dataclass(frozen=True)
class SendOutcome:
    success: bool
    message_id: str | None = None
    context_used: bool = False
    error: str | None = None
    error_code: str | None = None
    retry_after_seconds: int | None = None
    text_sent: bool = False
    media_sent: bool = False


def send_video(
    settings: Settings,
    account_id: str,
    bot_token: str,
    base_url: str,
    chat_id: str,
    message: str,
    video_path: str | None,
    context_token: str | None = None,
    skip_text: bool = False,
    skip_media: bool = False,
) -> SendOutcome:
    """Send through Hermes' official Weixin adapter; never implements iLink itself."""
    if settings.delivery_mode != "weixin":
        return SendOutcome(
            True, message_id=f"{settings.delivery_mode}-simulated", context_used=True
        )
    if not account_id or not bot_token or not chat_id:
        return SendOutcome(False, error="Employee Weixin Bot binding is incomplete")
    if message and video_path and not skip_text and not skip_media:
        return SendOutcome(
            False,
            error="微信发送阶段配置无效",
            error_code="weixin_phase_conflict",
        )

    install_hermes_agent_import_path()

    async def _send(hermes_home: str) -> dict[str, object]:
        from gateway.platforms.weixin import ContextTokenStore, send_weixin_direct

        if context_token:
            token_store = ContextTokenStore(hermes_home)
            token_store.set(account_id, chat_id, context_token)

        common = {
            "extra": {"account_id": account_id, "base_url": base_url},
            "token": bot_token,
            "chat_id": chat_id,
        }
        text_sent = skip_text or not bool(message)
        media_sent = skip_media or not bool(video_path)
        last_message_id: object = None
        if video_path and not skip_media:
            media_result = await send_weixin_direct(
                **common,
                message="",
                media_files=[(video_path, False)],
            )
            if not media_result.get("success"):
                return {**media_result, "text_sent": text_sent, "media_sent": False}
            media_sent = True
            last_message_id = media_result.get("message_id")
        if message and not skip_text:
            text_result = await send_weixin_direct(
                **common,
                message=message,
                media_files=[],
            )
            if not text_result.get("success"):
                return {
                    **text_result,
                    "text_sent": False,
                    "media_sent": media_sent,
                }
            text_sent = True
            last_message_id = text_result.get("message_id") or last_message_id
        return {
            "success": True,
            "message_id": last_message_id,
            "context_token_used": bool(context_token),
            "text_sent": text_sent,
            "media_sent": media_sent,
        }

    try:
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override

        with tempfile.TemporaryDirectory(prefix="evnc-weixin-") as temporary_home:
            os.chmod(temporary_home, 0o700)
            home_token = set_hermes_home_override(temporary_home)
            try:
                result = asyncio.run(_send(temporary_home))
            finally:
                reset_hermes_home_override(home_token)
    except Exception:  # transport boundary; never expose adapter exception contents
        return SendOutcome(
            False,
            error="微信发送服务暂时不可用，请稍后重试",
            error_code="weixin_transport_error",
        )
    if result.get("success"):
        return SendOutcome(
            True,
            message_id=str(result.get("message_id") or "") or None,
            context_used=bool(result.get("context_token_used")),
            text_sent=bool(result.get("text_sent")),
            media_sent=bool(result.get("media_sent")),
        )
    raw_error = str(result.get("error") or "").lower()
    if "rate limited" in raw_error or "cooldown active" in raw_error:
        return SendOutcome(
            False,
            error="微信发送频率受限，请30秒后重试",
            error_code="weixin_rate_limited",
            retry_after_seconds=30,
            text_sent=bool(result.get("text_sent")),
            media_sent=bool(result.get("media_sent")),
        )
    raw_code = result.get("ret")
    safe_code = f"weixin_ret_{raw_code}" if isinstance(raw_code, int) else "weixin_send_failed"
    return SendOutcome(
        False,
        error="微信发送失败，请稍后重试",
        error_code=safe_code,
        text_sent=bool(result.get("text_sent")),
        media_sent=bool(result.get("media_sent")),
    )
