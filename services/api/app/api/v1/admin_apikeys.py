from __future__ import annotations

from typing import Any, Optional

from app.api.audit_route import AuditRoute
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import current_user, require_admin
from app.db.session import get_db
from app.services.api_keys import ApiKeyError, ApiKeyService


router = APIRouter(route_class=AuditRoute, prefix="/admin/access-keys", tags=["admin-access-keys"])


def _raise(error: ApiKeyError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _service(db: Session) -> ApiKeyService:
    return ApiKeyService(db)


# -- account-facing: a user manages their own registered domains ---------


@router.get("")
def list_own_keys(
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    return {"data": _service(db).list_keys(int(user["uid"]))}


@router.post("")
def register_domain(
    payload: dict[str, Any],
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Register a domain and receive the one-time key plus a challenge."""
    service = _service(db)
    try:
        result = service.register(
            user_uid=int(user["uid"]),
            email=str(payload.get("email") or user.get("email") or ""),
            site_url=str(payload.get("site_url") or ""),
            module_slug=str(payload.get("module_slug") or "oauth"),
        )
    except ApiKeyError as error:
        _raise(error)
    return {"data": result}


@router.post("/{key_id}/verify")
def verify_domain(
    key_id: int,
    payload: Optional[dict[str, Any]] = None,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Run the ownership check for a pending registration."""
    service = _service(db)
    record = service.repo.get_by_id(key_id)
    if not record:
        raise HTTPException(status_code=404, detail="access_key_not_found")
    if int(record["user_uid"]) != int(user["uid"]) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="not_your_access_key")

    method = str((payload or {}).get("method") or "auto")
    try:
        return {"data": service.verify(key_id, method=method)}
    except ApiKeyError as error:
        _raise(error)


@router.post("/{key_id}/challenge")
def regenerate_challenge(
    key_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    service = _service(db)
    record = service.repo.get_by_id(key_id)
    if not record:
        raise HTTPException(status_code=404, detail="access_key_not_found")
    if int(record["user_uid"]) != int(user["uid"]) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="not_your_access_key")
    try:
        return {"data": service.regenerate_challenge(key_id)}
    except ApiKeyError as error:
        _raise(error)


@router.post("/{key_id}/rotate")
def rotate_own_key(
    key_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    service = _service(db)
    record = service.repo.get_by_id(key_id)
    if not record:
        raise HTTPException(status_code=404, detail="access_key_not_found")
    if int(record["user_uid"]) != int(user["uid"]) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="not_your_access_key")
    try:
        return {"data": service.rotate_key(key_id)}
    except ApiKeyError as error:
        _raise(error)


@router.delete("/{key_id}")
def delete_own_key(
    key_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    service = _service(db)
    record = service.repo.get_by_id(key_id)
    if not record:
        raise HTTPException(status_code=404, detail="access_key_not_found")
    if int(record["user_uid"]) != int(user["uid"]) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="not_your_access_key")
    service.delete(key_id)
    return {"success": True}


# -- admin-only: operate on any tenant's registration --------------------


@router.get("/all")
def list_all_keys(
    user_uid: Optional[int] = None,
    module_slug: Optional[str] = None,
    status: Optional[str] = None,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = _service(db).repo.list_all(
        user_uid=user_uid, module_slug=module_slug, status=status
    )
    return {"data": [ApiKeyService._public_view(row) for row in rows]}


@router.get("/all/{key_id}")
def get_key(
    key_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {"data": _service(db).get_key(key_id)}
    except ApiKeyError as error:
        _raise(error)


@router.post("/all/{key_id}/verify")
def admin_verify(
    key_id: int,
    payload: Optional[dict[str, Any]] = None,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    method = str((payload or {}).get("method") or "auto")
    try:
        return {"data": _service(db).verify(key_id, method=method)}
    except ApiKeyError as error:
        _raise(error)


@router.patch("/all/{key_id}")
def admin_update(
    key_id: int,
    payload: dict[str, Any],
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {"data": _service(db).update_settings(key_id, payload)}
    except ApiKeyError as error:
        _raise(error)


@router.post("/all/{key_id}/rotate")
def admin_rotate(
    key_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {"data": _service(db).rotate_key(key_id)}
    except ApiKeyError as error:
        _raise(error)


@router.delete("/all/{key_id}")
def admin_delete(
    key_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = _service(db)
    try:
        service.get_key(key_id)
    except ApiKeyError as error:
        _raise(error)
    service.delete(key_id)
    return {"success": True}


@router.get("/modules")
def list_modules(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Modules an access key can be issued for."""
    from sqlalchemy import text

    rows = db.execute(
        text(
            """
            SELECT slug, name, description, base_path, access_mode, enabled
            FROM api_modules
            ORDER BY id ASC
            """
        )
    ).mappings().all()
    return {"data": [dict(row) for row in rows]}
