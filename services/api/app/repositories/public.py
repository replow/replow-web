import json
from typing import Any, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session


def _json_value(value: Any, fallback: Any = "") -> Any:
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return fallback if value is None else value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return fallback


def _tags(value: Any) -> list[str]:
    parsed = _json_value(value, [])
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def article_row(row: dict[str, Any]) -> dict[str, Any]:
    published = row.get("published_at") or row.get("updated_at") or row.get("created_at")
    return {
        "id": int(row.get("id") or 0),
        "title": str(row.get("title") or ""),
        "slug": str(row.get("slug") or ""),
        "excerpt": str(row.get("excerpt") or ""),
        "body_markdown": str(row.get("body_markdown") or ""),
        "cover_url": str(row.get("cover_url") or ""),
        "icon_url": str(row.get("icon_url") or ""),
        "author": str(row.get("author") or row.get("owner_username") or ""),
        "author_avatar": str(row.get("author_avatar") or ""),
        "category": str(row.get("category") or ""),
        "tags": _tags(row.get("tags")),
        "status": str(row.get("status") or ""),
        "is_pinned": bool(row.get("is_pinned")),
        "published_at": published.isoformat() if hasattr(published, "isoformat") else str(published or ""),
        "updated_at": row.get("updated_at").isoformat() if hasattr(row.get("updated_at"), "isoformat") else str(row.get("updated_at") or ""),
    }


class PublicRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_articles(
        self,
        limit: int,
        offset: int,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[dict], int]:
        where = ["a.status = 'published'"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if category:
            where.append("a.category = :category")
            params["category"] = category
        if tag:
            where.append("(a.tags LIKE :tag_json OR a.tags LIKE :tag_text)")
            params["tag_json"] = f'%"{tag}"%'
            params["tag_text"] = f"%{tag}%"
        if search:
            where.append("(a.title LIKE :search OR a.excerpt LIKE :search OR a.body_markdown LIKE :search)")
            params["search"] = f"%{search}%"
        condition = " AND ".join(where)
        total = int(self.db.execute(text(f"SELECT COUNT(*) FROM articles a WHERE {condition}"), params).scalar_one())
        rows = self.db.execute(
            text(
                f"""
                SELECT a.*, u.username AS owner_username,
                       COALESCE(NULLIF(u.display_name, ''), u.username) AS author,
                       u.avatar_url AS author_avatar
                FROM articles a
                LEFT JOIN users u ON u.uid = a.owner_id
                WHERE {condition}
                ORDER BY a.is_pinned DESC, a.published_at DESC, a.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        return [article_row(dict(row)) for row in rows], total

    def get_article(self, slug: str) -> Optional[dict]:
        row = self.db.execute(
            text(
                """
                SELECT a.*, u.username AS owner_username,
                       COALESCE(NULLIF(u.display_name, ''), u.username) AS author,
                       u.avatar_url AS author_avatar
                FROM articles a
                LEFT JOIN users u ON u.uid = a.owner_id
                WHERE a.slug = :slug AND a.status = 'published'
                LIMIT 1
                """
            ),
            {"slug": slug},
        ).mappings().first()
        return article_row(dict(row)) if row else None

    def settings(self, keys: Optional[List[str]] = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        query = "SELECT setting_key, setting_value FROM site_settings"
        if keys:
            placeholders = []
            for index, key in enumerate(keys):
                name = f"key_{index}"
                placeholders.append(f":{name}")
                params[name] = key
            query += f" WHERE setting_key IN ({','.join(placeholders)})"
        rows = self.db.execute(text(query), params).mappings().all()
        return {str(row["setting_key"]): _json_value(row["setting_value"], "") for row in rows}

    def friends(self) -> list[dict]:
        rows = self.db.execute(
            text(
                """
                SELECT id, name, avatar_url, description, website_url,
                       language, rss_url, category,
                       sort_order, is_enabled, updated_at
                FROM friend_links
                WHERE is_enabled = 1
                ORDER BY sort_order ASC, id ASC
                LIMIT 500
                """
            )
        ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "name": str(row["name"] or ""),
                "avatar_url": str(row["avatar_url"] or ""),
                "description": str(row["description"] or ""),
                "website_url": str(row["website_url"] or ""),
                "language": str(row["language"] or ""),
                "rss_url": str(row["rss_url"] or ""),
                "category": str(row["category"] or ""),
                "sort_order": int(row["sort_order"] or 0),
                "is_enabled": bool(row["is_enabled"]),
                "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"] or ""),
            }
            for row in rows
        ]

    def comments(self, article_id: Optional[int] = None, limit: int = 100, offset: int = 0, public_only: bool = False) -> Tuple[List[dict], int]:
        where = ["1 = 1"]
        if public_only:
            where += ["c.status='visible'", "a.status='published'"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if article_id:
            where.append("c.article_id = :article_id")
            params["article_id"] = article_id
        condition = " AND ".join(where)
        total = int(self.db.execute(text(f"SELECT COUNT(*) FROM comments c LEFT JOIN articles a ON a.id=c.article_id WHERE {condition}"), params).scalar_one())
        rows = self.db.execute(
            text(
                f"""
                SELECT c.id, c.article_id, c.parent_id, c.user_id,
                       c.user_name_snapshot, c.user_avatar_snapshot, c.body_markdown,
                       c.status, c.browser_name, c.os_name, c.created_at,
                       a.title AS article_title
                FROM comments c
                LEFT JOIN articles a ON a.id = c.article_id
                WHERE {condition}
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "article_id": int(row["article_id"]),
                "article_title": str(row["article_title"] or ""),
                "parent_id": int(row["parent_id"]) if row["parent_id"] is not None else None,
                "user_id": int(row["user_id"]) if row["user_id"] is not None else None,
                "user_name": str(row["user_name_snapshot"] or ""),
                "user_avatar": str(row["user_avatar_snapshot"] or ""),
                "body_markdown": str(row["body_markdown"] or ""),
                "status": str(row["status"] or ""),
                "browser": str(row["browser_name"] or ""),
                "os": str(row["os_name"] or ""),
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"] or ""),
            }
            for row in rows
        ], total

    def songs(self) -> list[dict]:
        rows = self.db.execute(
            text(
                """
                SELECT id, title, artist, audio_url, cover_url, sort_order
                FROM songs
                WHERE is_enabled = 1
                ORDER BY sort_order ASC, id ASC
                """
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        tables = {
            "articles": "articles",
            "comments": "comments",
            "friends": "friend_links",
            "users": "users",
            "media": "media_objects",
        }
        result: dict[str, int] = {}
        for key, table in tables.items():
            result[key] = int(self.db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
        result["published_articles"] = int(
            self.db.execute(text("SELECT COUNT(*) FROM articles WHERE status = 'published'")).scalar_one()
        )
        return result
