"""Bounded request snapshots and readable names for administrative operations."""
import re
from sqlalchemy import text

PRIVATE = re.compile(r"password|secret|token|authorization|api.?key|access.?key|credential|cookie|(^|_)code($|_)|verification", re.I)
RESOURCES = {"users": "用户", "articles": "文章", "article-drafts": "文章草稿", "comments": "评论",
    "friends": "友情链接", "albums": "相册", "media": "媒体", "site": "站点设置", "account": "账号设置",
    "cdn": "CDN 缓存", "storage": "存储配置", "fq": "番茄小说", "access-keys": "访问密钥",
    "dynamics": "动态", "oauth": "应用授权"}


def sanitize(value, depth=0):
    if depth > 6:
        return "[层级过深，已省略]"
    if isinstance(value, dict):
        # Generic key/value configuration endpoints can carry secrets under value.
        private_value = any(PRIVATE.search(str(value.get(k, ""))) for k in ("key", "setting_key", "name"))
        return {str(k)[:100]: "[已隐藏]" if PRIVATE.search(str(k)) or (private_value and k == "value")
                else sanitize(v, depth + 1) for k, v in list(value.items())[:60]}
    if isinstance(value, list):
        return [sanitize(v, depth + 1) for v in value[:30]] + (["[其余项目已省略]"] if len(value) > 30 else [])
    if isinstance(value, str):
        # Signed URLs can contain credentials inside the string itself.
        value = re.sub(r"([?&](?:token|key|secret|signature|sig|code|password|access_token|refresh_token)=)[^&#\s]*", r"\1[已隐藏]", value, flags=re.I)
        return value[:2000] + ("…[内容过长，已截断]" if len(value) > 2000 else "")
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)[:200]


def operation(method, resource, path):
    label = RESOURCES.get(resource, resource)
    for fragment, title in [("/restrictions", "调整用户限制"), ("/restore", "恢复"), ("/purge", "永久删除"),
                            ("/publish", "发布"), ("/build", "构建站点"), ("/test", "测试"), ("/purge-cache", "刷新缓存")]:
        if fragment in path:
            return title + ("" if fragment == "/restrictions" else label)
    return {"POST": "新增/执行", "PUT": "更新", "PATCH": "修改", "DELETE": "删除"}.get(method, method) + label


def target_name(db, resource, target):
    tables = {"users": ("users", "uid", "CONCAT(COALESCE(NULLIF(display_name,''),username),' (@',username,')')"),
              "articles": ("articles", "id", "title"), "comments": ("comments", "id", "LEFT(body_markdown,120)"),
              "friends": ("friend_links", "id", "name"), "albums": ("photo_albums", "id", "title"),
              "media": ("media_objects", "id", "original_name"), "dynamics": ("dynamics", "id", "LEFT(body_markdown,120)")}
    if resource not in tables or not str(target).isdigit():
        return ""
    table, key, column = tables[resource]
    try:
        return str(db.execute(text(f"SELECT {column} FROM {table} WHERE {key}=:id"), {"id": target}).scalar() or "")[:500]
    except Exception:
        db.rollback()
        return ""
