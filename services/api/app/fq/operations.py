"""Persistent FQ controls and credential-free operational events."""
import json
import time

DEFAULT_SETTINGS = {"enabled": True, "paused": False, "user_queue_limit": 3, "global_queue_limit": 100}
ACTIVE = ("queued", "running", "retry")


class ServiceDisabled(Exception):
    pass


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS fq_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fq_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
            job_id TEXT, user_id INTEGER, book_id TEXT,
            details TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS fq_events_time ON fq_events(created_at);
        CREATE INDEX IF NOT EXISTS fq_events_job ON fq_events(job_id,id);
    """)


def settings(db):
    values = dict(DEFAULT_SETTINGS)
    for row in db.execute("SELECT key,value FROM fq_settings"):
        if row["key"] in values:
            values[row["key"]] = json.loads(row["value"])
    return values


def record(db, event, job=None, user_id=None, details=None):
    job = job or {}
    allowed = {"reason", "added_chapters", "reused_chapters", "total_chapters", "removed_files",
               "new_chapters", "has_updates", "changed_fields", "source_job_id"}
    safe = {key: value for key, value in (details or {}).items() if key in allowed}
    db.execute("INSERT INTO fq_events(event,job_id,user_id,book_id,details,created_at) VALUES(?,?,?,?,?,?)",
               (event[:60], job.get("id"), user_id or job.get("user_id"), job.get("book_id"),
                json.dumps(safe, ensure_ascii=False), time.time()))


def job_details(job):
    return {"reason": job.get("error"), "added_chapters": job.get("added_chapters", 0),
            "reused_chapters": job.get("reused_chapters", 0), "total_chapters": job.get("total", 0)}


def write_settings(store, values, actor):
    with store.connection(transaction=True) as db:
        before = settings(db)
        for key, value in values.items():
            db.execute("INSERT INTO fq_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))
        changed = [key for key, value in values.items() if before.get(key) != value]
        record(db, "settings_updated", user_id=actor, details={"changed_fields": changed})
        return before, settings(db)


def capacity(db, user_id):
    limits = settings(db)
    count = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','retry')").fetchone()[0]
    own = db.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('queued','running','retry')", (user_id,)).fetchone()[0]
    return own < limits["user_queue_limit"] and count < limits["global_queue_limit"]


def manage_job(store, job_id, action, actor):
    with store.connection(transaction=True) as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None, "job_not_found"
        job = dict(row)
        if action == "cancel":
            if job["status"] not in ("queued", "retry"):
                return None, "only_waiting_jobs_can_be_cancelled"
            db.execute("UPDATE jobs SET status='cancelled',error='cancelled_by_admin',updated_at=? WHERE id=?", (time.time(), job_id))
            record(db, "cancelled", job, actor)
        else:
            if job["status"] not in ("failed", "cancelled"):
                return None, "only_failed_or_cancelled_jobs_can_be_retried"
            if not settings(db)["enabled"]:
                return None, "download_service_disabled"
            if not capacity(db, job["user_id"]):
                return None, "download_queue_full"
            db.execute("UPDATE jobs SET status='queued',attempts=0,error=NULL,available_at=?,updated_at=? WHERE id=?", (time.time(), time.time(), job_id))
            record(db, "admin_retry", job, actor)
        return job, None


def cleanup_result(store, removed):
    with store.connection(transaction=True) as db:
        db.execute("INSERT INTO fq_settings(key,value) VALUES('last_cleanup_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(time.time()),))
        db.execute("DELETE FROM fq_events WHERE created_at<?", (time.time() - 90 * 86400,))
        if removed:
            record(db, "cleanup", details={"removed_files": removed})
