import os
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.api.v1 import account, admin, admin_apikeys, admin_tools, auth, comments, dynamics, gallery, oauth, public
from app.api.v1.content_tools import admin_router as content_admin, account_router as content_account
from app.core.config import get_settings
from app.core.security import decode_token
from app.core.request_context import request_context
from app.db.session import engine
from app.fq.router import router as fq_router
from app.fq.admin import router as fq_admin_router


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", debug=settings.app_debug)


@app.exception_handler(HTTPException)
async def account_restriction_error(request: Request, error: HTTPException):
    response = JSONResponse(status_code=error.status_code, content={"detail": error.detail}, headers=error.headers)
    if error.status_code == 401 and isinstance(error.detail, str) and error.detail.startswith("账号封禁："):
        from app.api.v1.auth import _clear_session_cookie
        _clear_session_cookie(response, request)
    return response


_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Requested-With",
    ],
    allow_origin_regex=settings.cors_origin_regex,
)


def _origin_allowed(origin: str) -> bool:
    if not origin:
        return True
    normalized = origin.rstrip("/").lower()
    if normalized in {item.rstrip("/").lower() for item in settings.cors_origin_list}:
        return True
    return re.fullmatch(settings.cors_origin_regex, normalized) is not None


def _public_path(path: str) -> bool:
    # FQ routes validate their own scoped token, including login exchange.
    if path == "/fq" or path.startswith("/fq/"):
        return True
    if re.fullmatch(r"/(?:api/)?v1/public/(?:albums|dynamics)(?:/\d+)?", path):
        return True
    if path == "/healthz":
        return True
    public_exact = {
        "/v1/public/site",
        "/v1/public/articles",
        "/v1/public/friends",
        "/v1/public/comments",
        "/v1/public/songs",
        # 主站友链页的内嵌申请：面向匿名访客，必须公网可达。
        # 安全性由 6 位邮箱验证码 + 统一限流保证，不是靠登录态。
        "/v1/public/friend-links/verification/send",
        "/v1/public/friend-links/apply",
        "/v1/auth/login",
        "/v1/auth/verification/send",
        "/v1/auth/register/verify",
        "/v1/auth/password/setup",
        "/v1/auth/code-login",
        "/v1/auth/password-reset/verify",
        "/v1/auth/password-reset/confirm",
        "/v1/auth/refresh",
        # Cookie-only endpoints. These read the HttpOnly session cookie and
        # rotate it forward, so they must never be gated behind a Bearer
        # access token -- otherwise a short access token expiry looks like a
        # dead session to the polling client.
        "/v1/auth/session",
        "/v1/auth/status",
        "/v1/auth/logout",
        "/v1/account/friend-links/verification/confirm",
        # OAuth protocol surface. The token/authorize/userinfo endpoints carry
        # their own authentication (client secret and/or PKCE, or an OAuth
        # bearer token), so they must not be gated behind the first-party
        # session access token.
        "/oauth/authorize",
        "/oauth/authorize/consent",
        "/oauth/authorize/context",
        "/oauth/authorize/approve",
        "/oauth/authorize/deny",
        "/oauth/token",
        "/oauth/userinfo",
        "/oauth/introspect",
        "/oauth/revoke",
        "/oauth/scopes",
        "/oauth/debug",
        "/v1/oauth/authorize",
        "/v1/oauth/authorize/consent",
        "/v1/oauth/token",
        "/v1/oauth/userinfo",
        "/v1/oauth/introspect",
        "/v1/oauth/revoke",
        "/v1/oauth/scopes",
        "/v1/oauth/debug",
    }
    if path in public_exact:
        return True
    if path.startswith("/oauth/."):
        # RFC 8414 / OIDC discovery documents.
        return True
    if path in {"/v1/oauth/.well-known/oauth-authorization-server", "/v1/oauth/.well-known/openid-configuration"}:
        return True
    if path == "/.well-known/replow-verify.txt":
        # Domain-ownership proof for this API's own origin; must be readable
        # by the verifier without credentials.
        return True
    if path in {"/v1/public/heif-source", "/api/v1/public/heif-source"}:
        return True
    if path.startswith("/v1/public/media/"):
        return True
    return path.startswith("/v1/public/articles/")


def _has_valid_access_token(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return False
    try:
        decode_token(token.strip())
    except (HTTPException, RuntimeError):
        return False
    return True


@app.middleware("http")
async def api_access_guard(request: Request, call_next):
    origin = request.headers.get("origin", "")
    if not _origin_allowed(origin):
        return JSONResponse(
            status_code=403,
            content={"detail": "origin_not_allowed"},
        )
    if request.method == "OPTIONS" or _public_path(request.url.path):
        return await call_next(request)
    if not _has_valid_access_token(request):
        return JSONResponse(
            status_code=401,
            content={"detail": "not_authenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


@app.middleware("http")
async def session_request_metadata(request: Request, call_next):
    import ipaddress
    raw_ip = (request.headers.get("cf-connecting-ip") or
              request.headers.get("x-forwarded-for", "").split(",")[0].strip() or
              (request.client.host if request.client else ""))
    try:
        ip = str(ipaddress.ip_address(raw_ip))
    except ValueError:
        ip = ""
    header = request.headers.get("authorization", "")
    token = request_context.set({
        "ip": ip, "user_agent": request.headers.get("user-agent", "")[:512],
        "access_token": header[7:] if header.lower().startswith("bearer ") else "",
        "refresh_token": request.cookies.get(settings.session_cookie_name, "")
    })
    try:
        return await call_next(request)
    finally:
        request_context.reset(token)


@app.middleware("http")
async def public_content_cache_control(request: Request, call_next):
    response = await call_next(request)
    if re.fullmatch(r"/(?:api/)?v1/(?:public/(?:comments|articles/[^/]+/discussion)|account(?:/.*)?)", request.url.path) or request.url.path == "/fq" or request.url.path.startswith("/fq/") or re.fullmatch(r"/(?:api/)?v1/admin/fq(?:/.*)?", request.url.path) or re.fullmatch(r"/(?:api/)?v1/public/(?:albums|dynamics)(?:/[^/]*)?", request.url.path):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["CDN-Cache-Control"] = "no-store"
        response.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/")
def root():
    return {"service": "replow-api", "version": app.version, "docs": "/docs"}


@app.get("/healthz")
def healthz():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "service": "replow-api", "database": "ok"}


@app.get("/oauth/debug")
@app.get("/v1/oauth/debug")
def oauth_debug_page():
    """Interactive console for exercising the OAuth flow end to end."""
    path = os.path.normpath(os.path.join(_STATIC_DIR, "oauth-debug.html"))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="debug_page_missing")
    return FileResponse(path, media_type="text/html")


@app.get("/oauth/authorize/consent")
@app.get("/v1/oauth/authorize/consent")
def oauth_consent_page():
    """Consent screen the authorize endpoint redirects to.

    Pure HTML shell: the query string carries client_id / redirect_uri /
    scope / state / code_challenge, and the page reads them client-side to
    call ``/oauth/authorize/context`` and ``/oauth/authorize/approve``.

    It must stay reachable without a Bearer token -- the browser lands here
    via a top-level 302 from ``/oauth/authorize``, which cannot carry an
    Authorization header. The page itself then requires the viewer to supply
    a token before it can read context or approve.
    """
    path = os.path.normpath(os.path.join(_STATIC_DIR, "oauth-consent.html"))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="consent_page_missing")
    return FileResponse(path, media_type="text/html")


@app.get("/.well-known/replow-verify.txt")
def verify_ownership_file():
    """Serve the domain-ownership token for api.example.com itself.

    The HTTP verification channel checks ``<origin>/.well-known/replow-verify.txt``
    on the registrant's site. Publishing this API's own token at the same path
    lets the endpoint verify itself, which is what makes an end-to-end test of
    the positive path possible without standing up a second host.
    """
    path = os.path.normpath(os.path.join(_STATIC_DIR, ".well-known", "replow-verify.txt"))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="verification_file_missing")
    return FileResponse(path, media_type="text/plain")


from app.fq.reading import router as reading_router
app.include_router(reading_router)
app.include_router(fq_router)
app.include_router(public.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(account.router, prefix=settings.api_prefix)
app.include_router(comments.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(content_admin, prefix=settings.api_prefix)
app.include_router(content_account, prefix=settings.api_prefix)
app.include_router(fq_admin_router, prefix=settings.api_prefix)
app.include_router(admin_tools.router, prefix=settings.api_prefix)
app.include_router(gallery.router, prefix=settings.api_prefix)
app.include_router(dynamics.router, prefix=settings.api_prefix)
app.include_router(dynamics.admin_router, prefix=settings.api_prefix)
app.include_router(admin_apikeys.router, prefix=settings.api_prefix)

# OAuth is exposed twice on purpose. Every other new-stack contract stays
# under /v1, but the product-facing authorization endpoint is published as
# api.example.com/oauth so third-party clients get a short, memorable URL. The
# /v1 alias keeps the api_modules registry entry (/api/v1/oauth) honest.
app.include_router(oauth.router)
app.include_router(oauth.router, prefix=settings.api_prefix)

# The new Firefly/admin contract is served from direct /v1. The old PHP v1/v2
# contracts are routed by Nginx and are intentionally not moved into this
# process.
if settings.api_prefix != "/v1":
    app.include_router(public.router, prefix="/v1")
    app.include_router(auth.router, prefix="/v1")
    app.include_router(account.router, prefix="/v1")
    app.include_router(comments.router, prefix="/v1")
    app.include_router(admin.router, prefix="/v1")
    app.include_router(content_admin, prefix="/v1")
    app.include_router(content_account, prefix="/v1")
    app.include_router(fq_admin_router, prefix="/v1")
    app.include_router(admin_tools.router, prefix="/v1")
    app.include_router(gallery.router, prefix="/v1")
    app.include_router(dynamics.router, prefix="/v1")
    app.include_router(dynamics.admin_router, prefix="/v1")
    app.include_router(admin_apikeys.router, prefix="/v1")
    app.include_router(oauth.router, prefix="/v1")

