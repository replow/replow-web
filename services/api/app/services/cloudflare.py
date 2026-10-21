from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from app.core.secret_store import decrypt_secret, encrypt_secret
from app.repositories.settings import SettingsRepository


CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 502):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class CloudflareConfig:
    auth_type: str
    email: str
    credential: str
    account_id: str
    zone_id: str
    zone_name: str

    @property
    def configured(self) -> bool:
        if not self.credential:
            return False
        # account_id is optional on purpose. A Global API Key can see every
        # account the user belongs to, and the zone is already pinned by
        # zone_id / zone_name -- requiring the account id as well would only
        # add a way to be configured-but-broken. When it *is* set it is passed
        # to the zone lookup, which disambiguates the same zone name appearing
        # under two accounts (this key genuinely sees three accounts).
        if not (self.zone_id or self.zone_name):
            return False
        if self.auth_type == "global_key" and not self.email:
            return False
        return True


class CloudflareService:
    namespace = "cloudflare"
    credential_key = "cloudflare.api_credential"
    # Cloudflare caps the `hosts` purge parameter at 30 per request.
    PURGE_CHUNK = 30

    def __init__(self, db: Session):
        self.db = db
        self.settings = SettingsRepository(db)

    def config(self) -> CloudflareConfig:
        values = self.settings.namespace(self.namespace)
        encrypted = self.settings.get_secure(self.credential_key)
        credential = ""
        if encrypted:
            try:
                credential = decrypt_secret(encrypted)
            except RuntimeError:
                credential = ""
        auth_type = str(values.get("auth_type") or "api_token").strip().lower()
        if auth_type not in {"api_token", "global_key"}:
            auth_type = "api_token"
        return CloudflareConfig(
            auth_type=auth_type,
            email=str(values.get("email") or "").strip(),
            credential=credential,
            account_id=str(values.get("account_id") or "").strip(),
            zone_id=str(values.get("zone_id") or "").strip(),
            zone_name=str(values.get("zone_name") or "example.com").strip().lower(),
        )

    def public_config(self) -> dict[str, Any]:
        cfg = self.config()
        return {
            "auth_type": cfg.auth_type,
            "email": cfg.email,
            "account_id": cfg.account_id,
            "zone_id": cfg.zone_id,
            "zone_name": cfg.zone_name,
            "credential_configured": bool(cfg.credential),
            "configured": cfg.configured,
        }

    def update_config(self, payload: dict[str, Any], actor_id: int) -> dict[str, Any]:
        auth_type = str(payload.get("auth_type") or "api_token").strip().lower()
        if auth_type not in {"api_token", "global_key"}:
            raise CloudflareError("cloudflare_invalid_auth_type", 422)

        zone_id = str(payload.get("zone_id") or "").strip()
        zone_name = str(payload.get("zone_name") or "").strip().lower()
        email = str(payload.get("email") or "").strip().lower()
        # Optional: only used to disambiguate a zone name that exists under
        # more than one account. See the note on CloudflareConfig.configured.
        account_id = str(payload.get("account_id") or "").strip()
        if not zone_id and not zone_name:
            raise CloudflareError("cloudflare_zone_required", 422)
        if auth_type == "global_key" and not email:
            raise CloudflareError("cloudflare_email_required", 422)

        values = {
            "auth_type": auth_type,
            "email": email,
            "account_id": account_id,
            "zone_id": zone_id,
            "zone_name": zone_name,
        }
        for key, value in values.items():
            self.settings.upsert(self.namespace, key, value, is_secret=False, commit=False)

        if bool(payload.get("clear_credential")):
            self.settings.delete_secure(self.credential_key, commit=False)
        else:
            credential = str(payload.get("credential") or "").strip()
            if credential:
                self.settings.upsert_secure(
                    self.credential_key,
                    encrypt_secret(credential),
                    actor_id,
                    commit=False,
                )

        self.db.commit()
        return self.public_config()

    def _headers(self, cfg: CloudflareConfig) -> dict[str, str]:
        if not cfg.credential:
            raise CloudflareError("cloudflare_credential_required", 422)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "SilverCode-Nexus-Admin/1.0",
        }
        if cfg.auth_type == "global_key":
            if not cfg.email:
                raise CloudflareError("cloudflare_email_required", 422)
            headers["X-Auth-Email"] = cfg.email
            headers["X-Auth-Key"] = cfg.credential
        else:
            headers["Authorization"] = f"Bearer {cfg.credential}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        cfg: CloudflareConfig,
        *,
        query: Optional[dict[str, str]] = None,
        body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = CLOUDFLARE_API_BASE + path
        if query:
            url += "?" + urlencode(query)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=data, headers=self._headers(cfg), method=method.upper())
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8", errors="replace")
                payload = json.loads(raw or "{}")
        except HTTPError as error:
            try:
                raw = error.read().decode("utf-8", errors="replace")
                payload = json.loads(raw or "{}")
            except Exception:
                payload = {}
            message = self._error_message(payload)
            if error.code in {401, 403}:
                detail = f"cloudflare_auth_failed (HTTP {error.code})"
                if message:
                    detail += f": {message}"
                # This is an upstream Cloudflare failure, not an expired admin
                # session. Keep the original status in the detail without
                # returning 401 to the admin client (which would log it out).
                raise CloudflareError(detail, 502) from error
            detail = message or f"cloudflare_http_{error.code}"
            raise CloudflareError(f"{detail} (HTTP {error.code})", 502) from error
        except (URLError, TimeoutError, OSError) as error:
            reason = str(getattr(error, "reason", error)).strip()
            detail = "cloudflare_request_failed"
            if reason:
                detail += f": {reason}"
            raise CloudflareError(detail, 502) from error
        except (ValueError, json.JSONDecodeError) as error:
            raise CloudflareError(f"cloudflare_invalid_response: {error}", 502) from error

        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise CloudflareError(self._error_message(payload) or "cloudflare_api_failed", 502)
        return payload

    @staticmethod
    def _error_message(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        errors = payload.get("errors")
        if not isinstance(errors, list) or not errors:
            return ""
        details: list[str] = []
        for item in errors[:5]:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            message = str(item.get("message") or "").strip()
            if code and message:
                details.append(f"cloudflare_error_{code}: {message}")
            elif message:
                details.append(message)
        return "; ".join(details)

    def resolve_zone_id(self, cfg: Optional[CloudflareConfig] = None) -> str:
        cfg = cfg or self.config()
        if cfg.zone_id:
            return cfg.zone_id
        if not cfg.zone_name:
            raise CloudflareError("cloudflare_zone_required", 422)
        query = {"name": cfg.zone_name, "status": "active", "per_page": "1"}
        # Only narrow by account when we actually know it -- filtering on an
        # empty account.id would match nothing.
        if cfg.account_id:
            query["account.id"] = cfg.account_id
        payload = self._request("GET", "/zones", cfg, query=query)
        result = payload.get("result")
        detail = f"cloudflare_zone_not_found: zone={cfg.zone_name}"
        if cfg.account_id:
            detail += f", account_id={cfg.account_id}"
        if not isinstance(result, list) or not result:
            raise CloudflareError(detail, 404)
        zone_id = str(result[0].get("id") or "").strip()
        if not zone_id:
            raise CloudflareError(detail, 404)
        return zone_id

    def list_hostnames(self, cfg: Optional[CloudflareConfig] = None) -> list[dict[str, Any]]:
        """Custom hostnames attached to the zone (Cloudflare for SaaS).

        example.com and example.com are *not* zones of their own -- they are custom
        hostnames riding on the isip.eu.cc zone, with cname.isip.eu.cc as the
        fallback origin. Knowing this list is what makes a correct purge
        possible; see purge_all().
        """
        cfg = cfg or self.config()
        zone_id = self.resolve_zone_id(cfg)
        hosts: list[dict[str, Any]] = []
        # 50 per page, capped at 20 pages (1000 hostnames) so a runaway loop
        # cannot spin forever.
        for page in range(1, 21):
            payload = self._request(
                "GET",
                f"/zones/{zone_id}/custom_hostnames",
                cfg,
                query={"per_page": "50", "page": str(page)},
            )
            rows = payload.get("result")
            if not isinstance(rows, list) or not rows:
                break
            hosts.extend(rows)
            if len(rows) < 50:
                break
        return hosts

    def purge_hosts(
        self,
        hosts: list[str],
        cfg: Optional[CloudflareConfig] = None,
    ) -> dict[str, Any]:
        """Purge by hostname -- Cloudflare's documented way to clear a custom
        hostname's cache under Cloudflare for SaaS."""
        cfg = cfg or self.config()
        if not cfg.configured:
            raise CloudflareError("cloudflare_not_configured", 422)
        zone_id = self.resolve_zone_id(cfg)

        cleaned: list[str] = []
        for host in hosts:
            name = str(host or "").strip().lower()
            if name and name not in cleaned:
                cleaned.append(name)
        if not cleaned:
            raise CloudflareError("cloudflare_no_hosts", 422)

        purge_ids: list[str] = []
        for start in range(0, len(cleaned), self.PURGE_CHUNK):
            chunk = cleaned[start : start + self.PURGE_CHUNK]
            payload = self._request(
                "POST",
                f"/zones/{zone_id}/purge_cache",
                cfg,
                body={"hosts": chunk},
            )
            result = payload.get("result")
            if isinstance(result, dict):
                purge_ids.append(str(result.get("id") or ""))

        return {
            "success": True,
            "mode": "hosts",
            "zone_id": zone_id,
            "zone_name": cfg.zone_name,
            "hosts": cleaned,
            "purge_ids": purge_ids,
            # kept for the existing admin UI, which reads a single id
            "purge_id": purge_ids[0] if purge_ids else "",
            "purged_at": datetime.now(timezone.utc).isoformat(),
        }

    def purge_all(self, mode: str = "hostnames") -> dict[str, Any]:
        """Clear the cache for everything this deployment publishes.

        Why this is not simply `{"purge_everything": true}`:

        The configured zone is `isip.eu.cc`, a Cloudflare for SaaS zone. The
        actual sites (example.com, www.example.com, account.example.com, example.com,
        ...) are *custom hostnames* on it. For that arrangement Cloudflare
        documents hostname purging as the correct instrument, and
        `purge_everything` would additionally blow away isip.eu.cc's own cache
        -- which has nothing to do with us.

        So the default mode enumerates the zone's custom hostnames and purges
        those. `mode="everything"` keeps the blunt behaviour for the case where
        the configured zone really is the site's own zone (no custom hostnames),
        which is also the automatic fallback.
        """
        cfg = self.config()
        if not cfg.configured:
            raise CloudflareError("cloudflare_not_configured", 422)

        if mode == "everything":
            zone_id = self.resolve_zone_id(cfg)
            payload = self._request(
                "POST",
                f"/zones/{zone_id}/purge_cache",
                cfg,
                body={"purge_everything": True},
            )
            result = payload.get("result")
            result = result if isinstance(result, dict) else {}
            return {
                "success": True,
                "mode": "everything",
                "zone_id": zone_id,
                "zone_name": cfg.zone_name,
                "purge_ids": [str(result.get("id") or "")],
                "purged_at": datetime.now(timezone.utc).isoformat(),
            }

        hostnames = [
            str(entry.get("hostname") or "").strip()
            for entry in self.list_hostnames(cfg)
            if entry.get("hostname")
        ]
        if not hostnames:
            # No SaaS hostnames: this zone *is* the site, so the blunt purge is
            # the only thing that can work here.
            return self.purge_all("everything")
        return self.purge_hosts(hostnames, cfg)
