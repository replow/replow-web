"""Admin-only FQ operations. Never returns upstream credentials or private chapter paths."""
import json
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.audit_route import AuditRoute
from app.core.security import require_admin
from .artifacts import cleanup
from .config import Config, get_config
from .operations import DEFAULT_SETTINGS, manage_job, record, settings, write_settings
from .store import Store

router = APIRouter(prefix="/admin/fq", tags=["admin fq"], route_class=AuditRoute,
                   dependencies=[Depends(require_admin)])
STATES = {"queued", "running", "retry", "completed", "failed", "cancelled"}


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)
    paused: bool = Field(strict=True)
    user_queue_limit: int = Field(strict=True, ge=1, le=20)
    global_queue_limit: int = Field(strict=True, ge=1, le=1000)


def describe_settings(store):
    with store.connection() as db:
        values = settings(db)
    return {**values, "retention_days": 31, "cdn_ttl_days": 31, "log_retention_days": 90,
            "download_base": store.config.public_base, "serial_downloads": True}


@router.get("/overview")
def overview(config: Config = Depends(get_config)):
    store = Store(config)
    now = time.time()
    with store.connection() as db:
        counts = {row["status"]: row["n"] for row in db.execute("SELECT status,COUNT(*) AS n FROM jobs GROUP BY status")}
        recent = db.execute("SELECT COUNT(*) FROM jobs WHERE created_at>?", (now - 86400,)).fetchone()[0]
        running_activity = db.execute("SELECT MAX(updated_at) FROM jobs WHERE status='running'").fetchone()[0]
        last = db.execute("SELECT value FROM fq_settings WHERE key='last_cleanup_at'").fetchone()
        files = db.execute("SELECT filename,size_bytes FROM artifacts WHERE expires_at>?", (now,)).fetchall()
    valid = [row for row in files if (config.download_dir / row["filename"]).is_file()]
    heartbeat = config.state_dir / "worker.heartbeat"
    try:
        heartbeat_at = heartbeat.stat().st_mtime
    except OSError:
        heartbeat_at = None
    heartbeat_at = max(heartbeat_at or 0, running_activity or 0) or None
    usage = shutil.disk_usage(config.download_dir)
    return {"data": {"counts": counts, "today_jobs": recent, "available_files": len(valid),
        "cached_bytes": sum(row["size_bytes"] for row in valid), "disk_free_bytes": usage.free,
        "worker_online": bool(heartbeat_at and now - heartbeat_at < 180), "heartbeat_at": heartbeat_at,
        "last_cleanup_at": float(last[0]) if last else None, "settings": describe_settings(store)}}


@router.get("/settings")
def get_settings(config: Config = Depends(get_config)):
    return {"data": describe_settings(Store(config))}


@router.put("/settings")
def put_settings(payload: SettingsRequest, request: Request, user: dict = Depends(require_admin),
                 config: Config = Depends(get_config)):
    store = Store(config)
    before, after = write_settings(store, payload.model_dump(), int(user["uid"]))
    request.state.audit_changes = [{"field": key, "before": str(before[key]), "after": str(after[key])}
                                   for key in DEFAULT_SETTINGS if before[key] != after[key]]
    return {"success": True, "data": describe_settings(store)}


@router.get("/jobs")
def jobs(page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100),
         search: str = Query("", max_length=100), state: str = "", format: str = "",
         config: Config = Depends(get_config)):
    if state and state not in STATES:
        raise HTTPException(422, "invalid_job_state")
    if format and format not in {"txt", "epub"}:
        raise HTTPException(422, "invalid_format")
    store = Store(config)
    where, args = " WHERE 1=1", []
    if search.strip():
        where += " AND (book_id=? OR id=? OR CAST(user_id AS TEXT)=? OR title LIKE ? OR author LIKE ?)"
        term = search.strip()
        args += [term, term, term, "%" + term + "%", "%" + term + "%"]
    if state:
        where += " AND status=?"
        args.append(state)
    if format:
        where += " AND format=?"
        args.append(format)
    with store.connection() as db:
        total = db.execute("SELECT COUNT(*) FROM jobs" + where, args).fetchone()[0]
        rows = db.execute("SELECT * FROM jobs" + where + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                          args + [size, (page - 1) * size]).fetchall()
        items = [{**store.describe(dict(row), db), "user_id": row["user_id"], "source_job_id": row["source_job_id"]} for row in rows]
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("/jobs/{job_id}/{action}")
def job_action(job_id: str, action: str, request: Request, user: dict = Depends(require_admin),
               config: Config = Depends(get_config)):
    if action not in {"retry", "cancel"}:
        raise HTTPException(404, "action_not_found")
    request.state.audit_target = job_id
    store = Store(config)
    before, error = manage_job(store, job_id, action, int(user["uid"]))
    if error:
        raise HTTPException(404 if error == "job_not_found" else 409, error)
    request.state.audit_changes = [{"field": "status", "before": before["status"],
                                    "after": "cancelled" if action == "cancel" else "queued"}]
    return {"success": True, "data": store.get(job_id, before["user_id"])}


@router.post("/cleanup")
def cleanup_expired(request: Request, user: dict = Depends(require_admin), config: Config = Depends(get_config)):
    store = Store(config)
    removed = cleanup(store)
    with store.connection() as db:
        record(db, "admin_cleanup", user_id=int(user["uid"]), details={"removed_files": removed})
    request.state.audit_changes = [{"field": "removed_files", "before": "", "after": str(removed)}]
    return {"success": True, "data": {"removed_files": removed}}


@router.get("/logs")
def logs(page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=100),
         search: str = Query("", max_length=100), event: str = Query("", max_length=60),
         config: Config = Depends(get_config)):
    store = Store(config)
    where, args = " WHERE 1=1", []
    if search.strip():
        where += " AND (e.job_id=? OR e.book_id=? OR CAST(e.user_id AS TEXT)=? OR CAST(j.user_id AS TEXT)=? OR j.title LIKE ?)"
        term = search.strip()
        args += [term, term, term, term, "%" + term + "%"]
    if event:
        where += " AND e.event=?"
        args.append(event)
    query = " FROM fq_events e LEFT JOIN jobs j ON j.id=e.job_id"
    with store.connection() as db:
        total = db.execute("SELECT COUNT(*)" + query + where, args).fetchone()[0]
        rows = db.execute("SELECT e.*,j.title,j.user_id AS job_user_id" + query + where +
                          " ORDER BY e.id DESC LIMIT ? OFFSET ?", args + [size, (page - 1) * size]).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["details"] = json.loads(item["details"])
        items.append(item)
    return {"items": items, "total": total, "page": page, "size": size}
