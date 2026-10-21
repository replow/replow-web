from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OAuthRepository:
    """Persistence for the standard OAuth 2.1 authorization-code flow.

    Three tables back this: ``oauth_clients`` (registered applications),
    ``oauth_authorization_codes`` (short-lived, single-use, PKCE-bound grant
    codes) and ``oauth_tokens`` (issued access/refresh pairs, stored hashed).
    Every secret is persisted as a SHA-256 hex digest, never in the clear.
    """

    def __init__(self, db: Session):
        self.db = db

    # -- clients ---------------------------------------------------------

    def get_client(self, client_id: str) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT id, client_id, client_secret_hash, name, icon_url,
                       redirect_uris, description, confidential, enabled,
                       created_by, created_at
                FROM oauth_clients
                WHERE client_id = :client_id
                LIMIT 1
                """
            ),
            {"client_id": client_id},
        ).mappings().first()
        return dict(row) if row else None

    def list_clients(self, owner_uid: Optional[int] = None) -> list[dict]:
        params: dict[str, Any] = {}
        clause = ""
        if owner_uid is not None:
            clause = "WHERE created_by = :owner_uid"
            params["owner_uid"] = owner_uid
        rows = self.db.execute(
            text(
                f"""
                SELECT id, client_id, name, icon_url, redirect_uris, description,
                       confidential, enabled, created_by, created_at
                FROM oauth_clients
                {clause}
                ORDER BY id DESC
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def create_client(
        self,
        *,
        client_id: str,
        client_secret_hash: Optional[str],
        name: str,
        redirect_uris: str,
        owner_uid: int,
        description: str = "",
        icon_url: str = "",
        confidential: bool = True,
    ) -> dict:
        self.db.execute(
            text(
                """
                INSERT INTO oauth_clients
                  (client_id, client_secret_hash, name, icon_url, redirect_uris,
                   description, confidential, enabled, created_by, created_at, updated_at)
                VALUES
                  (:client_id, :client_secret_hash, :name, :icon_url, :redirect_uris,
                   :description, :confidential, 1, :owner_uid, NOW(), NOW())
                """
            ),
            {
                "client_id": client_id,
                "client_secret_hash": client_secret_hash,
                "name": name,
                "icon_url": icon_url or None,
                "redirect_uris": redirect_uris,
                "description": description or None,
                "confidential": int(confidential),
                "owner_uid": owner_uid,
            },
        )
        self.db.commit()
        return self.get_client(client_id) or {}

    def update_client(
        self,
        client_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        icon_url: Optional[str] = None,
        redirect_uris: Optional[str] = None,
        enabled: Optional[bool] = None,
        client_secret_hash: Optional[str] = None,
    ) -> Optional[dict]:
        fields: list[str] = []
        params: dict[str, Any] = {"client_id": client_id}
        if name is not None:
            fields.append("name = :name")
            params["name"] = name
        if description is not None:
            fields.append("description = :description")
            params["description"] = description or None
        if icon_url is not None:
            fields.append("icon_url = :icon_url")
            params["icon_url"] = icon_url or None
        if redirect_uris is not None:
            fields.append("redirect_uris = :redirect_uris")
            params["redirect_uris"] = redirect_uris
        if enabled is not None:
            fields.append("enabled = :enabled")
            params["enabled"] = int(enabled)
        if client_secret_hash is not None:
            fields.append("client_secret_hash = :client_secret_hash")
            params["client_secret_hash"] = client_secret_hash
        if not fields:
            return self.get_client(client_id)
        fields.append("updated_at = NOW()")
        self.db.execute(
            text(f"UPDATE oauth_clients SET {', '.join(fields)} WHERE client_id = :client_id"),
            params,
        )
        self.db.commit()
        return self.get_client(client_id)

    def delete_client(self, client_id: str, owner_uid: Optional[int] = None) -> bool:
        params: dict[str, Any] = {"client_id": client_id}
        clause = ""
        if owner_uid is not None:
            clause = " AND created_by = :owner_uid"
            params["owner_uid"] = owner_uid
        result = self.db.execute(
            text(f"DELETE FROM oauth_clients WHERE client_id = :client_id{clause}"),
            params,
        )
        self.db.commit()
        return bool(result.rowcount)

    # -- authorization codes --------------------------------------------

    def create_authorization_code(
        self,
        *,
        client_id: str,
        user_uid: int,
        code_hash: str,
        redirect_uri: str,
        scope: str,
        code_challenge: Optional[str],
        challenge_method: str,
        ttl_seconds: int = 600,
        created_ip: Optional[str] = None,
    ) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO oauth_authorization_codes
                  (client_id, user_uid, code_hash, redirect_uri, scope,
                   code_challenge, challenge_method, expires_at, created_ip, created_at)
                VALUES
                  (:client_id, :user_uid, :code_hash, :redirect_uri, :scope,
                   :code_challenge, :challenge_method, :expires_at, :created_ip, NOW())
                """
            ),
            {
                "client_id": client_id,
                "user_uid": user_uid,
                "code_hash": code_hash,
                "redirect_uri": redirect_uri,
                "scope": scope,
                "code_challenge": code_challenge,
                "challenge_method": challenge_method or "S256",
                "expires_at": _utcnow() + timedelta(seconds=ttl_seconds),
                "created_ip": _pack_ip(created_ip),
            },
        )
        self.db.commit()

    def get_authorization_code(self, code_hash: str) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT id, client_id, user_uid, code_hash, redirect_uri, scope,
                       code_challenge, challenge_method, expires_at, used_at, created_at
                FROM oauth_authorization_codes
                WHERE code_hash = :code_hash
                LIMIT 1
                """
            ),
            {"code_hash": code_hash},
        ).mappings().first()
        return dict(row) if row else None

    def consume_authorization_code(self, code_hash: str) -> bool:
        """Mark a code used. Returns False when it was already redeemed.

        The conditional UPDATE is the replay guard: two concurrent token
        requests cannot both win because only one sees ``used_at IS NULL``.
        """
        result = self.db.execute(
            text(
                """
                UPDATE oauth_authorization_codes
                SET used_at = NOW()
                WHERE code_hash = :code_hash AND used_at IS NULL
                """
            ),
            {"code_hash": code_hash},
        )
        self.db.commit()
        return bool(result.rowcount)

    def purge_expired_codes(self) -> int:
        result = self.db.execute(
            text("DELETE FROM oauth_authorization_codes WHERE expires_at < NOW()")
        )
        self.db.commit()
        return int(result.rowcount or 0)

    # -- tokens ----------------------------------------------------------

    def create_token(
        self,
        *,
        client_id: str,
        user_uid: int,
        access_token_hash: str,
        refresh_token_hash: Optional[str],
        scope: str,
        access_expires_at: datetime,
        refresh_expires_at: Optional[datetime],
        created_ip: Optional[str] = None,
    ) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO oauth_tokens
                  (client_id, user_uid, access_token_hash, refresh_token_hash, scope,
                   access_expires_at, refresh_expires_at, created_ip, created_at)
                VALUES
                  (:client_id, :user_uid, :access_token_hash, :refresh_token_hash, :scope,
                   :access_expires_at, :refresh_expires_at, :created_ip, NOW())
                """
            ),
            {
                "client_id": client_id,
                "user_uid": user_uid,
                "access_token_hash": access_token_hash,
                "refresh_token_hash": refresh_token_hash,
                "scope": scope,
                "access_expires_at": access_expires_at,
                "refresh_expires_at": refresh_expires_at,
                "created_ip": _pack_ip(created_ip),
            },
        )
        self.db.commit()

    def get_token_by_access(self, access_token_hash: str) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT id, client_id, user_uid, access_token_hash, refresh_token_hash,
                       scope, access_expires_at, refresh_expires_at, revoked_at,
                       last_used_at, created_at
                FROM oauth_tokens
                WHERE access_token_hash = :access_token_hash
                LIMIT 1
                """
            ),
            {"access_token_hash": access_token_hash},
        ).mappings().first()
        return dict(row) if row else None

    def get_token_by_refresh(self, refresh_token_hash: str) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT id, client_id, user_uid, access_token_hash, refresh_token_hash,
                       scope, access_expires_at, refresh_expires_at, revoked_at,
                       last_used_at, created_at
                FROM oauth_tokens
                WHERE refresh_token_hash = :refresh_token_hash
                LIMIT 1
                """
            ),
            {"refresh_token_hash": refresh_token_hash},
        ).mappings().first()
        return dict(row) if row else None

    def touch_token(self, token_id: int) -> None:
        self.db.execute(
            text("UPDATE oauth_tokens SET last_used_at = NOW() WHERE id = :token_id"),
            {"token_id": token_id},
        )
        self.db.commit()

    def revoke_token(self, token_id: int) -> None:
        self.db.execute(
            text(
                "UPDATE oauth_tokens SET revoked_at = NOW() WHERE id = :token_id AND revoked_at IS NULL"
            ),
            {"token_id": token_id},
        )
        self.db.commit()

    def revoke_by_pair(
        self, *, client_id: str, user_uid: int, commit: bool = True
    ) -> int:
        result = self.db.execute(
            text(
                """
                UPDATE oauth_tokens
                SET revoked_at = NOW()
                WHERE client_id = :client_id AND user_uid = :user_uid AND revoked_at IS NULL
                """
            ),
            {"client_id": client_id, "user_uid": user_uid},
        )
        if commit:
            self.db.commit()
        return int(result.rowcount or 0)

    def rotate_refresh(
        self,
        *,
        token_id: int,
        old_refresh_hash: str,
        new_access_hash: str,
        new_refresh_hash: str,
        access_expires_at: datetime,
        refresh_expires_at: datetime,
    ) -> bool:
        """Rotate a refresh token in place.

        Conditional on the old hash still being present, so a replayed refresh
        token fails instead of silently minting a parallel session.
        """
        result = self.db.execute(
            text(
                """
                UPDATE oauth_tokens
                SET access_token_hash = :new_access_hash,
                    refresh_token_hash = :new_refresh_hash,
                    access_expires_at = :access_expires_at,
                    refresh_expires_at = :refresh_expires_at,
                    last_used_at = NOW()
                WHERE id = :token_id
                  AND refresh_token_hash = :old_refresh_hash
                  AND revoked_at IS NULL
                """
            ),
            {
                "token_id": token_id,
                "old_refresh_hash": old_refresh_hash,
                "new_access_hash": new_access_hash,
                "new_refresh_hash": new_refresh_hash,
                "access_expires_at": access_expires_at,
                "refresh_expires_at": refresh_expires_at,
            },
        )
        self.db.commit()
        return bool(result.rowcount)

    def list_tokens(self, user_uid: int) -> list[dict]:
        rows = self.db.execute(
            text(
                """
                SELECT t.id, t.client_id, c.name AS client_name, c.icon_url,
                       t.scope, t.access_expires_at, t.refresh_expires_at,
                       t.revoked_at, t.last_used_at, t.created_at
                FROM oauth_tokens t
                LEFT JOIN oauth_clients c ON c.client_id = t.client_id
                WHERE t.user_uid = :user_uid
                ORDER BY t.id DESC
                """
            ),
            {"user_uid": user_uid},
        ).mappings().all()
        return [dict(row) for row in rows]

    def list_active_grants(self, user_uid: int) -> list[dict]:
        rows = self.db.execute(
            text(
                """
                SELECT t.client_id, c.name AS client_name, c.icon_url, c.description,
                       t.scope, MAX(t.created_at) AS granted_at, MAX(t.last_used_at) AS last_used_at
                FROM oauth_tokens t
                LEFT JOIN oauth_clients c ON c.client_id = t.client_id
                WHERE t.user_uid = :user_uid
                  AND t.revoked_at IS NULL
                  AND (t.refresh_expires_at IS NULL OR t.refresh_expires_at > NOW())
                GROUP BY t.client_id, c.name, c.icon_url, c.description, t.scope
                ORDER BY granted_at DESC
                """
            ),
            {"user_uid": user_uid},
        ).mappings().all()
        return [dict(row) for row in rows]


def _pack_ip(ip: Optional[str]) -> Optional[bytes]:
    """Store an IPv4/IPv6 literal as the 4/16-byte binary column expects."""
    if not ip:
        return None
    import socket

    try:
        return socket.inet_pton(socket.AF_INET, ip)
    except OSError:
        pass
    try:
        return socket.inet_pton(socket.AF_INET6, ip)
    except OSError:
        return None
