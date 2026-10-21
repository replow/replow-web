from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.security import (
    current_user,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import (
    AccountSetupRequest,
    CodeLoginRequest,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetVerifyRequest,
    PasswordSetupRequest,
    RegisterCodeRequest,
    TokenData,
    VerificationSendRequest,
    UserSummary,
)
from app.services.account import AccountError, AccountService
from app.services.auth import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _user_summary(user: dict) -> UserSummary:
    return UserSummary(
        uid=int(user["uid"]),
        username=str(user["username"]),
        email=str(user["email"]),
        display_name=str(user.get("display_name") or user["username"]),
        avatar_url=str(user.get("avatar_url") or ""),
        role=str(user.get("role") or "user"),
        status=str(user.get("status") or "active"),
        setup_completed=bool(user.get("setup_completed", True)),
    )


def _token_data(user: dict, access_token: str, refresh_token: str, expires) -> TokenData:
    role = str(user.get("role") or "user")
    return TokenData(
        accessToken=access_token,
        refreshToken=refresh_token,
        expires=expires,
        avatar=str(user.get("avatar_url") or ""),
        username=str(user["username"]),
        nickname=str(user.get("display_name") or user["username"]),
        roles=[role],
        permissions=["*:*:*"] if role == "admin" else [],
    )


def _session_cookie_kwargs(request: Request | None = None) -> dict:
    """Shared cookie attributes for every host that participates in SSO.

    ``domain`` is the critical one: without it the browser pins the cookie to
    the API host (api.example.com) and every other first-party surface loses the
    session on the next request. It is resolved per request because a single
    process serves more than one registrable domain.
    """
    host = request.headers.get("host") if request is not None else None
    kwargs: dict = {
        "key": settings.session_cookie_name,
        "httponly": True,
        "secure": settings.session_cookie_secure,
        "samesite": settings.session_cookie_samesite,
        "path": "/",
    }
    domain = settings.cookie_domain_for_host(host)
    if domain:
        kwargs["domain"] = domain
    return kwargs


def _set_session_cookie(response: Response, refresh_token: str, request: Request | None = None) -> None:
    response.set_cookie(
        value=refresh_token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        **_session_cookie_kwargs(request),
    )


def _clear_session_cookie(response: Response, request: Request | None = None) -> None:
    response.delete_cookie(**_session_cookie_kwargs(request))


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    identity = payload.resolved_identity
    if not identity:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="identity_required")
    service = AuthService(db)
    user = service.authenticate(identity, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    access_token, refresh_token, expires = service.issue_tokens(user, new_session=True)
    data = _token_data(user, access_token, refresh_token, expires)
    _set_session_cookie(response, refresh_token, request)
    return LoginResponse(data=data)


def _raise_account_error(error: AccountError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/verification/send")
def send_verification_code(
    payload: VerificationSendRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    service = AccountService(db)
    try:
        return service.request_code(
            email=payload.email,
            purpose=payload.purpose,
            ip=_client_ip(request),
            username=payload.username,
            display_name=payload.display_name,
        )
    except AccountError as error:
        _raise_account_error(error)


@router.post("/register/verify")
def verify_registration(payload: RegisterCodeRequest, db: Session = Depends(get_db)):
    try:
        return AccountService(db).register_by_code(
            username=payload.username,
            email=payload.email,
            code=payload.code,
            display_name=payload.display_name,
        )
    except AccountError as error:
        _raise_account_error(error)


@router.post("/password/setup", response_model=LoginResponse)
def setup_password(
    payload: PasswordSetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        result = AccountService(db).set_signup_password(
            payload.signup_token, payload.password
        )
        _set_session_cookie(response, result["data"]["refreshToken"], request)
        return LoginResponse.model_validate(result)
    except AccountError as error:
        _raise_account_error(error)


@router.post("/code-login", response_model=LoginResponse)
def code_login(
    payload: CodeLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        result = AccountService(db).login_by_code(
            email=payload.email, code=payload.code
        )
        _set_session_cookie(response, result["data"]["refreshToken"], request)
        return LoginResponse.model_validate(result)
    except AccountError as error:
        _raise_account_error(error)


@router.post("/account/setup", response_model=LoginResponse)
def complete_account_setup(
    payload: AccountSetupRequest,
    request: Request,
    response: Response,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Set username + password on an account created by a first-time code login."""
    try:
        result = AccountService(db).complete_setup(
            user=user,
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
        )
        _set_session_cookie(response, result["data"]["refreshToken"], request)
        return LoginResponse.model_validate(result)
    except AccountError as error:
        _raise_account_error(error)


@router.post("/account/setup/skip", response_model=LoginResponse)
def skip_account_setup(
    request: Request,
    response: Response,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Dismiss the setup dialog; keep the generated username, stay password-less."""
    try:
        result = AccountService(db).skip_setup(user=user)
        _set_session_cookie(response, result["data"]["refreshToken"], request)
        return LoginResponse.model_validate(result)
    except AccountError as error:
        _raise_account_error(error)


@router.post("/password-reset/verify")
def verify_password_reset(
    payload: PasswordResetVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        return AccountService(db).verify_reset_code(
            email=payload.email, code=payload.code, ip=_client_ip(request)
        )
    except AccountError as error:
        _raise_account_error(error)


@router.post("/password-reset/confirm", response_model=LoginResponse)
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        result = AccountService(db).reset_password(
            token=payload.reset_token, password=payload.password
        )
        _set_session_cookie(response, result["data"]["refreshToken"], request)
        return LoginResponse.model_validate(result)
    except AccountError as error:
        _raise_account_error(error)


@router.post("/me/password/verification")
def send_my_password_change_code(
    request: Request,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        return AccountService(db).request_password_change_code(user=user, ip=_client_ip(request))
    except AccountError as error:
        _raise_account_error(error)


@router.post("/me/password", response_model=LoginResponse)
def change_my_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = AccountService(db).change_password(
            user=user,
            new_password=payload.new_password,
            code=payload.code,
        )
        _set_session_cookie(response, result["data"]["refreshToken"], request)
        return LoginResponse.model_validate(result)
    except AccountError as error:
        _raise_account_error(error)


@router.post("/refresh", response_model=LoginResponse)
def refresh(
    payload: dict,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    token = str(
        payload.get("refreshToken")
        or payload.get("refresh_token")
        or request.cookies.get(settings.session_cookie_name)
        or ""
    )
    service = AuthService(db)
    user, access_token, new_refresh_token, expires = service.refresh(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account_unavailable")
    data = _token_data(user, access_token, new_refresh_token, expires)
    _set_session_cookie(response, new_refresh_token, request)
    return LoginResponse(data=data)


@router.post("/session", response_model=LoginResponse)
def session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Restore one API session for account, admin, and the public site."""
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    try:
        user, access_token, new_refresh_token, expires = AuthService(db).refresh(token)
    except HTTPException:
        _clear_session_cookie(response, request)
        raise
    if not user:
        _clear_session_cookie(response, request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account_unavailable")
    _set_session_cookie(response, new_refresh_token, request)
    return LoginResponse(data=_token_data(user, access_token, new_refresh_token, expires))


@router.post("/status")
def auth_status(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Return login metadata without exposing access or refresh tokens."""
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return {"authenticated": False}
    try:
        user, _, new_refresh_token, _ = AuthService(db).refresh(token)
    except HTTPException:
        _clear_session_cookie(response, request)
        return {"authenticated": False}
    if not user:
        _clear_session_cookie(response, request)
        return {"authenticated": False}
    _set_session_cookie(response, new_refresh_token, request)
    return {"authenticated": True, "user": _user_summary(user).model_dump()}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    from app.core.security import decode_token
    from app.repositories.sessions import SessionRepository
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        try:
            claims = decode_token(token, "refresh")
            if claims.get("sid"):
                SessionRepository(db).revoke(int(claims["sub"]), claims["sid"])
        except HTTPException:
            pass
    _clear_session_cookie(response, request)
    return {"success": True}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {"data": _user_summary(user).model_dump()}


@router.get("/sessions")
def my_sessions(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    from app.repositories.sessions import SessionRepository
    items = SessionRepository(db).list_active(int(user["uid"]), int(user.get("session_version") or 0))
    for item in items:
        item["is_current"] = item["id"] == user.get("_session_id")
    return {"items": items, "tracked_current": bool(user.get("_session_id"))}


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, request: Request, response: Response,
                   user: dict = Depends(current_user), db: Session = Depends(get_db)):
    from app.repositories.sessions import SessionRepository
    if not SessionRepository(db).revoke(int(user["uid"]), session_id):
        raise HTTPException(404, "session_not_found")
    current = session_id == user.get("_session_id")
    if current:
        _clear_session_cookie(response, request)
    return {"success": True, "current_revoked": current}


@router.post("/sessions/revoke-others", response_model=LoginResponse)
def revoke_other_sessions(payload: dict, request: Request, response: Response,
                          user: dict = Depends(current_user), db: Session = Depends(get_db)):
    from app.repositories.sessions import SessionRepository
    if payload.get("confirmed") is not True:
        raise HTTPException(422, "confirmation_required")
    sid = user.get("_session_id")
    if not sid:
        raise HTTPException(409, "session_refresh_required")
    version = SessionRepository(db).revoke_others(int(user["uid"]), sid, int(user.get("session_version") or 0))
    if version is None:
        raise HTTPException(401, "session_revoked")
    user["session_version"] = version
    access, refresh, expires = AuthService(db).issue_tokens(user, session_id=sid)
    _set_session_cookie(response, refresh, request)
    return LoginResponse(data=_token_data(user, access, refresh, expires))
