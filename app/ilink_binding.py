from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.hermes_runtime import install_hermes_agent_import_path


class IlinkStatus(StrEnum):
    PENDING = "pending"
    SCANNED = "scanned"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True)
class IlinkQrTicket:
    ticket: str
    scan_data: str
    base_url: str
    expires_at: datetime


@dataclass(frozen=True)
class IlinkLoginResult:
    status: IlinkStatus
    account_id: str = ""
    token: str = ""
    base_url: str = ""
    user_id: str = ""
    current_base_url: str = ""
    failure_code: str = ""


def _official_weixin():
    install_hermes_agent_import_path()
    from gateway.platforms import weixin

    return weixin


class IlinkQrAdapter:
    """Thin, stateless facade over Hermes' installed official iLink QR primitives."""

    @classmethod
    def create(cls, *, ttl_seconds: int) -> IlinkQrTicket:
        return asyncio.run(cls._create(ttl_seconds=ttl_seconds))

    @classmethod
    async def _create(cls, *, ttl_seconds: int) -> IlinkQrTicket:
        official = _official_weixin()
        if not official.AIOHTTP_AVAILABLE:
            raise RuntimeError("Hermes Weixin QR login requires aiohttp")
        async with official.aiohttp.ClientSession(
            trust_env=True, connector=official._make_ssl_connector()
        ) as client:
            response = await official._api_get(
                client,
                base_url=official.ILINK_BASE_URL,
                endpoint=f"{official.EP_GET_BOT_QR}?bot_type=3",
                timeout_ms=official.QR_TIMEOUT_MS,
            )
        ticket = str(response.get("qrcode") or "")
        scan_data = str(response.get("qrcode_img_content") or ticket)
        if not ticket or not scan_data:
            raise RuntimeError("Official iLink QR response was incomplete")
        return IlinkQrTicket(
            ticket=ticket,
            scan_data=scan_data,
            base_url=official.ILINK_BASE_URL,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )

    @classmethod
    def poll(cls, *, ticket: str, current_base_url: str) -> IlinkLoginResult:
        return asyncio.run(cls._poll(ticket=ticket, current_base_url=current_base_url))

    @classmethod
    async def _poll(cls, *, ticket: str, current_base_url: str) -> IlinkLoginResult:
        official = _official_weixin()
        if not official.AIOHTTP_AVAILABLE:
            raise RuntimeError("Hermes Weixin QR login requires aiohttp")
        async with official.aiohttp.ClientSession(
            trust_env=True, connector=official._make_ssl_connector()
        ) as client:
            response = await official._api_get(
                client,
                base_url=current_base_url or official.ILINK_BASE_URL,
                endpoint=f"{official.EP_GET_QR_STATUS}?qrcode={ticket}",
                timeout_ms=official.QR_TIMEOUT_MS,
            )
        raw = str(response.get("status") or "wait")
        if raw == "wait":
            return IlinkLoginResult(status=IlinkStatus.PENDING)
        if raw == "scaned_but_redirect":
            host = str(response.get("redirect_host") or "").strip()
            redirected = f"https://{host}" if host else current_base_url
            return IlinkLoginResult(status=IlinkStatus.SCANNED, current_base_url=redirected)
        if raw == "scaned":
            return IlinkLoginResult(status=IlinkStatus.CONFIRMING)
        if raw == "expired":
            return IlinkLoginResult(status=IlinkStatus.EXPIRED)
        if raw == "confirmed":
            account_id = str(response.get("ilink_bot_id") or "")
            token = str(response.get("bot_token") or "")
            base_url = str(response.get("baseurl") or current_base_url)
            user_id = str(response.get("ilink_user_id") or "")
            if not account_id or not token or not user_id:
                return IlinkLoginResult(
                    status=IlinkStatus.FAILED, failure_code="incomplete_credentials"
                )
            return IlinkLoginResult(
                status=IlinkStatus.CONFIRMED,
                account_id=account_id,
                token=token,
                base_url=base_url,
                user_id=user_id,
            )
        return IlinkLoginResult(status=IlinkStatus.FAILED, failure_code="unexpected_status")


def render_qr_png(scan_data: str) -> bytes:
    import qrcode

    qr = qrcode.QRCode(version=None, box_size=8, border=4)
    qr.add_data(scan_data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
