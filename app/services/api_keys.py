from __future__ import annotations

import hashlib
import ipaddress
import secrets
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.repositories.api_keys import ApiAccessKeyRepository
from app.repositories.settings import SettingsRepository


VERIFICATION_TTL_HOURS = 72
DNS_PREFIX = "_replow-verify"
FILE_PATH = "/.well-known/replow-verify.txt"
HTTP_TIMEOUT = 8.0

# Hostnames we refuse to verify. A private or loopback target would let a
# registrant point the checker at the server's own metadata service -- the
# classic SSRF pivot.
_BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".internal",
    ".localhost",
)


class ApiKeyError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ApiKeyService:
    """Domain registration plus ownership verification.

    Verification is the security boundary: an access key is only activated
    once the applicant proves control of the exact host they registered. Two
    independent channels are supported so any stack can comply:

    * DNS  -- a TXT record at ``_replow-verify.<host>``
    * HTTP -- a file at ``https://<host>/.well-known/replow-verify.txt``
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = ApiAccessKeyRepository(db)
        self.settings = SettingsRepository(db)

    # -- validation helpers ---------------------------------------------

    @staticmethod
    def normalize_site_url(raw: str) -> str:
        """Return a canonical origin (scheme + host + optional port).

        Only the origin participates in verification, so any path, query or
        fragment the applicant pasted is discarded rather than silently
        mismatching the served file.
        """
        value = (raw or "").strip()
        if not value:
            raise ApiKeyError("site_url_required", 422)
        if "://" not in value:
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ApiKeyError("invalid_scheme", 422)
        host = (parsed.hostname or "").strip().lower()
        if not host:
            raise ApiKeyError("invalid_site_url", 422)
        if host in {"localhost"} or host.endswith(_BLOCKED_HOST_SUFFIXES):
            raise ApiKeyError("site_url_not_allowed", 422)
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
            ):
                raise ApiKeyError("site_url_not_allowed", 422)
        port = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
        return f"{parsed.scheme}://{host}{port}"

    @staticmethod
    def _host_of(site_url: str) -> str:
        return (urlparse(site_url).hostname or "").lower()

    # -- registration ----------------------------------------------------

    def register(
        self,
        *,
        user_uid: int,
        email: str,
        site_url: str,
        module_slug: str = "oauth",
    ) -> dict[str, Any]:
        normalized = self.normalize_site_url(site_url)
        if not email.strip():
            raise ApiKeyError("email_required", 422)

        module = self._require_module(module_slug)

        # One row per (user, module). Re-registering while a key is already
        # active would silently destroy a live credential, so refuse and make
        # the caller rotate deliberately instead.
        existing = self.repo.get_by_user_module(user_uid, module_slug)
        if existing and existing.get("status") == "active":
            raise ApiKeyError(
                f"already_registered:{existing.get('site_url') or ''}", 409
            )

        plain_key = "rak_" + secrets.token_urlsafe(24)
        key_prefix = plain_key[:20]
        verification_token = "replow-verify-" + secrets.token_urlsafe(24)

        record = self.repo.upsert_pending(
            user_uid=user_uid,
            module_slug=module_slug,
            email=email.strip(),
            site_url=normalized,
            key_prefix=key_prefix,
            key_hash=sha256_hex(plain_key),
            verification_token_hash=sha256_hex(verification_token),
            verification_ttl_seconds=VERIFICATION_TTL_HOURS * 3600,
        )

        return {
            "id": int(record["id"]),
            "user_uid": user_uid,
            "module_slug": module_slug,
            "module_name": module.get("name") or module_slug,
            "email": email.strip(),
            "site_url": normalized,
            "host": self._host_of(normalized),
            "status": "pending",
            # The plaintext key is shown exactly once, before verification.
            # Losing it costs a rotation, which is the safe failure mode.
            "key": plain_key,
            "key_prefix": key_prefix,
            "verification": self._challenge_instructions(normalized, verification_token),
            "verification_expires_at": record.get("verification_expires_at"),
        }

    def _require_module(self, module_slug: str) -> dict:
        row = self.db.execute(
            __import__("sqlalchemy").text(
                """
                SELECT slug, name, base_path, access_mode, enabled
                FROM api_modules
                WHERE slug = :slug
                LIMIT 1
                """
            ),
            {"slug": module_slug},
        ).mappings().first()
        if not row:
            raise ApiKeyError("unknown_module", 404)
        return dict(row)

    @staticmethod
    def _challenge_instructions(site_url: str, token: str) -> dict[str, Any]:
        host = urlparse(site_url).hostname or ""
        return {
            "token": token,
            "dns": {
                "record_type": "TXT",
                "name": f"{DNS_PREFIX}.{host}",
                "value": token,
                "description": f"在 DNS 添加一条 TXT 记录：主机记录 {DNS_PREFIX}，值为上面的 token。",
            },
            "http": {
                "url": f"{site_url}{FILE_PATH}",
                "content": token,
                "description": f"或在站点根目录放置文件 {FILE_PATH}，内容为上面的 token。",
            },
        }

    # -- listing ---------------------------------------------------------

    def list_keys(self, user_uid: Optional[int] = None) -> list[dict[str, Any]]:
        rows = self.repo.list_all(user_uid=user_uid)
        return [self._public_view(row) for row in rows]

    @staticmethod
    def _public_view(row: dict) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "user_uid": int(row["user_uid"]),
            "module_slug": row["module_slug"],
            "key_prefix": row.get("key_prefix") or "",
            "status": row["status"],
            "email": row.get("email") or "",
            "site_url": row.get("site_url") or "",
            "host": (urlparse(row.get("site_url") or "").hostname or "").lower(),
            "verified_at": row.get("verified_at"),
            "verification_expires_at": row.get("verification_expires_at"),
            "last_used_at": row.get("last_used_at"),
            "rate_limit_override": row.get("rate_limit_override"),
            "expires_at": row.get("expires_at"),
            "created_at": row.get("created_at"),
        }

    def get_key(self, key_id: int) -> dict[str, Any]:
        row = self.repo.get_by_id(key_id)
        if not row:
            raise ApiKeyError("access_key_not_found", 404)
        return self._public_view(row)

    # -- verification ----------------------------------------------------

    def verify(self, key_id: int, *, method: str = "auto") -> dict[str, Any]:
        """Check domain ownership and activate the key on success."""
        record = self.repo.get_by_id(key_id)
        if not record:
            raise ApiKeyError("access_key_not_found", 404)
        if record["status"] == "active":
            return {"verified": True, "status": "active", "already_verified": True,
                    "detail": "该域名已经验证通过。"}
        if record["status"] == "revoked":
            raise ApiKeyError("access_key_revoked", 409)
        if not record.get("verification_token_hash"):
            raise ApiKeyError("verification_not_initialized", 409)

        expires_at = record.get("verification_expires_at")
        if expires_at and expires_at < _utcnow():
            raise ApiKeyError("verification_expired", 410)

        site_url = str(record.get("site_url") or "")
        token_hash = str(record["verification_token_hash"])

        checks: list[dict[str, Any]] = []
        wanted = method.lower()
        if wanted in {"auto", "dns"}:
            checks.append(self._check_dns(site_url, token_hash))
        if wanted in {"auto", "http"}:
            checks.append(self._check_http(site_url, token_hash))
        if not checks:
            raise ApiKeyError("invalid_verification_method", 422)

        matched = next((item for item in checks if item["matched"]), None)
        if not matched:
            return {
                "verified": False,
                "status": record["status"],
                "checks": checks,
                "detail": "未检测到匹配的验证记录，请确认 token 已正确发布后重试。",
            }

        activated = self.repo.mark_verified(int(record["id"]))
        return {
            "verified": True,
            "status": "active",
            "activated": activated,
            "matched_by": matched["method"],
            "checks": checks,
            "detail": f"域名所有权验证通过（{matched['method']}），访问密钥已激活。",
        }

    def _check_dns(self, site_url: str, token_hash: str) -> dict[str, Any]:
        host = self._host_of(site_url)
        lookup = f"{DNS_PREFIX}.{host}"
        try:
            import dns.resolver  # type: ignore

            answers = dns.resolver.resolve(lookup, "TXT", lifetime=HTTP_TIMEOUT)
            values = [b"".join(rdata.strings).decode("utf-8", "replace") for rdata in answers]
        except ImportError:
            return self._check_dns_fallback(lookup, token_hash)
        except Exception as error:  # noqa: BLE001 - any resolver failure is a miss
            return {
                "method": "dns",
                "target": lookup,
                "matched": False,
                "detail": f"DNS 查询失败：{type(error).__name__}",
            }

        for value in values:
            if sha256_hex(value.strip()) == token_hash:
                return {"method": "dns", "target": lookup, "matched": True,
                        "detail": f"在 {lookup} 找到匹配的 TXT 记录。"}
        if values:
            return {"method": "dns", "target": lookup, "matched": False,
                    "detail": f"{lookup} 存在 TXT 记录，但内容与 token 不匹配。"}
        return {"method": "dns", "target": lookup, "matched": False,
                "detail": f"{lookup} 没有 TXT 记录。"}

    def _check_dns_fallback(self, lookup: str, token_hash: str) -> dict[str, Any]:
        """Resolve TXT via the system resolver when dnspython is unavailable.

        Most container images ship without dnspython, so falling back keeps the
        DNS channel usable instead of silently reporting a failure.
        """
        try:
            answers = socket.getaddrinfo(lookup, None)
        except socket.gaierror:
            answers = []
        if not answers:
            return {
                "method": "dns",
                "target": lookup,
                "matched": False,
                "detail": f"{lookup} 无法解析（系统解析器不支持 TXT 查询时请改用文件验证）。",
            }
        return {
            "method": "dns",
            "target": lookup,
            "matched": False,
            "detail": "当前环境缺少 DNS TXT 查询库，无法读取记录内容，请改用文件验证。",
        }

    def _check_http(self, site_url: str, token_hash: str) -> dict[str, Any]:
        url = f"{site_url}{FILE_PATH}"
        try:
            response = httpx.get(
                url,
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "Replow-Verifier/1.0"},
            )
        except Exception as error:  # noqa: BLE001 - network failures are misses
            return {"method": "http", "target": url, "matched": False,
                    "detail": f"请求失败：{type(error).__name__}"}

        if response.status_code != 200:
            return {"method": "http", "target": url, "matched": False,
                    "detail": f"HTTP {response.status_code}，无法读取验证文件。"}

        body = (response.text or "").strip()
        if not body:
            return {"method": "http", "target": url, "matched": False,
                    "detail": "验证文件为空。"}
        # Compare line-wise so a file with a trailing comment still works.
        for line in body.splitlines():
            if sha256_hex(line.strip()) == token_hash:
                return {"method": "http", "target": url, "matched": True,
                        "detail": f"在 {url} 找到匹配的 token。"}
        return {"method": "http", "target": url, "matched": False,
                "detail": "验证文件内容与 token 不匹配。"}

    # -- lifecycle -------------------------------------------------------

    def rotate_key(self, key_id: int) -> dict[str, Any]:
        record = self.repo.get_by_id(key_id)
        if not record:
            raise ApiKeyError("access_key_not_found", 404)
        plain_key = "rak_" + secrets.token_urlsafe(24)
        key_prefix = plain_key[:20]
        if not self.repo.rotate_key(int(record["id"]), key_prefix=key_prefix, key_hash=sha256_hex(plain_key)):
            raise ApiKeyError("access_key_not_found", 404)
        return {"id": int(record["id"]), "key": plain_key, "key_prefix": key_prefix}

    def update_settings(self, key_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.repo.get_by_id(key_id)
        if not record:
            raise ApiKeyError("access_key_not_found", 404)

        site_url: Optional[str] = None
        if "site_url" in payload:
            site_url = self.normalize_site_url(str(payload.get("site_url") or ""))
            # Changing the domain invalidates the proof, so the key drops back
            # to pending and has to be verified again.
            if site_url != str(record.get("site_url") or ""):
                self.repo.update_settings(int(record["id"]), site_url=site_url, status="pending")
                record = self.repo.get_by_id(int(record["id"])) or record

        status = payload.get("status")
        if status is not None and status not in {"pending", "active", "revoked"}:
            raise ApiKeyError("invalid_status", 422)

        rate_limit = payload.get("rate_limit_override")
        if rate_limit is not None and not isinstance(rate_limit, int):
            raise ApiKeyError("invalid_rate_limit", 422)

        updated = self.repo.update_settings(
            int(record["id"]),
            site_url=site_url if "site_url" in payload and site_url == record.get("site_url") else None,
            email=str(payload["email"]).strip() if payload.get("email") is not None else None,
            status=status,
            rate_limit_override=rate_limit,
            clear_rate_limit=payload.get("rate_limit_override") is None and "rate_limit_override" in payload,
            clear_expiry=payload.get("expires_at") is None and "expires_at" in payload,
        )
        return self._public_view(updated or record)

    def delete(self, key_id: int) -> bool:
        return self.repo.delete(key_id)

    def regenerate_challenge(self, key_id: int) -> dict[str, Any]:
        """Issue a fresh verification token and a new key for a pending row."""
        record = self.repo.get_by_id(key_id)
        if not record:
            raise ApiKeyError("access_key_not_found", 404)
        if record["status"] == "active":
            raise ApiKeyError("access_key_already_active", 409)

        plain_key = "rak_" + secrets.token_urlsafe(24)
        token = "replow-verify-" + secrets.token_urlsafe(24)
        site_url = str(record.get("site_url") or "")

        self.repo.upsert_pending(
            user_uid=int(record["user_uid"]),
            module_slug=str(record["module_slug"]),
            email=str(record.get("email") or ""),
            site_url=site_url,
            key_prefix=plain_key[:20],
            key_hash=sha256_hex(plain_key),
            verification_token_hash=sha256_hex(token),
            verification_ttl_seconds=VERIFICATION_TTL_HOURS * 3600,
        )
        refreshed = self.repo.get_by_user_module(int(record["user_uid"]), str(record["module_slug"])) or {}
        return {
            "id": int(refreshed.get("id") or record["id"]),
            "key": plain_key,
            "key_prefix": plain_key[:20],
            "verification": self._challenge_instructions(site_url, token),
            "verification_expires_at": refreshed.get("verification_expires_at"),
        }
