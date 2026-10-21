from datetime import datetime, timedelta
import secrets
from sqlalchemy import text


class SessionRepository:
    def __init__(self, db):
        self.db = db

    def active(self, sid, uid, version, lock=False):
        row = self.db.execute(text(
            "SELECT * FROM auth_sessions WHERE id=:sid AND user_uid=:uid "
            "AND session_version=:version AND revoked_at IS NULL "
            "AND expires_at > :now" + (" FOR UPDATE" if lock else "")
        ), {"sid": sid, "uid": uid, "version": version, "now": datetime.utcnow()}).mappings().first()
        return dict(row) if row else None

    def touch(self, sid):
        now = datetime.utcnow()
        result = self.db.execute(text(
            "UPDATE auth_sessions SET last_seen_at=:now WHERE id=:sid "
            "AND last_seen_at < :threshold"
        ), {"sid": sid, "now": now, "threshold": now - timedelta(minutes=1)})
        if result.rowcount:
            self.db.commit()

    def save(self, uid, version, days, metadata, sid=None):
        now = datetime.utcnow()
        expires = now + timedelta(days=days)
        params = {"sid": sid or secrets.token_hex(16), "uid": int(uid), "version": version,
                  "ua": str(metadata.get("user_agent") or "")[:512],
                  "ip": str(metadata.get("ip") or "")[:45], "now": now, "expires": expires}
        if sid:
            self.db.execute(text(
                "UPDATE auth_sessions SET session_version=:version, last_seen_at=:now, "
                "expires_at=:expires WHERE id=:sid AND user_uid=:uid AND revoked_at IS NULL"
            ), params)
        else:
            self.db.execute(text(
                "INSERT INTO auth_sessions (id,user_uid,session_version,user_agent,ip_address,"
                "created_at,last_seen_at,expires_at) "
                "VALUES (:sid,:uid,:version,:ua,:ip,:now,:now,:expires)"
            ), params)
        self.db.commit()
        return params["sid"]

    def list_active(self, uid, version):
        rows = self.db.execute(text(
            "SELECT id,user_agent,ip_address,created_at,last_seen_at,expires_at FROM auth_sessions "
            "WHERE user_uid=:uid AND session_version=:version AND revoked_at IS NULL "
            "AND expires_at>:now ORDER BY last_seen_at DESC LIMIT 100"
        ), {"uid": uid, "version": version, "now": datetime.utcnow()}).mappings()
        return [dict(row) for row in rows]

    def revoke(self, uid, sid):
        result = self.db.execute(text(
            "UPDATE auth_sessions SET revoked_at=:now WHERE id=:sid AND user_uid=:uid "
            "AND revoked_at IS NULL"
        ), {"uid": uid, "sid": sid, "now": datetime.utcnow()})
        self.db.commit()
        return result.rowcount > 0

    def revoke_others(self, uid, sid, version):
        current = self.db.execute(text(
            "SELECT session_version FROM users WHERE uid=:uid FOR UPDATE"
        ), {"uid": uid}).scalar_one()
        if int(current or 0) != version or not self.active(sid, uid, version, lock=True):
            self.db.rollback()
            return None
        version += 1
        self.db.execute(text("UPDATE users SET session_version=:version WHERE uid=:uid"),
                        {"uid": uid, "version": version})
        self.db.execute(text(
            "UPDATE auth_sessions SET revoked_at=:now WHERE user_uid=:uid AND id<>:sid "
            "AND revoked_at IS NULL"
        ), {"uid": uid, "sid": sid, "now": datetime.utcnow()})
        self.db.execute(text("UPDATE auth_sessions SET session_version=:version WHERE id=:sid"),
                        {"sid": sid, "version": version})
        self.db.commit()
        return version
