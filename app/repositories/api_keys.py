from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ApiAccessKeyRepository:
    """Persistence for domain-bound API access keys.

    A row binds one (user, module) pair to a verified site URL. Verification
    proves the applicant actually controls that domain, by publishing a token
    either as a DNS TXT record or as a file on the site.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, key_id: int) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT id, user_uid, module_slug, key_prefix, key_hash, status,
                       email, site_url, verification_token_hash,
                       verification_expires_at, verified_at, last_used_at,
                       rate_limit_override, expires_at, created_at, updated_at
                FROM api_access_keys
                WHERE id = :key_id
                LIMIT 1
                """
            ),
            {"key_id": key_id},
        ).mappings().first()
        return dict(row) if row else None

    def get_by_user_module(self, user_uid: int, module_slug: str) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT id, user_uid, module_slug, key_prefix, key_hash, status,
                       email, site_url, verification_token_hash,
                       verification_expires_at, verified_at, last_used_at,
                       rate_limit_override, expires_at, created_at, updated_at
                FROM api_access_keys
                WHERE user_uid = :user_uid AND module_slug = :module_slug
                LIMIT 1
                """
            ),
            {"user_uid": user_uid, "module_slug": module_slug},
        ).mappings().first()
        return dict(row) if row else None

    def get_by_key_hash(self, key_hash: str) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT id, user_uid, module_slug, key_prefix, key_hash, status,
                       email, site_url, verification_token_hash,
                       verification_expires_at, verified_at, last_used_at,
                       rate_limit_override, expires_at, created_at, updated_at
                FROM api_access_keys
                WHERE key_hash = :key_hash
                LIMIT 1
                """
            ),
            {"key_hash": key_hash},
        ).mappings().first()
        return dict(row) if row else None

    def list_all(
        self,
        *,
        user_uid: Optional[int] = None,
        module_slug: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if user_uid is not None:
            clauses.append("user_uid = :user_uid")
            params["user_uid"] = user_uid
        if module_slug:
            clauses.append("module_slug = :module_slug")
            params["module_slug"] = module_slug
        if status:
            clauses.append("status = :status")
            params["status"] = status
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.execute(
            text(
                f"""
                SELECT id, user_uid, module_slug, key_prefix, status, email,
                       site_url, verification_expires_at, verified_at,
                       last_used_at, rate_limit_override, expires_at,
                       created_at, updated_at
                FROM api_access_keys
                {where}
                ORDER BY id DESC
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def upsert_pending(
        self,
        *,
        user_uid: int,
        module_slug: str,
        email: str,
        site_url: str,
        key_prefix: str,
        key_hash: str,
        verification_token_hash: str,
        verification_ttl_seconds: int = 72 * 3600,
    ) -> dict:
        """Create or refresh the pending registration for (user, module).

        Re-registering the same pair overwrites the challenge instead of
        accumulating rows, which keeps the unique (user_uid, module_slug)
        invariant intact.
        """
        self.db.execute(
            text(
                """
                INSERT INTO api_access_keys
                  (user_uid, module_slug, key_prefix, key_hash, status, email,
                   site_url, verification_token_hash, verification_expires_at,
                   verified_at, created_at, updated_at)
                VALUES
                  (:user_uid, :module_slug, :key_prefix, :key_hash, 'pending', :email,
                   :site_url, :verification_token_hash, :verification_expires_at,
                   NULL, NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                  key_prefix = :key_prefix,
                  key_hash = :key_hash,
                  status = 'pending',
                  email = :email,
                  site_url = :site_url,
                  verification_token_hash = :verification_token_hash,
                  verification_expires_at = :verification_expires_at,
                  verified_at = NULL,
                  updated_at = NOW()
                """
            ),
            {
                "user_uid": user_uid,
                "module_slug": module_slug,
                "key_prefix": key_prefix,
                "key_hash": key_hash,
                "email": email,
                "site_url": site_url,
                "verification_token_hash": verification_token_hash,
                "verification_expires_at": _utcnow() + timedelta(seconds=verification_ttl_seconds),
            },
        )
        self.db.commit()
        return self.get_by_user_module(user_uid, module_slug) or {}

    def mark_verified(self, key_id: int) -> bool:
        """Activate a pending key. Conditional so a double-submit cannot race."""
        result = self.db.execute(
            text(
                """
                UPDATE api_access_keys
                SET status = 'active',
                    verified_at = NOW(),
                    verification_token_hash = NULL,
                    verification_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = :key_id AND status = 'pending'
                """
            ),
            {"key_id": key_id},
        )
        self.db.commit()
        return bool(result.rowcount)

    def rotate_key(
        self,
        key_id: int,
        *,
        key_prefix: str,
        key_hash: str,
    ) -> bool:
        result = self.db.execute(
            text(
                """
                UPDATE api_access_keys
                SET key_prefix = :key_prefix, key_hash = :key_hash, updated_at = NOW()
                WHERE id = :key_id
                """
            ),
            {"key_id": key_id, "key_prefix": key_prefix, "key_hash": key_hash},
        )
        self.db.commit()
        return bool(result.rowcount)

    def update_settings(
        self,
        key_id: int,
        *,
        site_url: Optional[str] = None,
        email: Optional[str] = None,
        status: Optional[str] = None,
        rate_limit_override: Optional[int] = None,
        clear_rate_limit: bool = False,
        expires_at: Optional[datetime] = None,
        clear_expiry: bool = False,
    ) -> Optional[dict]:
        fields: list[str] = []
        params: dict[str, Any] = {"key_id": key_id}
        if site_url is not None:
            fields.append("site_url = :site_url")
            params["site_url"] = site_url
        if email is not None:
            fields.append("email = :email")
            params["email"] = email
        if status is not None:
            fields.append("status = :status")
            params["status"] = status
        if clear_rate_limit:
            fields.append("rate_limit_override = NULL")
        elif rate_limit_override is not None:
            fields.append("rate_limit_override = :rate_limit_override")
            params["rate_limit_override"] = rate_limit_override
        if clear_expiry:
            fields.append("expires_at = NULL")
        elif expires_at is not None:
            fields.append("expires_at = :expires_at")
            params["expires_at"] = expires_at
        if not fields:
            return self.get_by_id(key_id)
        fields.append("updated_at = NOW()")
        self.db.execute(
            text(f"UPDATE api_access_keys SET {', '.join(fields)} WHERE id = :key_id"),
            params,
        )
        self.db.commit()
        return self.get_by_id(key_id)

    def delete(self, key_id: int) -> bool:
        result = self.db.execute(
            text("DELETE FROM api_access_keys WHERE id = :key_id"),
            {"key_id": key_id},
        )
        self.db.commit()
        return bool(result.rowcount)

    def touch_last_used(self, key_id: int) -> None:
        self.db.execute(
            text("UPDATE api_access_keys SET last_used_at = NOW() WHERE id = :key_id"),
            {"key_id": key_id},
        )
        self.db.commit()
