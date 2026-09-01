from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    COMPANY_ADMIN = "company_admin"
    VIEWER = "viewer"


class EmployeeStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DEPARTED = "departed"
    DELETED = "deleted"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    RETRYING = "retrying"
    WAITING_INTERACTION = "waiting_interaction"
    CANCELLED = "cancelled"
    SIMULATED = "simulated"


class NotificationType(StrEnum):
    BUSINESS = "business"
    BINDING_WELCOME = "binding_welcome"
    MANUAL_TEST = "manual_test"


class BindingSessionStatus(StrEnum):
    PENDING = "pending"
    SCANNED = "scanned"
    CONFIRMING = "confirming"
    BOUND = "bound"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REVOKED = "revoked"


class BotHealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    REVOKED = "revoked"


class TargetMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"
    DYNAMIC_ALL = "dynamic_all"


class BatchStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SIMULATED = "simulated"


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False)
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str] = mapped_column(String(120), default="")
    content_vertical: Mapped[str] = mapped_column(String(160), default="")
    secondary_topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    account_name: Mapped[str] = mapped_column(String(160), default="")
    phone_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phone_masked: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tone: Mapped[str] = mapped_column(String(160), default="")
    video_duration_seconds: Mapped[int] = mapped_column(Integer, default=60)
    publishing_frequency: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[EmployeeStatus] = mapped_column(
        Enum(EmployeeStatus), default=EmployeeStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BindingCode(Base):
    __tablename__ = "binding_codes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WeixinBinding(Base):
    __tablename__ = "weixin_bindings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    account_id_encrypted: Mapped[str] = mapped_column(Text)
    user_id_encrypted: Mapped[str] = mapped_column(Text)
    chat_id_encrypted: Mapped[str] = mapped_column(Text)
    context_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    user_id_masked: Mapped[str] = mapped_column(String(40))
    chat_id_masked: Mapped[str] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WeixinBotAccount(Base):
    """One independent iLink bot identity returned by an official QR login."""

    __tablename__ = "weixin_bot_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )
    account_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    account_id_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    bot_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    base_url_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    account_id_masked: Mapped[str] = mapped_column(String(40), nullable=False)
    health_status: Mapped[BotHealthStatus] = mapped_column(
        Enum(BotHealthStatus), nullable=False, default=BotHealthStatus.UNKNOWN
    )
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EmployeeBotBinding(Base):
    __tablename__ = "employee_bot_bindings"
    __table_args__ = (
        Index(
            "uq_employee_bot_bindings_active_employee",
            "employee_id",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
        Index(
            "uq_employee_bot_bindings_active_account",
            "bot_account_id",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    bot_account_id: Mapped[str] = mapped_column(
        ForeignKey("weixin_bot_accounts.id"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    context_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    chat_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_manual_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NotificationTarget(Base):
    __tablename__ = "notification_targets"
    __table_args__ = (
        UniqueConstraint("company_id", "target_code", name="uq_target_company_code"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    target_code: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    mode: Mapped[TargetMode] = mapped_column(Enum(TargetMode), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    is_user_object: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0"), index=True
    )
    employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TargetBotMember(Base):
    __tablename__ = "target_bot_members"
    __table_args__ = (
        Index(
            "uq_target_bot_members_active_binding",
            "target_id",
            "binding_id",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(
        ForeignKey("notification_targets.id"), nullable=False, index=True
    )
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("employee_bot_bindings.id"), nullable=False, index=True
    )
    bot_account_id: Mapped[str] = mapped_column(
        ForeignKey("weixin_bot_accounts.id"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserObjectContact(Base):
    __tablename__ = "user_object_contacts"
    __table_args__ = (
        Index(
            "uq_user_object_contacts_active_employee",
            "target_id",
            "employee_id",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("notification_targets.id"), nullable=False, index=True
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiClient(Base):
    __tablename__ = "api_clients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_target_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationBatch(Base):
    __tablename__ = "notification_batches"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "target_id", "idempotency_key", name="uq_batch_target_key"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(
        ForeignKey("notification_targets.id"), nullable=False, index=True
    )
    api_client_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_clients.id"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notification_type: Mapped[str] = mapped_column(String(40), nullable=False, default="business")
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus), nullable=False, default=BatchStatus.PENDING, index=True
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WeixinBindingSession(Base):
    __tablename__ = "weixin_binding_sessions"
    __table_args__ = (
        Index(
            "uq_weixin_binding_sessions_live_employee",
            "employee_id",
            unique=True,
            sqlite_where=text("status IN ('PENDING', 'SCANNED', 'CONFIRMING')"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    status: Mapped[BindingSessionStatus] = mapped_column(
        Enum(BindingSessionStatus), nullable=False, default=BindingSessionStatus.PENDING, index=True
    )
    official_ticket_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    scan_data_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    base_url_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    current_base_url_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class VideoAsset(Base):
    __tablename__ = "video_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    title: Mapped[str] = mapped_column(String(240), default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    claimed_delivery_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, unique=True, index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    file_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_delivery_tenant_key"),
        Index(
            "uq_deliveries_binding_welcome",
            "binding_id",
            unique=True,
            sqlite_where=text("notification_type = 'binding_welcome'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("notification_batches.id"), nullable=True, index=True
    )
    target_id: Mapped[str | None] = mapped_column(
        ForeignKey("notification_targets.id"), nullable=True, index=True
    )
    target_member_id: Mapped[str | None] = mapped_column(
        ForeignKey("target_bot_members.id"), nullable=True, index=True
    )
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    video_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_assets.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notification_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default=NotificationType.BUSINESS.value, index=True
    )
    binding_id: Mapped[str | None] = mapped_column(
        ForeignKey("employee_bot_bindings.id"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus), default=DeliveryStatus.PENDING
    )
    external_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatch_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    dispatch_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    text_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    media_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str] = mapped_column(String(120))
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
