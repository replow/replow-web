from datetime import datetime
import json
from sqlalchemy import text

PRIVATE_WORDS = ("password", "secret", "token", "authorization", "api_key", "access_key", "credential")


def payload_fields(payload):
    """Only field names, never arbitrary configuration values or secrets."""
    if not isinstance(payload, dict):
        return []
    result = []
    for key in list(payload)[:60]:
        if key in {"confirm_sensitive", "allow_uid_override", "confirmed"}:
            continue
        private = any(word in key.lower() for word in PRIVATE_WORDS)
        result.append({"field": "password" if "password" in key.lower() else key[:80],
                       "before": "", "after": "已重置" if private else "已提交"})
    return result


def user_changes(before, after, payload):
    fields = ("uid", "username", "email", "display_name", "avatar_url", "bio", "website_url", "role", "status")
    changes = []
    for field in fields:
        old, new = str(before.get(field) or ""), str(after.get(field) or "")
        if old != new:
            changes.append({"field": field, "before": old[:500], "after": new[:500]})
    if payload.get("password") or payload.get("generate_password") or payload.get("clear_password"):
        changes.append({"field": "password", "before": "", "after": "已重置"})
    return changes


class AuditRepository:
    def __init__(self, db):
        self.db = db

    def record(self, actor, method, resource, target, changes, status_code, ip):
        self.db.execute(text(
            "INSERT INTO admin_audit_logs (actor_uid,actor_name,action,resource,target_id,"
            "changes,status_code,ip_address,created_at) VALUES "
            "(:uid,:name,:action,:resource,:target,:changes,:status,:ip,:now)"
        ), {"uid": str(actor["uid"]) if actor else None,
            "name": str(actor.get("username") or "")[:80] if actor else "",
            "action": method, "resource": resource[:160], "target": target[:80],
            "changes": json.dumps(changes, ensure_ascii=False), "status": status_code,
            "ip": ip[:45], "now": datetime.utcnow()})
        self.db.commit()

    def list(self, limit, offset, search="", outcome=""):
        where, params = " WHERE 1=1", {"limit": limit, "offset": offset}
        if search:
            where += " AND (actor_uid=:search OR actor_name LIKE :like OR resource LIKE :like OR target_id=:search)"
            params.update(search=search, like="%" + search + "%")
        if outcome == "success":
            where += " AND status_code < 400"
        elif outcome == "failed":
            where += " AND status_code >= 400"
        count = self.db.execute(text("SELECT COUNT(*) FROM admin_audit_logs" + where), params).scalar_one()
        rows = self.db.execute(text("SELECT * FROM admin_audit_logs" + where +
            " ORDER BY id DESC LIMIT :limit OFFSET :offset"), params).mappings()
        items = []
        for row in rows:
            item = dict(row)
            if isinstance(item["changes"], str):
                item["changes"] = json.loads(item["changes"])
            items.append(item)
        return {"items": items, "total": count}
