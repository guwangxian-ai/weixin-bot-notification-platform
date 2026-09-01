from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from app.bot_worker import remove_legacy_plaintext_context_files
from app.config import Settings
from app.hermes_runtime import install_hermes_agent_import_path
from app.weixin_delivery import send_video


def _weixin_settings() -> Settings:
    return replace(Settings.from_env(), delivery_mode="weixin")


def test_concurrent_weixin_sends_use_isolated_temporary_homes(monkeypatch) -> None:
    install_hermes_agent_import_path()
    from gateway.platforms import weixin
    from hermes_constants import get_hermes_home

    observed: list[tuple[str, str]] = []

    async def fake_send_weixin_direct(*, extra, token, chat_id, message, media_files):
        del token, message, media_files
        await asyncio.sleep(0.05)
        home = get_hermes_home()
        token_store = weixin.ContextTokenStore(str(home))
        token_store.restore(str(extra["account_id"]))
        stored = token_store.get(str(extra["account_id"]), chat_id)
        observed.append((str(home), str(stored)))
        return {"success": True, "message_id": f"message-{chat_id}", "context_token_used": True}

    monkeypatch.setattr(weixin, "send_weixin_direct", fake_send_weixin_direct)
    settings = _weixin_settings()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda values: send_video(
                    settings,
                    values[0],
                    "bot-token",  # noqa: S106 - simulated adapter credential
                    "https://example.invalid",
                    values[1],
                    "test",
                    None,
                    values[2],
                ),
                [
                    ("account-one", "chat-one", "context-one"),
                    ("account-two", "chat-two", "context-two"),
                ],
            )
        )

    assert all(outcome.success for outcome in outcomes)
    assert {token for _, token in observed} == {"context-one", "context-two"}
    homes = {home for home, _ in observed}
    assert len(homes) == 2
    assert all(not Path(home).exists() for home in homes)


def test_weixin_adapter_failure_is_sanitized(monkeypatch) -> None:
    install_hermes_agent_import_path()
    from gateway.platforms import weixin

    async def fake_send_weixin_direct(**_kwargs):
        return {
            "success": False,
            "ret": -2,
            "error": "sensitive upstream URL and identifier must not escape",
        }

    monkeypatch.setattr(weixin, "send_weixin_direct", fake_send_weixin_direct)
    outcome = send_video(
        _weixin_settings(),
        "account",
        "bot-token",  # noqa: S106 - simulated adapter credential
        "https://example.invalid",
        "chat",
        "test",
        None,
        "context",
    )

    assert outcome.success is False
    assert outcome.error_code == "weixin_ret_-2"
    assert outcome.error == "微信发送失败，请稍后重试"
    assert "sensitive" not in str(outcome)


def test_weixin_rate_limit_returns_retryable_safe_error(monkeypatch) -> None:
    install_hermes_agent_import_path()
    from gateway.platforms import weixin

    async def fake_send_weixin_direct(**_kwargs):
        return {
            "error": "Weixin send failed: iLink sendmessage rate limited; "
            "cooldown active for 30.0s"
        }

    monkeypatch.setattr(weixin, "send_weixin_direct", fake_send_weixin_direct)
    outcome = send_video(
        _weixin_settings(),
        "account",
        "bot-token",  # noqa: S106 - simulated adapter credential
        "https://example.invalid",
        "chat",
        "test",
        None,
        "context",
    )

    assert outcome.success is False
    assert outcome.error_code == "weixin_rate_limited"
    assert outcome.error == "微信发送频率受限，请30秒后重试"
    assert outcome.retry_after_seconds == 30
    assert "sendmessage" not in str(outcome)


def test_video_and_text_are_sent_as_separate_retryable_phases(
    tmp_path: Path, monkeypatch
) -> None:
    install_hermes_agent_import_path()
    from gateway.platforms import weixin

    video = tmp_path / "notice.mp4"
    video.write_bytes(b"video")
    calls: list[tuple[str, int]] = []
    fail_text = True

    async def fake_send_weixin_direct(*, message, media_files, **_kwargs):
        nonlocal fail_text
        calls.append((message, len(media_files)))
        if media_files:
            return {"success": True, "message_id": "media-message"}
        if fail_text:
            return {"error": "iLink sendmessage rate limited; cooldown active for 30.0s"}
        return {"success": True, "message_id": "text-message"}

    monkeypatch.setattr(weixin, "send_weixin_direct", fake_send_weixin_direct)
    media_outcome = send_video(
        _weixin_settings(),
        "account",
        "bot-token",  # noqa: S106 - simulated adapter credential
        "https://example.invalid",
        "chat",
        "",
        str(video),
        "context",
    )

    assert calls == [("", 1)]
    assert media_outcome.success is True
    assert media_outcome.media_sent is True

    calls.clear()
    outcome = send_video(
        _weixin_settings(),
        "account",
        "bot-token",  # noqa: S106 - simulated adapter credential
        "https://example.invalid",
        "chat",
        "caption",
        None,
        "context",
    )

    assert calls == [("caption", 0)]
    assert outcome.success is False
    assert outcome.media_sent is True
    assert outcome.text_sent is False
    assert outcome.error_code == "weixin_rate_limited"

    calls.clear()
    fail_text = False
    resumed = send_video(
        _weixin_settings(),
        "account",
        "bot-token",  # noqa: S106 - simulated adapter credential
        "https://example.invalid",
        "chat",
        "caption",
        str(video),
        "context",
        skip_media=True,
    )

    assert calls == [("caption", 0)]
    assert resumed.success is True
    assert resumed.media_sent is True
    assert resumed.text_sent is True


def test_legacy_plaintext_context_files_are_removed(tmp_path: Path) -> None:
    account_dir = tmp_path / "weixin" / "accounts"
    account_dir.mkdir(parents=True)
    plaintext = account_dir / "account.context-tokens.json"
    plaintext.write_text('{"peer":"plaintext-context"}', encoding="utf-8")
    unrelated = account_dir / "account-state.json"
    unrelated.write_text("{}", encoding="utf-8")

    assert remove_legacy_plaintext_context_files(tmp_path) == 1
    assert not plaintext.exists()
    assert unrelated.exists()
