import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.public import article_row


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


class AccountRepository:
    def __init__(self, db: Session):
        self.db = db

    def profile(self, user_id: int) -> Optional[dict[str, Any]]:
        row = self.db.execute(
            text(
                """
                SELECT uid, username, email, display_name, avatar_url, bio, website_url,
                       role, status, setup_completed, last_login_at, created_at, updated_at
                FROM users
                WHERE uid = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
        if not row:
            return None
        data = dict(row)
        return {
            "uid": str(data["uid"]),
            "username": str(data["username"] or ""),
            "email": str(data["email"] or ""),
            "display_name": str(data["display_name"] or data["username"] or ""),
            "avatar_url": str(data["avatar_url"] or ""),
            "bio": str(data["bio"] or ""),
            "website_url": str(data["website_url"] or ""),
            "role": str(data["role"] or "user"),
            "status": str(data["status"] or "active"),
            "setup_completed": bool(data.get("setup_completed", True)),
            "last_login_at": _iso(data.get("last_login_at")),
            "created_at": _iso(data.get("created_at")),
            "updated_at": _iso(data.get("updated_at")),
        }

    def update_profile(
        self,
        user_id: int,
        *,
        display_name: str,
        avatar_url: str,
        bio: str,
        website_url: str,
    ) -> Optional[dict[str, Any]]:
        result = self.db.execute(
            text(
                """
                UPDATE users
                SET display_name=:display_name,
                    avatar_url=:avatar_url,
                    bio=:bio,
                    website_url=:website_url,
                    updated_at=NOW()
                WHERE uid=:user_id AND status='active'
                """
            ),
            {
                "display_name": display_name,
                "avatar_url": avatar_url or None,
                "bio": bio or None,
                "website_url": website_url or None,
                "user_id": user_id,
            },
        )
        if result.rowcount:
            self.db.execute(
                text(
                    """
                    UPDATE comments
                    SET user_name_snapshot=:display_name,
                        user_avatar_snapshot=:avatar_url,
                        updated_at=updated_at
                    WHERE user_id=:user_id
                    """
                ),
                {
                    "display_name": display_name,
                    "avatar_url": avatar_url or None,
                    "user_id": user_id,
                },
            )
        self.db.commit()
        return self.profile(user_id) if result.rowcount else None

    def update_email(self, user_id: int, email: str) -> Optional[dict[str, Any]]:
        result = self.db.execute(
            text(
                """
                UPDATE users
                SET email=:email, updated_at=NOW()
                WHERE uid=:user_id AND status='active'
                """
            ),
            {"email": email.lower(), "user_id": user_id},
        )
        self.db.commit()
        return self.profile(user_id) if result.rowcount else None

    def overview(self, user_id: int) -> dict[str, int]:
        queries = {
            "articles": "SELECT COUNT(*) FROM articles WHERE owner_id=:uid",
            "published_articles": "SELECT COUNT(*) FROM articles WHERE owner_id=:uid AND status='published'",
            "comments": "SELECT COUNT(*) FROM comments WHERE user_id=:uid",
            "friend_applications": "SELECT COUNT(*) FROM friend_link_applications WHERE user_id=:uid",
            "replies": """
                SELECT COUNT(*)
                FROM comments reply
                JOIN comments mine ON mine.id = reply.parent_id
                WHERE mine.user_id=:uid
                  AND COALESCE(reply.user_id, 0) <> :uid
                  AND reply.status='visible'
            """,
        }
        return {
            key: int(self.db.execute(text(sql), {"uid": user_id}).scalar_one())
            for key, sql in queries.items()
        }

    def list_articles(
        self, user_id: int, limit: int, offset: int, search: Optional[str] = None
    ) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {"uid": user_id, "limit": limit, "offset": offset}
        where = ["a.owner_id=:uid"]
        if search:
            where.append("(a.title LIKE :search OR a.slug LIKE :search)")
            params["search"] = f"%{search}%"
        condition = " AND ".join(where)
        total = int(
            self.db.execute(
                text(f"SELECT COUNT(*) FROM articles a WHERE {condition}"), params
            ).scalar_one()
        )
        rows = self.db.execute(
            text(
                f"""
                SELECT a.*, COALESCE(NULLIF(u.display_name, ''), u.username, '') AS author,
                       u.avatar_url AS author_avatar
                FROM articles a
                LEFT JOIN users u ON u.uid=a.owner_id
                WHERE {condition}
                ORDER BY a.updated_at DESC, a.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        return [article_row(dict(row)) for row in rows], total

    def get_article(self, user_id: int, article_id: int) -> Optional[dict[str, Any]]:
        row = self.db.execute(
            text(
                """
                SELECT a.*, COALESCE(NULLIF(u.display_name, ''), u.username, '') AS author,
                       u.avatar_url AS author_avatar
                FROM articles a
                LEFT JOIN users u ON u.uid=a.owner_id
                WHERE a.id=:article_id AND a.owner_id=:uid
                LIMIT 1
                """
            ),
            {"article_id": article_id, "uid": user_id},
        ).mappings().first()
        return article_row(dict(row)) if row else None

    def list_comments(
        self, user_id: int, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        params = {"uid": user_id, "limit": limit, "offset": offset}
        total = int(
            self.db.execute(
                text("SELECT COUNT(*) FROM comments WHERE user_id=:uid"), params
            ).scalar_one()
        )
        rows = self.db.execute(
            text(
                """
                SELECT c.id, c.article_id, c.parent_id, c.body_markdown, c.status,
                       c.edited_at, c.created_at, c.updated_at,
                       a.title AS article_title, a.slug AS article_slug
                FROM comments c
                LEFT JOIN articles a ON a.id=c.article_id
                WHERE c.user_id=:uid
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        items = []
        for row in rows:
            items.append(
                {
                    "id": int(row["id"]),
                    "article_id": int(row["article_id"]),
                    "article_title": str(row["article_title"] or ""),
                    "article_slug": str(row["article_slug"] or ""),
                    "parent_id": int(row["parent_id"]) if row["parent_id"] is not None else None,
                    "body_markdown": str(row["body_markdown"] or ""),
                    "status": str(row["status"] or ""),
                    "edited_at": _iso(row["edited_at"]),
                    "created_at": _iso(row["created_at"]),
                    "updated_at": _iso(row["updated_at"]),
                }
            )
        return items, total

    def update_comment(self, user_id: int, comment_id: int, body: str) -> bool:
        result = self.db.execute(
            text(
                """
                UPDATE comments
                SET body_markdown=:body, edited_at=NOW(), updated_at=NOW()
                WHERE id=:comment_id AND user_id=:uid
                """
            ),
            {"body": body, "comment_id": comment_id, "uid": user_id},
        )
        self.db.commit()
        return result.rowcount > 0

    def delete_comment(self, user_id: int, comment_id: int) -> bool:
        result = self.db.execute(
            text("DELETE FROM comments WHERE id=:comment_id AND user_id=:uid"),
            {"comment_id": comment_id, "uid": user_id},
        )
        self.db.commit()
        return result.rowcount > 0

    def notifications(self, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        replies = self.db.execute(
            text(
                """
                SELECT reply.id, reply.body_markdown, reply.user_name_snapshot,
                       reply.created_at, a.title AS article_title, a.slug AS article_slug
                FROM comments reply
                JOIN comments mine ON mine.id=reply.parent_id
                LEFT JOIN articles a ON a.id=reply.article_id
                WHERE mine.user_id=:uid
                  AND COALESCE(reply.user_id, 0) <> :uid
                  AND reply.status='visible'
                ORDER BY reply.created_at DESC
                LIMIT :limit
                """
            ),
            {"uid": user_id, "limit": limit},
        ).mappings().all()
        for row in replies:
            body = str(row["body_markdown"] or "")
            items.append(
                {
                    "id": f"reply:{row['id']}",
                    "type": "comment_reply",
                    "title": f"{row['user_name_snapshot'] or '访客'} 回复了你的评论",
                    "body": body[:180],
                    "created_at": _iso(row["created_at"]),
                    "href": (
                        f"https://www.example.com/post/{row['article_slug']}/#comment-{row['id']}"
                        if row["article_slug"]
                        else ""
                    ),
                }
            )

        applications = self.db.execute(
            text(
                """
                SELECT id, site_name, status, rejection_reason, updated_at
                FROM friend_link_applications
                WHERE user_id=:uid AND status IN ('approved','rejected')
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"uid": user_id, "limit": limit},
        ).mappings().all()
        for row in applications:
            approved = str(row["status"]) == "approved"
            items.append(
                {
                    "id": f"friend:{row['id']}",
                    "type": "friend_link",
                    "title": "友情链接已通过" if approved else "友情链接申请未通过",
                    "body": (
                        f"{row['site_name']} 已加入友链"
                        if approved
                        else str(row["rejection_reason"] or row["site_name"] or "")
                    ),
                    "created_at": _iso(row["updated_at"]),
                    "href": "https://www.example.com/friends/" if approved else "",
                }
            )

        article_events = self.db.execute(
            text(
                """
                SELECT id, title, slug, status, updated_at
                FROM articles
                WHERE owner_id=:uid AND status IN ('rejected','pending')
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"uid": user_id, "limit": limit},
        ).mappings().all()
        for row in article_events:
            status = str(row["status"])
            items.append(
                {
                    "id": f"article:{row['id']}:{status}",
                    "type": "article_status",
                    "title": "文章需要处理" if status == "rejected" else "文章正在等待处理",
                    "body": str(row["title"] or ""),
                    "created_at": _iso(row["updated_at"]),
                    "href": "",
                }
            )

        items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return items[:limit]

    def list_friend_applications(self, user_id: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                SELECT id, site_name, website_url, avatar_url, language, rss_url,
                       description, applicant_note,
                       status, verification_expires_at, email_verified_at,
                       rejection_reason, friend_link_id, created_at, updated_at
                FROM friend_link_applications
                WHERE user_id=:uid
                ORDER BY created_at DESC, id DESC
                """
            ),
            {"uid": user_id},
        ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "site_name": str(row["site_name"] or ""),
                "website_url": str(row["website_url"] or ""),
                "avatar_url": str(row["avatar_url"] or ""),
                "language": str(row["language"] or ""),
                "rss_url": str(row["rss_url"] or ""),
                "description": str(row["description"] or ""),
                "applicant_note": str(row["applicant_note"] or ""),
                "status": str(row["status"] or ""),
                "verification_expires_at": _iso(row["verification_expires_at"]),
                "email_verified_at": _iso(row["email_verified_at"]),
                "rejection_reason": str(row["rejection_reason"] or ""),
                "friend_link_id": int(row["friend_link_id"]) if row["friend_link_id"] else None,
                "created_at": _iso(row["created_at"]),
                "updated_at": _iso(row["updated_at"]),
            }
            for row in rows
        ]

    def active_friend_count(self, user_id: int) -> int:
        return int(
            self.db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM friend_link_applications
                    WHERE user_id=:uid AND status IN ('pending_email','approved')
                    """
                ),
                {"uid": user_id},
            ).scalar_one()
        )

    def friend_link_url_exists(self, website_url: str) -> bool:
        """这个网址是否已经是上线中的友链。"""
        return bool(
            self.db.execute(
                text("SELECT 1 FROM friend_links WHERE website_url=:u LIMIT 1"),
                {"u": website_url},
            ).first()
        )

    def friend_application_url_exists(self, user_id: int, website_url: str) -> bool:
        """该账号是否已经为这个网址提交过（待认证或已通过）。"""
        return bool(
            self.db.execute(
                text(
                    """
                    SELECT 1 FROM friend_link_applications
                    WHERE user_id=:uid AND website_url=:u
                      AND status IN ('pending_email','approved')
                    LIMIT 1
                    """
                ),
                {"uid": user_id, "u": website_url},
            ).first()
        )

    def create_friend_application(
        self,
        user_id: int,
        *,
        site_name: str,
        website_url: str,
        avatar_url: str,
        language: str,
        rss_url: str,
        description: str,
        applicant_note: str,
    ) -> dict[str, Any]:
        # Serialize creation per account so concurrent requests cannot exceed the quota.
        self.db.execute(
            text("SELECT uid FROM users WHERE uid=:uid FOR UPDATE"),
            {"uid": user_id},
        ).first()
        if self.active_friend_count(user_id) >= 3:
            self.db.rollback()
            raise ValueError("friend_link_limit_reached")

        duplicate = self.db.execute(
            text(
                """
                SELECT id
                FROM friend_link_applications
                WHERE user_id=:uid AND website_url=:website_url
                  AND status IN ('pending_email','approved')
                LIMIT 1
                """
            ),
            {"uid": user_id, "website_url": website_url},
        ).first()
        if duplicate:
            self.db.rollback()
            raise ValueError("friend_application_exists")
        if self.db.execute(
            text("SELECT 1 FROM friend_links WHERE website_url=:website_url LIMIT 1"),
            {"website_url": website_url},
        ).first():
            self.db.rollback()
            raise ValueError("friend_link_exists")

        result = self.db.execute(
            text(
                """
                INSERT INTO friend_link_applications
                  (user_id, site_name, website_url, avatar_url, language, rss_url,
                   description, applicant_note,
                   status, verification_token_hash, verification_expires_at,
                   created_at, updated_at)
                VALUES
                  (:uid, :site_name, :website_url, :avatar_url, :language, :rss_url,
                   :description, :applicant_note,
                   'pending_email', NULL, NULL, NOW(), NOW())
                """
            ),
            {
                "uid": user_id,
                "site_name": site_name,
                "website_url": website_url,
                "avatar_url": avatar_url or None,
                "language": language or None,
                "rss_url": rss_url or None,
                "description": description or None,
                "applicant_note": applicant_note or None,
            },
        )
        self.db.commit()
        application_id = int(result.lastrowid)
        return next(
            item for item in self.list_friend_applications(user_id)
            if item["id"] == application_id
        )

    def get_friend_application(
        self, user_id: int, application_id: int
    ) -> Optional[dict[str, Any]]:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM friend_link_applications
                WHERE id=:application_id AND user_id=:uid
                LIMIT 1
                """
            ),
            {"application_id": application_id, "uid": user_id},
        ).mappings().first()
        return dict(row) if row else None

    def get_friend_application_by_token(self, token_hash: str) -> Optional[dict[str, Any]]:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM friend_link_applications
                WHERE verification_token_hash=:token_hash
                LIMIT 1
                """
            ),
            {"token_hash": token_hash},
        ).mappings().first()
        return dict(row) if row else None

    def set_friend_verification(
        self,
        user_id: int,
        application_id: int,
        *,
        token_hash: Optional[str],
        expires_at: Any = None,
    ) -> bool:
        result = self.db.execute(
            text(
                """
                UPDATE friend_link_applications
                SET verification_token_hash=:token_hash,
                    verification_expires_at=:expires_at,
                    updated_at=NOW()
                WHERE id=:application_id
                  AND user_id=:uid
                  AND status='pending_email'
                """
            ),
            {
                "token_hash": token_hash,
                "expires_at": expires_at,
                "application_id": application_id,
                "uid": user_id,
            },
        )
        self.db.commit()
        return result.rowcount > 0

    def approve_friend_application(
        self, user_id: int, application_id: int
    ) -> dict[str, Any]:
        application = self.db.execute(
            text(
                """
                SELECT *
                FROM friend_link_applications
                WHERE id=:application_id AND user_id=:uid
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"application_id": application_id, "uid": user_id},
        ).mappings().first()
        if not application:
            self.db.rollback()
            raise ValueError("friend_application_not_found")
        if application["status"] == "approved":
            self.db.rollback()
            return self.get_friend_application(user_id, application_id) or {}
        if application["status"] != "pending_email":
            self.db.rollback()
            raise ValueError("friend_application_not_pending")

        existing = self.db.execute(
            text(
                """
                SELECT id
                FROM friend_links
                WHERE website_url=:website_url
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"website_url": application["website_url"]},
        ).first()
        if existing:
            self.db.rollback()
            raise ValueError("friend_link_exists")

        sort_order = int(
            self.db.execute(
                text("SELECT COALESCE(MAX(sort_order), 0) + 10 FROM friend_links")
            ).scalar_one()
        )
        result = self.db.execute(
            text(
                """
                INSERT INTO friend_links
                  (name, avatar_url, description, website_url, language, rss_url, sort_order,
                   is_enabled, created_by, created_at, updated_at)
                VALUES
                  (:name, :avatar_url, :description, :website_url, :language, :rss_url, :sort_order,
                    1, :uid, NOW(), NOW())
                """
            ),
            {
                "name": application["site_name"],
                "avatar_url": application["avatar_url"],
                "description": application["description"],
                "website_url": application["website_url"],
                "language": application["language"],
                "rss_url": application["rss_url"],
                "sort_order": sort_order,
                "uid": user_id,
            },
        )
        friend_link_id = int(result.lastrowid)
        self.db.execute(
            text(
                """
                UPDATE friend_link_applications
                SET status='approved',
                    email_verified_at=NOW(),
                    reviewed_at=NOW(),
                    friend_link_id=:friend_link_id,
                    rejection_reason=NULL,
                    verification_token_hash=NULL,
                    verification_expires_at=NULL,
                    updated_at=NOW()
                WHERE id=:application_id AND user_id=:uid
                """
            ),
            {
                "friend_link_id": friend_link_id,
                "application_id": application_id,
                "uid": user_id,
            },
        )
        self.db.commit()
        return self.get_friend_application(user_id, application_id) or {}

    def update_friend_application(
        self,
        user_id: int,
        application_id: int,
        *,
        site_name: str,
        website_url: str,
        avatar_url: str,
        language: str,
        rss_url: str,
        description: str,
        applicant_note: str,
    ) -> dict[str, Any]:
        application = self.db.execute(
            text(
                """
                SELECT *
                FROM friend_link_applications
                WHERE id=:application_id AND user_id=:uid
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"application_id": application_id, "uid": user_id},
        ).mappings().first()
        if not application:
            self.db.rollback()
            raise ValueError("friend_application_not_found")

        duplicate = self.db.execute(
            text(
                """
                SELECT id
                FROM friend_link_applications
                WHERE user_id=:uid AND website_url=:website_url
                  AND id<>:application_id
                  AND status IN ('pending_email','approved')
                LIMIT 1
                """
            ),
            {
                "uid": user_id,
                "website_url": website_url,
                "application_id": application_id,
            },
        ).first()
        if duplicate:
            self.db.rollback()
            raise ValueError("friend_application_exists")

        friend_link_id = (
            int(application["friend_link_id"])
            if application.get("friend_link_id")
            else None
        )
        if application["status"] == "approved" and not friend_link_id:
            matched = self.db.execute(
                text(
                    """
                    SELECT id FROM friend_links
                    WHERE website_url=:old_website_url
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {"old_website_url": application["website_url"]},
            ).first()
            if matched:
                friend_link_id = int(matched[0])

        public_duplicate = self.db.execute(
            text(
                """
                SELECT id
                FROM friend_links
                WHERE website_url=:website_url
                  AND (:friend_link_id IS NULL OR id<>:friend_link_id)
                LIMIT 1
                """
            ),
            {"website_url": website_url, "friend_link_id": friend_link_id},
        ).first()
        if public_duplicate:
            self.db.rollback()
            raise ValueError("friend_link_exists")

        self.db.execute(
            text(
                """
                UPDATE friend_link_applications
                SET site_name=:site_name,
                    website_url=:website_url,
                    avatar_url=:avatar_url,
                    language=:language,
                    rss_url=:rss_url,
                    description=:description,
                    applicant_note=:applicant_note,
                    friend_link_id=COALESCE(:friend_link_id, friend_link_id),
                    updated_at=NOW()
                WHERE id=:application_id AND user_id=:uid
                """
            ),
            {
                "site_name": site_name,
                "website_url": website_url,
                "avatar_url": avatar_url or None,
                "language": language or None,
                "rss_url": rss_url or None,
                "description": description or None,
                "applicant_note": applicant_note or None,
                "friend_link_id": friend_link_id,
                "application_id": application_id,
                "uid": user_id,
            },
        )

        if application["status"] == "approved":
            if friend_link_id:
                self.db.execute(
                    text(
                        """
                        UPDATE friend_links
                        SET name=:name,
                            avatar_url=:avatar_url,
                            description=:description,
                            website_url=:website_url,
                            language=:language,
                            rss_url=:rss_url,
                            is_enabled=1,
                            updated_at=NOW()
                        WHERE id=:friend_link_id
                        """
                    ),
                    {
                        "name": site_name,
                        "avatar_url": avatar_url or None,
                        "description": description or None,
                        "website_url": website_url,
                        "language": language or None,
                        "rss_url": rss_url or None,
                        "friend_link_id": friend_link_id,
                    },
                )
            else:
                sort_order = int(
                    self.db.execute(
                        text("SELECT COALESCE(MAX(sort_order), 0) + 10 FROM friend_links")
                    ).scalar_one()
                )
                result = self.db.execute(
                    text(
                        """
                        INSERT INTO friend_links
                          (name, avatar_url, description, website_url, language, rss_url, sort_order,
                           is_enabled, created_by, created_at, updated_at)
                        VALUES
                          (:name, :avatar_url, :description, :website_url, :language, :rss_url, :sort_order,
                           1, :uid, NOW(), NOW())
                        """
                    ),
                    {
                        "name": site_name,
                        "avatar_url": avatar_url or None,
                        "description": description or None,
                        "website_url": website_url,
                        "language": language or None,
                        "rss_url": rss_url or None,
                        "sort_order": sort_order,
                        "uid": user_id,
                    },
                )
                friend_link_id = int(result.lastrowid)
                self.db.execute(
                    text(
                        """
                        UPDATE friend_link_applications
                        SET friend_link_id=:friend_link_id, updated_at=NOW()
                        WHERE id=:application_id AND user_id=:uid
                        """
                    ),
                    {
                        "friend_link_id": friend_link_id,
                        "application_id": application_id,
                        "uid": user_id,
                    },
                )

        self.db.commit()
        return next(
            item for item in self.list_friend_applications(user_id)
            if item["id"] == application_id
        )

    def delete_friend_application(self, user_id: int, application_id: int) -> bool:
        application = self.db.execute(
            text(
                """
                SELECT *
                FROM friend_link_applications
                WHERE id=:application_id AND user_id=:uid
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"application_id": application_id, "uid": user_id},
        ).mappings().first()
        if not application:
            self.db.rollback()
            return False

        friend_link_id = (
            int(application["friend_link_id"])
            if application.get("friend_link_id")
            else None
        )
        if application["status"] == "approved" and not friend_link_id:
            matched = self.db.execute(
                text(
                    """
                    SELECT id
                    FROM friend_links
                    WHERE website_url=:website_url
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {"website_url": application["website_url"]},
            ).first()
            if matched:
                friend_link_id = int(matched[0])

        if friend_link_id:
            self.db.execute(
                text("DELETE FROM friend_links WHERE id=:friend_link_id"),
                {"friend_link_id": friend_link_id},
            )
        result = self.db.execute(
            text(
                """
                DELETE FROM friend_link_applications
                WHERE id=:application_id AND user_id=:uid
                """
            ),
            {"application_id": application_id, "uid": user_id},
        )
        self.db.commit()
        return result.rowcount > 0
