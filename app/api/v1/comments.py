"""Authenticated article discussions. Reuses account identity and reply notifications."""
from __future__ import annotations

import io
import re
import warnings
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, StrictInt
from PIL import Image, UnidentifiedImageError
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.core.security import current_user
from app.db.session import get_db
from app.services.media_storage import MediaError, MediaStorageService

router = APIRouter(tags=["comments"])
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"),
               "GIF": ("image/gif", ".gif"), "WEBP": ("image/webp", ".webp"),
               "AVIF": ("image/avif", ".avif")}


class CommentCreate(BaseModel):
    article_id: StrictInt
    parent_id: Optional[StrictInt] = None
    body_markdown: str = Field(min_length=1, max_length=10000)


def image_limit(db: Session, uid: int) -> int:
    value = db.execute(text("SELECT comment_image_limit FROM users WHERE uid=:uid"), {"uid": uid}).scalar()
    return max(0, min(20, int(value) if value is not None else 6))


def article_exists(db: Session, article_id: int) -> None:
    if not db.execute(text("SELECT id FROM articles WHERE id=:id AND status='published'"),
                      {"id": article_id}).scalar():
        raise HTTPException(404, "article_not_found")


@router.get("/public/articles/{article_id}/discussion")
def discussion(article_id: int, limit: int = Query(100, ge=1, le=200),
               offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    article_exists(db, article_id)
    params = {"article": article_id, "limit": limit, "offset": offset}
    total = db.execute(text("SELECT COUNT(*) FROM comments WHERE article_id=:article AND status='visible'"), params).scalar()
    rows = db.execute(text("""
        SELECT id, article_id, parent_id, user_id, user_name_snapshot AS user_name,
               user_avatar_snapshot AS user_avatar, body_markdown, created_at, edited_at
        FROM comments WHERE article_id=:article AND status='visible'
        ORDER BY id ASC LIMIT :limit OFFSET :offset
    """), params).mappings().all()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/account/comments", status_code=201)
def create_comment(payload: CommentCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    from app.core.moderation import require_comment
    require_comment(user)
    uid = int(user["uid"])
    body = payload.body_markdown.strip()
    if not body:
        raise HTTPException(422, "comment_empty")
    article_exists(db, payload.article_id)
    # Serialize submissions per account, including across API workers.
    db.execute(text("SELECT uid FROM users WHERE uid=:uid FOR UPDATE"), {"uid": uid})
    recent = db.execute(text("""
        SELECT COUNT(*) FROM comments WHERE user_id=:uid
        AND created_at > DATE_SUB(NOW(), INTERVAL 10 SECOND)
    """), {"uid": uid}).scalar()
    if recent:
        raise HTTPException(429, "comment_too_fast")
    # Markdown images and raw HTML images share the per-account limit.
    images = len(re.findall(r"!\[|<img\b", body, re.I))
    if images > image_limit(db, uid):
        raise HTTPException(422, "comment_too_many_images")
    if payload.parent_id is not None:
        parent = db.execute(text("""
            SELECT id FROM comments WHERE id=:parent AND article_id=:article AND status='visible'
            FOR UPDATE
        """), {"parent": payload.parent_id, "article": payload.article_id}).scalar()
        if not parent:
            raise HTTPException(422, "comment_parent_invalid")
    result = db.execute(text("""
        INSERT INTO comments
          (article_id, parent_id, user_id, user_name_snapshot, user_avatar_snapshot, body_markdown, status)
        VALUES (:article, :parent, :uid, :name, :avatar, :body, 'visible')
    """), {"article": payload.article_id, "parent": payload.parent_id, "uid": uid,
           "name": str(user.get("display_name") or user["username"])[:80],
           "avatar": str(user.get("avatar_url") or "")[:2048], "body": body})
    comment_id = result.lastrowid
    db.commit()
    # AccountRepository.notifications derives notifications from the direct parent.
    return {"data": {"id": comment_id}, "success": True}


@router.post("/account/comments/images", status_code=201)
def upload_comment_image(file: UploadFile = File(...), user: dict = Depends(current_user),
                         db: Session = Depends(get_db)):
    from app.core.moderation import require_comment
    require_comment(user)
    uid = int(user["uid"])
    if image_limit(db, uid) == 0:
        raise HTTPException(403, "comment_images_disabled")
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "comment_image_too_large")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image_type = IMAGE_TYPES.get(image.format)
                if image_type is None or image.width * image.height > 24_000_000:
                    raise ValueError("invalid image")
                image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(415, "comment_image_invalid")
    # A durable reservation limits rejected/retried attempts as well as successful uploads.
    db.execute(text("SELECT uid FROM users WHERE uid=:uid FOR UPDATE"), {"uid": uid})
    used = db.execute(text("""
        SELECT COUNT(*) FROM comment_image_uploads WHERE user_id=:uid
        AND created_at > DATE_SUB(NOW(), INTERVAL 1 HOUR)
    """), {"uid": uid}).scalar()
    if used >= 30:
        raise HTTPException(429, "comment_upload_too_fast")
    db.execute(text("INSERT INTO comment_image_uploads (user_id) VALUES (:uid)"), {"uid": uid})
    db.commit()
    upload = UploadFile(filename="comment" + image_type[1], file=io.BytesIO(data),
                        headers=Headers({"content-type": image_type[0]}))
    try:
        item = MediaStorageService(db).upload(upload, "article", uid)
    except MediaError as error:
        # Never expose storage exception details or credentials to ordinary users.
        raise HTTPException(error.status_code, "comment_upload_failed") from None
    return {"data": {"url": item["public_url"]}}
