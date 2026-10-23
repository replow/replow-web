import secrets
import string
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import password_hasher
from app.core.password_policy import valid_new_password
from app.repositories.admin import AdminRepository
from app.repositories.public import PublicRepository
from app.repositories.users import UserRepository
from app.services.account import _clean_email, _clean_username


class AdminError(Exception):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


ARTICLE_STATUSES = {"draft", "pending", "published", "rejected"}
USER_ROLES = {"admin", "user"}
USER_STATUSES = {"active", "disabled"}
MAX_UNSIGNED_BIGINT = (1 << 64) - 1


def _text(value: Any, *, max_length: int, field: str, required: bool = False) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise AdminError(f"{field}_required")
    if len(result) > max_length:
        raise AdminError(f"{field}_too_long")
    return result


def _http_url(value: Any, *, field: str, required: bool = False, max_length: int = 2048) -> str:
    result = _text(value, max_length=max_length, field=field, required=required)
    if not result:
        return result
    parsed = urlparse(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AdminError(f"invalid_{field}")
    return result


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace("，", ",").split(",")
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result: list[str] = []
    for item in values:
        tag = str(item or "").strip()
        if not tag or tag in result:
            continue
        if len(tag) > 50:
            raise AdminError("tag_too_long")
        result.append(tag)
    if len(result) > 30:
        raise AdminError("too_many_tags")
    return result


def _clean_uid(value: Any, *, required: bool) -> Optional[int]:
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise AdminError("uid_required")
        return None
    if not raw.isdigit():
        raise AdminError("invalid_uid")
    uid = int(raw)
    if uid < 1 or uid > MAX_UNSIGNED_BIGINT:
        raise AdminError("invalid_uid")
    return uid


def _random_password(length: int = 20) -> str:
    groups = (
        string.ascii_uppercase,
        string.ascii_lowercase,
        string.digits,
        "!@#$%^&*()-_=+",
    )
    alphabet = "".join(groups)
    chars = [secrets.choice(group) for group in groups]
    chars.extend(secrets.choice(alphabet) for _ in range(max(0, length - len(chars))))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


class AdminService:
    """Admin use cases; all writes remain behind repositories."""

    def __init__(self, db: Session):
        self.repository = AdminRepository(db)
        self.public_repository = PublicRepository(db)
        self.user_repository = UserRepository(db)

    def dashboard(self) -> dict:
        return self.repository.dashboard()

    def articles(self, limit: int, offset: int, search: Optional[str]):
        return self.repository.list_articles(limit, offset, search)

    def article(self, article_id: int) -> Optional[dict]:
        return self.repository.get_article(article_id)

    def create_article(self, payload: dict[str, Any], user_id: int) -> dict:
        data = self._article_payload(payload)
        try:
            return self.repository.create_article(data, user_id)
        except IntegrityError as error:
            self.repository.db.rollback()
            raise AdminError("article_slug_already_exists", 409) from error

    def update_article(self, article_id: int, payload: dict[str, Any], actor_id: Optional[int] = None, reason: str = "save") -> Optional[dict]:
        from app.services.article_history import fingerprint
        from sqlalchemy import text
        from fastapi import HTTPException
        self.repository.db.execute(text("SELECT id FROM articles WHERE id=:id FOR UPDATE"), {"id": article_id})
        existing = self.repository.get_article(article_id)
        if not existing:
            return None
        if payload.get("_base_token") and payload["_base_token"] != fingerprint(existing):
            raise HTTPException(409, "article_changed_reload")
        data = self._article_payload(payload, existing=existing)
        data["_actor_id"] = actor_id
        data["_reason"] = reason
        try:
            return self.repository.update_article(article_id, data)
        except IntegrityError as error:
            self.repository.db.rollback()
            raise AdminError("article_slug_already_exists", 409) from error

    def delete_article(self, article_id: int) -> bool:
        return self.repository.delete_article(article_id)

    def comments(self, article_id: Optional[int], limit: int, offset: int):
        return self.public_repository.comments(article_id, limit, offset)

    def update_comment_status(self, comment_id: int, next_status: str) -> bool:
        return self.repository.update_comment_status(comment_id, next_status)

    def friends(self, limit: int, offset: int):
        return self.repository.friends(limit, offset)

    def save_friend(
        self, payload: dict[str, Any], user_id: int, friend_id: Optional[int] = None
    ) -> dict:
        if friend_id is not None and not self.repository.friend_exists(friend_id):
            raise AdminError("friend_not_found", 404)
        data = self._friend_payload(payload)
        try:
            return self.repository.save_friend(data, user_id, friend_id)
        except IntegrityError as error:
            self.repository.db.rollback()
            raise AdminError("friend_save_failed", 409) from error

    def delete_friend(self, friend_id: int) -> bool:
        return self.repository.delete_friend(friend_id)

    def site_settings(self) -> dict:
        return self.public_repository.settings()

    def update_site_settings(self, payload: dict[str, Any], user_id: int) -> dict:
        for key, value in payload.items():
            if not key.startswith("_"):
                self.repository.update_setting(str(key), value, user_id)
        return self.public_repository.settings()

    def firefly_config(self) -> dict[str, Any]:
        value = self.public_repository.settings(["firefly_config"]).get("firefly_config")
        return value if isinstance(value, dict) else {}

    def update_firefly_config(self, config: dict[str, Any], user_id: int) -> dict[str, Any]:
        """Persist the complete Firefly object and mirror legacy runtime aliases."""
        values: dict[str, Any] = {"firefly_config": config}
        site = config.get("siteConfig") if isinstance(config.get("siteConfig"), dict) else {}
        profile = config.get("profileConfig") if isinstance(config.get("profileConfig"), dict) else {}
        wallpaper = (
            config.get("backgroundWallpaper")
            if isinstance(config.get("backgroundWallpaper"), dict)
            else {}
        )
        announcement = (
            config.get("announcementConfig")
            if isinstance(config.get("announcementConfig"), dict)
            else {}
        )
        footer = config.get("footerConfig") if isinstance(config.get("footerConfig"), dict) else {}

        def first_image(value: Any) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return str(value[0]) if value else ""
            return ""

        src = wallpaper.get("src") if isinstance(wallpaper.get("src"), dict) else {}
        desktop = first_image(src.get("desktop"))
        mobile = first_image(src.get("mobile"))
        if not desktop:
            desktop = first_image(wallpaper.get("desktop"))
        if not mobile:
            mobile = first_image(wallpaper.get("mobile"))
        favicon = site.get("favicon")
        favicon_url = ""
        if isinstance(favicon, list) and favicon and isinstance(favicon[0], dict):
            favicon_url = str(favicon[0].get("src") or "")

        values.update(
            {
                "site_name": site.get("title", ""),
                "main_site_url": site.get("site_url", ""),
                "profile_name": profile.get("name", ""),
                "profile_intro": profile.get("bio", ""),
                "profile_avatar_url": profile.get("avatar", ""),
                "site_icon_url": favicon_url,
                "desktop_background_url": desktop,
                "mobile_background_url": mobile,
                "site_wallpaper": {
                    "desktop": desktop,
                    "mobile": mobile,
                    "mode": wallpaper.get("mode", "banner"),
                },
                "announcement_enabled": bool(announcement),
                "announcement_title": announcement.get("title", ""),
                "announcement_body_markdown": announcement.get("content", ""),
                "footer_html": footer.get("customHtml", ""),
            }
        )
        self.repository.update_settings(values, user_id)
        return config

    def media(self, limit: int, offset: int):
        return self.repository.media(limit, offset)

    def users(self, limit: int, offset: int):
        return self.user_repository.list_users(limit, offset)

    def create_user(self, payload: dict[str, Any]) -> dict:
        data = self._user_payload(payload)
        if data["uid"] is not None and self.user_repository.uid_exists(data["uid"]):
            raise AdminError("uid_already_exists", 409)
        password = payload.get("password")
        if password not in (None, ""):
            data["password_hash"] = password_hasher.hash(str(password))
        try:
            return self.user_repository.create_admin_user(data)
        except IntegrityError as error:
            self.user_repository.db.rollback()
            raise AdminError("username_or_email_already_exists", 409) from error

    def update_user(self, user_id: int, payload: dict[str, Any], actor_id: int) -> Optional[dict]:
        existing = self.user_repository.get_by_id(user_id)
        if not existing:
            return None
        data = self._user_payload(payload, existing=existing)
        if self.user_repository.uid_exists(data["uid"], exclude_user_id=user_id):
            raise AdminError("uid_already_exists", 409)
        if self.user_repository.email_exists(data["email"], exclude_user_id=user_id):
            raise AdminError("email_already_exists", 409)
        if user_id == actor_id and (
            data["role"] != existing["role"] or data["status"] != "active"
        ):
            raise AdminError("cannot_change_own_admin_access", 400)
        if (
            existing["role"] == "admin"
            and existing["status"] == "active"
            and (data["role"] != "admin" or data["status"] != "active")
            and self.user_repository.active_admin_count() <= 1
        ):
            raise AdminError("last_active_admin_required", 400)
        generated_password = None
        if payload.get("generate_password") or payload.get("clear_password"):
            generated_password = _random_password()
            data["password_hash"] = password_hasher.hash(generated_password)
        elif payload.get("password") not in (None, ""):
            data["password_hash"] = password_hasher.hash(str(payload["password"]))
        try:
            updated = self.user_repository.update_admin_user(user_id, data)
        except IntegrityError as error:
            self.user_repository.db.rollback()
            raise AdminError("user_save_failed", 409) from error
        if updated and generated_password:
            updated["generated_password"] = generated_password
        return updated

    def delete_user(self, user_id: int, actor_id: int) -> bool:
        existing = self.user_repository.get_by_id(user_id)
        if not existing:
            return False
        if user_id == actor_id:
            raise AdminError("cannot_delete_current_user", 400)
        if existing["role"] == "admin" and self.user_repository.admin_count() <= 1:
            raise AdminError("last_admin_required", 400)
        try:
            return self.user_repository.delete_admin_user(user_id)
        except IntegrityError as error:
            self.user_repository.db.rollback()
            raise AdminError("user_delete_failed", 409) from error

    @staticmethod
    def _article_payload(payload: dict[str, Any], existing: Optional[dict] = None) -> dict[str, Any]:
        current = existing or {}
        title = _text(
            payload.get("title", current.get("title")),
            max_length=200,
            field="title",
            required=True,
        )
        slug = _text(payload.get("slug", current.get("slug")), max_length=220, field="slug")
        if not slug:
            slug = "article-" + __import__("secrets").token_hex(6)
        excerpt = _text(
            payload.get("excerpt", current.get("excerpt")),
            max_length=500,
            field="excerpt",
        )
        body = str(payload.get("body_markdown", current.get("body_markdown", "")) or "")
        if not body.strip():
            raise AdminError("body_markdown_required")
        if len(body) > 8_000_000:
            raise AdminError("body_markdown_too_long")
        status = str(
            payload.get("status", current.get("status", "draft")) or "draft"
        ).strip().lower()
        if status not in ARTICLE_STATUSES:
            raise AdminError("invalid_article_status")
        category = _text(
            payload.get("category", current.get("category")),
            max_length=100,
            field="category",
        )
        cover_url = _text(
            payload.get("cover_url", current.get("cover_url")),
            max_length=2048,
            field="cover_url",
        )
        icon_url = _text(
            payload.get("icon_url", current.get("icon_url")),
            max_length=2048,
            field="icon_url",
        )
        return {
            "title": title,
            "slug": slug,
            "excerpt": excerpt,
            "body_markdown": body,
            "cover_url": cover_url,
            "icon_url": icon_url,
            "status": status,
            "is_pinned": bool(payload.get("is_pinned", current.get("is_pinned", False))),
            "published_at": payload.get("published_at", current.get("published_at")),
            "category": category,
            "tags": _tags(payload.get("tags", current.get("tags", []))),
        }

    @staticmethod
    def _friend_payload(payload: dict[str, Any]) -> dict[str, Any]:
        name = _text(
            payload.get("name"),
            max_length=120,
            field="friend_name",
            required=True,
        )
        website_url = _http_url(payload.get("website_url"), field="website_url", required=True)
        avatar_url = _http_url(payload.get("avatar_url"), field="avatar_url")
        description = _text(payload.get("description"), max_length=500, field="description")
        language = _text(payload.get("language"), max_length=80, field="language")
        rss_url = _http_url(payload.get("rss_url"), field="rss_url")
        category = _text(payload.get("category"), max_length=80, field="friend_category")
        try:
            sort_order = int(payload.get("sort_order", 0) or 0)
        except (TypeError, ValueError) as error:
            raise AdminError("invalid_sort_order") from error
        if sort_order < -1_000_000 or sort_order > 1_000_000:
            raise AdminError("invalid_sort_order")
        return {
            "name": name,
            "avatar_url": avatar_url,
            "description": description,
            "website_url": website_url,
            "language": language,
            "rss_url": rss_url,
            "category": category,
            "sort_order": sort_order,
            "is_enabled": bool(payload.get("is_enabled", True)),
        }

    @staticmethod
    def _user_payload(payload: dict[str, Any], existing: Optional[dict] = None) -> dict[str, Any]:
        current = existing or {}
        uid = _clean_uid(
            payload.get("uid", current.get("uid")),
            required=existing is not None,
        )
        username = _clean_username(payload.get("username", current.get("username")))
        email = _clean_email(payload.get("email", current.get("email")))
        display_name = _text(
            payload.get("display_name", current.get("display_name") or username),
            max_length=80,
            field="display_name",
        ) or username
        role = str(payload.get("role", current.get("role", "user")) or "user").strip().lower()
        status = str(payload.get("status", current.get("status", "active")) or "active").strip().lower()
        if role not in USER_ROLES:
            raise AdminError("invalid_user_role")
        if status not in USER_STATUSES:
            raise AdminError("invalid_user_status")
        password = payload.get("password")
        if password not in (None, "") and not valid_new_password(str(password)):
            raise AdminError("invalid_password")
        return {
            "uid": uid,
            "username": username,
            "email": email,
            "display_name": display_name,
            "avatar_url": _text(
                payload.get("avatar_url", current.get("avatar_url")),
                max_length=2048,
                field="avatar_url",
            ),
            "bio": _text(
                payload.get("bio", current.get("bio")),
                max_length=500,
                field="bio",
            ),
            "website_url": _http_url(
                payload.get("website_url", current.get("website_url")),
                field="website_url",
            ),
            "role": role,
            "status": status,
        }
