from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.contact_security import ContactPhoneProtector
from app.models import (
    ApiClient,
    AuditLog,
    BatchStatus,
    BindingCode,
    BindingSessionStatus,
    BotHealthStatus,
    Company,
    Delivery,
    DeliveryStatus,
    Employee,
    EmployeeBotBinding,
    EmployeeStatus,
    NotificationBatch,
    NotificationTarget,
    NotificationType,
    Role,
    TargetBotMember,
    TargetMode,
    User,
    UserObjectContact,
    VideoAsset,
    WeixinBinding,
    WeixinBindingSession,
    WeixinBotAccount,
    utcnow,
)
from app.security import hash_password


class UserCreate(BaseModel):
    username: str
    password: str = Field(min_length=12)
    role: Role
    company_id: str | None = None


class EmployeeCreate(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=120)
    department: str = ""
    content_vertical: str = ""
    secondary_topics: list[str] = []
    target_platforms: list[str] = []
    account_name: str = ""
    tone: str = ""
    video_duration_seconds: int = Field(default=60, ge=5, le=3600)
    publishing_frequency: str = ""


class EmployeeUpdate(BaseModel):
    department: str | None = None
    content_vertical: str | None = None
    secondary_topics: list[str] | None = None
    target_platforms: list[str] | None = None
    account_name: str | None = None
    tone: str | None = None
    video_duration_seconds: int | None = Field(default=None, ge=5, le=3600)
    publishing_frequency: str | None = None
    status: EmployeeStatus | None = None
    confirm: bool = False

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> EmployeeUpdate:
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class DeliveryCreate(BaseModel):
    company_id: str
    employee_id: str
    title: str = Field(default="", max_length=240)
    body: str = Field(default="", max_length=10000)
    video_asset_id: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def require_content(self) -> DeliveryCreate:
        if not self.title.strip() and not self.body.strip() and self.video_asset_id is None:
            raise ValueError("title, body, or video_asset_id is required")
        return self


class BotInbound(BaseModel):
    account_id: str
    user_id: str
    chat_id: str
    text: str
    context_token: str = ""


class ConfirmUnbind(BaseModel):
    confirm: bool


class BindingTransfer(BaseModel):
    source_employee_id: str
    target_employee_id: str


class CompanyCreate(BaseModel):
    company_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=120)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> CompanyUpdate:
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TargetCreate(BaseModel):
    company_id: str
    target_code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    mode: TargetMode
    binding_ids: list[str] = []


class TargetUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    mode: TargetMode | None = None
    enabled: bool | None = None
    binding_ids: list[str] | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> TargetUpdate:
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class UserObjectCreate(BaseModel):
    account_name: str = Field(min_length=1, max_length=120)
    routing_key: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$",
    )
    description: str = Field(default="", max_length=500)


class UserObjectUpdate(BaseModel):
    account_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    routing_key: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$",
    )
    enabled: bool | None = None
    confirm: bool = False

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> UserObjectUpdate:
        if "routing_key" in self.model_fields_set:
            raise ValueError("routing_key is immutable")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class UserObjectContactCreate(BaseModel):
    employee_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def require_existing_or_new_contact(self) -> UserObjectContactCreate:
        if self.employee_id and self.name:
            raise ValueError("employee_id and name are mutually exclusive")
        if not self.employee_id and not self.name:
            raise ValueError("employee_id or name is required")
        return self


class UserObjectContactUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> UserObjectContactUpdate:
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class DestructiveConfirmation(BaseModel):
    confirm: bool


class ApiClientCreate(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=120)
    permissions: list[str] = Field(min_length=1)
    allowed_target_codes: list[str] = []


class ApiClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    permissions: list[str] | None = Field(default=None, min_length=1)
    allowed_target_codes: list[str] | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> ApiClientUpdate:
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class NotificationPreview(BaseModel):
    company_slug: str
    target_code: str


class NotificationSend(NotificationPreview):
    title: str = Field(default="", max_length=240)
    body: str = Field(default="", max_length=10000)
    media_asset_id: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def require_message(self) -> NotificationSend:
        if not self.title.strip() and not self.body.strip() and not self.media_asset_id:
            raise ValueError("title, body, or media_asset_id is required")
        return self


def build_router(settings: Settings, factory: sessionmaker[Session]) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    cipher = Fernet(settings.identifier_encryption_key.encode())
    phone_protector = ContactPhoneProtector(
        encryption_key=settings.identifier_encryption_key,
        hmac_key=settings.identifier_hmac_key,
    )
    download_signer = URLSafeTimedSerializer(settings.secret_key, salt="video-download")
    binding_poll_lock = threading.Lock()

    def api_token_hash(value: str) -> str:
        return hmac.new(
            settings.identifier_hmac_key.encode(), value.encode(), hashlib.sha256
        ).hexdigest()

    def get_session():
        with factory() as session:
            yield session

    def current_user(request: Request, session: Session = Depends(get_session)) -> User:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            supplied_token = authorization[7:]
            if hmac.compare_digest(supplied_token, settings.service_api_token):
                service_user = session.scalar(select(User).where(User.role == Role.SUPER_ADMIN))
                if service_user is not None:
                    request.state.platform_service = True
                    return service_user
            for company_id, token in settings.company_service_tokens.items():
                if hmac.compare_digest(supplied_token, token):
                    request.state.business_service_company_id = company_id
                    return User(
                        id=f"business-service:{company_id}",
                        username=f"business-service:{company_id}",
                        password_hash="",
                        role=Role.COMPANY_ADMIN,
                        company_id=company_id,
                        enabled=True,
                    )
            database_client = session.scalar(
                select(ApiClient).where(
                    ApiClient.token_hash == api_token_hash(supplied_token),
                    ApiClient.enabled.is_(True),
                    ApiClient.revoked_at.is_(None),
                )
            )
            if database_client is not None:
                company = session.get(Company, database_client.company_id)
                if company is None or not company.enabled or company.deleted_at is not None:
                    raise HTTPException(403, "API 客户端所属公司已停用")
                relative_path = request.url.path.removeprefix("/api/v1")
                required_permission: str | None = None
                if request.method == "GET" and (
                    relative_path == "/authorized-companies"
                    or relative_path.startswith("/notification-targets")
                    or (
                        relative_path.startswith("/companies/")
                        and "/user-objects" in relative_path
                    )
                ):
                    required_permission = "query"
                elif request.method == "GET" and relative_path.startswith(
                    "/notification-batches"
                ):
                    required_permission = "status"
                elif request.method == "POST" and relative_path == "/notifications/preview":
                    required_permission = "query"
                elif request.method == "POST" and (
                    relative_path == "/notifications/send"
                    or relative_path == "/media-assets"
                ):
                    required_permission = "send"
                if (
                    required_permission is None
                    or required_permission not in database_client.permissions
                ):
                    raise HTTPException(403, "API 客户端无权调用该接口")
                database_client.last_used_at = utcnow()
                session.commit()
                request.state.business_service_company_id = database_client.company_id
                request.state.api_client = database_client
                return User(
                    id=f"api-client:{database_client.id}",
                    username=database_client.name,
                    password_hash="",
                    role=Role.COMPANY_ADMIN,
                    company_id=database_client.company_id,
                    enabled=True,
                )
        user_id = request.session.get("user_id")
        user = session.get(User, user_id) if user_id else None
        if user is None or not user.enabled:
            raise HTTPException(401, "Authentication required")
        return user

    def writable(request: Request, user: User = Depends(current_user)) -> User:
        if user.role == Role.VIEWER:
            raise HTTPException(403, "Read-only role")
        if getattr(request.state, "business_service_company_id", None) or getattr(
            request.state, "platform_service", False
        ):
            return user
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer ") and hmac.compare_digest(
            authorization[7:], settings.service_api_token
        ):
            return user
        expected = str(request.session.get("csrf_token") or "")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            raise HTTPException(403, "CSRF validation failed")
        return user

    def platform_user(request: Request, user: User = Depends(current_user)) -> User:
        if getattr(request.state, "business_service_company_id", None):
            raise HTTPException(403, "Platform administrator required")
        return user

    def platform_writable(request: Request, user: User = Depends(writable)) -> User:
        if getattr(request.state, "business_service_company_id", None):
            raise HTTPException(403, "Platform administrator required")
        return user

    def tenant(user: User, company_id: str) -> None:
        if user.role != Role.SUPER_ADMIN and user.company_id != company_id:
            raise HTTPException(403, "Cross-company access denied")

    def fingerprint(value: str) -> str:
        return hmac.new(
            settings.identifier_hmac_key.encode(), value.encode(), hashlib.sha256
        ).hexdigest()

    def enc(value: str) -> str:
        return cipher.encrypt(value.encode()).decode()

    def mask(value: str) -> str:
        if len(value) <= 8:
            return value[:2] + "***"
        return value[:4] + "***" + value[-3:]

    def audit(
        session: Session,
        user: User | None,
        action: str,
        target: object,
        company_id: str | None,
        details: dict[str, object] | None = None,
    ) -> None:
        session.add(
            AuditLog(
                company_id=company_id,
                actor_type="admin" if user else "bot",
                actor_id=user.id if user else "employee-bot",
                action=action,
                target_type=type(target).__name__,
                target_id=str(getattr(target, "id", "-")),
                details=details or {},
            )
        )

    def active_legacy_binding(session: Session, employee_id: str) -> WeixinBinding | None:
        return session.scalar(
            select(WeixinBinding).where(
                WeixinBinding.employee_id == employee_id, WeixinBinding.active.is_(True)
            )
        )

    def active_bot_binding(session: Session, employee_id: str) -> EmployeeBotBinding | None:
        return session.scalar(
            select(EmployeeBotBinding).where(
                EmployeeBotBinding.employee_id == employee_id,
                EmployeeBotBinding.active.is_(True),
            )
        )

    def available_video_path(asset: VideoAsset) -> Path | None:
        path = Path(asset.storage_path).resolve()
        upload_root = settings.upload_dir.resolve()
        if upload_root not in path.parents or not path.is_file():
            return None
        return path

    def binding_session_json(item: WeixinBindingSession) -> dict[str, Any]:
        live = item.status in {
            BindingSessionStatus.PENDING,
            BindingSessionStatus.SCANNED,
            BindingSessionStatus.CONFIRMING,
        }
        return {
            "id": item.id,
            "company_id": item.company_id,
            "employee_id": item.employee_id,
            "status": item.status.value,
            "expires_at": item.expires_at,
            "qr_image_url": (
                f"{settings.base_path}/api/v1/binding-sessions/{item.id}/qr.png"
                if live
                else None
            ),
            "failure_code": item.failure_code,
        }

    def latest_binding_session(
        session: Session, employee_id: str
    ) -> WeixinBindingSession | None:
        return session.scalar(
            select(WeixinBindingSession)
            .where(WeixinBindingSession.employee_id == employee_id)
            .order_by(desc(WeixinBindingSession.created_at))
        )

    def create_binding_session_record(
        session: Session, employee: Employee, user: User
    ) -> WeixinBindingSession:
        if employee.status != EmployeeStatus.ACTIVE:
            raise HTTPException(409, "Only active employees can bind a Weixin Bot")
        if active_bot_binding(session, employee.id):
            raise HTTPException(409, "Employee already has an active Weixin Bot")
        live = session.scalar(
            select(WeixinBindingSession).where(
                WeixinBindingSession.employee_id == employee.id,
                WeixinBindingSession.status.in_(
                    [
                        BindingSessionStatus.PENDING,
                        BindingSessionStatus.SCANNED,
                        BindingSessionStatus.CONFIRMING,
                    ]
                ),
            )
        )
        if live:
            live.status = BindingSessionStatus.CANCELLED
            live.cancelled_at = utcnow()
        try:
            from app.ilink_binding import IlinkQrAdapter

            ticket = IlinkQrAdapter.create(ttl_seconds=settings.binding_ttl_seconds)
            item = WeixinBindingSession(
                company_id=employee.company_id,
                employee_id=employee.id,
                status=BindingSessionStatus.PENDING,
                official_ticket_encrypted=enc(ticket.ticket),
                scan_data_encrypted=enc(ticket.scan_data),
                base_url_encrypted=enc(ticket.base_url),
                current_base_url_encrypted=enc(ticket.base_url),
                expires_at=ticket.expires_at,
            )
        except Exception:
            item = WeixinBindingSession(
                company_id=employee.company_id,
                employee_id=employee.id,
                status=BindingSessionStatus.FAILED,
                official_ticket_encrypted=enc(""),
                scan_data_encrypted=enc(""),
                base_url_encrypted=enc(""),
                current_base_url_encrypted=enc(""),
                expires_at=utcnow(),
                failure_code="official_qr_unavailable",
            )
        session.add(item)
        session.flush()
        audit(session, user, "binding_session.create", item, employee.company_id)
        return item

    def employee_json(
        session: Session,
        employee: Employee,
        *,
        include_management: bool = True,
        can_manage: bool = True,
    ) -> dict[str, Any]:
        bot_binding = active_bot_binding(session, employee.id)
        bot_account = (
            session.get(WeixinBotAccount, bot_binding.bot_account_id) if bot_binding else None
        )
        legacy = active_legacy_binding(session, employee.id) if bot_binding is None else None
        latest = latest_binding_session(session, employee.id)
        welcome = (
            session.scalar(
                select(Delivery)
                .where(
                    Delivery.binding_id == bot_binding.id,
                    Delivery.notification_type == NotificationType.BINDING_WELCOME.value,
                )
                .order_by(desc(Delivery.created_at))
            )
            if bot_binding
            else None
        )
        latest_manual_test = (
            session.scalar(
                select(Delivery)
                .where(
                    Delivery.binding_id == bot_binding.id,
                    Delivery.notification_type == NotificationType.MANUAL_TEST.value,
                )
                .order_by(desc(Delivery.created_at))
            )
            if bot_binding
            else None
        )
        manual_test_allowed, manual_test_reason, retry_after = manual_test_availability(
            employee, bot_binding, bot_account, can_manage=can_manage
        )
        result = {
            "id": employee.id,
            "company_id": employee.company_id,
            "name": employee.name,
            "department": employee.department,
            "content_vertical": employee.content_vertical,
            "secondary_topics": employee.secondary_topics,
            "target_platforms": employee.target_platforms,
            "account_name": employee.account_name,
            "tone": employee.tone,
            "video_duration_seconds": employee.video_duration_seconds,
            "publishing_frequency": employee.publishing_frequency,
            "status": employee.status.value,
            "binding": (
                {
                    "status": "bound",
                    "binding_id": bot_binding.id,
                    "account_id_masked": bot_account.account_id_masked if bot_account else "***",
                    "bound_at": bot_binding.bound_at,
                    "health_status": (
                        bot_account.health_status.value
                        if bot_account
                        else BotHealthStatus.UNKNOWN.value
                    ),
                    "last_health_at": bot_account.last_health_at if bot_account else None,
                    "delivery_ready": bool(
                        bot_binding.context_token_encrypted and bot_binding.chat_id_encrypted
                    ),
                    "welcome_delivery": delivery_summary(welcome),
                    "manual_test": {
                        "allowed": manual_test_allowed,
                        "reason": manual_test_reason,
                        "retry_after_seconds": retry_after,
                        "latest_delivery": delivery_summary(latest_manual_test),
                    },
                }
                if bot_binding
                else (
                    {
                        "status": "bound",
                        "account_id_masked": legacy.user_id_masked,
                        "user_id_masked": legacy.user_id_masked,
                        "bound_at": legacy.bound_at,
                        "health_status": "legacy",
                        "last_health_at": legacy.last_interaction_at,
                    }
                    if legacy
                    else None
                )
            ),
        }
        if include_management:
            result["binding_session"] = binding_session_json(latest) if latest else None
        return result

    def delivery_json(item: Delivery) -> dict[str, Any]:
        return {
            "id": item.id,
            "company_id": item.company_id,
            "employee_id": item.employee_id,
            "video_asset_id": item.video_asset_id,
            "title": item.title,
            "body": item.body,
            "notification_type": item.notification_type,
            "idempotency_key": item.idempotency_key,
            "status": item.status.value,
            "retry_count": item.retry_count,
            "failure_code": item.failure_code,
            "failure_message": item.failure_message,
            "next_retry_at": item.next_retry_at,
            "text_sent_at": item.text_sent_at,
            "media_sent_at": item.media_sent_at,
            "created_at": item.created_at,
        }

    def delivery_summary(item: Delivery | None) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "id": item.id,
            "notification_type": item.notification_type,
            "status": item.status.value,
            "failure_code": item.failure_code,
            "failure_message": item.failure_message,
            "created_at": item.created_at,
        }

    def aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    def manual_test_availability(
        employee: Employee,
        binding: EmployeeBotBinding | None,
        account: WeixinBotAccount | None,
        *,
        can_manage: bool,
    ) -> tuple[bool, str | None, int | None]:
        if not can_manage:
            return False, "当前账号无管理员测试发送权限", None
        if employee.status != EmployeeStatus.ACTIVE:
            return False, "员工账号未启用", None
        if binding is None or not binding.active:
            return False, "员工尚未绑定微信 Bot", None
        if account is None or account.health_status != BotHealthStatus.HEALTHY:
            return False, "微信 Bot 当前不是健康状态", None
        if not binding.context_token_encrypted or not binding.chat_id_encrypted:
            return False, "微信 Bot 会话尚未激活", None
        if binding.last_manual_test_at is not None:
            remaining = 60 - int((utcnow() - aware(binding.last_manual_test_at)).total_seconds())
            if remaining > 0:
                return False, f"测试发送冷却中，请 {remaining} 秒后重试", remaining
        return True, None, None

    def create_binding_welcome(
        session: Session,
        employee: Employee,
        binding: EmployeeBotBinding,
    ) -> Delivery:
        company = session.get(Company, employee.company_id)
        display_name = company.name if company else employee.company_id
        item = Delivery(
            company_id=employee.company_id,
            employee_id=employee.id,
            binding_id=binding.id,
            notification_type=NotificationType.BINDING_WELCOME.value,
            title="微信 Bot 绑定成功",
            body=(
                f"您已成功绑定{display_name}微信通知 Bot。后续通知将通过此通道发送；"
                "如非本人操作，请联系管理员。"
            ),
            idempotency_key=f"binding-welcome:{binding.id}",
        )
        session.add(item)
        session.flush()
        audit(
            session,
            None,
            "delivery.binding_welcome.create",
            item,
            employee.company_id,
            {"binding_id": binding.id},
        )
        return item

    def dispatch_binding_welcome(session: Session, binding_id: str) -> None:
        item = session.scalar(
            select(Delivery).where(
                Delivery.binding_id == binding_id,
                Delivery.notification_type == NotificationType.BINDING_WELCOME.value,
            )
        )
        if item is None or item.status != DeliveryStatus.PENDING:
            return
        dispatch_delivery(session, item)
        audit_delivery_failure(session, None, item)
        session.commit()

    def dispatch_lease_deadline() -> datetime:
        return utcnow() + timedelta(minutes=15)

    def renew_dispatch_lease(session: Session, item: Delivery) -> bool:
        if not item.dispatch_token:
            return False
        renewed = session.execute(
            update(Delivery)
            .where(
                Delivery.id == item.id,
                Delivery.dispatch_token == item.dispatch_token,
                Delivery.status.in_(
                    {DeliveryStatus.SENDING, DeliveryStatus.RETRYING}
                ),
            )
            .values(dispatch_lease_expires_at=dispatch_lease_deadline())
        )
        session.commit()
        session.refresh(item)
        return getattr(renewed, "rowcount", 0) == 1

    def send_mock(session: Session, item: Delivery, force_failure: bool = False) -> None:
        if item.binding_id is not None:
            bot_binding = session.get(EmployeeBotBinding, item.binding_id)
            if (
                bot_binding is None
                or not bot_binding.active
                or bot_binding.employee_id != item.employee_id
                or bot_binding.company_id != item.company_id
            ):
                item.status = DeliveryStatus.FAILED
                item.failure_code = "binding_version_changed"
                item.failure_message = "微信 Bot 绑定版本已变更，本次通知未发送"
                return
        else:
            bot_binding = None
        legacy = (
            active_legacy_binding(session, item.employee_id)
            if item.binding_id is None
            else None
        )
        if item.binding_id is None and legacy is None:
            item.status = DeliveryStatus.FAILED
            item.failure_code = "binding_version_unknown"
            item.failure_message = "历史通知缺少可验证的绑定版本，本次通知未发送"
            return
        if force_failure:
            item.status = DeliveryStatus.FAILED
            item.failure_code = "mock_failure"
            item.failure_message = "模拟发送失败，可由管理员重试"
        elif (
            bot_binding is not None
            and (not bot_binding.context_token_encrypted or not bot_binding.chat_id_encrypted)
        ) or (
            bot_binding is None and (legacy is None or not legacy.context_token_encrypted)
        ):
            item.status = DeliveryStatus.WAITING_INTERACTION
            item.failure_code = "context_required"
            item.failure_message = "等待员工首次私信通知 Bot 建立微信会话后自动补发"
        elif settings.delivery_mode == "weixin":
            from app.weixin_delivery import send_video

            asset = (
                session.get(VideoAsset, item.video_asset_id) if item.video_asset_id else None
            )
            if bot_binding is None:
                item.status = DeliveryStatus.FAILED
                item.failure_code = "bot_binding_unavailable"
                item.failure_message = "员工微信 Bot 绑定已失效，请重新绑定"
                return
            bot_account = session.get(WeixinBotAccount, bot_binding.bot_account_id)
            if bot_account is None:
                item.status = DeliveryStatus.FAILED
                item.failure_code = "bot_credentials_invalid"
                item.failure_message = "员工微信 Bot 凭据已失效，请重新绑定"
                return
            encrypted_chat_id = bot_binding.chat_id_encrypted
            if not encrypted_chat_id:
                item.status = DeliveryStatus.FAILED
                item.failure_code = "bot_conversation_unavailable"
                item.failure_message = "员工微信 Bot 会话已失效，请重新互动"
                return
            encrypted_context = bot_binding.context_token_encrypted
            if not encrypted_context:
                item.status = DeliveryStatus.FAILED
                item.failure_code = "bot_conversation_unavailable"
                item.failure_message = "员工微信 Bot 会话已失效，请重新互动"
                return
            try:
                account_id = cipher.decrypt(bot_account.account_id_encrypted.encode()).decode()
                bot_token = cipher.decrypt(bot_account.bot_token_encrypted.encode()).decode()
                base_url = cipher.decrypt(bot_account.base_url_encrypted.encode()).decode()
                chat_id = cipher.decrypt(encrypted_chat_id.encode()).decode()
                context_token = cipher.decrypt(encrypted_context.encode()).decode()
            except (InvalidToken, ValueError):
                item.status = DeliveryStatus.FAILED
                item.failure_code = "bot_credentials_invalid"
                item.failure_message = "员工微信 Bot 凭据已失效，请重新绑定"
                return
            message = f"{item.title}\n\n{item.body}".strip()
            if not message and asset is not None:
                message = f"{asset.title}\n\n{asset.caption}".strip()
            if asset is not None and asset.size_bytes > settings.native_video_max_bytes:
                item.status = DeliveryStatus.FAILED
                item.failure_code = "video_direct_send_limit"
                item.failure_message = "视频超过微信直接发送大小限制"
                return
            video_path = (
                available_video_path(asset)
                if asset is not None and item.media_sent_at is None
                else None
            )
            if asset is not None and item.media_sent_at is None and video_path is None:
                item.status = DeliveryStatus.FAILED
                item.failure_code = "video_file_unavailable"
                item.failure_message = "视频文件已不存在或不可用"
                return
            def fail_from_outcome(outcome: Any) -> None:
                failed = session.execute(
                    update(Delivery)
                    .where(
                        Delivery.id == item.id,
                        Delivery.dispatch_token == item.dispatch_token,
                        Delivery.status.in_(
                            {DeliveryStatus.SENDING, DeliveryStatus.RETRYING}
                        ),
                    )
                    .values(
                        status=DeliveryStatus.FAILED,
                        failure_code=outcome.error_code or "weixin_send_failed",
                        failure_message=outcome.error,
                        next_retry_at=(
                            utcnow() + timedelta(seconds=outcome.retry_after_seconds)
                            if outcome.retry_after_seconds
                            else None
                        ),
                        dispatch_token=None,
                        dispatch_lease_expires_at=None,
                    )
                )
                session.commit()
                session.refresh(item)
                if getattr(failed, "rowcount", 0) != 1:
                    return

            if asset is not None and item.media_sent_at is None:
                if not renew_dispatch_lease(session, item):
                    return
                media_outcome = send_video(
                    settings,
                    account_id,
                    bot_token,
                    base_url,
                    chat_id,
                    "",
                    str(video_path),
                    context_token,
                    skip_text=True,
                )
                if not media_outcome.success:
                    fail_from_outcome(media_outcome)
                    return
                completed_at = utcnow()
                media_values: dict[str, Any] = {
                    "media_sent_at": completed_at,
                    "external_message_id": media_outcome.message_id,
                    "failure_code": None,
                    "failure_message": None,
                    "next_retry_at": None,
                }
                if not message:
                    media_values.update(
                        status=DeliveryStatus.SENT,
                        dispatch_token=None,
                        dispatch_lease_expires_at=None,
                    )
                persisted = session.execute(
                    update(Delivery)
                    .where(
                        Delivery.id == item.id,
                        Delivery.dispatch_token == item.dispatch_token,
                        Delivery.status.in_(
                            {DeliveryStatus.SENDING, DeliveryStatus.RETRYING}
                        ),
                    )
                    .values(**media_values)
                )
                if getattr(persisted, "rowcount", 0) != 1:
                    session.rollback()
                    session.refresh(item)
                    return
                asset.consumed_at = asset.consumed_at or completed_at
                session.commit()
                session.refresh(item)
                cleanup_consumed_video_file(session, item)
            if message and item.text_sent_at is None:
                if not renew_dispatch_lease(session, item):
                    return
                text_outcome = send_video(
                    settings,
                    account_id,
                    bot_token,
                    base_url,
                    chat_id,
                    message,
                    None,
                    context_token,
                    skip_media=True,
                )
                if not text_outcome.success:
                    fail_from_outcome(text_outcome)
                    return
                persisted = session.execute(
                    update(Delivery)
                    .where(
                        Delivery.id == item.id,
                        Delivery.dispatch_token == item.dispatch_token,
                        Delivery.status.in_(
                            {DeliveryStatus.SENDING, DeliveryStatus.RETRYING}
                        ),
                    )
                    .values(
                        text_sent_at=utcnow(),
                        external_message_id=text_outcome.message_id
                        or item.external_message_id,
                        failure_code=None,
                        failure_message=None,
                        next_retry_at=None,
                        status=DeliveryStatus.SENT,
                        dispatch_token=None,
                        dispatch_lease_expires_at=None,
                    )
                )
                if getattr(persisted, "rowcount", 0) != 1:
                    session.rollback()
                    session.refresh(item)
                    return
                session.commit()
                session.refresh(item)
            if (not message or item.text_sent_at is not None) and (
                asset is None or item.media_sent_at is not None
            ) and item.status in {DeliveryStatus.SENDING, DeliveryStatus.RETRYING}:
                finalized = session.execute(
                    update(Delivery)
                    .where(
                        Delivery.id == item.id,
                        Delivery.dispatch_token == item.dispatch_token,
                    )
                    .values(
                        status=DeliveryStatus.SENT,
                        dispatch_token=None,
                        dispatch_lease_expires_at=None,
                    )
                )
                session.commit()
                if getattr(finalized, "rowcount", 0) == 1:
                    session.refresh(item)
        else:
            item.status = DeliveryStatus.SIMULATED
            item.external_message_id = None
            item.failure_code = None
            item.failure_message = None

    def dispatch_delivery(session: Session, item: Delivery) -> None:
        if item.status == DeliveryStatus.PENDING:
            token = secrets.token_urlsafe(32)
            claimed = session.execute(
                update(Delivery)
                .where(
                    Delivery.id == item.id,
                    Delivery.status == DeliveryStatus.PENDING,
                    Delivery.dispatch_token.is_(None),
                )
                .values(
                    status=DeliveryStatus.SENDING,
                    dispatch_token=token,
                    dispatch_lease_expires_at=dispatch_lease_deadline(),
                )
            )
            session.commit()
            if getattr(claimed, "rowcount", 0) != 1:
                session.refresh(item)
                return
            session.refresh(item)
        claim_token = item.dispatch_token
        try:
            send_mock(session, item)
        except Exception:
            exception_token = item.dispatch_token
            session.rollback()
            if exception_token:
                session.execute(
                    update(Delivery)
                    .where(
                        Delivery.id == item.id,
                        Delivery.dispatch_token == exception_token,
                        Delivery.status.in_(
                            {DeliveryStatus.SENDING, DeliveryStatus.RETRYING}
                        ),
                    )
                    .values(
                        status=DeliveryStatus.FAILED,
                        failure_code="delivery_dispatch_error",
                        failure_message="微信投递处理失败，请稍后重试",
                        next_retry_at=None,
                        dispatch_token=None,
                        dispatch_lease_expires_at=None,
                    )
                )
                session.commit()
                session.refresh(item)
            return
        if (
            claim_token
            and item.dispatch_token == claim_token
            and item.status not in {DeliveryStatus.SENDING, DeliveryStatus.RETRYING}
        ):
            outcome_values = {
                "status": item.status,
                "external_message_id": item.external_message_id,
                "failure_code": item.failure_code,
                "failure_message": item.failure_message,
                "next_retry_at": item.next_retry_at,
                "dispatch_token": None,
                "dispatch_lease_expires_at": None,
            }
            session.rollback()
            session.execute(
                update(Delivery)
                .where(
                    Delivery.id == item.id,
                    Delivery.dispatch_token == claim_token,
                    Delivery.status.in_(
                        {DeliveryStatus.SENDING, DeliveryStatus.RETRYING}
                    ),
                )
                .values(**outcome_values)
            )
            session.commit()
            session.refresh(item)

    def cleanup_consumed_video_file(session: Session, item: Delivery) -> None:
        if settings.delivery_mode != "weixin" or item.media_sent_at is None:
            return
        asset = session.get(VideoAsset, item.video_asset_id)
        if asset is None or asset.file_deleted_at is not None:
            return
        path = Path(asset.storage_path).resolve()
        upload_root = settings.upload_dir.resolve()
        if upload_root not in path.parents:
            audit(
                session,
                None,
                "delivery.video_file_delete_failed",
                item,
                item.company_id,
                {"failure_code": "unsafe_storage_path"},
            )
            session.commit()
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            audit(
                session,
                None,
                "delivery.video_file_delete_failed",
                item,
                item.company_id,
                {"failure_code": "file_delete_failed"},
            )
            session.commit()
            return
        asset.file_deleted_at = utcnow()
        audit(
            session,
            None,
            "delivery.video_file_deleted",
            item,
            item.company_id,
        )
        session.commit()

    def audit_delivery_failure(session: Session, user: User | None, item: Delivery) -> None:
        if item.status != DeliveryStatus.FAILED:
            return
        action = (
            "delivery.credentials_invalid"
            if item.failure_code == "bot_credentials_invalid"
            else "delivery.send_failed"
        )
        audit(
            session,
            user,
            action,
            item,
            item.company_id,
            {"failure_code": item.failure_code or "unknown"},
        )

    def dispatch_waiting_deliveries(session: Session, employee_id: str) -> None:
        """Atomically claim and dispatch each activation-waiting delivery."""
        delivery_ids = session.scalars(
            select(Delivery.id).where(
                Delivery.employee_id == employee_id,
                or_(
                    Delivery.status == DeliveryStatus.WAITING_INTERACTION,
                    and_(
                        Delivery.status == DeliveryStatus.PENDING,
                        Delivery.notification_type
                        == NotificationType.BINDING_WELCOME.value,
                    ),
                ),
            )
        ).all()
        for delivery_id in delivery_ids:
            token = secrets.token_urlsafe(32)
            claimed = session.execute(
                update(Delivery)
                .where(
                    Delivery.id == delivery_id,
                    or_(
                        Delivery.status == DeliveryStatus.WAITING_INTERACTION,
                        and_(
                            Delivery.status == DeliveryStatus.PENDING,
                            Delivery.notification_type
                            == NotificationType.BINDING_WELCOME.value,
                        ),
                    ),
                )
                .values(
                    status=DeliveryStatus.RETRYING,
                    retry_count=Delivery.retry_count + 1,
                    failure_code=None,
                    failure_message=None,
                    dispatch_token=token,
                    dispatch_lease_expires_at=dispatch_lease_deadline(),
                )
            )
            session.commit()
            if getattr(claimed, "rowcount", 0) != 1:
                continue
            item = session.get(Delivery, delivery_id)
            if item is None:
                continue
            dispatch_delivery(session, item)
            audit_delivery_failure(session, None, item)
            audit(session, None, "delivery.auto_retry", item, item.company_id)
            session.commit()
            cleanup_consumed_video_file(session, item)

    def company_json(item: Company) -> dict[str, Any]:
        return {
            "company_id": item.id,
            "company_slug": item.slug,
            "name": item.name,
            "enabled": item.enabled,
            **api_connection_json(),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    def api_connection_json() -> dict[str, Any]:
        base_url = settings.public_base_url.rstrip("/")
        api_base_url = base_url if base_url.endswith("/api/v1") else f"{base_url}/api/v1"
        parsed = urlsplit(api_base_url)
        hostname = (parsed.hostname or "").lower()
        address_scope = "configured"
        local_only = hostname == "localhost" or hostname.endswith(".localhost")
        if hostname:
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                if hostname.endswith((".lan", ".local", ".internal")):
                    address_scope = "lan"
            else:
                local_only = address.is_loopback
                if address.is_private and not local_only:
                    address_scope = "lan"
        if local_only:
            address_scope = "same_host"
            warning = (
                "当前地址只能被同一台机器上的应用调用；局域网其他设备请先通过 Nginx "
                "提供稳定 HTTPS 地址，并配置 APP_PUBLIC_BASE_URL。"
            )
        elif parsed.scheme != "https":
            warning = "跨机器调用当前未使用 HTTPS，局域网内也可能泄露 Token，请改用受信任 HTTPS。"
        else:
            warning = ""
        return {
            "api_base_url": api_base_url,
            "api_address_scope": address_scope,
            "api_address_warning": warning,
        }

    def api_client_json(item: ApiClient) -> dict[str, Any]:
        return {
            "id": item.id,
            "company_id": item.company_id,
            "name": item.name,
            "token_prefix": item.token_prefix,
            "permissions": item.permissions,
            "allowed_target_codes": item.allowed_target_codes,
            "enabled": item.enabled,
            "created_at": item.created_at,
            "last_used_at": item.last_used_at,
            "revoked_at": item.revoked_at,
        }

    def api_client_integration_json(session: Session, item: ApiClient) -> dict[str, Any]:
        company = session.get(Company, item.company_id)
        if company is None or company.deleted_at is not None:
            raise HTTPException(404, "API 客户端所属公司不存在")
        targets = session.scalars(
            select(NotificationTarget)
            .where(
                NotificationTarget.company_id == item.company_id,
                NotificationTarget.deleted_at.is_(None),
            )
            .order_by(NotificationTarget.created_at, NotificationTarget.id)
        ).all()
        targets_by_code = {target.target_code: target for target in targets}
        visible_codes = (
            item.allowed_target_codes
            if item.allowed_target_codes
            else [target.target_code for target in targets]
        )
        allowed_objects = [
            {
                "user_object_code": code,
                "account_name": (
                    targets_by_code[code].display_name if code in targets_by_code else "不可用对象"
                ),
                "description": (
                    targets_by_code[code].description if code in targets_by_code else ""
                ),
                "enabled": targets_by_code[code].enabled if code in targets_by_code else False,
            }
            for code in visible_codes
        ]
        connection = api_connection_json()
        permission_labels = {
            "query": "读取用户对象与预览",
            "send": "发送通知",
            "status": "查询发送结果",
        }
        permissions = [
            permission
            for permission in ("query", "send", "status")
            if permission in item.permissions
        ]
        permissions_text = "、".join(permission_labels[value] for value in permissions) or "无"
        if item.allowed_target_codes:
            scope_text = "仅允许指定用户对象：" + "、".join(item.allowed_target_codes)
        else:
            scope_text = "允许公司全部用户对象，包括未来新增对象"

        def markdown_table_text(value: object) -> str:
            return (
                str(value)
                .replace("\r", " ")
                .replace("\n", " ")
                .replace("|", "\\|")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

        object_mapping = [
            "| 调用标识 (`target_code`) | 对象名称 | 用途说明 | 状态 |",
            "| --- | --- | --- | --- |",
            *[
                "| `"
                + markdown_table_text(current["user_object_code"])
                + "` | "
                + markdown_table_text(current["account_name"])
                + " | "
                + markdown_table_text(current["description"] or "未填写")
                + " | "
                + ("启用" if current["enabled"] else "停用或不可用")
                + " |"
                for current in allowed_objects
            ],
        ]
        if not allowed_objects:
            object_mapping = ["_当前没有可用的用户对象。_"]

        api_base_url = str(connection["api_base_url"])
        steps: list[str] = []
        if "query" in permissions:
            steps.extend(
                [
                    f"1. `GET {api_base_url}/authorized-companies` 确认授权公司。",
                    f"2. `GET {api_base_url}/companies/{company.slug}/user-objects` "
                    "读取当前可用用户对象。",
                    "3. 从响应选择准确的 `user_object_code`；它在发送请求中对应 "
                    "`target_code`，禁止按名称模糊猜测。",
                    f"4. `POST {api_base_url}/notifications/preview` "
                    "预览该对象当前的微信绑定与健康状态。",
                ]
            )
        else:
            steps.append(
                "1. 当前凭据没有 `query` 权限，不能读取或预览用户对象；"
                "只能使用已配置的稳定对象代码。"
            )
        if "send" in permissions:
            steps.append(
                f"{len(steps) + 1}. `POST {api_base_url}/notifications/send` "
                "使用稳定幂等键发送。"
            )
        else:
            steps.append(f"{len(steps) + 1}. 当前凭据没有 `send` 权限，不得尝试发送通知。")
        if "status" in permissions:
            steps.append(
                f"{len(steps) + 1}. `GET {api_base_url}/notification-batches/"
                "{batch_id}` 查询批次及逐微信结果。"
            )

        guide_markdown = "\n".join(
            [
                "# 微信通知平台接入说明",
                "",
                "请把通知调用实现为服务端请求，不要把 Token 放进浏览器前端。",
                "",
                f"- API 地址：`{api_base_url}`",
                f"- 公司标识：`{company.slug}`",
                f"- 客户端名称：`{item.name.replace('`', '').replace(chr(10), ' ')}`",
                f"- 权限：{permissions_text}",
                f"- 用户对象范围：{scope_text}",
                f"- 当前投递模式：`{settings.delivery_mode}`",
                "- Token 已由部署人员保存到环境变量 "
                "`EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN`。禁止要求用户粘贴 Token，"
                "禁止打印、写日志或提交 Git。",
                "",
                "## 用户对象映射",
                "",
                *object_mapping,
                "",
                "调用时必须使用上表的精确 `target_code`；对象名称和用途说明"
                "只用于人工识别，禁止用名称、说明或 AI 猜测收件人。",
                "",
                "## 调用流程",
                "",
                *steps,
                "",
                "## 发送请求",
                "",
                "```json",
                "{",
                f'  "company_slug": "{company.slug}",',
                '  "target_code": "<user_object_code>",',
                '  "title": "通知标题",',
                '  "body": "通知正文",',
                '  "idempotency_key": "<业务事件稳定唯一ID>"',
                "}",
                "```",
                "",
                "一个用户对象会在发送时动态展开其下全部有效联系人和有效微信绑定；"
                "健康微信会发送，异常微信会体现在批次的跳过或部分成功结果中。"
                "未绑定联系人不会发送，应通过用户对象的 `pending_count` 识别。",
                "",
                "`sent` 只表示平台记录微信发送成功，`confirmed` 才表示员工回复确认；"
                "`partial` 必须检查逐微信结果。多人用户对象当前只使用纯文本通知，"
                "不使用一次性附件。",
            ]
        )
        curl_lines = [
            f"export EMPLOYEE_VIDEO_NOTIFICATION_API='{api_base_url}'",
            "# EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN 必须由部署人员写入秘密环境，"
            "禁止粘贴进 AI 对话或命令历史",
            'curl -fsS "$EMPLOYEE_VIDEO_NOTIFICATION_API/health"',
        ]
        if "query" in permissions:
            curl_lines.extend(
                [
                    'curl -fsS -H "Authorization: Bearer '
                    '$EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN" '
                    '"$EMPLOYEE_VIDEO_NOTIFICATION_API/authorized-companies"',
                    'curl -fsS -H "Authorization: Bearer '
                    '$EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN" '
                    f'"$EMPLOYEE_VIDEO_NOTIFICATION_API/companies/{company.slug}/user-objects"',
                ]
            )
        elif "status" in permissions:
            curl_lines.append(
                'curl -fsS -H "Authorization: Bearer '
                '$EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN" '
                f'"$EMPLOYEE_VIDEO_NOTIFICATION_API/notification-batches?company_id={company.id}"'
            )
        else:
            curl_lines.append(
                "# 当前凭据只有 send 权限；为避免真实通知，自检只检查服务健康，"
                "不发送测试消息。"
            )
        curl_check = "\n".join(curl_lines)
        return {
            **connection,
            "company_id": company.id,
            "company_slug": company.slug,
            "company_name": company.name,
            "client_id": item.id,
            "client_name": item.name,
            "permissions": permissions,
            "all_user_objects": not bool(item.allowed_target_codes),
            "allowed_user_objects": allowed_objects,
            "delivery_mode": settings.delivery_mode,
            "guide_markdown": guide_markdown,
            "curl_check": curl_check,
        }

    def require_api_permission(request: Request, permission: str, target_code: str = "") -> None:
        client = getattr(request.state, "api_client", None)
        if client is None:
            return
        if permission not in client.permissions:
            raise HTTPException(403, f"API 客户端缺少 {permission} 权限")
        allowed = client.allowed_target_codes
        if target_code and allowed and target_code not in allowed:
            raise HTTPException(403, "API 客户端无权访问该通知对象")

    def resolve_company(session: Session, user: User, company_slug: str) -> Company:
        item = session.scalar(
            select(Company).where(Company.slug == company_slug, Company.deleted_at.is_(None))
        )
        if item is None:
            raise HTTPException(404, "公司不存在")
        tenant(user, item.id)
        if not item.enabled:
            raise HTTPException(409, "公司已停用，不能预览或发送通知")
        return item

    def target_bindings(
        session: Session, item: NotificationTarget
    ) -> list[tuple[EmployeeBotBinding, WeixinBotAccount, TargetBotMember | None]]:
        if item.is_user_object:
            stable_rows = session.execute(
                select(EmployeeBotBinding, WeixinBotAccount)
                .join(
                    UserObjectContact,
                    UserObjectContact.employee_id == EmployeeBotBinding.employee_id,
                )
                .join(WeixinBotAccount, WeixinBotAccount.id == EmployeeBotBinding.bot_account_id)
                .join(Employee, Employee.id == EmployeeBotBinding.employee_id)
                .where(
                    UserObjectContact.target_id == item.id,
                    UserObjectContact.company_id == item.company_id,
                    UserObjectContact.active.is_(True),
                    EmployeeBotBinding.company_id == item.company_id,
                    EmployeeBotBinding.active.is_(True),
                    WeixinBotAccount.company_id == item.company_id,
                    Employee.status == EmployeeStatus.ACTIVE,
                )
            ).all()
            return [(binding, account, None) for binding, account in stable_rows]
        if item.employee_id is not None:
            compatibility_row = session.execute(
                select(EmployeeBotBinding, WeixinBotAccount)
                .join(WeixinBotAccount, WeixinBotAccount.id == EmployeeBotBinding.bot_account_id)
                .join(Employee, Employee.id == EmployeeBotBinding.employee_id)
                .where(
                    EmployeeBotBinding.company_id == item.company_id,
                    EmployeeBotBinding.employee_id == item.employee_id,
                    EmployeeBotBinding.active.is_(True),
                    WeixinBotAccount.company_id == item.company_id,
                    Employee.company_id == item.company_id,
                    Employee.status == EmployeeStatus.ACTIVE,
                )
            ).first()
            return (
                [(compatibility_row[0], compatibility_row[1], None)]
                if compatibility_row
                else []
            )
        if item.mode == TargetMode.DYNAMIC_ALL:
            rows = session.execute(
                select(EmployeeBotBinding, WeixinBotAccount)
                .join(WeixinBotAccount, WeixinBotAccount.id == EmployeeBotBinding.bot_account_id)
                .join(Employee, Employee.id == EmployeeBotBinding.employee_id)
                .where(
                    EmployeeBotBinding.company_id == item.company_id,
                    EmployeeBotBinding.active.is_(True),
                    WeixinBotAccount.company_id == item.company_id,
                    Employee.company_id == item.company_id,
                    Employee.status == EmployeeStatus.ACTIVE,
                )
            ).all()
            return [(binding, account, None) for binding, account in rows]
        explicit_rows = session.execute(
            select(EmployeeBotBinding, WeixinBotAccount, TargetBotMember)
            .join(TargetBotMember, TargetBotMember.binding_id == EmployeeBotBinding.id)
            .join(WeixinBotAccount, WeixinBotAccount.id == EmployeeBotBinding.bot_account_id)
            .join(Employee, Employee.id == EmployeeBotBinding.employee_id)
            .where(
                TargetBotMember.target_id == item.id,
                TargetBotMember.company_id == item.company_id,
                TargetBotMember.active.is_(True),
                EmployeeBotBinding.company_id == item.company_id,
                EmployeeBotBinding.active.is_(True),
                WeixinBotAccount.company_id == item.company_id,
                Employee.company_id == item.company_id,
                Employee.status == EmployeeStatus.ACTIVE,
            )
        ).all()
        unique: dict[str, tuple[EmployeeBotBinding, WeixinBotAccount, TargetBotMember | None]] = {}
        for binding, account, member in explicit_rows:
            unique[account.id] = (binding, account, member)
        return list(unique.values())

    def target_json(session: Session, item: NotificationTarget) -> dict[str, Any]:
        members = target_bindings(session, item)
        latest = session.scalar(
            select(NotificationBatch)
            .where(NotificationBatch.target_id == item.id)
            .order_by(desc(NotificationBatch.created_at))
        )
        return {
            "target_id": item.id,
            "company_id": item.company_id,
            "target_code": item.target_code,
            "display_name": item.display_name,
            "description": item.description,
            "mode": item.mode.value,
            "enabled": item.enabled,
            "member_count": len(members),
            "healthy_count": sum(
                account.health_status == BotHealthStatus.HEALTHY for _, account, _ in members
            ),
            "last_send_status": batch_json(session, latest)["status"] if latest else None,
            "created_at": item.created_at,
        }

    def replace_target_members(
        session: Session, item: NotificationTarget, binding_ids: list[str]
    ) -> None:
        if item.mode == TargetMode.DYNAMIC_ALL:
            if binding_ids:
                raise HTTPException(422, "全体人员动态对象不能指定固定 Bot 成员")
            return
        unique_ids = list(dict.fromkeys(binding_ids))
        if item.mode == TargetMode.SINGLE and len(unique_ids) != 1:
            raise HTTPException(422, "单人通知对象必须且只能关联一个微信 Bot")
        if item.mode == TargetMode.MULTI and not unique_ids:
            raise HTTPException(422, "多人通知对象至少关联一个微信 Bot")
        bindings = (
            session.scalars(
                select(EmployeeBotBinding)
                .join(Employee, Employee.id == EmployeeBotBinding.employee_id)
                .where(
                    EmployeeBotBinding.id.in_(unique_ids),
                    Employee.company_id == item.company_id,
                )
            ).all()
            if unique_ids
            else []
        )
        if len(bindings) != len(unique_ids) or any(
            binding.company_id != item.company_id or not binding.active for binding in bindings
        ):
            raise HTTPException(422, "Bot 成员不存在、已停用或不属于该公司")
        existing = session.scalars(
            select(TargetBotMember).where(
                TargetBotMember.target_id == item.id, TargetBotMember.active.is_(True)
            )
        ).all()
        by_binding = {member.binding_id: member for member in existing}
        for member in existing:
            if member.binding_id not in unique_ids:
                member.active = False
                member.removed_at = utcnow()
        for binding in bindings:
            if binding.id not in by_binding:
                session.add(
                    TargetBotMember(
                        company_id=item.company_id,
                        target_id=item.id,
                        binding_id=binding.id,
                        bot_account_id=binding.bot_account_id,
                    )
                )

    def batch_json(session: Session, item: NotificationBatch) -> dict[str, Any]:
        rows = session.execute(
            select(Delivery, WeixinBotAccount)
            .join(EmployeeBotBinding, EmployeeBotBinding.id == Delivery.binding_id)
            .join(WeixinBotAccount, WeixinBotAccount.id == EmployeeBotBinding.bot_account_id)
            .where(Delivery.batch_id == item.id, Delivery.company_id == item.company_id)
            .order_by(Delivery.created_at)
        ).all()
        sent_count = sum(
            delivery.status in {DeliveryStatus.SENT, DeliveryStatus.CONFIRMED}
            for delivery, _ in rows
        )
        failed_count = sum(
            delivery.status in {DeliveryStatus.FAILED, DeliveryStatus.CANCELLED}
            for delivery, _ in rows
        )
        simulated_count = sum(
            delivery.status == DeliveryStatus.SIMULATED for delivery, _ in rows
        )
        terminal_count = sent_count + failed_count + simulated_count
        if terminal_count < len(rows):
            aggregate_status = BatchStatus.PENDING
        elif simulated_count and not sent_count and not failed_count and item.skipped_count == 0:
            aggregate_status = BatchStatus.SIMULATED
        elif failed_count == 0 and item.skipped_count == 0:
            aggregate_status = BatchStatus.COMPLETED
        elif sent_count or simulated_count:
            aggregate_status = BatchStatus.PARTIAL
        else:
            aggregate_status = BatchStatus.FAILED
        return {
            "id": item.id,
            "company_id": item.company_id,
            "target_id": item.target_id,
            "status": aggregate_status.value,
            "total": item.total_count,
            "sent": sent_count,
            "simulated": simulated_count,
            "failed": failed_count,
            "skipped": item.skipped_count,
            "title": item.title,
            "created_at": item.created_at,
            "deliveries": [
                {
                    "delivery_id": delivery.id,
                    "bot_id": account.id,
                    "bot_masked": account.account_id_masked,
                    "status": delivery.status.value,
                    "failure_code": delivery.failure_code,
                    "failure_message": delivery.failure_message,
                }
                for delivery, account in rows
            ],
        }

    def recover_pending_batch(
        session: Session, item: NotificationBatch, user: User
    ) -> None:
        pending_ids = session.scalars(
            select(Delivery.id).where(
                Delivery.batch_id == item.id,
                Delivery.status == DeliveryStatus.PENDING,
                Delivery.dispatch_token.is_(None),
            )
        ).all()
        for delivery_id in pending_ids:
            delivery = session.get(Delivery, delivery_id)
            if delivery is None:
                continue
            dispatch_delivery(session, delivery)
            audit_delivery_failure(session, user, delivery)
            session.commit()

    @router.get("/companies", tags=["companies"])
    def list_companies(
        session: Session = Depends(get_session), user: User = Depends(current_user)
    ):
        query = select(Company).where(Company.deleted_at.is_(None))
        if user.role != Role.SUPER_ADMIN:
            query = query.where(Company.id == user.company_id)
        return [company_json(item) for item in session.scalars(query.order_by(Company.name)).all()]

    @router.post("/companies", status_code=201, tags=["companies"])
    def create_company(
        payload: CompanyCreate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        if user.role != Role.SUPER_ADMIN:
            raise HTTPException(403, "只有平台超级管理员可以新增公司")
        item = Company(id=payload.company_slug, slug=payload.company_slug, name=payload.name)
        session.add(item)
        audit(session, user, "company.create", item, item.id)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "公司标识已存在") from exc
        return company_json(item)

    @router.patch("/companies/{company_id}", tags=["companies"])
    def update_company(
        company_id: str,
        payload: CompanyUpdate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        item = session.get(Company, company_id)
        if item is None or item.deleted_at is not None:
            raise HTTPException(404, "公司不存在")
        tenant(user, item.id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, key, value)
        item.updated_at = utcnow()
        audit(session, user, "company.update", item, item.id, {"enabled": item.enabled})
        session.commit()
        return company_json(item)

    @router.get("/authorized-companies", tags=["business-api"])
    def authorized_companies(
        request: Request,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        require_api_permission(request, "query")
        query = select(Company).where(Company.deleted_at.is_(None))
        if user.role != Role.SUPER_ADMIN:
            query = query.where(Company.id == user.company_id)
        return [company_json(item) for item in session.scalars(query).all()]

    @router.get("/weixin-bots", tags=["bots"])
    def list_weixin_bots(
        company_id: str | None = None,
        session: Session = Depends(get_session),
        user: User = Depends(platform_user),
    ):
        scope = company_id or user.company_id
        if not scope:
            raise HTTPException(422, "company_id required")
        tenant(user, scope)
        rows = session.execute(
            select(EmployeeBotBinding, WeixinBotAccount, Employee)
            .join(WeixinBotAccount, WeixinBotAccount.id == EmployeeBotBinding.bot_account_id)
            .join(Employee, Employee.id == EmployeeBotBinding.employee_id)
            .where(EmployeeBotBinding.company_id == scope)
        ).all()
        return [
            {
                "bot_id": account.id,
                "binding_id": binding.id,
                "company_id": binding.company_id,
                "owner_target_id": employee.id,
                "owner_display_name": employee.name,
                "bot_masked": account.account_id_masked,
                "active": binding.active,
                "health_status": account.health_status.value,
                "last_heartbeat_at": account.last_health_at,
                "bound_at": binding.bound_at,
            }
            for binding, account, employee in rows
        ]

    def resolve_user_object_company(
        session: Session, user: User, company_ref: str
    ) -> Company:
        company = session.scalar(
            select(Company).where(
                or_(Company.id == company_ref, Company.slug == company_ref),
                Company.deleted_at.is_(None),
            )
        )
        if company is None:
            raise HTTPException(404, "公司不存在")
        tenant(user, company.id)
        return company

    def resolve_user_object(
        session: Session, company: Company, code: str
    ) -> NotificationTarget:
        item = session.scalar(
            select(NotificationTarget).where(
                NotificationTarget.company_id == company.id,
                NotificationTarget.target_code == code,
                NotificationTarget.deleted_at.is_(None),
            )
        )
        if item is None:
            raise HTTPException(404, "用户对象不存在")
        return item

    def user_object_employees(
        session: Session, item: NotificationTarget
    ) -> list[Employee]:
        if item.is_user_object:
            return list(
                session.scalars(
                    select(Employee)
                    .join(UserObjectContact, UserObjectContact.employee_id == Employee.id)
                    .where(
                        UserObjectContact.target_id == item.id,
                        UserObjectContact.company_id == item.company_id,
                        UserObjectContact.active.is_(True),
                        Employee.company_id == item.company_id,
                        Employee.status != EmployeeStatus.DELETED,
                    )
                    .order_by(UserObjectContact.created_at)
                ).all()
            )
        if item.employee_id:
            employee = session.get(Employee, item.employee_id)
            return [employee] if employee and employee.status != EmployeeStatus.DELETED else []
        if item.mode == TargetMode.DYNAMIC_ALL:
            return list(
                session.scalars(
                    select(Employee).where(
                        Employee.company_id == item.company_id,
                        Employee.status == EmployeeStatus.ACTIVE,
                    ).order_by(Employee.created_at)
                ).all()
            )
        rows = session.scalars(
            select(Employee)
            .join(EmployeeBotBinding, EmployeeBotBinding.employee_id == Employee.id)
            .join(TargetBotMember, TargetBotMember.binding_id == EmployeeBotBinding.id)
            .where(
                TargetBotMember.target_id == item.id,
                TargetBotMember.company_id == item.company_id,
                TargetBotMember.active.is_(True),
                Employee.company_id == item.company_id,
                Employee.status != EmployeeStatus.DELETED,
            )
            .order_by(TargetBotMember.created_at)
        ).all()
        return list({employee.id: employee for employee in rows}.values())

    def user_object_contact_json(
        session: Session,
        employee: Employee,
        *,
        can_manage: bool,
        supplied_binding: EmployeeBotBinding | None = None,
        use_supplied_binding: bool = False,
        include_binding_session: bool = True,
    ) -> dict[str, Any]:
        binding = (
            supplied_binding
            if use_supplied_binding
            else active_bot_binding(session, employee.id)
        )
        account = session.get(WeixinBotAccount, binding.bot_account_id) if binding else None
        test_allowed, _test_reason, _retry_after = manual_test_availability(
            employee, binding, account, can_manage=can_manage
        )
        binding_session = session.scalar(
            select(WeixinBindingSession)
            .where(WeixinBindingSession.employee_id == employee.id)
            .order_by(desc(WeixinBindingSession.created_at))
        )
        result: dict[str, Any] = {
            "employee_id": employee.id,
            "name": employee.name,
            "status": employee.status.value,
            "masked_phone": employee.phone_masked,
            "binding_status": "bound" if binding and binding.active else "unbound",
            "health_status": account.health_status.value if account else "unknown",
            "binding": (
                {
                    "binding_id": binding.id,
                    "status": "bound" if binding.active else "revoked",
                    "health_status": account.health_status.value if account else "unknown",
                    "bot_masked": account.account_id_masked if account else None,
                    "last_test_at": binding.last_manual_test_at,
                    "manual_test": {"allowed": test_allowed},
                }
                if binding
                else None
            ),
        }
        if can_manage and include_binding_session:
            result["binding_session"] = (
                binding_session_json(binding_session) if binding_session else None
            )
        if can_manage and employee.phone_encrypted:
            try:
                result["phone"] = phone_protector.decrypt(employee.phone_encrypted)
            except InvalidToken:
                pass
        return result

    def user_object_json(
        session: Session,
        item: NotificationTarget,
        *,
        can_manage: bool,
    ) -> dict[str, Any]:
        legacy_rows: list[tuple[Employee, EmployeeBotBinding]] = []
        if (
            not item.is_user_object
            and item.employee_id is None
            and item.mode != TargetMode.DYNAMIC_ALL
        ):
            legacy_rows = cast(
                list[tuple[Employee, EmployeeBotBinding]],
                session.execute(
                    select(Employee, EmployeeBotBinding)
                    .join(
                        TargetBotMember,
                        TargetBotMember.binding_id == EmployeeBotBinding.id,
                    )
                    .join(Employee, Employee.id == EmployeeBotBinding.employee_id)
                    .where(
                        TargetBotMember.target_id == item.id,
                        TargetBotMember.company_id == item.company_id,
                        TargetBotMember.active.is_(True),
                        EmployeeBotBinding.company_id == item.company_id,
                        Employee.company_id == item.company_id,
                    )
                    .order_by(TargetBotMember.created_at)
                ).all(),
            )
        employees = (
            [employee for employee, _ in legacy_rows]
            if legacy_rows
            else user_object_employees(session, item)
        )
        bindings = (
            [binding for _, binding in legacy_rows]
            if legacy_rows
            else [active_bot_binding(session, employee.id) for employee in employees]
        )
        accounts = [
            session.get(WeixinBotAccount, binding.bot_account_id) if binding else None
            for binding in bindings
        ]
        last_test_at = max(
            (
                binding.last_manual_test_at
                for binding in bindings
                if binding and binding.last_manual_test_at
            ),
            default=None,
        )
        return {
            "target_id": item.id,
            "company_id": item.company_id,
            "user_object_code": item.target_code,
            "account_name": item.display_name,
            "description": item.description,
            "mode": item.mode.value,
            "enabled": item.enabled,
            "is_user_object": item.is_user_object,
            "manageable": item.is_user_object,
            "all_available": item.mode == TargetMode.DYNAMIC_ALL,
            "bound_count": sum(binding is not None for binding in bindings),
            "pending_count": sum(binding is None for binding in bindings),
            "unhealthy_count": sum(
                binding is not None
                and (account is None or account.health_status != BotHealthStatus.HEALTHY)
                for binding, account in zip(bindings, accounts, strict=True)
            ),
            "last_test_at": last_test_at,
            "contacts": [
                user_object_contact_json(
                    session,
                    employee,
                    can_manage=can_manage,
                    supplied_binding=bindings[index],
                    use_supplied_binding=bool(legacy_rows),
                    include_binding_session=item.is_user_object,
                )
                for index, employee in enumerate(employees)
            ],
            "created_at": item.created_at,
        }

    def user_object_can_manage(request: Request, user: User) -> bool:
        return (
            user.role != Role.VIEWER
            and not getattr(request.state, "business_service_company_id", None)
            and not getattr(request.state, "api_client", None)
        )

    @router.get("/companies/{company_ref}/user-objects", tags=["user-objects"])
    def list_user_objects(
        company_ref: str,
        request: Request,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        company = resolve_user_object_company(session, user, company_ref)
        require_api_permission(request, "query")
        rows = session.scalars(
            select(NotificationTarget).where(
                NotificationTarget.company_id == company.id,
                NotificationTarget.deleted_at.is_(None),
            ).order_by(NotificationTarget.created_at)
        ).all()
        api_client = getattr(request.state, "api_client", None)
        if api_client and api_client.allowed_target_codes:
            rows = [item for item in rows if item.target_code in api_client.allowed_target_codes]
        can_manage = user_object_can_manage(request, user)
        return [user_object_json(session, item, can_manage=can_manage) for item in rows]

    @router.post(
        "/companies/{company_ref}/user-objects", status_code=201, tags=["user-objects"]
    )
    def create_user_object(
        company_ref: str,
        payload: UserObjectCreate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        company = resolve_user_object_company(session, user, company_ref)
        item = NotificationTarget(
            company_id=company.id,
            target_code=payload.routing_key or f"uo_{secrets.token_hex(10)}",
            display_name=payload.account_name,
            description=payload.description,
            mode=TargetMode.MULTI,
            is_user_object=True,
        )
        session.add(item)
        try:
            session.flush()
            audit(session, user, "user_object.create", item, company.id)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "该公司下调用标识已存在") from exc
        return user_object_json(session, item, can_manage=True)

    @router.get(
        "/companies/{company_ref}/user-objects/{user_object_code}", tags=["user-objects"]
    )
    def get_user_object(
        company_ref: str,
        user_object_code: str,
        request: Request,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        company = resolve_user_object_company(session, user, company_ref)
        require_api_permission(request, "query", user_object_code)
        item = resolve_user_object(session, company, user_object_code)
        return user_object_json(
            session, item, can_manage=user_object_can_manage(request, user)
        )

    @router.patch(
        "/companies/{company_ref}/user-objects/{user_object_code}", tags=["user-objects"]
    )
    def update_user_object(
        company_ref: str,
        user_object_code: str,
        payload: UserObjectUpdate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        company = resolve_user_object_company(session, user, company_ref)
        item = resolve_user_object(session, company, user_object_code)
        if not item.is_user_object:
            raise HTTPException(409, "兼容对象请使用原通知对象接口修改")
        values = payload.model_dump(exclude_unset=True)
        values.pop("confirm", None)
        if values.get("enabled") is False and not payload.confirm:
            raise HTTPException(422, "Explicit user object deactivation confirmation is required")
        if "account_name" in values:
            item.display_name = values["account_name"]
        if "description" in values:
            item.description = values["description"]
        if "enabled" in values:
            item.enabled = values["enabled"]
        item.updated_at = utcnow()
        audit(session, user, "user_object.update", item, company.id)
        session.commit()
        return user_object_json(session, item, can_manage=True)

    @router.post(
        "/companies/{company_ref}/user-objects/{user_object_code}/contacts",
        status_code=201,
        tags=["user-objects"],
    )
    def add_user_object_contact(
        company_ref: str,
        user_object_code: str,
        payload: UserObjectContactCreate,
        response: Response,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        company = resolve_user_object_company(session, user, company_ref)
        item = resolve_user_object(session, company, user_object_code)
        if not item.is_user_object:
            raise HTTPException(409, "兼容对象的成员请使用原通知对象接口管理")
        if payload.employee_id:
            employee = session.get(Employee, payload.employee_id)
            if (
                employee is None
                or employee.company_id != company.id
                or employee.status == EmployeeStatus.DELETED
            ):
                raise HTTPException(404, "联系人不存在")
        else:
            employee = Employee(
                company_id=company.id,
                name=payload.name or "",
                account_name=payload.name or "",
            )
            session.add(employee)
            session.flush()
        existing = session.scalar(
            select(UserObjectContact).where(
                UserObjectContact.target_id == item.id,
                UserObjectContact.employee_id == employee.id,
                UserObjectContact.active.is_(True),
            )
        )
        if existing:
            response.status_code = 200
            return user_object_contact_json(session, employee, can_manage=True)
        if payload.phone:
            try:
                protected = phone_protector.protect(payload.phone)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            employee.phone_encrypted = protected.encrypted
            employee.phone_fingerprint = protected.fingerprint
            employee.phone_masked = protected.masked
        relation = UserObjectContact(
            company_id=company.id, target_id=item.id, employee_id=employee.id
        )
        session.add(relation)
        try:
            session.flush()
            audit(
                session,
                user,
                "user_object.contact.add",
                relation,
                company.id,
                {"employee_id": employee.id, "target_id": item.id},
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            winner = session.scalar(
                select(UserObjectContact).where(
                    UserObjectContact.target_id == item.id,
                    UserObjectContact.employee_id == employee.id,
                    UserObjectContact.active.is_(True),
                )
            )
            if winner is None:
                raise HTTPException(409, "联系人关联冲突") from None
            response.status_code = 200
            employee = session.get(Employee, winner.employee_id)
            assert employee is not None
        return user_object_contact_json(session, employee, can_manage=True)

    @router.patch(
        "/companies/{company_ref}/user-objects/{user_object_code}/contacts/{employee_id}",
        tags=["user-objects"],
    )
    def update_user_object_contact(
        company_ref: str,
        user_object_code: str,
        employee_id: str,
        payload: UserObjectContactUpdate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        company = resolve_user_object_company(session, user, company_ref)
        item = resolve_user_object(session, company, user_object_code)
        relation = session.scalar(
            select(UserObjectContact).where(
                UserObjectContact.target_id == item.id,
                UserObjectContact.employee_id == employee_id,
                UserObjectContact.active.is_(True),
            )
        )
        employee = session.get(Employee, employee_id)
        if relation is None or employee is None or employee.company_id != company.id:
            raise HTTPException(404, "联系人关系不存在")
        values = payload.model_dump(exclude_unset=True)
        if "name" in values:
            employee.name = values["name"]
        if "phone" in values:
            try:
                protected = phone_protector.protect(values["phone"])
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            employee.phone_encrypted = protected.encrypted
            employee.phone_fingerprint = protected.fingerprint
            employee.phone_masked = protected.masked
        audit(session, user, "user_object.contact.update", relation, company.id)
        session.commit()
        return user_object_contact_json(session, employee, can_manage=True)

    @router.post(
        "/companies/{company_ref}/user-objects/{user_object_code}/contacts/"
        "{employee_id}/deactivate",
        tags=["user-objects"],
    )
    def deactivate_user_object_contact(
        company_ref: str,
        user_object_code: str,
        employee_id: str,
        payload: ConfirmUnbind,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        if not payload.confirm:
            raise HTTPException(422, "Explicit contact deactivation confirmation is required")
        company = resolve_user_object_company(session, user, company_ref)
        item = resolve_user_object(session, company, user_object_code)
        relation = session.scalar(
            select(UserObjectContact).where(
                UserObjectContact.target_id == item.id,
                UserObjectContact.employee_id == employee_id,
                UserObjectContact.company_id == company.id,
                UserObjectContact.active.is_(True),
            )
        )
        employee = session.get(Employee, employee_id)
        if relation is None or employee is None or employee.company_id != company.id:
            raise HTTPException(404, "联系人关系不存在")
        employee.status = EmployeeStatus.DISABLED
        audit(
            session,
            user,
            "user_object.contact.deactivate",
            relation,
            company.id,
            {"employee_id": employee.id, "target_id": item.id},
        )
        session.commit()
        return user_object_contact_json(session, employee, can_manage=True)

    @router.delete(
        "/companies/{company_ref}/user-objects/{user_object_code}/contacts/{employee_id}",
        tags=["user-objects"],
    )
    def remove_user_object_contact(
        company_ref: str,
        user_object_code: str,
        employee_id: str,
        payload: DestructiveConfirmation,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        if not payload.confirm:
            raise HTTPException(422, "Explicit contact removal confirmation is required")
        company = resolve_user_object_company(session, user, company_ref)
        item = resolve_user_object(session, company, user_object_code)
        relation = session.scalar(
            select(UserObjectContact).where(
                UserObjectContact.target_id == item.id,
                UserObjectContact.employee_id == employee_id,
                UserObjectContact.active.is_(True),
            )
        )
        if relation is None:
            raise HTTPException(404, "联系人关系不存在")
        relation.active = False
        relation.removed_at = utcnow()
        audit(session, user, "user_object.contact.remove", relation, company.id)
        session.commit()
        return {"ok": True}

    @router.post(
        "/companies/{company_ref}/user-objects/{user_object_code}/bind-all",
        tags=["user-objects"],
    )
    def bind_all_user_object_contacts(
        company_ref: str,
        user_object_code: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        company = resolve_user_object_company(session, user, company_ref)
        item = resolve_user_object(session, company, user_object_code)
        if not item.is_user_object:
            raise HTTPException(409, "兼容对象不能转换为固定全员范围")
        active_ids = set(
            session.scalars(
                select(UserObjectContact.employee_id).where(
                    UserObjectContact.target_id == item.id,
                    UserObjectContact.active.is_(True),
                )
            ).all()
        )
        employee_ids = session.scalars(
            select(Employee.id).where(
                Employee.company_id == company.id,
                Employee.status == EmployeeStatus.ACTIVE,
            )
        ).all()
        for employee_id in employee_ids:
            if employee_id not in active_ids:
                session.execute(
                    sqlite_insert(UserObjectContact)
                    .values(
                        id=secrets.token_hex(16),
                        company_id=company.id,
                        target_id=item.id,
                        employee_id=employee_id,
                        active=True,
                        created_at=utcnow(),
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            UserObjectContact.target_id,
                            UserObjectContact.employee_id,
                        ],
                        index_where=UserObjectContact.active.is_(True),
                    )
                )
        audit(
            session,
            user,
            "user_object.contact.bind_all",
            item,
            company.id,
            {"active_employee_count": len(employee_ids)},
        )
        session.commit()
        return user_object_json(session, item, can_manage=True)

    @router.delete(
        "/companies/{company_ref}/user-objects/{user_object_code}", tags=["user-objects"]
    )
    def delete_user_object(
        company_ref: str,
        user_object_code: str,
        payload: DestructiveConfirmation,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        if not payload.confirm:
            raise HTTPException(422, "Explicit user object deletion confirmation is required")
        company = resolve_user_object_company(session, user, company_ref)
        item = resolve_user_object(session, company, user_object_code)
        if not item.is_user_object:
            raise HTTPException(409, "兼容对象不能通过别名删除")
        item.enabled = False
        item.deleted_at = utcnow()
        for relation in session.scalars(
            select(UserObjectContact).where(
                UserObjectContact.target_id == item.id,
                UserObjectContact.active.is_(True),
            )
        ).all():
            relation.active = False
            relation.removed_at = utcnow()
        audit(session, user, "user_object.soft_delete", item, company.id)
        session.commit()
        return {"ok": True}

    @router.get("/notification-targets", tags=["targets"])
    def list_targets(
        request: Request,
        company_id: str | None = None,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        require_api_permission(request, "query")
        scope = company_id or user.company_id
        if not scope:
            raise HTTPException(422, "company_id required")
        tenant(user, scope)
        rows = session.scalars(
            select(NotificationTarget).where(
                NotificationTarget.company_id == scope,
                NotificationTarget.deleted_at.is_(None),
            ).order_by(NotificationTarget.created_at)
        ).all()
        client = getattr(request.state, "api_client", None)
        if client and client.allowed_target_codes:
            rows = [item for item in rows if item.target_code in client.allowed_target_codes]
        return [target_json(session, item) for item in rows]

    @router.get("/notification-targets/{target_id}/members", tags=["targets"])
    def get_target_members(
        target_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_user),
    ):
        item = session.get(NotificationTarget, target_id)
        if item is None or item.deleted_at is not None:
            raise HTTPException(404, "通知对象不存在")
        tenant(user, item.company_id)
        return {
            "target_id": item.id,
            "binding_ids": session.scalars(
                select(TargetBotMember.binding_id).where(
                    TargetBotMember.target_id == item.id,
                    TargetBotMember.active.is_(True),
                )
            ).all(),
        }

    @router.post("/notification-targets", status_code=201, tags=["targets"])
    def create_target_endpoint(
        payload: TargetCreate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        tenant(user, payload.company_id)
        company = session.get(Company, payload.company_id)
        if company is None or company.deleted_at is not None:
            raise HTTPException(404, "公司不存在")
        item = NotificationTarget(
            company_id=payload.company_id,
            target_code=payload.target_code,
            display_name=payload.display_name,
            description=payload.description,
            mode=payload.mode,
        )
        session.add(item)
        try:
            session.flush()
            replace_target_members(session, item, payload.binding_ids)
            audit(session, user, "target.create", item, item.company_id)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "该公司下通知对象 code 已存在") from exc
        return target_json(session, item)

    @router.patch("/notification-targets/{target_id}", tags=["targets"])
    def update_target_endpoint(
        target_id: str,
        payload: TargetUpdate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        item = session.get(NotificationTarget, target_id)
        if item is None or item.deleted_at is not None:
            raise HTTPException(404, "通知对象不存在")
        tenant(user, item.company_id)
        if item.is_user_object:
            raise HTTPException(409, "用户对象必须通过公司级 user-objects 接口修改")
        values = payload.model_dump(exclude_unset=True)
        binding_ids = values.pop("binding_ids", None)
        for key, value in values.items():
            setattr(item, key, value)
        if binding_ids is None and "mode" in values:
            binding_ids = session.scalars(
                select(TargetBotMember.binding_id).where(
                    TargetBotMember.target_id == item.id,
                    TargetBotMember.active.is_(True),
                )
            ).all()
        if binding_ids is not None:
            replace_target_members(session, item, binding_ids)
        item.updated_at = utcnow()
        audit(session, user, "target.update", item, item.company_id)
        session.commit()
        return target_json(session, item)

    @router.get("/api-clients", tags=["api-clients"])
    def list_api_clients(
        company_id: str | None = None,
        session: Session = Depends(get_session),
        user: User = Depends(platform_user),
    ):
        scope = company_id or user.company_id
        if not scope:
            raise HTTPException(422, "company_id required")
        tenant(user, scope)
        return [
            api_client_json(item)
            for item in session.scalars(
                select(ApiClient)
                .where(ApiClient.company_id == scope)
                .order_by(ApiClient.created_at)
            ).all()
        ]

    def issue_api_token() -> tuple[str, str, str]:
        token = f"evnc_{secrets.token_urlsafe(32)}"
        return token, token[:16], api_token_hash(token)

    def validated_api_client_target_codes(
        session: Session, company_id: str, target_codes: list[str]
    ) -> list[str]:
        unique_codes = list(dict.fromkeys(target_codes))
        if not unique_codes:
            return []
        existing_codes = set(
            session.scalars(
                select(NotificationTarget.target_code).where(
                    NotificationTarget.company_id == company_id,
                    NotificationTarget.target_code.in_(unique_codes),
                    NotificationTarget.deleted_at.is_(None),
                )
            ).all()
        )
        unknown_codes = [code for code in unique_codes if code not in existing_codes]
        if unknown_codes:
            raise HTTPException(422, f"用户对象不存在或不属于当前公司：{', '.join(unknown_codes)}")
        return unique_codes

    @router.get("/api-clients/{client_id}/integration-guide", tags=["api-clients"])
    def get_api_client_integration_guide(
        client_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_user),
    ):
        item = session.get(ApiClient, client_id)
        if item is None:
            raise HTTPException(404, "API 客户端不存在")
        tenant(user, item.company_id)
        return api_client_integration_json(session, item)

    @router.post("/api-clients", status_code=201, tags=["api-clients"])
    def create_api_client(
        payload: ApiClientCreate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        tenant(user, payload.company_id)
        if not set(payload.permissions) <= {"query", "send", "status"}:
            raise HTTPException(422, "permissions 只能包含 query/send/status")
        token, prefix, digest = issue_api_token()
        item = ApiClient(
            company_id=payload.company_id,
            name=payload.name,
            token_hash=digest,
            token_prefix=prefix,
            permissions=list(dict.fromkeys(payload.permissions)),
            allowed_target_codes=validated_api_client_target_codes(
                session, payload.company_id, payload.allowed_target_codes
            ),
        )
        session.add(item)
        session.flush()
        audit(session, user, "api_client.create", item, item.company_id)
        session.commit()
        return {
            **api_client_json(item),
            "token": token,
            "integration": api_client_integration_json(session, item),
        }

    @router.patch("/api-clients/{client_id}", tags=["api-clients"])
    def update_api_client(
        client_id: str,
        payload: ApiClientUpdate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        item = session.get(ApiClient, client_id)
        if item is None:
            raise HTTPException(404, "API 客户端不存在")
        tenant(user, item.company_id)
        values = payload.model_dump(exclude_unset=True)
        if "permissions" in values and not set(values["permissions"]) <= {
            "query",
            "send",
            "status",
        }:
            raise HTTPException(422, "permissions 只能包含 query/send/status")
        if "allowed_target_codes" in values:
            values["allowed_target_codes"] = validated_api_client_target_codes(
                session, item.company_id, values["allowed_target_codes"]
            )
        for key, value in values.items():
            setattr(item, key, list(dict.fromkeys(value)) if isinstance(value, list) else value)
        audit(session, user, "api_client.update", item, item.company_id)
        session.commit()
        return api_client_json(item)

    @router.post("/api-clients/{client_id}/rotate", tags=["api-clients"])
    def rotate_api_client(
        client_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        item = session.get(ApiClient, client_id)
        if item is None:
            raise HTTPException(404, "API 客户端不存在")
        tenant(user, item.company_id)
        token, prefix, digest = issue_api_token()
        item.token_hash = digest
        item.token_prefix = prefix
        item.updated_at = utcnow()
        audit(session, user, "api_client.rotate", item, item.company_id)
        session.commit()
        return {
            **api_client_json(item),
            "token": token,
            "integration": api_client_integration_json(session, item),
        }

    @router.delete("/api-clients/{client_id}", tags=["api-clients"])
    def delete_api_client(
        client_id: str,
        payload: DestructiveConfirmation,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        if not payload.confirm:
            raise HTTPException(422, "Explicit API client deletion confirmation is required")
        item = session.get(ApiClient, client_id)
        if item is None:
            raise HTTPException(404, "API 客户端不存在")
        tenant(user, item.company_id)
        detached = session.execute(
            update(NotificationBatch)
            .where(NotificationBatch.api_client_id == item.id)
            .values(api_client_id=None)
        )
        detached_count = int(getattr(detached, "rowcount", 0) or 0)
        audit(
            session,
            user,
            "api_client.delete",
            item,
            item.company_id,
            {"detached_notification_batches": detached_count},
        )
        session.delete(item)
        session.commit()
        return {
            "ok": True,
            "deleted_id": client_id,
            "detached_notification_batches": detached_count,
        }

    def resolve_target_for_request(
        session: Session,
        request: Request,
        user: User,
        payload: NotificationPreview,
        permission: str,
    ) -> tuple[
        Company,
        NotificationTarget,
        list[tuple[EmployeeBotBinding, WeixinBotAccount, TargetBotMember | None]],
    ]:
        require_api_permission(request, permission, payload.target_code)
        company = resolve_company(session, user, payload.company_slug)
        item = session.scalar(
            select(NotificationTarget).where(
                NotificationTarget.company_id == company.id,
                NotificationTarget.target_code == payload.target_code,
                NotificationTarget.deleted_at.is_(None),
            )
        )
        if item is None:
            raise HTTPException(404, "通知对象不存在")
        if not item.enabled:
            raise HTTPException(409, "通知对象已停用，不能发送")
        return company, item, target_bindings(session, item)

    @router.post("/notifications/preview", tags=["business-api"])
    def preview_notification(
        payload: NotificationPreview,
        request: Request,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        company, item, members = resolve_target_for_request(
            session, request, user, payload, "query"
        )
        return {
            "company_id": company.id,
            "company_slug": company.slug,
            "target_code": item.target_code,
            "account_name": item.display_name,
            "description": item.description,
            "bot_count": len(members),
            "healthy_count": sum(
                account.health_status == BotHealthStatus.HEALTHY for _, account, _ in members
            ),
            "bots": [
                {
                    "bot_id": account.id,
                    "bot_masked": account.account_id_masked,
                    "health_status": account.health_status.value,
                    "sendable": account.health_status == BotHealthStatus.HEALTHY,
                }
                for _, account, _ in members
            ],
        }

    @router.post("/notifications/send", status_code=201, tags=["business-api"])
    def send_notification_batch(
        payload: NotificationSend,
        request: Request,
        response: Response,
        session: Session = Depends(get_session),
        user: User = Depends(writable),
    ):
        if settings.environment != "test" and settings.delivery_mode != "weixin":
            raise HTTPException(409, "当前运行模式不允许正式发送通知")
        company, item, members = resolve_target_for_request(
            session, request, user, payload, "send"
        )
        normalized = json.dumps(
            {
                "company": company.id,
                "target": item.id,
                "title": payload.title,
                "body": payload.body,
                "media_asset_id": payload.media_asset_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        request_hash = hashlib.sha256(normalized.encode()).hexdigest()
        existing = session.scalar(
            select(NotificationBatch).where(
                NotificationBatch.company_id == company.id,
                NotificationBatch.target_id == item.id,
                NotificationBatch.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise HTTPException(409, "幂等键已用于不同的通知内容")
            recover_pending_batch(session, existing, user)
            response.status_code = 200
            return batch_json(session, existing)
        ready = [row for row in members if row[1].health_status == BotHealthStatus.HEALTHY]
        if not ready:
            raise HTTPException(409, "通知对象没有健康且可发送的微信 Bot")
        asset = session.get(VideoAsset, payload.media_asset_id) if payload.media_asset_id else None
        if payload.media_asset_id:
            if len(ready) != 1:
                raise HTTPException(409, "一次性附件当前只允许发送给恰好一个健康 Bot")
            binding = ready[0][0]
            if (
                asset is None
                or asset.company_id != company.id
                or asset.employee_id != binding.employee_id
                or asset.consumed_at is not None
                or asset.claimed_delivery_id is not None
                or available_video_path(asset) is None
            ):
                raise HTTPException(404, "附件不存在、已使用或不属于该公司和通知对象")
        api_client = getattr(request.state, "api_client", None)
        batch = NotificationBatch(
            company_id=company.id,
            target_id=item.id,
            api_client_id=api_client.id if api_client else None,
            idempotency_key=payload.idempotency_key,
            request_hash=request_hash,
            title=payload.title,
            body=payload.body,
            total_count=len(members),
            skipped_count=len(members) - len(ready),
        )
        session.add(batch)
        try:
            session.flush()
            deliveries: list[Delivery] = []
            for binding, account, member in ready:
                delivery = Delivery(
                    batch_id=batch.id,
                    target_id=item.id,
                    target_member_id=member.id if member else None,
                    company_id=company.id,
                    employee_id=binding.employee_id,
                    binding_id=binding.id,
                    video_asset_id=asset.id if asset else None,
                    title=payload.title,
                    body=payload.body,
                    notification_type=NotificationType.BUSINESS.value,
                    idempotency_key=f"batch:{batch.id}:{account.id}",
                )
                session.add(delivery)
                deliveries.append(delivery)
            session.flush()
            if asset is not None:
                claimed = session.execute(
                    update(VideoAsset)
                    .where(
                        VideoAsset.id == asset.id,
                        VideoAsset.claimed_delivery_id.is_(None),
                        VideoAsset.consumed_at.is_(None),
                    )
                    .values(claimed_delivery_id=deliveries[0].id)
                )
                if getattr(claimed, "rowcount", 0) != 1:
                    session.rollback()
                    raise HTTPException(409, "附件已被其他通知占用")
            audit(
                session,
                user,
                "notification_batch.create",
                batch,
                company.id,
                {
                    "api_client_id": api_client.id if api_client else None,
                    "target_id": item.id,
                    "delivery_count": len(deliveries),
                },
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            winner = session.scalar(
                select(NotificationBatch).where(
                    NotificationBatch.company_id == company.id,
                    NotificationBatch.target_id == item.id,
                    NotificationBatch.idempotency_key == payload.idempotency_key,
                )
            )
            if winner is None:
                raise HTTPException(409, "通知批次创建冲突") from None
            if winner.request_hash != request_hash:
                raise HTTPException(409, "幂等键已用于不同的通知内容") from None
            recover_pending_batch(session, winner, user)
            response.status_code = 200
            return batch_json(session, winner)
        forced_failure_binding = (
            request.headers.get("X-Test-Fail-Binding-ID")
            if settings.environment == "test"
            else None
        )
        for delivery in deliveries:
            if forced_failure_binding and delivery.binding_id == forced_failure_binding:
                send_mock(session, delivery, True)
            else:
                dispatch_delivery(session, delivery)
            audit_delivery_failure(session, user, delivery)
            session.commit()
        sent = sum(delivery.status == DeliveryStatus.SENT for delivery in deliveries)
        simulated = sum(
            delivery.status == DeliveryStatus.SIMULATED for delivery in deliveries
        )
        failed = sum(
            delivery.status
            not in {
                DeliveryStatus.SENT,
                DeliveryStatus.CONFIRMED,
                DeliveryStatus.SIMULATED,
            }
            for delivery in deliveries
        )
        batch.sent_count = sent
        batch.failed_count = failed
        batch.status = (
            BatchStatus.SIMULATED
            if simulated == len(deliveries) and failed == 0 and batch.skipped_count == 0
            else
            BatchStatus.COMPLETED
            if failed == 0 and batch.skipped_count == 0
            else BatchStatus.PARTIAL
            if sent > 0 or simulated > 0
            else BatchStatus.FAILED
        )
        batch.completed_at = utcnow()
        audit(
            session,
            user,
            "notification_batch.complete",
            batch,
            company.id,
            {
                "sent": sent,
                "simulated": simulated,
                "failed": failed,
                "skipped": batch.skipped_count,
            },
        )
        session.commit()
        return batch_json(session, batch)

    @router.get("/notification-batches", tags=["business-api"])
    def list_notification_batches(
        request: Request,
        company_id: str | None = None,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        require_api_permission(request, "status")
        scope = company_id or user.company_id
        if not scope:
            raise HTTPException(422, "company_id required")
        tenant(user, scope)
        rows = session.scalars(
            select(NotificationBatch)
            .where(NotificationBatch.company_id == scope)
            .order_by(desc(NotificationBatch.created_at))
        ).all()
        client = getattr(request.state, "api_client", None)
        if client and client.allowed_target_codes:
            allowed_target_ids = set(
                session.scalars(
                    select(NotificationTarget.id).where(
                        NotificationTarget.company_id == scope,
                        NotificationTarget.target_code.in_(client.allowed_target_codes),
                    )
                ).all()
            )
            rows = [item for item in rows if item.target_id in allowed_target_ids]
        return [batch_json(session, item) for item in rows]

    @router.get("/notification-batches/{batch_id}", tags=["business-api"])
    def get_notification_batch(
        batch_id: str,
        request: Request,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        require_api_permission(request, "status")
        item = session.get(NotificationBatch, batch_id)
        if item is None:
            raise HTTPException(404, "通知批次不存在")
        tenant(user, item.company_id)
        client = getattr(request.state, "api_client", None)
        target = session.get(NotificationTarget, item.target_id)
        if (
            client
            and client.allowed_target_codes
            and (target is None or target.target_code not in client.allowed_target_codes)
        ):
            raise HTTPException(403, "API 客户端无权访问该通知对象的批次")
        return batch_json(session, item)

    @router.post("/users", status_code=201, tags=["auth"])
    def create_user(
        payload: UserCreate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        if user.role != Role.SUPER_ADMIN:
            raise HTTPException(403, "Super administrator required")
        if payload.role != Role.SUPER_ADMIN and not payload.company_id:
            raise HTTPException(422, "company_id required")
        created = User(
            username=payload.username,
            password_hash=hash_password(payload.password),
            role=payload.role,
            company_id=payload.company_id,
        )
        session.add(created)
        session.commit()
        return {
            "id": created.id,
            "username": created.username,
            "role": created.role.value,
            "company_id": created.company_id,
        }

    @router.get("/employees", tags=["employees"])
    def list_employees(
        request: Request,
        company_id: str | None = None,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        scope = company_id or user.company_id
        if user.role != Role.SUPER_ADMIN and scope != user.company_id:
            raise HTTPException(403, "Cross-company access denied")
        query = select(Employee).where(Employee.status != EmployeeStatus.DELETED)
        if scope:
            query = query.where(Employee.company_id == scope)
        include_management = not bool(
            getattr(request.state, "business_service_company_id", None)
        )
        return [
            employee_json(
                session,
                row,
                include_management=include_management,
                can_manage=include_management and user.role != Role.VIEWER,
            )
            for row in session.scalars(query.order_by(Employee.created_at)).all()
        ]

    @router.post("/employees", status_code=201, tags=["employees"])
    def create_employee(
        payload: EmployeeCreate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        tenant(user, payload.company_id)
        employee = Employee(**payload.model_dump())
        session.add(employee)
        session.flush()
        audit(session, user, "employee.create", employee, employee.company_id)
        create_binding_session_record(session, employee, user)
        session.commit()
        return employee_json(session, employee)

    def employee_has_user_object_relationship(session: Session, employee_id: str) -> bool:
        return (
            session.scalar(
                select(UserObjectContact.id)
                .join(
                    NotificationTarget,
                    NotificationTarget.id == UserObjectContact.target_id,
                )
                .where(
                    UserObjectContact.employee_id == employee_id,
                    NotificationTarget.is_user_object.is_(True),
                )
                .limit(1)
            )
            is not None
        )

    @router.get("/employees/{employee_id}", tags=["employees"])
    def get_employee(
        request: Request,
        employee_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        employee = session.get(Employee, employee_id)
        if employee is None or employee.status == EmployeeStatus.DELETED:
            raise HTTPException(404, "Employee not found")
        tenant(user, employee.company_id)
        return employee_json(
            session,
            employee,
            include_management=not bool(
                getattr(request.state, "business_service_company_id", None)
            ),
            can_manage=(
                not bool(getattr(request.state, "business_service_company_id", None))
                and user.role != Role.VIEWER
            ),
        )

    @router.patch("/employees/{employee_id}", tags=["employees"])
    def update_employee(
        employee_id: str,
        payload: EmployeeUpdate,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(404, "Employee not found")
        tenant(user, employee.company_id)
        values = payload.model_dump(exclude_unset=True)
        confirmed = bool(values.pop("confirm", False))
        if (
            values.get("status") in {EmployeeStatus.DISABLED, EmployeeStatus.DELETED}
            and employee_has_user_object_relationship(session, employee.id)
            and not confirmed
        ):
            raise HTTPException(422, "Confirmation required for user object contact")
        for key, value in values.items():
            setattr(employee, key, value)
        audit(session, user, "employee.update", employee, employee.company_id)
        session.commit()
        return employee_json(session, employee)

    @router.delete("/employees/{employee_id}", tags=["employees"])
    def delete_employee(
        employee_id: str,
        payload: ConfirmUnbind | None = None,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(404, "Employee not found")
        tenant(user, employee.company_id)
        if employee_has_user_object_relationship(session, employee.id) and not (
            payload and payload.confirm
        ):
            raise HTTPException(422, "Confirmation required for user object contact")
        employee.status = EmployeeStatus.DELETED
        audit(session, user, "employee.soft_delete", employee, employee.company_id)
        session.commit()
        return {"ok": True}

    @router.post(
        "/employees/{employee_id}/binding-sessions", status_code=201, tags=["binding"]
    )
    def create_binding_session(
        employee_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        employee = session.get(Employee, employee_id)
        if employee is None or employee.status == EmployeeStatus.DELETED:
            raise HTTPException(404, "Employee not found")
        tenant(user, employee.company_id)
        item = create_binding_session_record(session, employee, user)
        session.commit()
        return binding_session_json(item)

    def authorized_binding_session(
        session_id: str, session: Session, user: User
    ) -> WeixinBindingSession:
        item = session.get(WeixinBindingSession, session_id)
        if item is None:
            raise HTTPException(404, "Binding session not found")
        tenant(user, item.company_id)
        return item

    def mark_expired(item: WeixinBindingSession) -> bool:
        expires = item.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if item.status in {
            BindingSessionStatus.PENDING,
            BindingSessionStatus.SCANNED,
            BindingSessionStatus.CONFIRMING,
        } and expires <= utcnow():
            item.status = BindingSessionStatus.EXPIRED
            item.failure_code = "expired"
            return True
        return False

    @router.get("/binding-sessions/{session_id}", tags=["binding"])
    def get_binding_session(
        session_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_user),
    ):
        item = authorized_binding_session(session_id, session, user)
        if mark_expired(item):
            session.commit()
        return binding_session_json(item)

    @router.get("/binding-sessions/{session_id}/qr.png", tags=["binding"])
    def binding_qr(
        session_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_user),
    ) -> Response:
        item = authorized_binding_session(session_id, session, user)
        if mark_expired(item):
            session.commit()
        if item.status not in {
            BindingSessionStatus.PENDING,
            BindingSessionStatus.SCANNED,
            BindingSessionStatus.CONFIRMING,
        }:
            raise HTTPException(410, "Binding QR is no longer active")
        from app.ilink_binding import render_qr_png

        scan_data = cipher.decrypt(item.scan_data_encrypted.encode()).decode()
        return Response(
            render_qr_png(scan_data),
            media_type="image/png",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @router.post("/binding-sessions/{session_id}/poll", tags=["binding"])
    def poll_binding_session(
        session_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        with binding_poll_lock:
            session.expire_all()
            item = authorized_binding_session(session_id, session, user)
            if mark_expired(item):
                session.commit()
                return binding_session_json(item)
            if item.status not in {
                BindingSessionStatus.PENDING,
                BindingSessionStatus.SCANNED,
                BindingSessionStatus.CONFIRMING,
            }:
                if item.status == BindingSessionStatus.BOUND:
                    current_binding = active_bot_binding(session, item.employee_id)
                    if current_binding is not None:
                        dispatch_binding_welcome(session, current_binding.id)
                return binding_session_json(item)
            from app.ilink_binding import IlinkQrAdapter, IlinkStatus

            outcome = None
            poll_failed = False
            try:
                outcome = IlinkQrAdapter.poll(
                    ticket=cipher.decrypt(item.official_ticket_encrypted.encode()).decode(),
                    current_base_url=cipher.decrypt(
                        item.current_base_url_encrypted.encode()
                    ).decode(),
                )
            except Exception:
                poll_failed = True
            claim = session.execute(
                update(WeixinBindingSession)
                .where(
                    WeixinBindingSession.id == session_id,
                    WeixinBindingSession.status.in_(
                        {
                            BindingSessionStatus.PENDING,
                            BindingSessionStatus.SCANNED,
                            BindingSessionStatus.CONFIRMING,
                        }
                    ),
                )
                .values(status=BindingSessionStatus.CONFIRMING)
                .execution_options(synchronize_session=False)
            )
            if getattr(claim, "rowcount", 0) != 1:
                session.rollback()
                latest = authorized_binding_session(session_id, session, user)
                return binding_session_json(latest)
            session.expire_all()
            item = authorized_binding_session(session_id, session, user)
            if poll_failed:
                item.status = BindingSessionStatus.FAILED
                item.failure_code = "official_poll_failed"
                audit(session, user, "binding_session.failed", item, item.company_id)
                session.commit()
                return binding_session_json(item)
            assert outcome is not None
            if outcome.current_base_url:
                item.current_base_url_encrypted = enc(outcome.current_base_url)
            if outcome.status == IlinkStatus.PENDING:
                item.status = BindingSessionStatus.PENDING
            elif outcome.status == IlinkStatus.SCANNED:
                item.status = BindingSessionStatus.SCANNED
            elif outcome.status == IlinkStatus.CONFIRMING:
                item.status = BindingSessionStatus.CONFIRMING
            elif outcome.status == IlinkStatus.EXPIRED:
                item.status = BindingSessionStatus.EXPIRED
                item.failure_code = "expired"
            elif outcome.status == IlinkStatus.FAILED:
                item.status = BindingSessionStatus.FAILED
                item.failure_code = outcome.failure_code or "official_login_failed"
            elif outcome.status == IlinkStatus.CONFIRMED:
                employee = session.get(Employee, item.employee_id)
                if employee is None or employee.status != EmployeeStatus.ACTIVE:
                    item.status = BindingSessionStatus.FAILED
                    item.failure_code = "employee_unavailable"
                else:
                    account_fp = fingerprint(outcome.account_id)
                    account = session.scalar(
                        select(WeixinBotAccount).where(
                            WeixinBotAccount.account_fingerprint == account_fp
                        )
                    )
                    if account:
                        if account.company_id != employee.company_id:
                            item.status = BindingSessionStatus.FAILED
                            item.failure_code = "bot_account_company_mismatch"
                            session.commit()
                            return binding_session_json(item)
                        occupied = session.scalar(
                            select(EmployeeBotBinding).where(
                                EmployeeBotBinding.bot_account_id == account.id,
                                EmployeeBotBinding.active.is_(True),
                            )
                        )
                        if occupied and occupied.employee_id != employee.id:
                            item.status = BindingSessionStatus.FAILED
                            item.failure_code = "bot_account_already_bound"
                            session.commit()
                            return binding_session_json(item)
                        account.account_id_encrypted = enc(outcome.account_id)
                        account.bot_token_encrypted = enc(outcome.token)
                        account.base_url_encrypted = enc(outcome.base_url)
                        account.owner_user_id_encrypted = enc(outcome.user_id)
                        account.health_status = BotHealthStatus.UNKNOWN
                    else:
                        account = WeixinBotAccount(
                            company_id=employee.company_id,
                            account_fingerprint=account_fp,
                            account_id_encrypted=enc(outcome.account_id),
                            bot_token_encrypted=enc(outcome.token),
                            base_url_encrypted=enc(outcome.base_url),
                            owner_user_id_encrypted=enc(outcome.user_id),
                            account_id_masked=mask(outcome.account_id),
                        )
                        session.add(account)
                        session.flush()
                    existing_employee = active_bot_binding(session, employee.id)
                    if existing_employee is None:
                        created_binding = EmployeeBotBinding(
                            company_id=employee.company_id,
                            employee_id=employee.id,
                            bot_account_id=account.id,
                        )
                        session.add(created_binding)
                        session.flush()
                        create_binding_welcome(session, employee, created_binding)
                    item.status = BindingSessionStatus.BOUND
                    item.consumed_at = utcnow()
                    audit(session, user, "binding.confirm", item, item.company_id)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                current = session.get(WeixinBindingSession, session_id)
                if current and current.status == BindingSessionStatus.BOUND:
                    return binding_session_json(current)
                if current:
                    current.status = BindingSessionStatus.FAILED
                    current.failure_code = "concurrent_binding_conflict"
                    session.commit()
                    return binding_session_json(current)
                raise HTTPException(409, "Binding session conflict") from None
            if item.status == BindingSessionStatus.BOUND:
                current_binding = active_bot_binding(session, item.employee_id)
                if current_binding is not None:
                    dispatch_binding_welcome(session, current_binding.id)
            return binding_session_json(item)

    @router.post("/binding-sessions/{session_id}/cancel", tags=["binding"])
    def cancel_binding_session(
        session_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        item = authorized_binding_session(session_id, session, user)
        cancelled_at = utcnow()
        result = session.execute(
            update(WeixinBindingSession)
            .where(
                WeixinBindingSession.id == session_id,
                WeixinBindingSession.status.in_(
                    {
                        BindingSessionStatus.PENDING,
                        BindingSessionStatus.SCANNED,
                        BindingSessionStatus.CONFIRMING,
                    }
                ),
            )
            .values(
                status=BindingSessionStatus.CANCELLED,
                cancelled_at=cancelled_at,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) == 1:
            session.expire_all()
            item = authorized_binding_session(session_id, session, user)
            audit(session, user, "binding_session.cancel", item, item.company_id)
            session.commit()
        else:
            session.rollback()
            item = authorized_binding_session(session_id, session, user)
        return binding_session_json(item)

    @router.post("/employees/{employee_id}/binding-code", status_code=201, tags=["binding"])
    def binding_code(
        employee_id: str,
        request: Request,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(404, "Employee not found")
        tenant(user, employee.company_id)
        code = secrets.token_hex(3).upper()
        expires = utcnow() + timedelta(seconds=settings.binding_ttl_seconds)
        if settings.environment == "test" and request.headers.get("X-Test-Expires-At"):
            expires = datetime.fromisoformat(request.headers["X-Test-Expires-At"])
        record = BindingCode(
            company_id=employee.company_id,
            employee_id=employee.id,
            code_hash=fingerprint(code),
            expires_at=expires,
        )
        session.add(record)
        audit(session, user, "binding_code.create", record, employee.company_id)
        session.commit()
        return {"code": code, "expires_at": expires}

    @router.post("/employees/{employee_id}/unbind", tags=["binding"])
    def unbind(
        employee_id: str,
        payload: ConfirmUnbind,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        if not payload.confirm:
            raise HTTPException(422, "Explicit unbind confirmation is required")
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(404, "Employee not found")
        tenant(user, employee.company_id)
        bot_binding = active_bot_binding(session, employee.id)
        if bot_binding:
            session.execute(
                update(EmployeeBotBinding)
                .where(EmployeeBotBinding.id == bot_binding.id)
                .values(
                    active=False,
                    revoked_at=utcnow(),
                    context_token_encrypted=None,
                    chat_id_encrypted=None,
                )
            )
        legacy = active_legacy_binding(session, employee.id)
        if legacy:
            legacy.active = False
            legacy.revoked_at = utcnow()
            legacy.context_token_encrypted = None
        live_sessions = session.scalars(
            select(WeixinBindingSession).where(
                WeixinBindingSession.employee_id == employee.id,
                WeixinBindingSession.status.in_(
                    [
                        BindingSessionStatus.PENDING,
                        BindingSessionStatus.SCANNED,
                        BindingSessionStatus.CONFIRMING,
                    ]
                ),
            )
        ).all()
        for live in live_sessions:
            live.status = BindingSessionStatus.REVOKED
            live.cancelled_at = utcnow()
        audit(session, user, "binding.revoke", employee, employee.company_id)
        session.commit()
        return {"ok": True}

    def require_user_object_contact(
        session: Session,
        user: User,
        company_ref: str,
        user_object_code: str,
        employee_id: str,
    ) -> tuple[Company, NotificationTarget, Employee]:
        company = resolve_user_object_company(session, user, company_ref)
        item = resolve_user_object(session, company, user_object_code)
        relation = session.scalar(
            select(UserObjectContact).where(
                UserObjectContact.target_id == item.id,
                UserObjectContact.employee_id == employee_id,
                UserObjectContact.company_id == company.id,
                UserObjectContact.active.is_(True),
            )
        )
        employee = session.get(Employee, employee_id)
        if relation is None or employee is None or employee.company_id != company.id:
            raise HTTPException(404, "联系人关系不存在")
        return company, item, employee

    @router.post(
        "/companies/{company_ref}/user-objects/{user_object_code}/contacts/"
        "{employee_id}/binding-sessions",
        status_code=201,
        tags=["user-objects"],
    )
    def create_user_object_contact_binding_session(
        company_ref: str,
        user_object_code: str,
        employee_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        _company, _item, employee = require_user_object_contact(
            session, user, company_ref, user_object_code, employee_id
        )
        binding_session = create_binding_session_record(session, employee, user)
        session.commit()
        return binding_session_json(binding_session)

    @router.post(
        "/companies/{company_ref}/user-objects/{user_object_code}/contacts/"
        "{employee_id}/unbind",
        tags=["user-objects"],
    )
    def unbind_user_object_contact(
        company_ref: str,
        user_object_code: str,
        employee_id: str,
        payload: ConfirmUnbind,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        require_user_object_contact(
            session, user, company_ref, user_object_code, employee_id
        )
        return unbind(employee_id, payload, session, user)

    @router.post("/binding-transfers", tags=["binding"])
    def transfer_binding(
        payload: BindingTransfer,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        source = session.get(Employee, payload.source_employee_id)
        target = session.get(Employee, payload.target_employee_id)
        if source is None or target is None:
            raise HTTPException(404, "Employee not found")
        tenant(user, source.company_id)
        tenant(user, target.company_id)
        if source.company_id != target.company_id:
            raise HTTPException(403, "Cross-company Bot transfer is forbidden")
        if target.status != EmployeeStatus.ACTIVE:
            raise HTTPException(409, "Target employee is not active")
        if active_bot_binding(session, target.id):
            raise HTTPException(409, "Target employee already has a Weixin Bot")
        source_binding = active_bot_binding(session, source.id)
        if source_binding is None:
            source_binding = session.scalar(
                select(EmployeeBotBinding)
                .where(EmployeeBotBinding.employee_id == source.id)
                .order_by(desc(EmployeeBotBinding.bound_at))
            )
        if source_binding is None:
            raise HTTPException(409, "Source employee has no reusable Weixin Bot")
        occupied = session.scalar(
            select(EmployeeBotBinding).where(
                EmployeeBotBinding.bot_account_id == source_binding.bot_account_id,
                EmployeeBotBinding.active.is_(True),
            )
        )
        if occupied and occupied.employee_id != source.id:
            raise HTTPException(409, "Weixin Bot is assigned to another employee")
        session.execute(
            update(EmployeeBotBinding)
            .where(EmployeeBotBinding.id == source_binding.id)
            .values(
                active=False,
                revoked_at=utcnow(),
                context_token_encrypted=None,
                chat_id_encrypted=None,
            )
        )
        created = EmployeeBotBinding(
            company_id=target.company_id,
            employee_id=target.id,
            bot_account_id=source_binding.bot_account_id,
        )
        session.add(created)
        session.flush()
        create_binding_welcome(session, target, created)
        audit(
            session,
            user,
            "binding.transfer",
            created,
            target.company_id,
            {"source_employee_id": source.id, "target_employee_id": target.id},
        )
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "Weixin Bot transfer conflict; no changes applied") from exc
        dispatch_binding_welcome(session, created.id)
        return {"ok": True, "binding": employee_json(session, target)["binding"]}

    @router.post(
        "/employees/{employee_id}/test-notification",
        status_code=201,
        tags=["deliveries"],
    )
    def send_manual_test(
        employee_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        employee = session.get(Employee, employee_id)
        if employee is None or employee.status == EmployeeStatus.DELETED:
            raise HTTPException(404, "Employee not found")
        tenant(user, employee.company_id)
        binding = active_bot_binding(session, employee.id)
        account = session.get(WeixinBotAccount, binding.bot_account_id) if binding else None
        allowed, reason, retry_after = manual_test_availability(
            employee, binding, account, can_manage=True
        )
        if not allowed:
            if retry_after:
                raise HTTPException(
                    429,
                    reason or "Test notification cooldown is active",
                    headers={"Retry-After": str(retry_after)},
                )
            raise HTTPException(409, reason or "Test notification is unavailable")
        assert binding is not None
        now = utcnow()
        claimed = session.execute(
            update(EmployeeBotBinding)
            .where(
                EmployeeBotBinding.id == binding.id,
                EmployeeBotBinding.active.is_(True),
                or_(
                    EmployeeBotBinding.last_manual_test_at.is_(None),
                    EmployeeBotBinding.last_manual_test_at <= now - timedelta(seconds=60),
                ),
            )
            .values(last_manual_test_at=now)
            .execution_options(synchronize_session=False)
        )
        if getattr(claimed, "rowcount", 0) != 1:
            session.rollback()
            current = session.get(EmployeeBotBinding, binding.id)
            remaining = 60
            if current and current.last_manual_test_at:
                remaining = max(
                    1,
                    60 - int((utcnow() - aware(current.last_manual_test_at)).total_seconds()),
                )
            raise HTTPException(
                429,
                f"测试发送冷却中，请 {remaining} 秒后重试",
                headers={"Retry-After": str(remaining)},
            )
        company = session.get(Company, employee.company_id)
        display_name = company.name if company else employee.company_id
        item = Delivery(
            company_id=employee.company_id,
            employee_id=employee.id,
            binding_id=binding.id,
            notification_type=NotificationType.MANUAL_TEST.value,
            title="微信通知通道测试",
            body=(
                f"这是{display_name}管理员发起的微信通知通道测试。"
                "收到此消息表示当前通道可正常发送通知，无需回复。"
            ),
            idempotency_key=f"manual-test:{binding.id}:{int(now.timestamp() * 1_000_000)}",
            status=DeliveryStatus.SENDING,
            dispatch_token=secrets.token_urlsafe(32),
            dispatch_lease_expires_at=dispatch_lease_deadline(),
        )
        session.add(item)
        session.flush()
        audit(
            session,
            user,
            "delivery.manual_test.create",
            item,
            employee.company_id,
            {"binding_id": binding.id, "status": DeliveryStatus.SENDING.value},
        )
        session.commit()
        dispatch_delivery(session, item)
        audit_delivery_failure(session, user, item)
        session.commit()
        return delivery_json(item)

    @router.post("/employees/{employee_id}/binding/context-expire", tags=["binding"])
    def expire_context(
        employee_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(404, "Employee not found")
        tenant(user, employee.company_id)
        binding = active_legacy_binding(session, employee.id)
        if binding is None:
            raise HTTPException(409, "Employee is not bound")
        binding.context_token_encrypted = None
        audit(session, user, "binding.context_expire", binding, employee.company_id)
        session.commit()
        return {"ok": True}

    @router.post("/video-assets", status_code=201, tags=["video-assets"])
    @router.post("/media-assets", status_code=201, tags=["media-assets"])
    async def create_asset(
        request: Request,
        company_id: str = Form(),
        employee_id: str = Form(),
        title: str = Form(""),
        caption: str = Form(""),
        file: UploadFile = File(),
        session: Session = Depends(get_session),
        user: User = Depends(writable),
    ):
        tenant(user, company_id)
        employee = session.get(Employee, employee_id)
        if employee is None or employee.company_id != company_id:
            raise HTTPException(404, "Employee not found")
        api_client = getattr(request.state, "api_client", None)
        if api_client and api_client.allowed_target_codes:
            allowed_targets = session.scalars(
                select(NotificationTarget).where(
                    NotificationTarget.company_id == company_id,
                    NotificationTarget.target_code.in_(api_client.allowed_target_codes),
                    NotificationTarget.enabled.is_(True),
                    NotificationTarget.deleted_at.is_(None),
                )
            ).all()
            if not any(
                target.mode == TargetMode.DYNAMIC_ALL
                or any(
                    binding.employee_id == employee_id
                    for binding, _, _ in target_bindings(session, target)
                )
                for target in allowed_targets
            ):
                raise HTTPException(403, "API 客户端无权为该通知对象所有者上传附件")
        original_filename = Path(file.filename or "video.bin").name
        suffix = Path(original_filename).suffix.lower()
        content_type = (file.content_type or "application/octet-stream").lower()
        allowed_types = {
            ".csv": {"application/csv", "text/csv", "text/plain"},
            ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            ".gif": {"image/gif"},
            ".jpg": {"image/jpeg"},
            ".jpeg": {"image/jpeg"},
            ".m4v": {"application/octet-stream", "video/mp4", "video/x-m4v"},
            ".mov": {"application/octet-stream", "video/quicktime"},
            ".mp4": {"application/octet-stream", "video/mp4"},
            ".pdf": {"application/pdf"},
            ".png": {"image/png"},
            ".txt": {"text/plain"},
            ".webm": {"application/octet-stream", "video/webm"},
            ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        }
        if suffix not in allowed_types or content_type not in allowed_types[suffix]:
            raise HTTPException(415, "Unsupported attachment type")
        first_chunk = await file.read(1024 * 1024)
        if not first_chunk:
            raise HTTPException(422, "Empty file")
        quicktime_atoms = {b"free", b"mdat", b"moov", b"pnot", b"skip", b"wide"}
        is_iso_video = suffix in {".m4v", ".mov", ".mp4"} and (
            b"ftyp" in first_chunk[:32]
            or (suffix == ".mov" and first_chunk[4:8] in quicktime_atoms)
        )
        is_webm = suffix == ".webm" and first_chunk.startswith(b"\x1aE\xdf\xa3")
        is_image = (
            suffix == ".png" and first_chunk.startswith(b"\x89PNG\r\n\x1a\n")
        ) or (
            suffix in {".jpg", ".jpeg"} and first_chunk.startswith(b"\xff\xd8\xff")
        ) or (suffix == ".gif" and first_chunk.startswith((b"GIF87a", b"GIF89a")))
        is_document = (
            suffix == ".pdf" and first_chunk.startswith(b"%PDF-")
        ) or (
            suffix in {".docx", ".xlsx"} and first_chunk.startswith(b"PK\x03\x04")
        ) or (
            suffix in {".txt", ".csv"} and b"\x00" not in first_chunk
        )
        if not (is_iso_video or is_webm or is_image or is_document):
            raise HTTPException(415, "Attachment signature does not match the declared type")
        asset_id = secrets.token_hex(16)
        directory = settings.upload_dir / company_id / employee_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{asset_id}{suffix}"
        temporary_path = directory / f".{asset_id}.upload"
        size_bytes = 0
        digest = hashlib.sha256()
        try:
            with temporary_path.open("xb") as stream:
                chunk = first_chunk
                while chunk:
                    size_bytes += len(chunk)
                    if size_bytes > settings.upload_max_bytes:
                        resource = (
                            "Video" if request.url.path.endswith("/video-assets") else "Attachment"
                        )
                        raise HTTPException(413, f"{resource} exceeds the upload size limit")
                    if size_bytes > settings.native_video_max_bytes:
                        resource = (
                            "Video" if request.url.path.endswith("/video-assets") else "Attachment"
                        )
                        raise HTTPException(413, f"{resource} exceeds the direct-send size limit")
                    digest.update(chunk)
                    stream.write(chunk)
                    chunk = await file.read(1024 * 1024)
            temporary_path.replace(path)
            asset = VideoAsset(
                id=asset_id,
                company_id=company_id,
                employee_id=employee_id,
                title=title,
                caption=caption,
                original_filename=original_filename,
                storage_path=str(path),
                content_type=content_type,
                size_bytes=size_bytes,
                sha256=digest.hexdigest(),
            )
            session.add(asset)
            audit(session, user, "video_asset.create", asset, company_id)
            session.commit()
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            raise
        return {
            "id": asset.id,
            "company_id": asset.company_id,
            "employee_id": asset.employee_id,
            "title": asset.title,
            "caption": asset.caption,
            "size_bytes": asset.size_bytes,
            "content_type": asset.content_type,
        }

    @router.get("/video-assets", tags=["video-assets"])
    def list_assets(
        company_id: str | None = None,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        scope = company_id or user.company_id
        if user.role != Role.SUPER_ADMIN and scope != user.company_id:
            raise HTTPException(403, "Cross-company access denied")
        query = select(VideoAsset)
        if scope:
            query = query.where(VideoAsset.company_id == scope)
        rows = session.scalars(query.order_by(desc(VideoAsset.created_at))).all()
        return [
            {
                "id": item.id,
                "company_id": item.company_id,
                "employee_id": item.employee_id,
                "title": item.title,
                "caption": item.caption,
                "size_bytes": item.size_bytes,
                "content_type": item.content_type,
                "created_at": item.created_at,
            }
            for item in rows
        ]

    @router.post("/video-assets/{asset_id}/download-link", tags=["video-assets"])
    def create_download_link(
        asset_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        asset = session.get(VideoAsset, asset_id)
        if asset is None:
            raise HTTPException(404, "Video asset not found")
        tenant(user, asset.company_id)
        token = download_signer.dumps({"asset_id": asset.id})
        return {
            "url": f"{settings.public_base_url}/api/v1/downloads/{token}",
            "expires_in_seconds": settings.download_ttl_seconds,
        }

    @router.get("/downloads/{token}", tags=["video-assets"])
    def secure_download(token: str, session: Session = Depends(get_session)):
        try:
            payload = download_signer.loads(token, max_age=settings.download_ttl_seconds)
        except SignatureExpired as exc:
            raise HTTPException(410, "Download link expired") from exc
        except BadSignature as exc:
            raise HTTPException(404, "Download link invalid") from exc
        asset = session.get(VideoAsset, str(payload.get("asset_id", "")))
        if asset is None:
            raise HTTPException(404, "Video asset not found")
        path = Path(asset.storage_path).resolve()
        if settings.upload_dir not in path.parents or not path.is_file():
            raise HTTPException(404, "Video file unavailable")
        return FileResponse(path, filename=asset.original_filename, media_type=asset.content_type)

    @router.post("/deliveries", status_code=201, tags=["deliveries"])
    def create_delivery(
        payload: DeliveryCreate,
        request: Request,
        session: Session = Depends(get_session),
        user: User = Depends(writable),
    ):
        tenant(user, payload.company_id)
        existing = session.scalar(
            select(Delivery).where(
                Delivery.company_id == payload.company_id,
                Delivery.idempotency_key == payload.idempotency_key,
            )
        )
        if existing:
            from fastapi.responses import JSONResponse

            if (
                existing.status == DeliveryStatus.PENDING
                and existing.dispatch_token is None
            ):
                dispatch_delivery(session, existing)
                audit_delivery_failure(session, user, existing)
                audit(
                    session,
                    user,
                    "delivery.idempotent_recovery",
                    existing,
                    existing.company_id,
                    {"status": existing.status.value},
                )
                session.commit()
                cleanup_consumed_video_file(session, existing)
            return JSONResponse(jsonable_encoder(delivery_json(existing)), status_code=200)
        employee = session.get(Employee, payload.employee_id)
        asset = session.get(VideoAsset, payload.video_asset_id) if payload.video_asset_id else None
        if (
            employee is None
            or employee.company_id != payload.company_id
            or (
                payload.video_asset_id is not None
                and (
                    asset is None
                    or asset.company_id != payload.company_id
                    or asset.employee_id != employee.id
                )
            )
        ):
            raise HTTPException(404, "Employee or video asset not found")
        if asset is not None and asset.size_bytes > settings.native_video_max_bytes:
            raise HTTPException(409, "Video cannot be sent directly")
        if asset is not None and asset.consumed_at is not None:
            raise HTTPException(409, "Video is no longer available")
        if asset is not None and asset.claimed_delivery_id is not None:
            raise HTTPException(409, "Video is already assigned to a delivery")
        if asset is not None and available_video_path(asset) is None:
            raise HTTPException(409, "Video is no longer available")
        if employee.status != EmployeeStatus.ACTIVE:
            audit(
                session,
                user,
                "delivery.rejected.employee_inactive",
                employee,
                employee.company_id,
                {"employee_status": employee.status.value},
            )
            session.commit()
            raise HTTPException(409, "Employee is not eligible for delivery")
        bot_binding = active_bot_binding(session, employee.id)
        legacy_binding = active_legacy_binding(session, employee.id)
        if bot_binding is None and legacy_binding is None:
            audit(
                session,
                user,
                "delivery.rejected.unbound",
                employee,
                employee.company_id,
            )
            session.commit()
            raise HTTPException(409, "Employee has no active Weixin notification binding")
        values = payload.model_dump()
        if bot_binding is not None:
            values["binding_id"] = bot_binding.id
        if asset is not None:
            values["title"] = payload.title or asset.title
            values["body"] = payload.body or asset.caption
        item = Delivery(**values)
        session.add(item)
        try:
            session.flush()
            if asset is not None:
                claimed = session.execute(
                    update(VideoAsset)
                    .where(
                        VideoAsset.id == asset.id,
                        VideoAsset.claimed_delivery_id.is_(None),
                        VideoAsset.consumed_at.is_(None),
                    )
                    .values(claimed_delivery_id=item.id)
                )
                if getattr(claimed, "rowcount", 0) != 1:
                    session.rollback()
                    concurrent = session.scalar(
                        select(Delivery).where(
                            Delivery.company_id == payload.company_id,
                            Delivery.idempotency_key == payload.idempotency_key,
                        )
                    )
                    if concurrent:
                        from fastapi.responses import JSONResponse

                        return JSONResponse(
                            jsonable_encoder(delivery_json(concurrent)), status_code=200
                        )
                    raise HTTPException(409, "Video is already assigned to a delivery")
            audit(
                session,
                user,
                "delivery.create",
                item,
                item.company_id,
                {"status": DeliveryStatus.PENDING.value},
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            concurrent = session.scalar(
                select(Delivery).where(
                    Delivery.company_id == payload.company_id,
                    Delivery.idempotency_key == payload.idempotency_key,
                )
            )
            if concurrent:
                from fastapi.responses import JSONResponse

                return JSONResponse(jsonable_encoder(delivery_json(concurrent)), status_code=200)
            raise HTTPException(409, "Delivery creation conflict") from None
        session.refresh(item)
        force_failure = (
            settings.environment == "test"
            and request.headers.get("X-Test-Force-Failure") == "true"
        )
        if force_failure:
            send_mock(session, item, True)
        else:
            dispatch_delivery(session, item)
        audit_delivery_failure(session, user, item)
        session.commit()
        cleanup_consumed_video_file(session, item)
        if item.status == DeliveryStatus.WAITING_INTERACTION:
            ready_binding = active_bot_binding(session, employee.id)
            ready_context = bool(
                ready_binding
                and ready_binding.context_token_encrypted
                and ready_binding.chat_id_encrypted
            )
            ready_legacy = active_legacy_binding(session, employee.id)
            if ready_context or (ready_legacy and ready_legacy.context_token_encrypted):
                dispatch_waiting_deliveries(session, employee.id)
                session.refresh(item)
        return delivery_json(item)

    @router.get("/deliveries", tags=["deliveries"])
    def list_deliveries(
        company_id: str | None = None,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        scope = company_id or user.company_id
        if user.role != Role.SUPER_ADMIN and scope != user.company_id:
            raise HTTPException(403, "Cross-company access denied")
        query = select(Delivery)
        if scope:
            query = query.where(Delivery.company_id == scope)
        return [
            delivery_json(x)
            for x in session.scalars(query.order_by(desc(Delivery.created_at))).all()
        ]

    @router.get("/deliveries/{delivery_id}", tags=["deliveries"])
    def get_delivery(
        delivery_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(current_user),
    ):
        item = session.get(Delivery, delivery_id)
        if item is None:
            raise HTTPException(404, "Delivery not found")
        tenant(user, item.company_id)
        return delivery_json(item)

    @router.post("/deliveries/{delivery_id}/retry", tags=["deliveries"])
    def retry(
        delivery_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        item = session.get(Delivery, delivery_id)
        if item is None:
            raise HTTPException(404, "Delivery not found")
        tenant(user, item.company_id)
        retryable_status = item.status in {
            DeliveryStatus.FAILED,
            DeliveryStatus.WAITING_INTERACTION,
        }
        lease_expires_at = item.dispatch_lease_expires_at
        if lease_expires_at is not None and lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        stale_inflight = item.status in {
            DeliveryStatus.SENDING,
            DeliveryStatus.RETRYING,
        } and (lease_expires_at is None or lease_expires_at <= utcnow())
        if not retryable_status and not stale_inflight:
            raise HTTPException(409, "Delivery is not retryable")
        if item.status == DeliveryStatus.FAILED and item.next_retry_at is not None:
            retry_at = item.next_retry_at
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            if retry_at > utcnow():
                raise HTTPException(409, "Delivery retry is not due yet")
        if item.video_asset_id is not None:
            asset = session.get(VideoAsset, item.video_asset_id)
            if asset is None or asset.claimed_delivery_id != item.id:
                raise HTTPException(409, "Video is assigned to another delivery")
        token = secrets.token_urlsafe(32)
        claimed = session.execute(
            update(Delivery)
            .where(
                Delivery.id == item.id,
                or_(
                    Delivery.status.in_(
                        {DeliveryStatus.FAILED, DeliveryStatus.WAITING_INTERACTION}
                    ),
                    and_(
                        Delivery.status.in_(
                            {DeliveryStatus.SENDING, DeliveryStatus.RETRYING}
                        ),
                        or_(
                            Delivery.dispatch_lease_expires_at.is_(None),
                            Delivery.dispatch_lease_expires_at <= utcnow(),
                        ),
                    ),
                ),
            )
            .values(
                status=DeliveryStatus.RETRYING,
                retry_count=Delivery.retry_count + 1,
                failure_code=None,
                failure_message=None,
                next_retry_at=None,
                dispatch_token=token,
                dispatch_lease_expires_at=dispatch_lease_deadline(),
            )
            .execution_options(synchronize_session=False)
        )
        session.commit()
        if getattr(claimed, "rowcount", 0) != 1:
            raise HTTPException(409, "Delivery is already being retried")
        session.refresh(item)
        dispatch_delivery(session, item)
        audit_delivery_failure(session, user, item)
        audit(session, user, "delivery.retry", item, item.company_id)
        session.commit()
        cleanup_consumed_video_file(session, item)
        return delivery_json(item)

    @router.post("/deliveries/{delivery_id}/cancel", tags=["deliveries"])
    def cancel(
        delivery_id: str,
        session: Session = Depends(get_session),
        user: User = Depends(platform_writable),
    ):
        item = session.get(Delivery, delivery_id)
        if item is None:
            raise HTTPException(404, "Delivery not found")
        tenant(user, item.company_id)
        if item.status in {
            DeliveryStatus.CONFIRMED,
            DeliveryStatus.SENDING,
            DeliveryStatus.RETRYING,
        }:
            raise HTTPException(409, "Confirmed or in-progress delivery cannot be cancelled")
        cancelled = session.execute(
            update(Delivery)
            .where(Delivery.id == item.id, Delivery.status == item.status)
            .values(
                status=DeliveryStatus.CANCELLED,
                dispatch_token=None,
                dispatch_lease_expires_at=None,
            )
        )
        if getattr(cancelled, "rowcount", 0) != 1:
            session.rollback()
            raise HTTPException(409, "Delivery state changed; cancellation rejected")
        session.refresh(item)
        audit(session, user, "delivery.cancel", item, item.company_id)
        session.commit()
        return delivery_json(item)

    @router.post("/bot/inbound", tags=["bot"])
    def bot_inbound(
        payload: BotInbound,
        x_bot_secret: str = Header(default=""),
        session: Session = Depends(get_session),
    ):
        if not hmac.compare_digest(x_bot_secret, settings.bot_webhook_secret):
            raise HTTPException(401, "Invalid bot secret")
        text = re.sub(r"\s+", " ", payload.text.strip())
        bot_account = session.scalar(
            select(WeixinBotAccount).where(
                WeixinBotAccount.account_fingerprint == fingerprint(payload.account_id)
            )
        )
        if bot_account is not None:
            assignment = session.scalar(
                select(EmployeeBotBinding).where(
                    EmployeeBotBinding.bot_account_id == bot_account.id,
                    EmployeeBotBinding.active.is_(True),
                )
            )
            expected_owner = cipher.decrypt(bot_account.owner_user_id_encrypted.encode()).decode()
            if assignment is None or not hmac.compare_digest(expected_owner, payload.user_id):
                raise HTTPException(403, "Weixin Bot is not assigned to this identity")
            employee = session.get(Employee, assignment.employee_id)
            if employee is None or employee.status != EmployeeStatus.ACTIVE:
                raise HTTPException(409, "Employee is not eligible for Bot commands")
            first_interaction = assignment.context_token_encrypted is None
            allowed = {
                "今日视频",
                "查看文案",
                "重新下载",
                "换一个标题",
                "视频不合适",
                "已收到",
                "已发布",
                "退订",
                "帮助",
            }
            command = text if text in allowed else "帮助"
            if command == "已收到":
                delivery = session.scalar(
                    select(Delivery)
                    .where(
                        Delivery.employee_id == assignment.employee_id,
                        Delivery.binding_id == assignment.id,
                        Delivery.status == DeliveryStatus.SENT,
                    )
                    .order_by(desc(Delivery.created_at))
                )
                if delivery:
                    delivery.status = DeliveryStatus.CONFIRMED
                    delivery.confirmed_at = utcnow()
            binding_values: dict[str, Any] = {"last_health_at": utcnow()}
            if command == "退订":
                binding_values.update(
                    active=False,
                    revoked_at=utcnow(),
                    context_token_encrypted=None,
                    chat_id_encrypted=None,
                )
            elif payload.context_token:
                binding_values.update(
                    context_token_encrypted=enc(payload.context_token),
                    chat_id_encrypted=enc(payload.chat_id),
                )
            claimed_binding = session.execute(
                update(EmployeeBotBinding)
                .where(
                    EmployeeBotBinding.id == assignment.id,
                    EmployeeBotBinding.active.is_(True),
                )
                .values(**binding_values)
            )
            if getattr(claimed_binding, "rowcount", 0) != 1:
                session.rollback()
                raise HTTPException(409, "Weixin Bot binding changed; retry the command")
            session.refresh(assignment)
            bot_account.health_status = BotHealthStatus.HEALTHY
            bot_account.last_health_at = utcnow()
            audit(session, None, f"bot.{command}", assignment, assignment.company_id)
            session.commit()
            if (
                assignment.active
                and assignment.context_token_encrypted
                and assignment.chat_id_encrypted
            ):
                dispatch_waiting_deliveries(session, assignment.employee_id)
            message = (
                "通知通道已激活。后续文字通知和可选视频附件会通过这里发送。"
                if assignment.active and first_interaction and payload.context_token
                else "指令已处理"
            )
            return {"command": command, "message": message}
        if text.startswith("绑定 "):
            code = text.split(" ", 1)[1].strip().upper()
            record = session.scalar(
                select(BindingCode).where(BindingCode.code_hash == fingerprint(code))
            )
            if record is None or record.used_at is not None:
                raise HTTPException(409, "Binding code invalid or already used")
            expires = (
                record.expires_at
                if record.expires_at.tzinfo
                else record.expires_at.replace(tzinfo=UTC)
            )
            if expires <= utcnow():
                raise HTTPException(410, "Binding code expired")
            employee = session.get(Employee, record.employee_id)
            if employee is None or employee.status != EmployeeStatus.ACTIVE:
                raise HTTPException(409, "Employee unavailable")
            collision = session.scalar(
                select(WeixinBinding).where(
                    WeixinBinding.user_fingerprint == fingerprint(payload.user_id),
                    WeixinBinding.active.is_(True),
                )
            )
            if collision is not None:
                raise HTTPException(409, "Weixin account already bound")
            created_binding = WeixinBinding(
                company_id=record.company_id,
                employee_id=record.employee_id,
                account_id_encrypted=enc(payload.account_id),
                user_id_encrypted=enc(payload.user_id),
                chat_id_encrypted=enc(payload.chat_id),
                context_token_encrypted=enc(payload.context_token)
                if payload.context_token
                else None,
                user_fingerprint=fingerprint(payload.user_id),
                user_id_masked=mask(payload.user_id),
                chat_id_masked=mask(payload.chat_id),
                last_interaction_at=utcnow(),
            )
            record.used_at = utcnow()
            session.add(created_binding)
            audit(
                session,
                None,
                "binding.confirm",
                created_binding,
                created_binding.company_id,
            )
            session.commit()
            return {"command": "bind", "message": "绑定成功"}
        binding = session.scalar(
            select(WeixinBinding).where(
                WeixinBinding.user_fingerprint == fingerprint(payload.user_id),
                WeixinBinding.active.is_(True),
            )
        )
        if binding is None:
            raise HTTPException(403, "Weixin account is not bound")
        binding.context_token_encrypted = (
            enc(payload.context_token) if payload.context_token else binding.context_token_encrypted
        )
        binding.last_interaction_at = utcnow()
        allowed = {
            "今日视频",
            "查看文案",
            "重新下载",
            "换一个标题",
            "视频不合适",
            "已收到",
            "已发布",
            "退订",
            "帮助",
        }
        if text not in allowed:
            text = "帮助"
        # Legacy WeixinBinding deliveries do not carry an immutable binding
        # version, so inbound confirmations must fail closed.
        if text == "退订":
            binding.active = False
            binding.revoked_at = utcnow()
            binding.context_token_encrypted = None
        if binding.active and binding.context_token_encrypted:
            waiting = session.scalars(
                select(Delivery).where(
                    Delivery.employee_id == binding.employee_id,
                    Delivery.status == DeliveryStatus.WAITING_INTERACTION,
                )
            ).all()
            for item in waiting:
                dispatch_delivery(session, item)
                audit_delivery_failure(session, None, item)
        audit(session, None, f"bot.{text}", binding, binding.company_id)
        session.commit()
        return {"command": text, "message": "指令已处理"}

    @router.get("/bot/health", tags=["bot"])
    def bot_health(
        session: Session = Depends(get_session), _user: User = Depends(platform_user)
    ):
        active_count = session.scalar(
            select(func.count(EmployeeBotBinding.id)).where(
                EmployeeBotBinding.active.is_(True)
            )
        )
        return {
            "mode": settings.delivery_mode,
            "configured": bool(active_count),
            "active_bot_count": int(active_count or 0),
            "safe_to_send": settings.delivery_mode == "weixin" and bool(active_count),
        }

    @router.get("/audit-logs", tags=["audit"])
    def logs(
        company_id: str | None = None,
        session: Session = Depends(get_session),
        user: User = Depends(platform_user),
    ):
        scope = company_id or user.company_id
        if user.role != Role.SUPER_ADMIN and scope != user.company_id:
            raise HTTPException(403, "Cross-company access denied")
        query = select(AuditLog)
        if scope:
            query = query.where(AuditLog.company_id == scope)
        rows = session.scalars(query.order_by(desc(AuditLog.created_at)).limit(200)).all()
        return [
            {
                "id": x.id,
                "company_id": x.company_id,
                "action": x.action,
                "target_type": x.target_type,
                "target_id": x.target_id,
                "created_at": x.created_at,
            }
            for x in rows
        ]

    return router
