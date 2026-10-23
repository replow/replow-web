from datetime import datetime
from urllib.parse import urlparse
from fastapi import HTTPException
from sqlalchemy import text


def clean_text(value, limit, required=False):
    value = str(value or "").strip()
    if len(value) > limit or (required and not value):
        raise HTTPException(422, "invalid_album_text")
    return value


class GalleryService:
    def __init__(self, db):
        self.db = db

    def albums(self, public=False):
        where = " WHERE a.is_published=1" if public else ""
        rows = [dict(row) for row in self.db.execute(text(
            "SELECT a.* FROM photo_albums a" + where + " ORDER BY a.sort_order,a.id DESC LIMIT 500"
        )).mappings()]
        photos = self.db.execute(text(
            "SELECT p.album_id,m.public_url FROM album_photos p JOIN media_objects m ON m.id=p.media_id "
            "JOIN photo_albums a ON a.id=p.album_id" + where + " ORDER BY p.sort_order,p.id"
        )).mappings()
        by_album = {}
        for photo in photos:
            by_album.setdefault(photo["album_id"], []).append(photo["public_url"])
        for row in rows:
            urls = by_album.get(row["id"], [])
            row["photo_count"] = len(urls)
            row["resolved_cover"] = row["cover_url"] or (urls[0] if urls else "")
        return rows

    def album(self, album_id, public=False):
        row = self.db.execute(text("SELECT * FROM photo_albums WHERE id=:id" +
            (" AND is_published=1" if public else "")), {"id": album_id}).mappings().first()
        if not row:
            raise HTTPException(404, "album_not_found")
        photos = self.db.execute(text(
            "SELECT p.id,p.media_id,p.caption,p.sort_order,m.public_url,m.original_name "
            "FROM album_photos p JOIN media_objects m ON m.id=p.media_id "
            "WHERE p.album_id=:id ORDER BY p.sort_order,p.id"
        ), {"id": album_id}).mappings()
        return {**dict(row), "photos": [dict(photo) for photo in photos]}

    def save(self, payload, album_id=None):
        if album_id:
            self.album(album_id)
        cover = clean_text(payload.get("cover_url"), 2048)
        if cover and (urlparse(cover).scheme not in {"http", "https"} or not urlparse(cover).netloc):
            raise HTTPException(422, "invalid_cover_url")
        try:
            order = int(payload.get("sort_order") or 0)
        except (ValueError, TypeError):
            raise HTTPException(422, "invalid_sort_order")
        if not -100000 <= order <= 100000:
            raise HTTPException(422, "invalid_sort_order")
        data = {"title": clean_text(payload.get("title"), 100, True),
                "description": clean_text(payload.get("description"), 1000),
                "cover": cover, "sort": order, "published": bool(payload.get("is_published", False)),
                "now": datetime.utcnow(), "id": album_id}
        if album_id:
            self.db.execute(text("UPDATE photo_albums SET title=:title,description=:description,"
                "cover_url=:cover,sort_order=:sort,is_published=:published,updated_at=:now WHERE id=:id"), data)
        else:
            result = self.db.execute(text("INSERT INTO photo_albums "
                "(title,description,cover_url,sort_order,is_published,created_at,updated_at) "
                "VALUES (:title,:description,:cover,:sort,:published,:now,:now)"), data)
            album_id = int(result.lastrowid)
        self.db.commit()
        return self.album(album_id)

    def save_photos(self, album_id, photos):
        self.album(album_id)
        if not isinstance(photos, list) or len(photos) > 500:
            raise HTTPException(422, "invalid_album_photos")
        normalized, seen = [], set()
        for index, item in enumerate(photos):
            if not isinstance(item, dict):
                raise HTTPException(422, "invalid_album_photo")
            try:
                mid = int(item["media_id"])
            except (KeyError, TypeError, ValueError):
                raise HTTPException(422, "invalid_album_photo")
            if mid in seen:
                raise HTTPException(422, "duplicate_album_photo")
            seen.add(mid)
            media = self.db.execute(text("SELECT mime_type FROM media_objects WHERE id=:id AND deleted_at IS NULL"), {"id": mid}).scalar()
            if not media or not media.startswith("image/") or media == "image/svg+xml":
                raise HTTPException(422, "album_photo_must_be_image")
            normalized.append({"album": album_id, "media": mid,
                               "caption": clean_text(item.get("caption"), 500), "sort": index})
        # Validate the complete replacement before changing anything.
        self.db.execute(text("DELETE FROM album_photos WHERE album_id=:id"), {"id": album_id})
        if normalized:
            self.db.execute(text("INSERT INTO album_photos (album_id,media_id,caption,sort_order) "
                                 "VALUES (:album,:media,:caption,:sort)"), normalized)
        self.db.execute(text("UPDATE photo_albums SET updated_at=:now WHERE id=:id"),
                        {"id": album_id, "now": datetime.utcnow()})
        self.db.commit()
        return self.album(album_id)

    def delete(self, album_id):
        self.album(album_id)
        self.db.execute(text("DELETE FROM photo_albums WHERE id=:id"), {"id": album_id})
        self.db.commit()
