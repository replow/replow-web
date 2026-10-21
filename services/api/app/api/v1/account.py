from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.friend_payload import friend_application_payload
from app.api.v1.validation import (
    client_ip,
    text_field,
    url_field,
)
from app.core.security import current_user
from app.db.session import get_db
from app.repositories.account import AccountRepository
from app.services.account import AccountError, AccountService
from app.services.admin import AdminError, AdminService
from app.services.portal import PortalService


router = APIRouter(prefix="/account", tags=["account"])


def _raise(error: AccountError | AdminError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


# 这几个校验函数已抽到 validation.py 与 public.py 共用（主站友链申请要用同一套规则）。
# 这里用别名导入，调用点保持不变。
_client_ip = client_ip
_text = text_field
_url = url_field


def _account_article_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    status = str(data.get("status") or "draft").strip()
    if status not in {"draft", "pending", "published"}:
        raise HTTPException(status_code=422, detail="invalid_article_status")
    data["status"] = status
    data["is_pinned"] = False
    return data


@router.get("/overview")
def overview(
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    repository = AccountRepository(db)
    return {
        "data": {
            "profile": repository.profile(int(user["uid"])),
            "counts": repository.overview(int(user["uid"])),
            "notifications": repository.notifications(int(user["uid"]), 6),
        }
    }


@router.get("/profile")
def profile(
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    data = AccountRepository(db).profile(int(user["uid"]))
    if not data:
        raise HTTPException(status_code=404, detail="account_not_found")
    return {"data": data}


@router.put("/profile")
def update_profile(
    payload: dict[str, Any],
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    display_name = _text(
        payload.get("display_name", user.get("display_name")),
        field="display_name",
        max_length=80,
        required=True,
    )
    avatar_url = _url(payload.get("avatar_url"), field="avatar_url")
    website_url = _url(payload.get("website_url"), field="website_url")
    bio = _text(payload.get("bio"), field="bio", max_length=500)
    data = AccountRepository(db).update_profile(
        int(user["uid"]),
        display_name=display_name,
        avatar_url=avatar_url,
        bio=bio,
        website_url=website_url,
    )
    if not data:
        raise HTTPException(status_code=404, detail="account_not_found")
    return {"success": True, "data": data}


@router.post("/email/verification")
def send_email_change_code(
    payload: dict[str, Any],
    request: Request,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        return PortalService(db).request_email_change_code(
            user=user,
            new_email=str(payload.get("email") or ""),
            ip=_client_ip(request),
        )
    except AccountError as error:
        _raise(error)


@router.post("/email/change")
def change_email(
    payload: dict[str, Any],
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        data = PortalService(db).confirm_email_change(
            user=user,
            new_email=str(payload.get("email") or ""),
            code=str(payload.get("code") or ""),
        )
        return {"success": True, "data": data}
    except AccountError as error:
        _raise(error)


@router.post("/password/verification")
def send_password_change_code(
    request: Request,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        return AccountService(db).request_password_change_code(user=user, ip=_client_ip(request))
    except AccountError as error:
        _raise(error)


@router.post("/password")
def change_password(
    payload: dict[str, Any],
    request: Request,
    response: Response,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = AccountService(db).change_password(
            user=user,
            code=str(payload.get("code") or ""),
            new_password=str(payload.get("new_password") or ""),
        )
        # Keep the browser's shared HttpOnly session aligned with the new
        # session version returned after a password change.
        from app.api.v1.auth import _set_session_cookie

        _set_session_cookie(response, result["data"]["refreshToken"], request)
        return result
    except AccountError as error:
        _raise(error)


@router.get("/articles")
def articles(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = None,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    items, total = AccountRepository(db).list_articles(
        int(user["uid"]), limit, offset, search
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/articles")
def create_article(
    payload: dict[str, Any],
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        data = AdminService(db).create_article(
            _account_article_payload(payload), int(user["uid"])
        )
        return {"data": data}
    except AdminError as error:
        _raise(error)


@router.get("/articles/{article_id}")
def article(
    article_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    data = AccountRepository(db).get_article(int(user["uid"]), article_id)
    if not data:
        raise HTTPException(status_code=404, detail="article_not_found")
    return {"data": data}


@router.put("/articles/{article_id}")
def update_article(
    article_id: int,
    payload: dict[str, Any],
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    repository = AccountRepository(db)
    if not repository.get_article(int(user["uid"]), article_id):
        raise HTTPException(status_code=404, detail="article_not_found")
    try:
        data = AdminService(db).update_article(
            article_id, _account_article_payload(payload)
        )
        if not data:
            raise HTTPException(status_code=404, detail="article_not_found")
        return {"data": data}
    except AdminError as error:
        _raise(error)


@router.delete("/articles/{article_id}")
def delete_article(
    article_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    repository = AccountRepository(db)
    if not repository.get_article(int(user["uid"]), article_id):
        raise HTTPException(status_code=404, detail="article_not_found")
    if not AdminService(db).delete_article(article_id):
        raise HTTPException(status_code=404, detail="article_not_found")
    return {"success": True}


@router.get("/comments")
def comments(
    limit: int = Query(default=100, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    items, total = AccountRepository(db).list_comments(
        int(user["uid"]), limit, offset
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.put("/comments/{comment_id}")
def update_comment(
    comment_id: int,
    payload: dict[str, Any],
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    body = _text(
        payload.get("body_markdown"),
        field="comment_body",
        max_length=20000,
        required=True,
    )
    if not AccountRepository(db).update_comment(
        int(user["uid"]), comment_id, body
    ):
        raise HTTPException(status_code=404, detail="comment_not_found")
    return {"success": True}


@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not AccountRepository(db).delete_comment(int(user["uid"]), comment_id):
        raise HTTPException(status_code=404, detail="comment_not_found")
    return {"success": True}


@router.get("/notifications")
def notifications(
    limit: int = Query(default=100, ge=1, le=200),
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    return {
        "items": AccountRepository(db).notifications(int(user["uid"]), limit)
    }


# 友链申请的字段校验与默认值已抽到 friend_payload.py，与主站那条路径共用
# （原来两份实现，改一处容易漏另一处）。这里用别名导入，调用点保持不变。
_friend_application_payload = friend_application_payload


@router.get("/friend-links")
def friend_links(
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    repository = AccountRepository(db)
    user_id = int(user["uid"])
    return {
        "items": repository.list_friend_applications(user_id),
        "active_count": repository.active_friend_count(user_id),
        "limit": 3,
    }


@router.post("/friend-links")
def create_friend_link_application(
    payload: dict[str, Any],
    request: Request,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    data = _friend_application_payload(payload)
    repository = AccountRepository(db)
    try:
        application = repository.create_friend_application(
            int(user["uid"]), **data
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    try:
        verification = PortalService(db).request_friend_link_verification(
            user=user,
            application_id=int(application["id"]),
            ip=_client_ip(request),
        )
    except AccountError as error:
        # Keep the application pending_email so the user can resend the link later.
        return {
            "success": True,
            "data": application,
            "verification": {
                "sent": False,
                "detail": error.detail,
            },
        }
    return {
        "success": True,
        "data": application,
        "verification": {"sent": True, **verification},
    }


@router.put("/friend-links/{application_id}")
def update_friend_link_application(
    application_id: int,
    payload: dict[str, Any],
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    data = _friend_application_payload(payload)
    try:
        updated = AccountRepository(db).update_friend_application(
            int(user["uid"]), application_id, **data
        )
        return {"success": True, "data": updated}
    except ValueError as error:
        detail = str(error)
        status_code = 404 if detail == "friend_application_not_found" else 409
        raise HTTPException(status_code=status_code, detail=detail) from error


@router.delete("/friend-links/{application_id}")
def delete_friend_link_application(
    application_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not AccountRepository(db).delete_friend_application(
        int(user["uid"]), application_id
    ):
        raise HTTPException(status_code=404, detail="friend_application_not_found")
    return {"success": True}


@router.post("/friend-links/{application_id}/verification/send")
def send_friend_link_verification(
    application_id: int,
    request: Request,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        return PortalService(db).request_friend_link_verification(
            user=user,
            application_id=application_id,
            ip=_client_ip(request),
        )
    except AccountError as error:
        _raise(error)


@router.get("/friend-links/verification/confirm")
def confirm_friend_link_verification(
    token: str = Query(min_length=32, max_length=256),
    db: Session = Depends(get_db),
):
    try:
        data = PortalService(db).confirm_friend_link_token(token=token)
        return {"success": True, "data": data, "auto_approved": True}
    except AccountError as error:
        _raise(error)
