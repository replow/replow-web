from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.repositories.users import UserRepository


class AuthService:
    """Authentication use cases backed by the MySQL user repository."""

    def __init__(self, db: Session):
        self.repository = UserRepository(db)

    def authenticate(self, identity: str, password: str) -> Optional[dict[str, Any]]:
        user = self.repository.find_by_identity(identity)
        if (
            not user
            or not verify_password(password, str(user.get("password_hash") or ""))
        ):
            return None
        from app.core.moderation import enforce
        enforce(user)
        if user.get("status") != "active":
            return None
        self.repository.mark_login(int(user["uid"]))
        return user

    def issue_tokens(self, user, session_id=None, new_session=False):
        from app.services.sessions import SessionService
        return SessionService(self.repository.db).issue(user, session_id, new_session=new_session)

    def refresh(self, token: str) -> tuple[dict[str, Any], str, str, Any]:
        """Rotate one session forward without shortening its lifetime.

        Returns (user, access_token, refresh_token, expires). The refresh token
        is re-issued so an active browser keeps its full window instead of being
        logged out the moment the original token ages out.
        """
        claims = decode_token(token, expected_kind="refresh")
        user = self.repository.get_by_id(int(claims["sub"]))
        if not user or user.get("status") != "active":
            return {}, "", "", None
        from app.core.moderation import enforce
        enforce(user)
        session_version = int(user.get("session_version") or 0)
        if int(claims.get("sv") or 0) != session_version:
            return {}, "", "", None
        sid = claims.get("sid")
        if sid:
            from app.repositories.sessions import SessionRepository
            if not SessionRepository(self.repository.db).active(sid, int(user["uid"]), session_version):
                return {}, "", "", None
        access_token, refresh_token, expires = self.issue_tokens(user, session_id=sid)
        return user, access_token, refresh_token, expires
