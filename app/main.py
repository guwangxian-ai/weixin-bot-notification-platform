from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app.api import build_router
from app.config import Settings
from app.database import Base, create_database
from app.models import Company, Role, User
from app.security import hash_password, verify_password


class LoginRequest(BaseModel):
    username: str
    password: str


def create_app() -> FastAPI:
    settings = Settings.from_env()
    settings.validate()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    engine, factory = create_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        Base.metadata.create_all(engine)
        _bootstrap(factory, settings)
        yield
        engine.dispose()

    app = FastAPI(
        title="Weixin Bot Notification System API",
        version="0.2.0",
        description="通用多公司个人微信 Bot 通知平台 · 由猫王AI开发",
        contact={"name": "猫王AI", "url": "https://github.com/guwangxian-ai"},
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/license/mit",
        },
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        servers=[{"url": settings.base_path}],
    )
    app.state.settings = settings
    app.state.session_factory = factory

    @app.middleware("http")
    async def reject_oversized_upload_request(request: Request, call_next):
        if request.method == "POST" and request.url.path in {
            "/api/v1/video-assets",
            "/api/v1/media-assets",
        }:
            content_length = request.headers.get("content-length")
            if content_length is None:
                return JSONResponse({"detail": "Content-Length is required"}, status_code=411)
            try:
                request_bytes = int(content_length)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
            multipart_overhead_allowance = 1024 * 1024
            if request_bytes > settings.upload_max_bytes + multipart_overhead_allowance:
                resource = "Video" if request.url.path.endswith("/video-assets") else "Attachment"
                return JSONResponse(
                    {"detail": f"{resource} exceeds the upload size limit"}, status_code=413
                )
        return await call_next(request)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="evnc_session",
        same_site="strict",
        https_only=settings.environment == "production",
        max_age=28800,
    )

    def get_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    def get_user(request: Request, session: Session = Depends(get_session)) -> User:
        user_id = request.session.get("user_id")
        user = session.scalar(select(User).where(User.id == user_id, User.enabled.is_(True)))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
            )
        return user

    @app.get("/api/v1/health", tags=["system"])
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "delivery_mode": settings.delivery_mode,
            "bot_configured": bool(settings.weixin_account_id and settings.weixin_token),
        }

    @app.post("/api/v1/auth/login", tags=["auth"])
    def login(
        payload: LoginRequest, request: Request, session: Session = Depends(get_session)
    ) -> dict[str, str]:
        user = session.scalar(select(User).where(User.username == payload.username))
        if (
            user is None
            or not user.enabled
            or not verify_password(payload.password, user.password_hash)
        ):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        request.session.clear()
        request.session["user_id"] = user.id
        csrf = __import__("secrets").token_urlsafe(32)
        request.session["csrf_token"] = csrf
        return {"role": user.role.value, "company_id": user.company_id or "*", "csrf_token": csrf}

    @app.get("/api/v1/auth/session", tags=["auth"])
    def auth_session(request: Request, session: Session = Depends(get_session)) -> dict[str, str]:
        user_id = request.session.get("user_id")
        user = session.get(User, user_id) if user_id else None
        csrf = str(request.session.get("csrf_token") or "")
        if user is None or not user.enabled or not csrf:
            raise HTTPException(status_code=401, detail="Authentication required")
        return {
            "role": user.role.value,
            "company_id": user.company_id or "*",
            "csrf_token": csrf,
        }

    @app.post("/api/v1/auth/logout", tags=["auth"])
    def logout(request: Request) -> dict[str, bool]:
        expected = str(request.session.get("csrf_token") or "")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        request.session.clear()
        return {"ok": True}

    app.include_router(build_router(settings, factory))

    web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if web_dist.exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="web-assets")

        @app.get("/", include_in_schema=False)
        @app.get("/{ui_path:path}", include_in_schema=False)
        def web_ui(ui_path: str = "") -> FileResponse:
            del ui_path
            return FileResponse(web_dist / "index.html")

    return app


def _bootstrap(factory: sessionmaker[Session], settings: Settings) -> None:
    with factory.begin() as session:
        for company_id, name in (("greenhome", "绿色家装饰"), ("sanlin", "三林装饰")):
            if session.get(Company, company_id) is None:
                session.add(Company(id=company_id, slug=company_id, name=name))
        if settings.bootstrap_admin_password:
            existing = session.scalar(
                select(User).where(User.username == settings.bootstrap_admin_username)
            )
            if existing is None:
                session.add(
                    User(
                        username=settings.bootstrap_admin_username,
                        password_hash=hash_password(settings.bootstrap_admin_password),
                        role=Role.SUPER_ADMIN,
                    )
                )


app = create_app()
