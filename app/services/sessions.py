from fastapi import HTTPException
from sqlalchemy import text
from app.core.request_context import request_context
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.config import get_settings
from app.repositories.sessions import SessionRepository


class SessionService:
    def __init__(self, db):
        self.db = db
        self.repository = SessionRepository(db)

    def _candidate(self, user):
        meta = request_context.get()
        for key, kind in [("access_token", "access"), ("refresh_token", "refresh")]:
            token = meta.get(key)
            if not token:
                continue
            try:
                claims = decode_token(token, kind)
            except HTTPException:
                continue
            if claims["sub"] == str(user["uid"]):
                return claims
        return {}

    def issue(self, user, session_id=None, previous_version=None, new_session=False):
        from app.core.moderation import enforce
        enforce(user)
        uid, version = int(user["uid"]), int(user.get("session_version") or 0)
        # Serialize refresh/issue with revocation to avoid resurrecting a device.
        live_version = self.db.execute(text(
            "SELECT session_version FROM users WHERE uid=:uid FOR UPDATE"
        ), {"uid": uid}).scalar_one_or_none()
        if live_version is None or int(live_version or 0) != version:
            self.db.rollback()
            raise HTTPException(401, "session_revoked")
        candidate = {} if new_session else self._candidate(user)
        sid = session_id or candidate.get("sid")
        if sid:
            old_version = int(previous_version if previous_version is not None else (version if session_id else candidate.get("sv", version)))
            existing = self.repository.active(sid, uid, old_version, lock=True)
            if not existing:
                self.db.rollback()
                raise HTTPException(401, "session_revoked")
        sid = self.repository.save(uid, version, get_settings().refresh_token_days,
                                   request_context.get(), sid)
        access, expires = create_access_token(uid, user["role"], version, sid)
        refresh = create_refresh_token(uid, user["role"], version, sid)
        return access, refresh, expires
