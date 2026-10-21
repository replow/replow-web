from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
import time
import uuid

from .config import Config
from .operations import initialize, settings, record, job_details, capacity, ServiceDisabled


class QueueFull(Exception):
    pass


class Store:
    def __init__(self, config: Config):
        self.config = config
        config.prepare()
        self.path = config.state_dir / "queue.sqlite3"
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, book_id TEXT NOT NULL,
                    format TEXT NOT NULL CHECK(format IN ('txt','epub')),
                    refresh INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL, total INTEGER NOT NULL DEFAULT 0,
                    done INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '',
                    filename TEXT, sha256 TEXT, size_bytes INTEGER,
                    error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status,available_at,created_at);
                CREATE INDEX IF NOT EXISTS jobs_user ON jobs(user_id,created_at);
                CREATE TABLE IF NOT EXISTS rate_limits (
                    key TEXT PRIMARY KEY, window_start REAL NOT NULL, count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signing_grants (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, session_id TEXT,
                    session_version INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signing_nonces (
                    grant_id TEXT NOT NULL, nonce TEXT NOT NULL, expires_at INTEGER NOT NULL,
                    PRIMARY KEY (grant_id, nonce)
                );
            """)

            initialize(db)
            columns = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
            additions = {"author":"TEXT NOT NULL DEFAULT ''", "cover_url":"TEXT NOT NULL DEFAULT ''",
                "start_chapter":"INTEGER NOT NULL DEFAULT 1", "end_chapter":"INTEGER", "actual_end":"INTEGER",
                "catalog_total":"INTEGER NOT NULL DEFAULT 0", "expires_at":"REAL", "artifact_id":"TEXT",
                "source_job_id":"TEXT", "added_chapters":"INTEGER NOT NULL DEFAULT 0", "reused_chapters":"INTEGER NOT NULL DEFAULT 0",
                "started_at":"REAL"}
            for name, definition in additions.items():
                if name not in columns: db.execute("ALTER TABLE jobs ADD COLUMN " + name + " " + definition)
            db.execute("UPDATE jobs SET expires_at=updated_at+?,actual_end=total,catalog_total=total WHERE status='completed' AND expires_at IS NULL", (31*86400,))
            db.executescript("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, book_id TEXT NOT NULL, format TEXT NOT NULL,
                    first INTEGER NOT NULL, last INTEGER NOT NULL, catalog_total INTEGER NOT NULL,
                    title TEXT NOT NULL, author TEXT NOT NULL, cover_url TEXT NOT NULL,
                    filename TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL, catalog_ids TEXT NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS artifacts_lookup ON artifacts(book_id,format,first,last,expires_at);
            """)

    @contextmanager
    def connection(self, transaction=False):
        db = sqlite3.connect(str(self.path), timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=20000")
        try:
            if transaction:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if transaction:
                db.commit()
        except BaseException:
            if transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def enqueue(self, user_id, book_id, format, refresh=False, start_chapter=1, end_chapter=None, source_job_id=None):
        now = time.time()
        with self.connection(transaction=True) as db:
            old = db.execute("SELECT * FROM jobs WHERE user_id=? AND book_id=? AND format=? AND start_chapter=? AND end_chapter IS ? AND refresh=? AND status IN ('queued','running','retry') ORDER BY created_at LIMIT 1", (user_id, book_id, format, start_chapter, end_chapter, int(refresh))).fetchone()
            if old:
                return dict(old)
            if not settings(db)["enabled"]:
                raise ServiceDisabled
            if not capacity(db, user_id):
                raise QueueFull
            job_id = uuid.uuid4().hex
            db.execute("INSERT INTO jobs (id,user_id,book_id,format,refresh,status,available_at,created_at,updated_at,start_chapter,end_chapter,source_job_id) VALUES (?,?,?,?,?,'queued',?,?,?,?,?,?)", (job_id,user_id,book_id,format,int(refresh),now,now,now,start_chapter,end_chapter,source_job_id))
            created = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            record(db, "queued", created, details={"source_job_id": source_job_id})
            return created

    def recover(self):
        # Call only after obtaining the lifetime worker lock.
        with self.connection(transaction=True) as db:
            interrupted = [dict(row) for row in db.execute("SELECT * FROM jobs WHERE status='running'")]
            db.execute("UPDATE jobs SET status='queued', error='resuming_after_restart', available_at=?, updated_at=? WHERE status='running'", (time.time(), time.time()))
            for job in interrupted:
                record(db, "recovered", job, details={"reason": "resuming_after_restart"})

    def claim(self):
        with self.connection(transaction=True) as db:
            if settings(db)["paused"]:
                return None
            if db.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone():
                return None
            row = db.execute("SELECT * FROM jobs WHERE status IN ('queued','retry') AND available_at<=? ORDER BY created_at,id LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running', attempts=attempts+1, error=NULL, started_at=?, updated_at=? WHERE id=?", (time.time(), time.time(), row["id"]))
            started = dict(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())
            record(db, "started", started)
            return started

    def update(self, job_id, **values):
        allowed = {"status", "total", "done", "title", "filename", "sha256", "size_bytes", "error", "available_at", "author", "cover_url", "expires_at", "artifact_id", "catalog_total", "actual_end", "added_chapters", "reused_chapters"}
        if not values or set(values) - allowed:
            raise ValueError("invalid job update")
        values["updated_at"] = time.time()
        with self.connection(transaction=True) as db:
            previous = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            db.execute("UPDATE jobs SET " + ",".join(key + "=?" for key in values) + " WHERE id=?", (*values.values(), job_id))
            if "status" in values and previous and previous[0] != values["status"]:
                changed = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
                record(db, values["status"], changed, details=job_details(changed))

    def fail(self, job, reason, retryable=True):
        retry = retryable and job["attempts"] < 6
        delay = (30, 60, 120, 300, 600, 900)[min(job["attempts"] - 1, 5)]
        self.update(job["id"], status="retry" if retry else "failed", error=reason[:120], available_at=time.time() + delay)

    def get(self, job_id, user_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
            return self.describe(dict(row), db) if row else None

    def list(self, user_id, page=1, size=20):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (user_id,size,(page-1)*size)).fetchall()
            return [self.describe(dict(row), db) for row in rows]

    def describe(self, row, db):
        covers=self.config.download_dir/'covers'
        if covers.exists():
            cached=sorted(covers.glob(row['book_id']+'-*.jpg'),key=lambda p:p.stat().st_mtime,reverse=True)
            if cached and cached[0].stat().st_mtime+31*86400>time.time():
                row['cover_url']=self.config.public_base+'/covers/'+cached[0].name
        if not row['author'] or not row['cover_url']:
            try:
                meta=json.loads((self.config.state_dir/'books'/row['book_id']/'catalog.json').read_text())['metadata']
                row['title']=row['title'] or meta.get('title','')
                row['author']=row['author'] or meta.get('author','')
                row['cover_url']=row['cover_url'] or meta.get('cover_url','')
            except (OSError,ValueError,KeyError):pass
        position = 0
        if row["status"] in ("queued", "retry"):
            position = 1 + db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','retry') AND (created_at<? OR (created_at=? AND id<?))", (row["created_at"], row["created_at"], row["id"])).fetchone()[0]
        available = (row["status"] == "completed" and row["filename"] and row["sha256"] and
                     row["expires_at"] and row["expires_at"] > time.time() and
                     (self.config.download_dir / row["filename"]).is_file())
        return {
            "job_id": row["id"], "book_id": row["book_id"], "format": row["format"],
            "status": row["status"], "queue_position": position,
            "completed_chapters": row["done"], "total_chapters": row["total"],
            "progress": round(row["done"] / row["total"], 4) if row["total"] else 0,
            "title": row["title"], "author": row["author"], "cover_url": row["cover_url"], "filename": row["filename"],
            "start_chapter": row["start_chapter"], "end_chapter": row["actual_end"] or row["end_chapter"],
            "requested_end_chapter": row["end_chapter"], "catalog_total": row["catalog_total"],
            "expires_at": row["expires_at"], "file_available": bool(available),
            "expired": row["status"] == "completed" and not available,
            "added_chapters": row["added_chapters"], "reused_chapters": row["reused_chapters"],
            "download_url": self.config.public_base + "/" + row["filename"] + "?v=" + row["sha256"] if available else None,
            "sha256": row["sha256"], "size_bytes": row["size_bytes"],
            "error": row["error"], "attempts": row["attempts"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "started_at": row["started_at"],
        }

    def rate_limit(self, key, limit, seconds):
        now = time.time()
        with self.connection(transaction=True) as db:
            row = db.execute("SELECT window_start,count FROM rate_limits WHERE key=?", (key,)).fetchone()
            if row and now - row["window_start"] < seconds:
                if row["count"] >= limit:
                    return False
                db.execute("UPDATE rate_limits SET count=count+1 WHERE key=?", (key,))
            else:
                db.execute("INSERT INTO rate_limits(key,window_start,count) VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET window_start=excluded.window_start,count=1", (key, now))
            db.execute("DELETE FROM rate_limits WHERE window_start<?", (now - 86400,))
        return True

    def create_grant(self, user_id, session_id, session_version, seconds=900):
        now = int(time.time())
        grant = {"id": uuid.uuid4().hex, "user_id": user_id, "session_id": session_id,
                 "session_version": session_version, "expires_at": now + seconds, "created_at": now}
        with self.connection(transaction=True) as db:
            db.execute("DELETE FROM signing_grants WHERE expires_at<=?", (now,))
            db.execute("DELETE FROM signing_nonces WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO signing_grants (id,user_id,session_id,session_version,expires_at,created_at) VALUES (:id,:user_id,:session_id,:session_version,:expires_at,:created_at)", grant)
        return grant

    def get_grant(self, grant_id, user_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM signing_grants WHERE id=? AND user_id=? AND expires_at>?", (grant_id, user_id, int(time.time()))).fetchone()
            return dict(row) if row else None

    def consume_nonce(self, grant_id, nonce, expires_at):
        with self.connection(transaction=True) as db:
            db.execute("DELETE FROM signing_nonces WHERE expires_at<=?", (int(time.time()),))
            return db.execute("INSERT OR IGNORE INTO signing_nonces (grant_id,nonce,expires_at) VALUES (?,?,?)", (grant_id, nonce, expires_at)).rowcount == 1

    def raw_job(self, job_id, user_id):
        with self.connection() as db:
            row=db.execute("SELECT * FROM jobs WHERE id=? AND user_id=?",(job_id,user_id)).fetchone()
            return dict(row) if row else None

    def history(self, user_id, page=1, size=20):
        with self.connection() as db:
            total=db.execute("SELECT COUNT(*) FROM jobs WHERE user_id=?",(user_id,)).fetchone()[0]
        return {"items":self.list(user_id,page,size),"page":page,"size":size,"total":total,"has_more":page*size<total}
