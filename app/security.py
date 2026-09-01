from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, User

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return str(token)


def current_user(request: Request, session: Session = Depends()) -> User:
    user_id = request.session.get("user_id")
    user = session.scalar(select(User).where(User.id == user_id, User.enabled.is_(True)))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return user


def require_write(user: User) -> None:
    if user.role == Role.VIEWER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only role")


def authorize_company(user: User, company_id: str) -> None:
    if user.role != Role.SUPER_ADMIN and user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cross-company access denied"
        )
