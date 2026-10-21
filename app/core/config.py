from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    app_name: str = "Replow API"
    app_env: str = "staging"
    app_debug: bool = False
    # Direct API used by the new stack. Legacy /api/v1 and /api/v2 traffic is
    # kept outside this FastAPI process so the old PHP API can remain stable.
    api_prefix: str = "/v1"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_database: str = "replow-next"
    db_username: str = "replow_next"
    db_password: str = ""

    jwt_secret: str = ""
    access_token_minutes: int = 720
    # The refresh token and the cross-site SSO cookie both represent one
    # browser session. Keep their lifetime aligned with the product policy.
    refresh_token_days: int = 14
    session_cookie_name: str = "replow_sso"
    session_cookie_secure: bool = True
    # A single SharedSession cookie must be readable by every first-party
    # surface, otherwise each host falls back to its own origin-scoped storage
    # and the login silently drops on navigation between sites.
    #
    # Browsers never share a cookie across registrable domains, so example.com
    # and example.com each need their own cookie. The domain is derived per request
    # from the Host header against this allowlist; a host that matches nothing
    # gets a host-only cookie (previous behaviour). Comma-separated, each entry
    # is the registrable domain with a leading dot.
    session_cookie_domains: str = ".example.com,.example.com"
    # Fallback used when the request Host cannot be matched. Empty means the
    # cookie stays host-only.
    session_cookie_domain: str = ""
    # SameSite for the session cookie. "lax" is correct once every surface
    # reaches the API on its own registrable domain, because all calls are then
    # same-site. Keep "none" only while a cross-site API host is still in use.
    session_cookie_samesite: str = "lax"

    cors_origins: str = (
        "https://example.com,https://www.example.com,"
        "https://example.com,https://www.example.com,"
        "https://account.example.com,https://account.example.com,"
        "https://admin.example.com,https://admin.example.com"
    )
    # Browser origins allowed for both apex domains and any HTTPS subdomain.
    cors_origin_regex: str = r"^https://([a-z0-9-]+\.)*(example\.com|example\.com)$"
    redis_url: str = ""

    # SMTP defaults are intentionally environment-driven. The admin panel can
    # store the same settings in the database, while passwords stay encrypted
    # in secure_settings.
    mail_smtp_host: str = ""
    mail_smtp_port: int = 465
    mail_smtp_username: str = ""
    mail_smtp_password: str = ""
    mail_from: str = ""
    mail_sender_name: str = "SilverCode"
    mail_use_tls: bool = True
    mail_use_ssl: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="mysql+pymysql",
            username=self.db_username,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_database,
            query={"charset": "utf8mb4"},
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def session_cookie_domain_list(self) -> list[str]:
        return [item.strip() for item in self.session_cookie_domains.split(",") if item.strip()]

    def cookie_domain_for_host(self, host: Optional[str]) -> str:
        """Pick the cookie domain that covers the requesting host.

        A host matches when it equals the domain minus the leading dot or ends
        with the dot-prefixed suffix, so ``account.example.com`` matches
        ``.example.com`` while ``api.example.com`` matches ``.example.com``. An unmatched
        host falls back to the configured default (usually host-only), which is
        still correct — the cookie simply does not cross that host.
        """
        candidate = (host or "").split(":")[0].strip().lower()
        if candidate:
            for domain in self.session_cookie_domain_list:
                suffix = domain if domain.startswith(".") else "." + domain
                bare = suffix.lstrip(".")
                if candidate == bare or candidate.endswith(suffix):
                    return suffix
        return self.session_cookie_domain


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
