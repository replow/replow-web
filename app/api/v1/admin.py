from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import _set_session_cookie
from app.core.security import require_admin
from app.api.audit_route import AuditRoute
from app.repositories.audit import user_changes
from app.repositories.users import UserRepository
from app.services.user_edit import validate_sensitive_edit
from app.db.session import get_db
from app.services.account import AccountError, AccountService
from app.services.admin import AdminError, AdminService
from app.services.cloudflare import CloudflareError, CloudflareService
from app.services.media_storage import MediaError, MediaStorageService
from app.services.site_build import site_build_status, start_site_build


router = APIRouter(prefix="/admin", tags=["admin"], route_class=AuditRoute)


def _raise_admin_error(error: AdminError | AccountError | CloudflareError | MediaError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.get("/dashboard")
def dashboard(_: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return AdminService(db).dashboard()


@router.get("/articles")
def admin_articles(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = None,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items, total = AdminService(db).articles(limit, offset, search)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/articles")
def create_article(payload: dict[str, Any], user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return {"data": AdminService(db).create_article(payload, int(user["uid"]))}
    except AdminError as error:
        _raise_admin_error(error)


@router.get("/articles/{article_id}")
def get_admin_article(article_id: int, _: dict = Depends(require_admin), db: Session = Depends(get_db)):
    article = AdminService(db).article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="article_not_found")
    return {"data": article}


@router.put("/articles/{article_id}")
def update_article(article_id: int, payload: dict[str, Any], user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        article = AdminService(db).update_article(article_id, payload, int(user["uid"]))
    except AdminError as error:
        _raise_admin_error(error)
    if not article:
        raise HTTPException(status_code=404, detail="article_not_found")
    return {"data": article}


@router.delete("/articles/{article_id}")
def delete_article(article_id: int, _: dict = Depends(require_admin), db: Session = Depends(get_db)):
    if not AdminService(db).delete_article(article_id):
        raise HTTPException(status_code=404, detail="article_not_found")
    return {"success": True}


@router.get("/comments")
def admin_comments(
    article_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items, total = AdminService(db).comments(article_id, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.patch("/comments/{comment_id}/status")
def update_comment_status(comment_id: int, payload: dict[str, Any], _: dict = Depends(require_admin), db: Session = Depends(get_db)):
    next_status = str(payload.get("status", "")).strip()
    if next_status not in {"visible", "hidden"}:
        raise HTTPException(status_code=422, detail="invalid_comment_status")
    if not AdminService(db).update_comment_status(comment_id, next_status):
        raise HTTPException(status_code=404, detail="comment_not_found")
    return {"success": True}


@router.get("/friends")
def admin_friends(
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items, total = AdminService(db).friends(limit, offset)
    return {"items": items, "total": total}


@router.post("/friends")
def create_friend(payload: dict[str, Any], user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return {"data": AdminService(db).save_friend(payload, int(user["uid"]))}
    except AdminError as error:
        _raise_admin_error(error)


@router.put("/friends/{friend_id}")
def update_friend(friend_id: int, payload: dict[str, Any], user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return {"data": AdminService(db).save_friend(payload, int(user["uid"]), friend_id)}
    except AdminError as error:
        _raise_admin_error(error)


@router.delete("/friends/{friend_id}")
def delete_friend(friend_id: int, _: dict = Depends(require_admin), db: Session = Depends(get_db)):
    if not AdminService(db).delete_friend(friend_id):
        raise HTTPException(status_code=404, detail="friend_not_found")
    return {"success": True}


@router.get("/site/settings")
def get_admin_site_settings(_: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return {"data": AdminService(db).site_settings()}


@router.put("/site/settings")
def update_admin_site_settings(payload: dict[str, Any], user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "success": True,
        "data": AdminService(db).update_site_settings(payload, int(user["uid"])),
    }


@router.get("/firefly/config")
def get_firefly_config(_: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return {"data": AdminService(db).firefly_config()}


@router.put("/firefly/config")
def update_firefly_config(
    payload: dict[str, Any],
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    config = payload.get("config", payload)
    if not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="firefly_config_object_required")
    return {
        "success": True,
        "data": AdminService(db).update_firefly_config(config, int(user["uid"])),
    }


@router.get("/account/settings")
def get_account_settings(_: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return {"data": AccountService(db).admin_settings()}


@router.put("/account/settings")
def update_account_settings(
    payload: dict[str, Any],
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return {
        "success": True,
        "data": AccountService(db).update_admin_settings(payload, int(user["uid"])),
    }


@router.post("/account/mail/test")
def send_test_mail(
    payload: dict[str, Any],
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return AccountService(db).send_test_mail(str(payload.get("recipient") or ""))
    except AccountError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except RuntimeError as error:
        detail = "mail_not_configured" if str(error) == "mail_not_configured" else "mail_delivery_failed"
        raise HTTPException(status_code=503, detail=detail) from error



@router.get("/cdn/cloudflare/settings")
def get_cloudflare_settings(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return {"data": CloudflareService(db).public_config()}


@router.put("/cdn/cloudflare/settings")
def update_cloudflare_settings(
    payload: dict[str, Any],
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "data": CloudflareService(db).update_config(payload, int(user["uid"])),
        }
    except CloudflareError as error:
        _raise_admin_error(error)


@router.get("/cdn/cloudflare/hostnames")
def list_cloudflare_hostnames(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """The Cloudflare for SaaS custom hostnames on the configured zone.

    These are the names a purge will actually clear -- replow.org / 4z.ink are
    custom hostnames riding on the isip.eu.cc zone, not zones of their own.
    """
    try:
        rows = CloudflareService(db).list_hostnames()
    except CloudflareError as error:
        _raise_admin_error(error)
    return {
        "data": [
            {
                "hostname": row.get("hostname"),
                "status": row.get("status"),
                "ssl_status": (row.get("ssl") or {}).get("status"),
            }
            for row in rows
        ]
    }


@router.post("/cdn/cloudflare/purge-all")
def purge_cloudflare_cache(
    payload: Optional[dict[str, Any]] = None,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Purge the cache.

    Body is optional. Default behaviour purges every custom hostname on the
    zone, which is what "clear the CDN cache" means for this deployment.

    {"mode": "everything"}      -> blunt zone-wide purge_everything
    {"hosts": ["a.example"]}    -> purge only those hostnames
    """
    payload = payload or {}
    mode = str(payload.get("mode") or "hostnames").strip().lower()
    hosts = payload.get("hosts")
    try:
        service = CloudflareService(db)
        if isinstance(hosts, list) and hosts:
            return service.purge_hosts([str(h) for h in hosts])
        return service.purge_all(mode if mode in {"hostnames", "everything"} else "hostnames")
    except CloudflareError as error:
        _raise_admin_error(error)


@router.get("/media")
def admin_media(
    trash: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.media_trash import MediaTrash
    items, total = MediaTrash(db).list(limit, offset, trashed=trash)
    return {"items": items, "total": total}


@router.get("/storage/settings")
def get_media_storage_settings(_: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return {"data": MediaStorageService(db).public_config()}


@router.put("/storage/settings")
def update_media_storage_settings(
    payload: dict[str, Any],
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "data": MediaStorageService(db).update_config(payload, int(user["uid"])),
        }
    except MediaError as error:
        _raise_admin_error(error)


@router.get("/storage/status")
def get_media_storage_status(_: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return {"data": MediaStorageService(db).status()}


@router.post("/media/direct/prepare")
def prepare_admin_media_direct(
    payload: dict[str, Any],
    response: Response,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"data": MediaStorageService(db).prepare_direct_upload(payload, int(user["uid"]))}
    except MediaError as error:
        _raise_admin_error(error)


@router.post("/media/direct/confirm")
def confirm_admin_media_direct(
    payload: dict[str, Any],
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {"data": MediaStorageService(db).confirm_direct_upload(
            str(payload.get("ticket") or ""), int(user["uid"])
        )}
    except MediaError as error:
        _raise_admin_error(error)


@router.post("/media/upload")
def upload_admin_media(
    file: UploadFile = File(...),
    category: str = Form(default="general"),
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {
            "data": MediaStorageService(db).upload(file, category, int(user["uid"])),
        }
    except MediaError as error:
        _raise_admin_error(error)


@router.delete("/media/{media_id}")
def delete_admin_media(
    media_id: int,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        from app.services.media_trash import MediaTrash
        deleted = MediaTrash(db).trash(media_id, int(user["uid"]))
    except MediaError as error:
        _raise_admin_error(error)
    if not deleted:
        raise HTTPException(status_code=404, detail="media_not_found")
    return {"success": True}


@router.get("/users")
def admin_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items, total = AdminService(db).users(limit, offset)
    return {"items": items, "total": total}


@router.post("/users")
def create_user(payload: dict[str, Any], _: dict = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        validate_sensitive_edit(payload, None)
        return {"data": AdminService(db).create_user(payload)}
    except (AdminError, AccountError) as error:
        _raise_admin_error(error)


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    payload: dict[str, Any],
    request: Request,
    response: Response,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = UserRepository(db).get_by_id(user_id)
    validate_sensitive_edit(payload, existing)
    request.state.audit_changes = user_changes(existing or {}, {**(existing or {}), **payload}, payload)
    try:
        updated = AdminService(db).update_user(user_id, payload, int(user["uid"]))
    except (AdminError, AccountError) as error:
        _raise_admin_error(error)
    if not updated:
        raise HTTPException(status_code=404, detail="user_not_found")
    result: dict[str, Any] = {"data": updated}
    # Only an edit of the authenticated administrator may replace the session.
    # Compare the original target ID: a self-edit can also change the UID.
    if user_id == int(user["uid"]):
        session = AccountService(db).issue_tokens(updated, session_id=user.get("_session_id"), previous_version=int(user.get("session_version") or 0))["data"]
        _set_session_cookie(response, session["refreshToken"], request)
        result["session"] = session
    return result


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    confirmed: bool = Query(False),
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not confirmed:
        raise HTTPException(422, "confirmation_required")
    try:
        deleted = AdminService(db).delete_user(user_id, int(user["uid"]))
    except AdminError as error:
        _raise_admin_error(error)
    if not deleted:
        raise HTTPException(status_code=404, detail="user_not_found")
    return {"success": True}


@router.get("/routes")
def admin_routes(_: dict = Depends(require_admin)):
    # The Pure Admin shell uses static route modules. This endpoint is kept as
    # a contract for future server-side RBAC without loading client components
    # from an untrusted response.
    return {"success": True, "data": []}


@router.get("/site/build")
def get_site_build(_: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return {"data": site_build_status(db)}


@router.post("/site/build")
def post_site_build(_: dict = Depends(require_admin)):
    return {"success": True, "data": start_site_build()}
