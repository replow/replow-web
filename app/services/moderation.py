"""Transactional restriction updates and durable email delivery."""
from datetime import datetime, timedelta
import logging
from fastapi import HTTPException
from sqlalchemy import text
from app.core.moderation import KINDS, utc, restrictions, notice, date_label
from app.services.mail import MailService

logger = logging.getLogger(__name__)


def change_restriction(db, uid, actor, payload):
    kind = payload.get("kind")
    if kind not in KINDS:
        raise HTTPException(422, "请选择封号、禁言或禁止发布文章")
    if payload.get("confirmed") is not True:
        raise HTTPException(422, "confirmation_required")
    if not isinstance(payload.get("enabled"), bool):
        raise HTTPException(422, "请选择限制或解除")
    enabled = payload["enabled"]
    reason = str(payload.get("reason") or "").strip()
    if not reason or len(reason) > 1000:
        raise HTTPException(422, "请填写 1–1000 字的操作理由")
    try:
        end = utc(payload.get("until")) if enabled else None
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(422, "解除日期格式不正确") from None
    now = datetime.utcnow()
    if end and end <= now:
        raise HTTPException(422, "解除日期必须晚于当前时间")
    # Serialize admin restrictions so two administrators cannot ban each other
    # concurrently and leave the installation without an available admin.
    admins = list(db.execute(text("SELECT * FROM users WHERE role='admin' ORDER BY uid FOR UPDATE")).mappings())
    target = db.execute(text("SELECT * FROM users WHERE uid=:uid FOR UPDATE"), {"uid": uid}).mappings().first()
    if not target:
        raise HTTPException(404, "user_not_found")
    if enabled and uid == int(actor["uid"]):
        raise HTTPException(409, "不能限制当前登录的管理员")
    if kind == "ban" and enabled and target["role"] == "admin":
        available = [u for u in admins if u["status"] == "active" and not any(r["kind"] == "ban" for r in restrictions(u))]
        if not any(int(u["uid"]) != uid for u in available):
            raise HTTPException(409, "至少保留一名未封禁的启用管理员")
    before = next((r for r in restrictions(target) if r["kind"] == kind), None)
    db.execute(text(f"UPDATE users SET {kind}_started_at=:start, {kind}_until=:end, "
                    f"{kind}_reason=:reason, updated_at=:now WHERE uid=:uid"),
               {"uid": uid, "start": now if enabled else None, "end": end,
                "reason": reason if enabled else None, "now": now})
    if kind == "ban" and enabled:
        db.execute(text("UPDATE users SET session_version=session_version+1 WHERE uid=:uid"), {"uid": uid})
        db.execute(text("UPDATE auth_sessions SET revoked_at=:now WHERE user_uid=:uid AND revoked_at IS NULL"), {"uid": uid, "now": now})
        db.execute(text("UPDATE oauth_tokens SET revoked_at=:now WHERE user_uid=:uid AND revoked_at IS NULL"), {"uid": uid, "now": now})
        db.execute(text("DELETE FROM oauth_authorization_codes WHERE user_uid=:uid"), {"uid": uid})
    item = {"kind": kind, "label": KINDS[kind], "started_at": now, "until": end, "reason": reason}
    summary = notice(item) if enabled else f"已解除{KINDS[kind]}；操作日期：{date_label(now)}；理由：{reason}"
    if not enabled and before:
        summary += "\n原限制：" + notice(before)
    db.execute(text("INSERT INTO moderation_mail_outbox (recipient,subject,body,created_at,next_attempt_at) "
                    "VALUES (:email,:subject,:body,:now,:now)"),
               {"email": target["email"], "subject": "SilverCode " + (KINDS[kind] if enabled else "解除" + KINDS[kind]) + "通知",
                "body": f"您好，{target['display_name'] or target['username']}：\n\n{summary}\n\nSilverCode Nexus", "now": now})
    db.commit()
    return {"success": True, "message": summary, "email_status": "queued"}


def deliver_pending():
    from app.db.session import SessionLocal
    # Commit each message individually. SMTP outages never roll back a restriction.
    with SessionLocal() as db:
        for _ in range(20):
            row = db.execute(text("SELECT * FROM moderation_mail_outbox WHERE sent_at IS NULL "
                "AND next_attempt_at<=:now ORDER BY id LIMIT 1 FOR UPDATE"),
                {"now": datetime.utcnow()}).mappings().first()
            if not row:
                db.rollback()
                break
            try:
                MailService(db).send(recipient=row["recipient"], subject=row["subject"], body=row["body"])
            except Exception:
                logger.warning("Moderation notification delivery deferred (message %s)", row["id"])
                db.execute(text("UPDATE moderation_mail_outbox SET attempts=attempts+1,next_attempt_at=:next WHERE id=:id"),
                    {"id": row["id"], "next": datetime.utcnow() + timedelta(minutes=min(60, 2 ** min(row["attempts"], 6)))})
            else:
                db.execute(text("UPDATE moderation_mail_outbox SET sent_at=:now,attempts=attempts+1 WHERE id=:id"),
                           {"id": row["id"], "now": datetime.utcnow()})
            db.commit()


if __name__ == "__main__":
    deliver_pending()
