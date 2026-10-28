from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def _allocate_uid(self, requested_uid: Optional[int] = None) -> int:
        """Reserve a UID in the same transaction as the user write.

        Lock the durable counter first for every automatic/manual UID change.
        A failed insert rolls the reservation back; deleted IDs are not reused.
        The current locking read also accounts for existing or imported UIDs.
        """
        last_uid = self.db.execute(
            text("SELECT last_uid FROM user_uid_sequences WHERE id = 1 FOR UPDATE")
        ).scalar_one()
        current_max = self.db.execute(
            text("SELECT uid FROM users ORDER BY uid DESC LIMIT 1 FOR UPDATE")
        ).scalar_one_or_none()
        high_water = max(9999, int(last_uid), int(current_max or 0))
        user_id = high_water + 1 if requested_uid is None else int(requested_uid)
        self.db.execute(
            text(
                "UPDATE user_uid_sequences SET last_uid = :last_uid WHERE id = 1"
            ),
            {"last_uid": max(high_water, user_id)},
        )
        return user_id

    def get_by_id(self, user_id: int) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT uid, username, email, password_hash, display_name, avatar_url,
                       bio, website_url, role, status, locked_until, last_login_at,
                       password_changed_at, session_version, setup_completed, ban_started_at, ban_until, ban_reason, mute_started_at, mute_until, mute_reason, publish_started_at, publish_until, publish_reason, created_at
                FROM users
                WHERE uid = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
        return dict(row) if row else None

    def find_by_identity(self, identity: str) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT uid, username, email, password_hash, display_name, avatar_url,
                       bio, website_url, role, status, locked_until, last_login_at,
                       password_changed_at, session_version, setup_completed, ban_started_at, ban_until, ban_reason, mute_started_at, mute_until, mute_reason, publish_started_at, publish_until, publish_reason, created_at
                FROM users
                WHERE LOWER(username) = LOWER(:identity)
                   OR LOWER(email) = LOWER(:identity)
                LIMIT 1
                """
            ),
            {"identity": identity.strip()},
        ).mappings().first()
        return dict(row) if row else None

    def find_by_email(self, email: str) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT uid, username, email, password_hash, display_name, avatar_url,
                       bio, website_url, role, status, locked_until, last_login_at,
                       password_changed_at, session_version, setup_completed, ban_started_at, ban_until, ban_reason, mute_started_at, mute_until, mute_reason, publish_started_at, publish_until, publish_reason, created_at
                FROM users
                WHERE LOWER(email) = LOWER(:email)
                LIMIT 1
                """
            ),
            {"email": email.strip().lower()},
        ).mappings().first()
        return dict(row) if row else None

    def username_exists(self, username: str) -> bool:
        return bool(
            self.db.execute(
                text("SELECT 1 FROM users WHERE LOWER(username) = LOWER(:username) LIMIT 1"),
                {"username": username.strip()},
            ).scalar()
        )

    def email_exists(self, email: str, exclude_user_id: Optional[int] = None) -> bool:
        params: dict[str, Any] = {"email": email.strip().lower()}
        exclusion = ""
        if exclude_user_id is not None:
            exclusion = " AND uid <> :exclude_user_id"
            params["exclude_user_id"] = exclude_user_id
        return bool(
            self.db.execute(
                text(f"SELECT 1 FROM users WHERE LOWER(email) = LOWER(:email){exclusion} LIMIT 1"),
                params,
            ).scalar()
        )

    def uid_exists(self, user_id: int, exclude_user_id: Optional[int] = None) -> bool:
        params: dict[str, Any] = {"user_id": user_id}
        exclusion = ""
        if exclude_user_id is not None:
            exclusion = " AND uid <> :exclude_user_id"
            params["exclude_user_id"] = exclude_user_id
        return bool(
            self.db.execute(
                text(f"SELECT 1 FROM users WHERE uid = :user_id{exclusion} LIMIT 1"),
                params,
            ).scalar()
        )

    def create_verified_user(
        self,
        *,
        username: str,
        email: str,
        display_name: str,
        setup_completed: bool = True,
    ) -> dict:
        user_id = self._allocate_uid()
        self.db.execute(
            text(
                """
                INSERT INTO users
                  (uid, username, email, password_hash, display_name, role, status,
                   password_changed_at, setup_completed, created_at, updated_at)
                VALUES
                  (:uid, :username, :email, '!password-unset!', :display_name,
                   'user', 'active', NOW(), :setup_completed, NOW(), NOW())
                """
            ),
            {
                "uid": user_id,
                "username": username.strip(),
                "email": email.strip().lower(),
                "display_name": display_name.strip() or username.strip(),
                "setup_completed": 1 if setup_completed else 0,
            },
        )
        self.db.commit()
        return self.get_by_id(user_id) or {}

    def update_password(self, user_id: int, password_hash: str) -> bool:
        result = self.db.execute(
            text(
                """
                UPDATE users
                SET password_hash = :password_hash,
                    password_changed_at = NOW(),
                    session_version = COALESCE(session_version, 0) + 1,
                    failed_attempts = 0,
                    locked_until = NULL,
                    updated_at = NOW()
                WHERE uid = :user_id AND status = 'active'
                """
            ),
            {"user_id": user_id, "password_hash": password_hash},
        )
        self.db.commit()
        return result.rowcount > 0

    def update_username(self, user_id: int, username: str) -> bool:
        """Rename a user. Usernames are unique case-insensitively."""
        result = self.db.execute(
            text(
                """
                UPDATE users
                SET username = :username, updated_at = NOW()
                WHERE uid = :user_id AND status = 'active'
                """
            ),
            {"user_id": user_id, "username": username.strip()},
        )
        self.db.commit()
        return result.rowcount > 0

    def update_display_name(self, user_id: int, display_name: str) -> bool:
        result = self.db.execute(
            text(
                """
                UPDATE users
                SET display_name = :display_name, updated_at = NOW()
                WHERE uid = :user_id AND status = 'active'
                """
            ),
            {"user_id": user_id, "display_name": display_name.strip()},
        )
        self.db.commit()
        return result.rowcount > 0

    def mark_setup_completed(self, user_id: int) -> bool:
        """Stop prompting the account-setup dialog for this user."""
        result = self.db.execute(
            text(
                """
                UPDATE users
                SET setup_completed = 1, updated_at = NOW()
                WHERE uid = :user_id AND status = 'active'
                """
            ),
            {"user_id": user_id},
        )
        self.db.commit()
        return result.rowcount > 0

    def mark_login(self, user_id: int) -> None:
        self.db.execute(
            text("UPDATE users SET last_login_at = NOW(), failed_attempts = 0 WHERE uid = :user_id"),
            {"user_id": user_id},
        )
        self.db.commit()

    def get_verification(self, email: str, purpose: str) -> Optional[dict[str, Any]]:
        row = self.db.execute(
            text(
                """
                SELECT id, email, username, purpose, code_hash, attempts, expires_at
                FROM email_verifications
                WHERE LOWER(email) = LOWER(:email) AND purpose = :purpose
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"email": email.strip().lower(), "purpose": purpose},
        ).mappings().first()
        return dict(row) if row else None

    def create_verification(
        self,
        *,
        email: str,
        username: str,
        purpose: str,
        code_hash: str,
        expires_at: datetime,
        requested_ip: Optional[str],
    ) -> None:
        self.db.execute(
            text(
                """
                DELETE FROM email_verifications
                WHERE LOWER(email) = LOWER(:email) AND purpose = :purpose
                """
            ),
            {"email": email.strip().lower(), "purpose": purpose},
        )
        self.db.execute(
            text(
                """
                INSERT INTO email_verifications
                  (email, username, purpose, code_hash, attempts, expires_at, requested_ip, created_at)
                VALUES
                  (:email, :username, :purpose, :code_hash, 0, :expires_at,
                   INET6_ATON(:requested_ip), NOW())
                """
            ),
            {
                "email": email.strip().lower(),
                "username": username.strip(),
                "purpose": purpose,
                "code_hash": code_hash,
                "expires_at": expires_at,
                "requested_ip": requested_ip,
            },
        )
        self.db.commit()

    def delete_verification(self, email: str, purpose: str) -> None:
        self.db.execute(
            text(
                "DELETE FROM email_verifications WHERE LOWER(email) = LOWER(:email) AND purpose = :purpose"
            ),
            {"email": email.strip().lower(), "purpose": purpose},
        )
        self.db.commit()

    def increment_verification_attempts(self, verification_id: int) -> None:
        self.db.execute(
            text(
                """
                UPDATE email_verifications
                SET attempts = attempts + 1
                WHERE id = :verification_id
                """
            ),
            {"verification_id": verification_id},
        )
        self.db.commit()

    def consume_verification(self, verification_id: int) -> bool:
        result = self.db.execute(
            text("DELETE FROM email_verifications WHERE id = :verification_id"),
            {"verification_id": verification_id},
        )
        self.db.commit()
        return result.rowcount > 0

    def check_rate_limit(self, action: str, identity_hash: str, *, limit: int, window_seconds: int) -> bool:
        """Increment a small DB-backed fixed-window limiter and return whether it is allowed."""
        row = self.db.execute(
            text(
                """
                SELECT id, window_started_at, hit_count
                FROM rate_limits
                WHERE action_name = :action AND identity_hash = :identity_hash
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"action": action, "identity_hash": identity_hash},
        ).mappings().first()

        now = datetime.utcnow()
        if not row:
            self.db.execute(
                text(
                    """
                    INSERT INTO rate_limits
                      (action_name, identity_hash, window_started_at, hit_count, updated_at)
                    VALUES (:action, :identity_hash, NOW(), 1, NOW())
                    """
                ),
                {"action": action, "identity_hash": identity_hash},
            )
            self.db.commit()
            return True

        started = row["window_started_at"]
        elapsed = (now - started).total_seconds() if isinstance(started, datetime) else window_seconds
        if elapsed >= window_seconds:
            self.db.execute(
                text(
                    """
                    UPDATE rate_limits
                    SET window_started_at = NOW(), hit_count = 1, blocked_until = NULL, updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"id": row["id"]},
            )
            self.db.commit()
            return True

        next_count = int(row["hit_count"] or 0) + 1
        self.db.execute(
            text(
                "UPDATE rate_limits SET hit_count = :hit_count, updated_at = NOW() WHERE id = :id"
            ),
            {"hit_count": next_count, "id": row["id"]},
        )
        self.db.commit()
        return next_count <= limit

    def create_password_reset_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
        requested_ip: Optional[str],
    ) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO password_reset_tokens
                  (user_id, token_hash, expires_at, used_at, requested_ip, created_at)
                VALUES (:user_id, :token_hash, :expires_at, NULL, INET6_ATON(:requested_ip), NOW())
                """
            ),
            {
                "user_id": user_id,
                "token_hash": token_hash,
                "expires_at": expires_at,
                "requested_ip": requested_ip,
            },
        )
        self.db.commit()

    def consume_password_reset_token(self, token_hash: str) -> Optional[int]:
        row = self.db.execute(
            text(
                """
                SELECT id, user_id
                FROM password_reset_tokens
                WHERE token_hash = :token_hash
                  AND used_at IS NULL
                  AND expires_at > NOW()
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"token_hash": token_hash},
        ).mappings().first()
        if not row:
            self.db.rollback()
            return None
        self.db.execute(
            text("UPDATE password_reset_tokens SET used_at = NOW() WHERE id = :id"),
            {"id": row["id"]},
        )
        self.db.commit()
        return int(row["user_id"])

    def list_users(self, limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        total = int(self.db.execute(text("SELECT COUNT(*) FROM users")).scalar_one())
        rows = self.db.execute(
            text(
                """
                SELECT uid, username, email, display_name, avatar_url, bio, website_url,
                       role, status, password_hash, ban_started_at, ban_until, ban_reason, mute_started_at, mute_until, mute_reason, publish_started_at, publish_until, publish_reason, last_login_at, created_at, updated_at
                FROM users
                ORDER BY uid ASC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        ).mappings().all()
        return [self._admin_row(dict(row)) for row in rows], total

    def create_admin_user(self, data: dict[str, Any]) -> dict:
        password_hash = str(data.get("password_hash") or "!password-unset!")
        user_id = self._allocate_uid(data.get("uid"))
        self.db.execute(
            text(
                """
                INSERT INTO users
                  (uid, username, email, password_hash, display_name, avatar_url,
                   bio, website_url, role, status, password_changed_at, created_at, updated_at)
                VALUES
                  (:uid, :username, :email, :password_hash, :display_name, :avatar_url,
                   :bio, :website_url, :role, :status, NOW(), NOW(), NOW())
                """
            ),
            {
                "uid": user_id,
                "username": data["username"],
                "email": data["email"],
                "password_hash": password_hash,
                "display_name": data["display_name"],
                "avatar_url": data.get("avatar_url") or None,
                "bio": data.get("bio") or None,
                "website_url": data.get("website_url") or None,
                "role": data["role"],
                "status": data["status"],
            },
        )
        self.db.commit()
        return self._admin_row(self.get_by_id(user_id))

    def update_admin_user(self, user_id: int, data: dict[str, Any]) -> Optional[dict]:
        existing = self.get_by_id(user_id)
        if not existing:
            return None
        password_hash = data.get("password_hash")
        new_uid = int(data["uid"])
        if new_uid != user_id:
            self._allocate_uid(new_uid)
        revoke_sessions = int(
            password_hash is not None
            or str(existing.get("status") or "") != str(data["status"])
            or str(existing.get("role") or "") != str(data["role"])
        )
        self.db.execute(
            text(
                """
                UPDATE users
                SET uid = :new_uid,
                    email = :email,
                    display_name = :display_name,
                    avatar_url = :avatar_url,
                    bio = :bio,
                    website_url = :website_url,
                    role = :role,
                    status = :status,
                    password_hash = COALESCE(:password_hash, password_hash),
                    password_changed_at = CASE
                      WHEN :password_hash IS NULL THEN password_changed_at
                      ELSE NOW()
                    END,
                    session_version = COALESCE(session_version, 0) + :revoke_sessions,
                    failed_attempts = CASE
                      WHEN :password_hash IS NULL THEN failed_attempts
                      ELSE 0
                    END,
                    locked_until = CASE
                      WHEN :password_hash IS NULL THEN locked_until
                      ELSE NULL
                    END,
                    updated_at = NOW()
                WHERE uid = :user_id
                """
            ),
            {
                "user_id": user_id,
                "new_uid": new_uid,
                "email": data["email"],
                "display_name": data["display_name"],
                "avatar_url": data.get("avatar_url") or None,
                "bio": data.get("bio") or None,
                "website_url": data.get("website_url") or None,
                "role": data["role"],
                "status": data["status"],
                "password_hash": password_hash,
                "revoke_sessions": revoke_sessions,
            },
        )
        self.db.commit()
        user = self.get_by_id(new_uid)
        return self._admin_row(user) if user else None

    def delete_admin_user(self, user_id: int) -> bool:
        result = self.db.execute(text("DELETE FROM users WHERE uid = :user_id"), {"user_id": user_id})
        self.db.commit()
        return result.rowcount > 0

    def active_admin_count(self) -> int:
        return int(
            self.db.execute(
                text("SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active' AND (ban_started_at IS NULL OR (ban_until IS NOT NULL AND ban_until<=UTC_TIMESTAMP()))")
            ).scalar_one()
        )

    def admin_count(self) -> int:
        return int(self.db.execute(text("SELECT COUNT(*) FROM users WHERE role = 'admin'")).scalar_one())

    @staticmethod
    def _admin_row(row: Optional[dict]) -> dict:
        if not row:
            return {}
        result = dict(row)
        from app.core.moderation import restrictions
        result["restrictions"] = restrictions(result)
        for key in list(result):
            if any(key.startswith(k + "_") for k in ("ban", "mute", "publish")):
                result.pop(key)
        password_hash = str(result.pop("password_hash", "") or "")
        result["password_configured"] = bool(password_hash and password_hash != "!password-unset!")
        if result.get("uid") is not None:
            # Keep the established string representation for API clients,
            # including accounts whose UID was assigned manually.
            result["uid"] = str(result["uid"])
        return result
