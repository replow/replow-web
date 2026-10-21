from typing import Optional

from sqlalchemy.orm import Session

from app.core.firefly import firefly_group, first_image, public_firefly_config
from app.repositories.public import PublicRepository
from app.services.rss import latest_article_cached


class PublicService:
    """Read-only use cases consumed by the public blog frontend."""

    def __init__(self, db: Session):
        self.repository = PublicRepository(db)

    def site(self) -> dict:
        settings = self.repository.settings()
        firefly = settings.get("firefly_config")
        if not isinstance(firefly, dict):
            firefly = {}
        site_config = firefly_group(firefly, "siteConfig", "site_config")
        profile_config = firefly_group(firefly, "profileConfig", "profile_config")
        wallpaper_config = firefly_group(
            firefly, "backgroundWallpaper", "background_wallpaper"
        )
        announcement_config = firefly_group(firefly, "announcementConfig", "announcement_config")
        theme_config = firefly_group(firefly, "theme", "themeConfig")
        theme = settings.get("theme") if isinstance(settings.get("theme"), dict) else {}
        wallpaper = (
            settings.get("site_wallpaper")
            if isinstance(settings.get("site_wallpaper"), dict)
            else {}
        )
        if not wallpaper:
            wallpaper = {
                "desktop": settings.get("desktop_background_url", ""),
                "mobile": settings.get("mobile_background_url", ""),
            }
        wallpaper_src = wallpaper_config.get("src")
        if isinstance(wallpaper_src, dict):
            wallpaper = {
                "desktop": first_image(wallpaper_src.get("desktop")) or wallpaper.get("desktop", ""),
                "mobile": first_image(wallpaper_src.get("mobile")) or wallpaper.get("mobile", ""),
            }
        elif wallpaper_config.get("src"):
            source = first_image(wallpaper_config.get("src"))
            wallpaper = {"desktop": source, "mobile": source}
        site_name = site_config.get("title") or settings.get("site_name", "Replow")
        profile_name = profile_config.get("name") or settings.get("profile_name", site_name)
        profile_intro = profile_config.get("bio") or settings.get("profile_intro", "")
        announcement_title = announcement_config.get("title") or settings.get("announcement_title", "")
        announcement_body = announcement_config.get("content") or settings.get("announcement_body_markdown", "")
        announcement_enabled = bool(
            settings.get("announcement_enabled", False)
            or announcement_config
        )
        site_url = site_config.get("site_url") or settings.get("main_site_url", "https://example.com")
        favicon = site_config.get("favicon")
        site_icon = settings.get("site_icon_url", "")
        if isinstance(favicon, list) and favicon and isinstance(favicon[0], dict):
            site_icon = favicon[0].get("src") or site_icon
        desktop_background = wallpaper.get("desktop") or settings.get("desktop_background_url", "")
        mobile_background = wallpaper.get("mobile") or settings.get("mobile_background_url", "")
        return {
            "site": {
                "name": site_name,
                "icon_url": site_icon,
                "url": site_url,
                "description": site_config.get("description") or profile_intro,
                "keywords": site_config.get("keywords") or settings.get("site_keywords", []),
            },
            "profile": {
                "name": profile_name,
                "avatar_url": profile_config.get("avatar") or settings.get("profile_avatar_url", ""),
                "intro": profile_intro,
                "github_url": settings.get("profile_github_url", ""),
                "bilibili_url": settings.get("profile_bilibili_url", ""),
                "qq_url": settings.get("profile_qq_url", ""),
                "qq_group_url": settings.get("profile_qq_group_url", ""),
            },
            "theme": {
                **theme,
                **theme_config,
                "wallpaper": wallpaper,
                "desktop_background_url": desktop_background,
                "mobile_background_url": mobile_background,
                "mode": wallpaper_config.get("mode") or theme.get("mode", "banner"),
            },
            "announcement": {
                "enabled": announcement_enabled,
                "title": announcement_title,
                "body_markdown": announcement_body,
                "link": announcement_config.get("link") or {},
            },
            "navigation": firefly.get("navBarConfig", firefly.get("navBar", {})),
            "firefly": public_firefly_config(firefly),
            "account": {
                "registration_enabled": bool(settings.get("registration_enabled", True)),
                "email_verification_enabled": bool(
                    settings.get("email_verification_enabled", True)
                ),
            },
            "friends": self.repository.friends(),
            "stats": self.repository.stats(),
        }

    def articles(
        self,
        limit: int,
        offset: int,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        return self.repository.list_articles(limit, offset, category, tag, search)

    def article(self, slug: str) -> Optional[dict]:
        return self.repository.get_article(slug)

    def friends(self) -> list[dict]:
        items = self.repository.friends()
        enriched: list[dict] = []
        for item in items:
            # 非阻塞：只读缓存，第三方 RSS 的抓取交给后台线程。
            # 之前这里逐个同步抓取，12 个友链里只要有一个站点慢/不可达，
            # 整个公开接口就会被挂住（实测 30s+ 超时）。
            latest = latest_article_cached(item.get("rss_url"), item.get("website_url"))
            enriched.append(
                {
                    **item,
                    "latest_article_title": latest.get("title", ""),
                    "latest_article_url": latest.get("url", ""),
                }
            )
        return enriched

    def comments(
        self, article_id: Optional[int], limit: int, offset: int
    ) -> tuple[list[dict], int]:
        return self.repository.comments(article_id, limit, offset, public_only=True)

    def songs(self) -> list[dict]:
        return self.repository.songs()
