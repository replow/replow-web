import json
from typing import Any, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.public import article_row


class AdminRepository:
    def __init__(self, db: Session):
        self.db = db

    def dashboard(self) -> dict[str, Any]:
        counts = {}
        for key, table in {
            "articles": "articles",
            "comments": "comments",
            "users": "users",
            "friends": "friend_links",
            "media": "media_objects",
        }.items():
            counts[key] = int(self.db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
        counts["published_articles"] = int(self.db.execute(text("SELECT COUNT(*) FROM articles WHERE status = 'published'")).scalar_one())
        recent = self.db.execute(
            text(
                """
                SELECT a.id, a.title, a.slug, a.status, a.updated_at,
                       COALESCE(NULLIF(u.display_name, ''), u.username, '') AS author
                FROM articles a
                LEFT JOIN users u ON u.uid = a.owner_id
                ORDER BY a.updated_at DESC, a.id DESC
                LIMIT 8
                """
            )
        ).mappings().all()
        return {
            "counts": counts,
            "recent_articles": [
                {
                    "id": int(row["id"]),
                    "title": str(row["title"] or ""),
                    "slug": str(row["slug"] or ""),
                    "status": str(row["status"] or ""),
                    "author": str(row["author"] or ""),
                    "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"] or ""),
                }
                for row in recent
            ],
        }

    def list_articles(self, limit: int, offset: int, search: Optional[str] = None) -> Tuple[List[dict], int]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE a.title LIKE :search OR a.slug LIKE :search"
            params["search"] = f"%{search}%"
        total = int(self.db.execute(text(f"SELECT COUNT(*) FROM articles a {where}"), params).scalar_one())
        rows = self.db.execute(
            text(
                f"""
                SELECT a.*, COALESCE(NULLIF(u.display_name, ''), u.username, '') AS author,
                       u.avatar_url AS author_avatar
                FROM articles a
                LEFT JOIN users u ON u.uid = a.owner_id
                {where}
                ORDER BY a.is_pinned DESC, a.updated_at DESC, a.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        return [article_row(dict(row)) for row in rows], total

    def get_article(self, article_id: int) -> Optional[dict]:
        row = self.db.execute(
            text("SELECT * FROM articles WHERE id = :article_id LIMIT 1"),
            {"article_id": article_id},
        ).mappings().first()
        return article_row(dict(row)) if row else None

    def create_article(self, data: dict[str, Any], actor_id: int) -> dict:
        result = self.db.execute(
            text(
                """
                INSERT INTO articles
                  (owner_id, title, slug, excerpt, body_markdown, cover_url, icon_url,
                   status, is_pinned, published_at, category, tags, created_at, updated_at)
                VALUES
                  (:owner_id, :title, :slug, :excerpt, :body_markdown, :cover_url, :icon_url,
                   :status, :is_pinned,
                   CASE WHEN :status = 'published' THEN COALESCE(:published_at, NOW()) ELSE :published_at END,
                   :category, :tags, NOW(), NOW())
                """
            ),
            self._article_params(data, actor_id),
        )
        self.db.commit()
        return self.get_article(int(result.lastrowid)) or {}

    def update_article(self, article_id: int, data: dict[str, Any]) -> Optional[dict]:
        existing = self.get_article(article_id)
        if not existing:
            return None
        params = {
            "article_id": article_id,
            "title": data.get("title", existing["title"]),
            "slug": data.get("slug", existing["slug"]),
            "excerpt": data.get("excerpt", existing["excerpt"]),
            "body_markdown": data.get("body_markdown", existing["body_markdown"]),
            "cover_url": data.get("cover_url", existing["cover_url"]),
            "icon_url": data.get("icon_url", existing["icon_url"]),
            "status": data.get("status", existing["status"]),
            "is_pinned": int(bool(data.get("is_pinned", existing["is_pinned"]))),
            "published_at": (
                data.get("published_at") or existing["published_at"] or None
                if data.get("status", existing["status"]) == "published"
                else None
            ),
            "category": data.get("category", existing["category"]),
            "tags": json.dumps(data.get("tags", existing["tags"]), ensure_ascii=False),
        }
        self.db.execute(
            text(
                """
                UPDATE articles
                SET title=:title, slug=:slug, excerpt=:excerpt, body_markdown=:body_markdown,
                    cover_url=:cover_url, icon_url=:icon_url, status=:status, is_pinned=:is_pinned,
                    published_at=:published_at, category=:category, tags=:tags, updated_at=NOW()
                WHERE id=:article_id
                """
            ),
            params,
        )
        self.db.commit()
        return self.get_article(article_id)

    def delete_article(self, article_id: int) -> bool:
        result = self.db.execute(text("DELETE FROM articles WHERE id=:article_id"), {"article_id": article_id})
        self.db.commit()
        return result.rowcount > 0

    @staticmethod
    def _article_params(data: dict[str, Any], actor_id: int) -> dict[str, Any]:
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        return {
            "owner_id": actor_id,
            "title": str(data.get("title", "")).strip(),
            "slug": str(data.get("slug", "")).strip(),
            "excerpt": str(data.get("excerpt", "")).strip(),
            "body_markdown": str(data.get("body_markdown", "")),
            "cover_url": str(data.get("cover_url", "")).strip(),
            "icon_url": str(data.get("icon_url", "")).strip(),
            "status": str(data.get("status", "draft")),
            "is_pinned": int(bool(data.get("is_pinned", False))),
            "published_at": data.get("published_at"),
            "category": str(data.get("category", "")).strip(),
            "tags": json.dumps(tags, ensure_ascii=False),
        }

    def update_setting(self, key: str, value: Any, actor_id: int) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO site_settings(setting_key, setting_value, updated_by, updated_at)
                VALUES (:key, :value, :actor_id, NOW())
                ON DUPLICATE KEY UPDATE setting_value=:value, updated_by=:actor_id, updated_at=NOW()
                """
            ),
            {"key": key, "value": json.dumps(value, ensure_ascii=False), "actor_id": actor_id},
        )
        self.db.commit()

    def update_settings(self, values: dict[str, Any], actor_id: int) -> None:
        for key, value in values.items():
            if not key or key.startswith("_"):
                continue
            self.db.execute(
                text(
                    """
                    INSERT INTO site_settings(setting_key, setting_value, updated_by, updated_at)
                    VALUES (:key, :value, :actor_id, NOW())
                    ON DUPLICATE KEY UPDATE setting_value=:value, updated_by=:actor_id, updated_at=NOW()
                    """
                ),
                {
                    "key": str(key),
                    "value": json.dumps(value, ensure_ascii=False),
                    "actor_id": actor_id,
                },
            )
        self.db.commit()

    def update_comment_status(self, comment_id: int, status: str) -> bool:
        result = self.db.execute(
            text("UPDATE comments SET status=:status, updated_at=NOW() WHERE id=:comment_id"),
            {"status": status, "comment_id": comment_id},
        )
        self.db.commit()
        return result.rowcount > 0

    def friends(self, limit: int = 500, offset: int = 0) -> tuple[list[dict], int]:
        total = int(self.db.execute(text("SELECT COUNT(*) FROM friend_links")).scalar_one())
        rows = self.db.execute(
            text(
                """
                SELECT id, name, avatar_url, description, website_url,
                       language, rss_url, category,
                       sort_order, is_enabled, updated_at
                FROM friend_links ORDER BY sort_order ASC, id ASC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        ).mappings().all()
        return [dict(row) for row in rows], total

    def friend_exists(self, friend_id: int) -> bool:
        return bool(
            self.db.execute(
                text("SELECT 1 FROM friend_links WHERE id = :friend_id LIMIT 1"),
                {"friend_id": friend_id},
            ).scalar()
        )

    def save_friend(self, data: dict[str, Any], actor_id: int, friend_id: Optional[int] = None) -> dict:
        params = {
            "name": str(data.get("name", "")).strip(),
            "avatar_url": str(data.get("avatar_url", "")).strip(),
            "description": str(data.get("description", "")).strip(),
            "website_url": str(data.get("website_url", "")).strip(),
            "language": str(data.get("language", "")).strip(),
            "rss_url": str(data.get("rss_url", "")).strip(),
            "category": str(data.get("category") or "").strip(),
            "sort_order": int(data.get("sort_order", 0) or 0),
            "is_enabled": int(bool(data.get("is_enabled", True))),
            "actor_id": actor_id,
        }
        if friend_id:
            params["friend_id"] = friend_id
            self.db.execute(
                text(
                    """
                    UPDATE friend_links
                    SET name=:name, avatar_url=:avatar_url, description=:description,
                        website_url=:website_url, language=:language, rss_url=:rss_url,
                        category=:category, sort_order=:sort_order,
                        is_enabled=:is_enabled, updated_at=NOW()
                    WHERE id=:friend_id
                    """
                ),
                params,
            )
        else:
            result = self.db.execute(
                text(
                    """
                    INSERT INTO friend_links
                      (name, avatar_url, description, website_url, language, rss_url, category, sort_order,
                       is_enabled, created_by, created_at, updated_at)
                    VALUES (:name, :avatar_url, :description, :website_url, :language, :rss_url, :category, :sort_order,
                            :is_enabled, :actor_id, NOW(), NOW())
                    """
                ),
                params,
            )
            friend_id = int(result.lastrowid)
        self.db.commit()
        row = self.db.execute(text("SELECT * FROM friend_links WHERE id=:friend_id"), {"friend_id": friend_id}).mappings().first()
        return dict(row) if row else {}

    def delete_friend(self, friend_id: int) -> bool:
        result = self.db.execute(text("DELETE FROM friend_links WHERE id=:friend_id"), {"friend_id": friend_id})
        self.db.commit()
        return result.rowcount > 0

    def media(self, limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        total = int(self.db.execute(text("SELECT COUNT(*) FROM media_objects")).scalar_one())
        rows = self.db.execute(
            text(
                """
                SELECT m.id, m.object_key, m.public_url, m.original_name, m.mime_type,
                       m.byte_size, m.category, m.storage_backend, m.sha256,
                       m.created_at, m.uploader_id,
                       COALESCE(NULLIF(u.display_name, ''), u.username) AS uploader_name,
                       u.username AS uploader_username
                FROM media_objects AS m
                LEFT JOIN users AS u ON u.uid = m.uploader_id
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        ).mappings().all()
        return [dict(row) for row in rows], total

    def media_storage_bytes(self) -> tuple[int, int, int]:
        row = self.db.execute(
            text(
                """
                SELECT
                  COALESCE(SUM(CASE WHEN storage_backend = 'r2' THEN byte_size ELSE 0 END), 0) AS r2_bytes,
                  COALESCE(SUM(CASE WHEN storage_backend = 'local' THEN byte_size ELSE 0 END), 0) AS local_bytes,
                  COALESCE(SUM(byte_size), 0) AS total_bytes
                FROM media_objects
                """
            )
        ).mappings().first() or {}
        return (
            int(row.get("r2_bytes") or 0),
            int(row.get("local_bytes") or 0),
            int(row.get("total_bytes") or 0),
        )

    def create_media(self, data: dict[str, Any]) -> dict:
        result = self.db.execute(
            text(
                """
                INSERT INTO media_objects
                  (object_key, public_url, original_name, mime_type, byte_size,
                   category, storage_backend, sha256, uploader_id, created_at)
                VALUES
                  (:object_key, :public_url, :original_name, :mime_type, :byte_size,
                   :category, :storage_backend, :sha256, :uploader_id, NOW())
                """
            ),
            data,
        )
        self.db.commit()
        return self.get_media(int(result.lastrowid)) or {}

    def get_media(self, media_id: int) -> Optional[dict]:
        row = self.db.execute(
            text("SELECT * FROM media_objects WHERE id=:media_id LIMIT 1"),
            {"media_id": media_id},
        ).mappings().first()
        return dict(row) if row else None

    def delete_media(self, media_id: int) -> bool:
        result = self.db.execute(
            text("DELETE FROM media_objects WHERE id=:media_id"),
            {"media_id": media_id},
        )
        self.db.commit()
        return result.rowcount > 0
