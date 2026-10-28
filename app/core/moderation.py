"""Restriction state and human-readable notices. All persisted times are UTC."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException

KINDS = {"ban": "账号封禁", "mute": "禁言", "publish": "禁止发布文章"}


def utc(value):
    if not value:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def restrictions(user, now=None):
    now = now or datetime.utcnow()
    result = []
    for kind, label in KINDS.items():
        start, end = utc(user.get(kind + "_started_at")), utc(user.get(kind + "_until"))
        if not start or (end and end <= now):
            continue
        result.append({"kind": kind, "label": label,
                       "started_at": start.isoformat() + "Z",
                       "until": end.isoformat() + "Z" if end else None,
                       "reason": user.get(kind + "_reason") or "未填写原因"})
    return result


def date_label(value):
    if not value:
        return "永久（需管理员解除）"
    return utc(value).replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S（北京时间）")


def notice(item):
    return (f"{item['label']}：{item['reason']}；开始日期：{date_label(item['started_at'])}；"
            f"解封/解除日期：{date_label(item['until'])}")


def enforce(user, kind="ban"):
    for item in restrictions(user):
        if item["kind"] == kind:
            raise HTTPException(401 if kind == "ban" else 403, notice(item))


def require_comment(user):
    enforce(user)
    enforce(user, "mute")


def require_publish(user):
    enforce(user)
    enforce(user, "publish")
