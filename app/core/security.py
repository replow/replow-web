from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.repositories.users import UserRepository
from app.repositories.sessions import SessionRepository


settings = get_settings()
password_hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def _jwt_secret() -> str:
    if len(settings.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters")
    return settings.jwt_secret


def verify_password(password: str, encoded_hash: str) -> bool:
    if not password or not encoded_hash or encoded_hash == "!password-unset!":
        return False
    if not encoded_hash.startswith("$argon2"):
        return False
    try:
        return password_hasher.verify(encoded_hash, password)
    except (InvalidHash, VerificationError, VerifyMismatchError):
        return False


def _create_token(
    subject: str,
    role: str,
    kind: str,
    expires_delta: timedelta,
    session_version: Optional[int] = None,
    session_id: Optional[str] = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "kind": kind,
        "iat": now,
        "exp": now + expires_delta,
    }
    if session_version is not None:
        payload["sv"] = int(session_version)
    if session_id:
        payload["sid"] = session_id
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def create_access_token(
    user_id: int, role: str, session_version: int = 0, session_id: Optional[str] = None
) -> tuple[str, datetime]:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return (
        _create_token(
            str(user_id),
            role,
            "access",
            timedelta(minutes=settings.access_token_minutes),
            session_version,
            session_id,
        ),
        expires,
    )


def create_refresh_token(user_id: int, role: str, session_version: int = 0, session_id: Optional[str] = None) -> str:
    return _create_token(
        str(user_id),
        role,
        "refresh",
        timedelta(days=settings.refresh_token_days),
        session_version,
        session_id,
    )


def create_signup_token(user_id: int) -> str:
    return _create_token(str(user_id), "user", "signup", timedelta(minutes=20))


def create_password_reset_token(user_id: int) -> str:
    return _create_token(str(user_id), "user", "password_reset", timedelta(minutes=20))


def decode_token(token: str, expected_kind: str = "access") -> dict[str, Any]:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token") from error
    if payload.get("kind") != expected_kind or not str(payload.get("sub", "")).isdigit():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    return payload


def current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    payload = decode_token(credentials.credentials)
    user = UserRepository(db).get_by_id(int(payload["sub"]))
    if not user or user["status"] != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account_unavailable")
    from app.core.moderation import enforce
    enforce(user)
    token_version = int(payload.get("sv") or 0)
    if token_version != int(user.get("session_version") or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_revoked")
    sid = payload.get("sid")
    if sid:
        sessions = SessionRepository(db)
        if not sessions.active(sid, int(user["uid"]), int(user.get("session_version") or 0)):
            raise HTTPException(status_code=401, detail="session_revoked")
        sessions.touch(sid)
    user["_session_id"] = sid
    request.state.audit_actor = {"uid": str(user["uid"]), "username": user["username"],
                                 "display_name": user.get("display_name") or user["username"], "email": user["email"]}
    return user


def require_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")
    return user
