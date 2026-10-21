from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.db.session import get_db
from app.services.oauth import OAuthError, OAuthService


router = APIRouter(prefix="/oauth", tags=["oauth"])

SCOPE_CATALOG = [
    {
        "scope": "profile",
        "name": "基础资料",
        "description": "读取你的用户名、昵称与头像",
        "required": True,
    },
    {
        "scope": "email",
        "name": "邮箱地址",
        "description": "读取你账号绑定的邮箱",
        "required": False,
    },
]


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _oauth_error_response(error: OAuthError) -> JSONResponse:
    """RFC 6749 §5.2 error body for the token endpoint."""
    return JSONResponse(
        status_code=error.status_code if error.status_code != 401 else 401,
        content={"error": error.error, "error_description": error.description},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _raise(error: OAuthError) -> None:
    raise HTTPException(status_code=error.status_code, detail={
        "error": error.error,
        "error_description": error.description,
    }) from error


# -- discovery -----------------------------------------------------------


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/openid-configuration")
def discovery(request: Request):
    """Minimal RFC 8414 authorization-server metadata."""
    base = str(request.base_url).rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "userinfo_endpoint": f"{base}/oauth/userinfo",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "registration_endpoint": f"{base}/oauth/clients",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
        "scopes_supported": [item["scope"] for item in SCOPE_CATALOG],
    }


@router.get("/scopes")
def scopes():
    return {"data": SCOPE_CATALOG}


# -- authorize -----------------------------------------------------------


@router.get("/authorize")
def authorize(
    request: Request,
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    response_type: str = Query("code"),
    scope: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    code_challenge: Optional[str] = Query(None),
    code_challenge_method: Optional[str] = Query("S256"),
    db: Session = Depends(get_db),
):
    """Validate the request, then bounce to the consent screen.

    Errors that happen *before* the redirect_uri is trusted must never
    redirect; they are returned as JSON so a hostile client cannot use this
    endpoint as an open redirector.
    """
    service = OAuthService(db)
    try:
        ctx = service.validate_authorize_request(
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
        )
    except OAuthError as error:
        if error.description == "redirect_uri_mismatch" or error.error == "invalid_client":
            return _oauth_error_response(error)
        # The redirect_uri is trusted from here on, so report via redirect.
        params = {"error": error.error, "error_description": error.description}
        if state:
            params["state"] = state
        return RedirectResponse(service.build_redirect(redirect_uri, params), status_code=302)

    consent_url = "/oauth/authorize/consent?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": ctx["scope"],
            "state": ctx["state"],
            "code_challenge": ctx["code_challenge"],
            "code_challenge_method": ctx["code_challenge_method"],
        }
    )
    # ``consent=1`` lets a client skip the UI when the user already approved;
    # the consent page re-validates everything, so this is only a hint.
    consent_url += "&consent=1"
    return RedirectResponse(consent_url, status_code=302)


@router.get("/authorize/context")
def authorize_context(
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    response_type: str = Query("code"),
    scope: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    code_challenge: Optional[str] = Query(None),
    code_challenge_method: Optional[str] = Query("S256"),
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Everything the consent screen needs, plus the viewer's identity."""
    service = OAuthService(db)
    try:
        ctx = service.validate_authorize_request(
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
        )
    except OAuthError as error:
        _raise(error)
    client = ctx["client"]
    return {
        "data": {
            "client": {
                "client_id": client["client_id"],
                "name": client["name"],
                "icon_url": client.get("icon_url") or "",
                "description": client.get("description") or "",
            },
            "redirect_uri": ctx["redirect_uri"],
            "scope": ctx["scope"],
            "scopes": [item for item in SCOPE_CATALOG if item["scope"] in ctx["scope"].split()],
            "state": ctx["state"],
            "user": {
                "uid": int(user["uid"]),
                "username": user["username"],
                "display_name": user.get("display_name") or user["username"],
                "avatar_url": user.get("avatar_url") or "",
            },
        }
    }


@router.post("/authorize/approve")
def authorize_approve(
    payload: dict[str, Any],
    request: Request,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Issue an authorization code after the user consents."""
    service = OAuthService(db)
    try:
        ctx = service.validate_authorize_request(
            client_id=str(payload.get("client_id") or ""),
            redirect_uri=str(payload.get("redirect_uri") or ""),
            response_type="code",
            scope=payload.get("scope"),
            code_challenge=payload.get("code_challenge"),
            code_challenge_method=str(payload.get("code_challenge_method") or "S256"),
            state=payload.get("state"),
        )
        code = service.issue_authorization_code(
            client_id=ctx["client"]["client_id"],
            user_uid=int(user["uid"]),
            redirect_uri=ctx["redirect_uri"],
            scope=ctx["scope"],
            code_challenge=ctx["code_challenge"],
            code_challenge_method=ctx["code_challenge_method"],
            created_ip=_client_ip(request),
        )
    except OAuthError as error:
        _raise(error)

    params = {"code": code}
    if ctx["state"]:
        params["state"] = ctx["state"]
    return {
        "data": {
            "code": code,
            "state": ctx["state"],
            "redirect_to": service.build_redirect(ctx["redirect_uri"], params),
        }
    }


@router.post("/authorize/deny")
def authorize_deny(payload: dict[str, Any], db: Session = Depends(get_db)):
    service = OAuthService(db)
    params = {"error": "access_denied", "error_description": "user_denied"}
    state = str(payload.get("state") or "")
    if state:
        params["state"] = state
    redirect_uri = str(payload.get("redirect_uri") or "")
    return {"data": {"redirect_to": service.build_redirect(redirect_uri, params) if redirect_uri else ""}}


# -- token ---------------------------------------------------------------


@router.post("/token")
def token(
    request: Request,
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: Optional[str] = Form(None),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    scope: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """RFC 6749 §4.1.3 / §6 token endpoint."""
    service = OAuthService(db)
    try:
        if grant_type == "authorization_code":
            if not code or not redirect_uri or not code_verifier:
                raise OAuthError("invalid_request", "missing_code_parameters", 400)
            result = service.exchange_authorization_code(
                client_id=client_id,
                client_secret=client_secret,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
                created_ip=_client_ip(request),
            )
        elif grant_type == "refresh_token":
            if not refresh_token:
                raise OAuthError("invalid_request", "missing_refresh_token", 400)
            result = service.refresh_token_grant(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                scope=scope,
            )
        else:
            raise OAuthError("unsupported_grant_type", f"grant_type:{grant_type}", 400)
    except OAuthError as error:
        return _oauth_error_response(error)

    return JSONResponse(content=result, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def _extract_bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise OAuthError("invalid_token", "bearer_token_required", 401)
    return value.strip()


@router.get("/userinfo")
def userinfo(request: Request, db: Session = Depends(get_db)):
    service = OAuthService(db)
    try:
        return service.userinfo(_extract_bearer(request))
    except OAuthError as error:
        return _oauth_error_response(error)


@router.post("/introspect")
def introspect(request: Request, token: str = Form(...), db: Session = Depends(get_db)):
    service = OAuthService(db)
    try:
        record = service.resolve_access_token(token)
    except OAuthError:
        return {"active": False}
    return {
        "active": True,
        "client_id": str(record["client_id"]),
        "sub": str(record["user_uid"]),
        "scope": str(record["scope"]),
        "exp": int(record["access_expires_at"].timestamp()),
    }


@router.post("/revoke")
def revoke(
    token: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """RFC 7009 revocation. Always 200, even for unknown tokens."""
    OAuthService(db).revoke(access_token=token, refresh_token=refresh_token)
    return {"success": True}


# -- client self-service / account consoles -----------------------------


@router.get("/clients")
def list_clients(
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    clients = OAuthService(db).repo.list_clients(int(user["uid"]))
    return {
        "data": [
            {
                "client_id": item["client_id"],
                "name": item["name"],
                "icon_url": item.get("icon_url") or "",
                "description": item.get("description") or "",
                "redirect_uris": item["redirect_uris"],
                "confidential": bool(item["confidential"]),
                "enabled": bool(item["enabled"]),
                "created_at": item["created_at"],
            }
            for item in clients
        ]
    }


@router.post("/clients")
def create_client(
    payload: dict[str, Any],
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    redirect_uris = payload.get("redirect_uris")
    if isinstance(redirect_uris, str):
        redirect_uris = [item.strip() for item in redirect_uris.splitlines() if item.strip()]
    service = OAuthService(db)
    try:
        client = service.register_client(
            name=str(payload.get("name") or ""),
            redirect_uris=list(redirect_uris or []),
            owner_uid=int(user["uid"]),
            description=str(payload.get("description") or ""),
            icon_url=str(payload.get("icon_url") or ""),
            confidential=bool(payload.get("confidential", True)),
        )
    except OAuthError as error:
        _raise(error)
    client.pop("client_secret_hash", None)
    return {"data": client}


@router.put("/clients/{client_id}")
def update_client(
    client_id: str,
    payload: dict[str, Any],
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    redirect_uris = payload.get("redirect_uris")
    encoded: Optional[str] = None
    if redirect_uris is not None:
        if isinstance(redirect_uris, str):
            redirect_uris = [item.strip() for item in redirect_uris.splitlines() if item.strip()]
        for uri in redirect_uris:
            if not OAuthService._valid_redirect_uri(str(uri)):
                raise HTTPException(status_code=422, detail=f"invalid_redirect_uri:{uri}")
        import json as _json

        encoded = _json.dumps([str(item) for item in redirect_uris])

    service = OAuthService(db)
    try:
        service._require_client(client_id, int(user["uid"]))
    except OAuthError as error:
        _raise(error)

    updated = service.repo.update_client(
        client_id,
        name=payload.get("name"),
        description=payload.get("description"),
        icon_url=payload.get("icon_url"),
        redirect_uris=encoded,
        enabled=payload.get("enabled"),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="client_not_found")
    updated.pop("client_secret_hash", None)
    return {"data": updated}


@router.post("/clients/{client_id}/secret")
def rotate_secret(
    client_id: str,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    service = OAuthService(db)
    try:
        result = service.rotate_client_secret(client_id, int(user["uid"]))
    except OAuthError as error:
        _raise(error)
    return {"data": {"client_id": result["client_id"], "client_secret": result["client_secret"]}}


@router.delete("/clients/{client_id}")
def delete_client(
    client_id: str,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    service = OAuthService(db)
    try:
        service._require_client(client_id, int(user["uid"]))
    except OAuthError as error:
        _raise(error)
    removed = service.repo.delete_client(client_id, int(user["uid"]))
    if not removed:
        raise HTTPException(status_code=404, detail="client_not_found")
    return {"success": True}


@router.get("/connections")
def connections(
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Apps the signed-in user has authorized."""
    service = OAuthService(db)
    return {
        "data": [
            {
                "client_id": item["client_id"],
                "client_name": item.get("client_name") or item["client_id"],
                "icon_url": item.get("icon_url") or "",
                "description": item.get("description") or "",
                "scope": item["scope"],
                "granted_at": item.get("granted_at"),
                "last_used_at": item.get("last_used_at"),
            }
            for item in service.connected_apps(int(user["uid"]))
        ]
    }


@router.delete("/connections/{client_id}")
def revoke_connection(
    client_id: str,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    count = OAuthService(db).revoke_grant(client_id=client_id, user_uid=int(user["uid"]))
    return {"success": True, "revoked": count}
