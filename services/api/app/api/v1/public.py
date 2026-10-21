import mimetypes
import httpx
from pathlib import Path
from urllib.parse import urlsplit
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.v1.friend_payload import friend_application_payload
from app.api.v1.validation import client_ip
from app.db.session import get_db
from app.schemas.friend_links import FriendLinkApplyRequest, FriendLinkCodeRequest
from app.services.account import AccountError
from app.services.portal import PortalService
from app.services.media_storage import MediaStorageService
from app.services.public import PublicService


mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/heif-source")
def public_heif_source(url: str = Query(max_length=2048), db: Session = Depends(get_db)):
    """Same-origin, byte-preserving HEIF fetch for browsers decoding via WASM.

    Only the configured public R2 media prefix is allowed; no arbitrary URL proxying.
    """
    cfg = MediaStorageService(db).config()
    base = urlsplit(cfg.r2_public_base_url)
    candidate = urlsplit(url)
    prefix = base.path.rstrip("/") + "/media/"
    if (
        base.scheme != "https"
        or candidate.scheme != "https"
        or candidate.netloc != base.netloc
        or not candidate.path.startswith(prefix)
        or not candidate.path.lower().endswith((".heic", ".heif"))
        or candidate.username or candidate.password
        or candidate.query or candidate.fragment
    ):
        raise HTTPException(status_code=400, detail="invalid_heif_url")
    # Preserve the original bytes and HEIC/HEIF MIME. Never request a JPEG conversion.
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            with client.stream("GET", url, headers={"Accept": "image/heic,image/heif"}) as upstream:
                if upstream.status_code != 200:
                    raise HTTPException(status_code=404, detail="heif_not_found")
                if int(upstream.headers.get("content-length") or 0) > 32 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="heif_too_large")
                data = bytearray()
                for chunk in upstream.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 32 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="heif_too_large")
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="heif_source_unavailable") from error
    mime = "image/heic" if candidate.path.lower().endswith(".heic") else "image/heif"
    return Response(
        content=bytes(data),
        media_type=mime,
        headers={"Cache-Control": "public, max-age=604800", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/media/{object_key:path}")
def public_media(object_key: str, db: Session = Depends(get_db)):
    """Serve files routed to local storage through the public API contract."""
    config = MediaStorageService(db).config()
    root = Path(config.local_root).expanduser().resolve()
    target = (root / object_key).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="media_not_found")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


def _raise_account_error(error: AccountError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.get("/site")
def get_site(db: Session = Depends(get_db)):
    return PublicService(db).site()


@router.get("/articles")
def list_articles(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    items, total = PublicService(db).articles(limit, offset, category, tag, search)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/articles/{slug}")
def get_article(slug: str, db: Session = Depends(get_db)):
    article = PublicService(db).article(slug)
    if not article:
        raise HTTPException(status_code=404, detail="article_not_found")
    return article


@router.get("/friends")
def list_friends(db: Session = Depends(get_db)):
    return {"items": PublicService(db).friends()}


@router.post("/friend-links/verification/send")
def send_friend_link_code(
    payload: FriendLinkCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """主站友链申请第一步：给邮箱发 6 位验证码（无需先登录）。"""
    try:
        return PortalService(db).send_friend_link_application_code(
            email=payload.email, ip=client_ip(request)
        )
    except AccountError as error:
        _raise_account_error(error)


@router.post("/friend-links/apply")
def apply_friend_link(
    payload: FriendLinkApplyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """主站友链申请：验码 → 该邮箱无账号则自动建号 → 建申请 → 自动通过上线。"""
    data = friend_application_payload(payload.model_dump())
    try:
        return PortalService(db).apply_friend_link(
            email=payload.email,
            code=payload.code,
            ip=client_ip(request),
            **data,
        )
    except AccountError as error:
        _raise_account_error(error)


@router.get("/comments")
def list_comments(
    article_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = PublicService(db).comments(article_id, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/songs")
def list_songs(db: Session = Depends(get_db)):
    return {"items": PublicService(db).songs()}
