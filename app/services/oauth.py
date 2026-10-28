from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.repositories.oauth import OAuthRepository
from app.repositories.users import UserRepository


SUPPORTED_SCOPES = ("profile", "email")
DEFAULT_SCOPE = "profile"
AUTHORIZATION_CODE_TTL = 600  # 10 minutes
ACCESS_TOKEN_TTL = 3600  # 1 hour
REFRESH_TOKEN_TTL = 30 * 24 * 3600  # 30 days


class OAuthError(Exception):
    """OAuth protocol error carrying an RFC 6749 error code."""

    def __init__(self, error: str, description: str = "", status_code: int = 400):
        super().__init__(description or error)
        self.error = error
        self.description = description or error
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _random_token(prefix: str, length: int = 48) -> str:
    return prefix + secrets.token_urlsafe(length)


def _b64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OAuthService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = OAuthRepository(db)

    # -- client registry -------------------------------------------------

    def register_client(
        self,
        *,
        name: str,
        redirect_uris: list[str],
        owner_uid: int,
        description: str = "",
        icon_url: str = "",
        confidential: bool = True,
        client_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if not name.strip():
            raise OAuthError("invalid_client_metadata", "name_required", 422)
        if not redirect_uris:
            raise OAuthError("invalid_redirect_uri", "redirect_uri_required", 422)
        for uri in redirect_uris:
            if not self._valid_redirect_uri(uri):
                raise OAuthError("invalid_redirect_uri", f"invalid_redirect_uri:{uri}", 422)

        cid = client_id or _random_token("scnc_", 44)
        plain_secret: Optional[str] = None
        secret_hash: Optional[str] = None
        if confidential:
            plain_secret = _random_token("scns_", 44)
            secret_hash = sha256_hex(plain_secret)

        client = self.repo.create_client(
            client_id=cid,
            client_secret_hash=secret_hash,
            name=name.strip(),
            redirect_uris=json.dumps(redirect_uris),
            owner_uid=owner_uid,
            description=description.strip(),
            icon_url=icon_url.strip(),
            confidential=confidential,
        )
        client = dict(client)
        # The plaintext secret is returned exactly once, at creation time.
        client["client_secret"] = plain_secret
        return client

    def rotate_client_secret(self, client_id: str, owner_uid: Optional[int] = None) -> dict[str, Any]:
        client = self._require_client(client_id, owner_uid)
        plain_secret = _random_token("scns_", 44)
        updated = self.repo.update_client(
            client_id, client_secret_hash=sha256_hex(plain_secret), enabled=True
        )
        result = dict(updated or client)
        result["client_secret"] = plain_secret
        return result

    @staticmethod
    def _valid_redirect_uri(uri: str) -> bool:
        from urllib.parse import urlparse

        parsed = urlparse(uri)
        if parsed.scheme == "https" and parsed.netloc:
            return True
        # Loopback redirects are allowed over plain HTTP for native/CLI clients.
        if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            return True
        return False

    def _require_client(self, client_id: str, owner_uid: Optional[int] = None) -> dict:
        client = self.repo.get_client(client_id)
        if not client:
            raise OAuthError("invalid_client", "unknown_client", 401)
        if not client.get("enabled"):
            raise OAuthError("invalid_client", "client_disabled", 401)
        if owner_uid is not None and int(client["created_by"]) != int(owner_uid):
            raise OAuthError("invalid_client", "client_not_owned", 403)
        return client

    def authenticate_client(
        self,
        *,
        client_id: str,
        client_secret: Optional[str] = None,
        code_verifier: Optional[str] = None,
        require_secret: bool = True,
    ) -> dict:
        """Authenticate the calling client.

        Confidential clients must present a matching secret. Public clients
        have no secret and are authenticated by PKCE alone, so a missing
        secret is tolerated only when the registration says so.
        """
        client = self._require_client(client_id)
        if client.get("confidential"):
            if require_secret and not client_secret:
                raise OAuthError("invalid_client", "client_secret_required", 401)
            if client_secret:
                if sha256_hex(client_secret) != (client.get("client_secret_hash") or ""):
                    raise OAuthError("invalid_client", "invalid_client_secret", 401)
        return client

    # -- authorize -------------------------------------------------------

    def validate_authorize_request(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        response_type: str,
        scope: Optional[str],
        code_challenge: Optional[str],
        code_challenge_method: Optional[str],
        state: Optional[str],
    ) -> dict[str, Any]:
        client = self._require_client(client_id)

        registered = _json_list(client.get("redirect_uris"))
        if redirect_uri not in registered:
            # Never redirect to an unregistered URI -- that is the open-redirect
            # hole OAuth exists to close.
            raise OAuthError("invalid_request", "redirect_uri_mismatch", 400)

        if response_type != "code":
            raise OAuthError("unsupported_response_type", "only_code_supported", 400)

        method = (code_challenge_method or "S256").upper()
        if not code_challenge:
            raise OAuthError("invalid_request", "code_challenge_required", 400)
        if method != "S256":
            raise OAuthError("invalid_request", "only_s256_supported", 400)
        if len(code_challenge) < 43 or len(code_challenge) > 128:
            raise OAuthError("invalid_request", "invalid_code_challenge", 400)

        resolved_scope = self._normalize_scope(scope)
        return {
            "client": client,
            "redirect_uri": redirect_uri,
            "scope": resolved_scope,
            "code_challenge": code_challenge,
            "code_challenge_method": method,
            "state": state or "",
            "response_type": response_type,
        }

    @staticmethod
    def _normalize_scope(scope: Optional[str]) -> str:
        if not scope or not scope.strip():
            return DEFAULT_SCOPE
        requested = [part.strip() for part in scope.split() if part.strip()]
        unknown = [part for part in requested if part not in SUPPORTED_SCOPES]
        if unknown:
            raise OAuthError("invalid_scope", f"unsupported_scope:{','.join(unknown)}", 400)
        # De-duplicate while preserving the canonical order.
        ordered = [part for part in SUPPORTED_SCOPES if part in requested]
        return " ".join(ordered) or DEFAULT_SCOPE

    def issue_authorization_code(
        self,
        *,
        client_id: str,
        user_uid: int,
        redirect_uri: str,
        scope: str,
        code_challenge: str,
        code_challenge_method: str,
        created_ip: Optional[str] = None,
    ) -> str:
        plain_code = _random_token("scac_", 40)
        self.repo.create_authorization_code(
            client_id=client_id,
            user_uid=user_uid,
            code_hash=sha256_hex(plain_code),
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            challenge_method=code_challenge_method,
            ttl_seconds=AUTHORIZATION_CODE_TTL,
            created_ip=created_ip,
        )
        return plain_code

    # -- token -----------------------------------------------------------

    def exchange_authorization_code(
        self,
        *,
        client_id: str,
        client_secret: Optional[str],
        code: str,
        redirect_uri: str,
        code_verifier: str,
        created_ip: Optional[str] = None,
    ) -> dict[str, Any]:
        client = self.authenticate_client(
            client_id=client_id, client_secret=client_secret, require_secret=False
        )

        record = self.repo.get_authorization_code(sha256_hex(code))
        if not record:
            raise OAuthError("invalid_grant", "unknown_code", 400)
        if str(record["client_id"]) != client_id:
            raise OAuthError("invalid_grant", "code_client_mismatch", 400)
        if record.get("used_at") is not None:
            raise OAuthError("invalid_grant", "code_already_used", 400)
        if record["expires_at"] < _utcnow():
            raise OAuthError("invalid_grant", "code_expired", 400)
        if record["redirect_uri"] != redirect_uri:
            raise OAuthError("invalid_grant", "redirect_uri_mismatch", 400)

        self._verify_pkce(record, code_verifier)

        # Single-use: claim the code before minting anything. A lost race
        # means somebody else already redeemed it.
        if not self.repo.consume_authorization_code(sha256_hex(code)):
            raise OAuthError("invalid_grant", "code_already_used", 400)

        return self._mint_token_pair(
            client_id=client_id,
            user_uid=int(record["user_uid"]),
            scope=str(record["scope"]),
            created_ip=created_ip,
        )

    @staticmethod
    def _verify_pkce(record: dict, code_verifier: str) -> None:
        challenge = record.get("code_challenge")
        if not challenge:
            raise OAuthError("invalid_grant", "code_challenge_missing", 400)
        if not code_verifier or len(code_verifier) < 43 or len(code_verifier) > 128:
            raise OAuthError("invalid_grant", "invalid_code_verifier", 400)
        if _b64url_sha256(code_verifier) != str(challenge):
            raise OAuthError("invalid_grant", "pkce_verification_failed", 400)

    def refresh_token_grant(
        self,
        *,
        client_id: str,
        client_secret: Optional[str],
        refresh_token: str,
        scope: Optional[str] = None,
    ) -> dict[str, Any]:
        self.authenticate_client(
            client_id=client_id, client_secret=client_secret, require_secret=False
        )
        record = self.repo.get_token_by_refresh(sha256_hex(refresh_token))
        if not record:
            raise OAuthError("invalid_grant", "unknown_refresh_token", 400)
        if str(record["client_id"]) != client_id:
            raise OAuthError("invalid_grant", "refresh_client_mismatch", 400)
        if record.get("revoked_at") is not None:
            raise OAuthError("invalid_grant", "refresh_token_revoked", 400)
        expires_at = record.get("refresh_expires_at")
        if expires_at and expires_at < _utcnow():
            raise OAuthError("invalid_grant", "refresh_token_expired", 400)

        from app.core.moderation import enforce
        user = UserRepository(self.db).get_by_id(int(record["user_uid"]))
        if not user or user.get("status") != "active":
            raise OAuthError("invalid_grant", "account_unavailable", 401)
        enforce(user)
        resolved_scope = str(record["scope"])
        if scope:
            requested = self._normalize_scope(scope)
            # Scope may shrink on refresh, never widen.
            granted = set(resolved_scope.split())
            resolved_scope = " ".join(part for part in requested.split() if part in granted) or resolved_scope

        access_token = _random_token("scat_", 48)
        new_refresh = _random_token("scrt_", 48)
        access_expires = _utcnow() + timedelta(seconds=ACCESS_TOKEN_TTL)
        refresh_expires = _utcnow() + timedelta(seconds=REFRESH_TOKEN_TTL)

        rotated = self.repo.rotate_refresh(
            token_id=int(record["id"]),
            old_refresh_hash=sha256_hex(refresh_token),
            new_access_hash=sha256_hex(access_token),
            new_refresh_hash=sha256_hex(new_refresh),
            access_expires_at=access_expires,
            refresh_expires_at=refresh_expires,
        )
        if not rotated:
            raise OAuthError("invalid_grant", "refresh_token_replayed", 400)

        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL,
            "refresh_token": new_refresh,
            "scope": resolved_scope,
        }

    def _mint_token_pair(
        self,
        *,
        client_id: str,
        user_uid: int,
        scope: str,
        created_ip: Optional[str] = None,
    ) -> dict[str, Any]:
        from app.core.moderation import enforce
        user = UserRepository(self.db).get_by_id(user_uid)
        if not user or user.get("status") != "active":
            raise OAuthError("invalid_grant", "account_unavailable", 401)
        enforce(user)
        access_token = _random_token("scat_", 48)
        refresh_token = _random_token("scrt_", 48)
        self.repo.create_token(
            client_id=client_id,
            user_uid=user_uid,
            access_token_hash=sha256_hex(access_token),
            refresh_token_hash=sha256_hex(refresh_token),
            scope=scope,
            access_expires_at=_utcnow() + timedelta(seconds=ACCESS_TOKEN_TTL),
            refresh_expires_at=_utcnow() + timedelta(seconds=REFRESH_TOKEN_TTL),
            created_ip=created_ip,
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL,
            "refresh_token": refresh_token,
            "scope": scope,
        }

    # -- resource / userinfo --------------------------------------------

    def resolve_access_token(self, access_token: str) -> dict[str, Any]:
        record = self.repo.get_token_by_access(sha256_hex(access_token))
        if not record:
            raise OAuthError("invalid_token", "unknown_token", 401)
        if record.get("revoked_at") is not None:
            raise OAuthError("invalid_token", "token_revoked", 401)
        if record["access_expires_at"] < _utcnow():
            raise OAuthError("invalid_token", "token_expired", 401)
        self.repo.touch_token(int(record["id"]))
        return record

    def userinfo(self, access_token: str) -> dict[str, Any]:
        record = self.resolve_access_token(access_token)
        user = UserRepository(self.db).get_by_id(int(record["user_uid"]))
        if not user or user["status"] != "active":
            raise OAuthError("invalid_token", "account_unavailable", 401)

        from app.core.moderation import enforce
        enforce(user)
        scopes = set(str(record["scope"]).split())
        payload: dict[str, Any] = {
            "sub": str(user["uid"]),
            "preferred_username": str(user["username"]),
            "name": str(user.get("display_name") or user["username"]),
            "picture": str(user.get("avatar_url") or ""),
        }
        if "email" in scopes:
            payload["email"] = str(user["email"])
        payload["scope"] = str(record["scope"])
        return payload

    # -- revocation / account views --------------------------------------

    def revoke(self, *, access_token: Optional[str], refresh_token: Optional[str]) -> None:
        record = None
        if refresh_token:
            record = self.repo.get_token_by_refresh(sha256_hex(refresh_token))
        if record is None and access_token:
            record = self.repo.get_token_by_access(sha256_hex(access_token))
        if record:
            self.repo.revoke_token(int(record["id"]))

    def revoke_grant(self, *, client_id: str, user_uid: int) -> int:
        return self.repo.revoke_by_pair(client_id=client_id, user_uid=user_uid)

    def connected_apps(self, user_uid: int) -> list[dict[str, Any]]:
        return self.repo.list_active_grants(user_uid)

    def build_redirect(self, redirect_uri: str, params: dict[str, str]) -> str:
        separator = "&" if "?" in redirect_uri else "?"
        return f"{redirect_uri}{separator}{urlencode(params)}"


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (ValueError, TypeError):
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []
