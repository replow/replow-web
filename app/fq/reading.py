"""Bookshelf metadata only; EPUB bytes are created and kept by the browser."""
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .config import Config, get_config
from .router import fq_user
from .client import Client, UpstreamError
from .books import chapter_record

router = APIRouter(prefix="/fq/reading", tags=["reading"])

class ShelfInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["fanqie", "local"]
    source_id: str = Field(pattern=r"^(?:[0-9]{1,24}|[a-f0-9]{64})$")
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(default="", max_length=200)
    cover: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=10000)
    total_chapters: int = Field(default=0, ge=0, le=1000000)

class ProgressInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    cfi: Optional[str] = Field(default=None, max_length=2000)
    percentage: Optional[float] = Field(default=None, ge=0, le=100)
    chapter: Optional[str] = Field(default=None, max_length=300)
    read_chapters: Optional[int] = Field(default=None, ge=0, le=1000000)
    total_chapters: Optional[int] = Field(default=None, ge=0, le=1000000)

    @model_validator(mode="after")
    def chapter_bounds(self):
        if self.total_chapters and self.read_chapters is not None and self.read_chapters > self.total_chapters:
            raise ValueError("read_chapters_exceeds_total")
        return self

class ShelfStore:
    def __init__(self, config):
        config.prepare()
        self.path = config.state_dir / "reading.sqlite3"
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS shelf(
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    source TEXT NOT NULL, source_id TEXT NOT NULL,
                    title TEXT NOT NULL, author TEXT NOT NULL, cover TEXT NOT NULL,
                    description TEXT NOT NULL, cfi TEXT NOT NULL DEFAULT '',
                    percentage REAL NOT NULL DEFAULT 0, chapter TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(user_id,source,source_id));
                CREATE INDEX IF NOT EXISTS shelf_owner ON shelf(user_id,updated_at);
            """)
            fields = ("read_chapters", "total_chapters")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(shelf)")}
            if any(name not in columns for name in fields):
                db.execute("BEGIN IMMEDIATE")
                columns = {row["name"] for row in db.execute("PRAGMA table_info(shelf)")}
                for name in fields:
                    if name not in columns:
                        db.execute("ALTER TABLE shelf ADD COLUMN " + name + " INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
    def list(self, uid):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM shelf WHERE user_id=? ORDER BY updated_at DESC", (uid,))]
    def add(self, uid, values):
        now = time.time()
        with self.connection() as db:
            old = db.execute("SELECT * FROM shelf WHERE user_id=? AND source=? AND source_id=?", (uid, values.source, values.source_id)).fetchone()
            if old:
                if values.total_chapters:
                    db.execute("UPDATE shelf SET total_chapters=? WHERE id=?", (values.total_chapters, old["id"]))
                    old = db.execute("SELECT * FROM shelf WHERE id=?", (old["id"],)).fetchone()
                return dict(old)
            if db.execute("SELECT COUNT(*) FROM shelf WHERE user_id=?", (uid,)).fetchone()[0] >= 1000:
                raise HTTPException(409, "书架已满，请先移除部分书籍。")
            db.execute("INSERT OR IGNORE INTO shelf(id,user_id,source,source_id,title,author,cover,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (uuid.uuid4().hex,uid,values.source,values.source_id,values.title,values.author,values.cover if values.cover.startswith("https://") else "",values.description,now,now))
            if values.total_chapters:
                db.execute("UPDATE shelf SET total_chapters=? WHERE user_id=? AND source=? AND source_id=?", (values.total_chapters,uid,values.source,values.source_id))
            return dict(db.execute("SELECT * FROM shelf WHERE user_id=? AND source=? AND source_id=?", (uid,values.source,values.source_id)).fetchone())
    def progress(self, uid, identifier, values):
        with self.connection() as db:
            row = db.execute("SELECT total_chapters FROM shelf WHERE id=? AND user_id=?", (identifier,uid)).fetchone()
            if row is None: return 0
            total = values.total_chapters or row["total_chapters"]
            if total and values.read_chapters is not None and values.read_chapters > total:
                raise HTTPException(422, "read_chapters_exceeds_total")
            return db.execute("""UPDATE shelf SET cfi=COALESCE(?,cfi), percentage=COALESCE(?,percentage),
                              chapter=COALESCE(?,chapter), read_chapters=CASE WHEN ? IS NOT NULL AND ? IS NULL AND ? != cfi THEN 0 ELSE COALESCE(?,read_chapters) END,
                              total_chapters=COALESCE(NULLIF(?,0),total_chapters),
                              updated_at=CASE WHEN ? IS NULL THEN updated_at ELSE ? END
                              WHERE id=? AND user_id=?""",
                              (values.cfi,values.percentage,values.chapter,values.cfi,values.read_chapters,values.cfi,values.read_chapters,values.total_chapters,
                               values.cfi,time.time(),identifier,uid)).rowcount
    def remove(self, uid, identifier):
        with self.connection() as db:
            return db.execute("DELETE FROM shelf WHERE user_id=? AND id=?", (uid,identifier)).rowcount

@router.get("/shelf")
def list_shelf(user: dict=Depends(fq_user), config: Config=Depends(get_config)):
    return {"data": {"uid": int(user["uid"]), "items": ShelfStore(config).list(int(user["uid"]))}}

@router.post("/shelf")
def add_shelf(payload: ShelfInput,user: dict=Depends(fq_user),config: Config=Depends(get_config)):
    if (payload.source == "fanqie" and not re.fullmatch(r"[0-9]{1,24}",payload.source_id)) or (payload.source == "local" and len(payload.source_id) != 64):
        raise HTTPException(422, "invalid_source_id")
    return {"data": ShelfStore(config).add(int(user["uid"]),payload)}

@router.post("/shelf/{identifier}/progress")
def save_progress(identifier: str,payload: ProgressInput,user: dict=Depends(fq_user),config: Config=Depends(get_config)):
    if not ShelfStore(config).progress(int(user["uid"]),identifier,payload):
        raise HTTPException(404, "book_not_found")
    return {"data": {"saved": True}}

@router.post("/shelf/{identifier}/remove")
def remove_shelf(identifier: str,user: dict=Depends(fq_user),config: Config=Depends(get_config)):
    if not ShelfStore(config).remove(int(user["uid"]),identifier):
        raise HTTPException(404, "book_not_found")
    return {"data": {"removed": True}}

@router.get("/batch/{book_id}")
def reading_batch(book_id: str,offset: int=Query(ge=0,le=999999),limit: int=Query(default=10,ge=1,le=20),
                  user: dict=Depends(fq_user),config: Config=Depends(get_config)):
    if not re.fullmatch(r"[0-9]{1,24}",book_id): raise HTTPException(422, "invalid_book_id")
    # Relay verified text in memory. Never write EPUB files or chapter caches.
    try:
        data = Client(config).request("/api/batch/"+book_id,{"offset":offset,"limit":limit})["data"]
        if str(data.get("book_id")) != book_id or data.get("offset") != offset:
            raise UpstreamError("chapter_identity_mismatch")
        chapters = [chapter_record(c,book_id,str(c.get("chapterId",""))) for c in data.get("chapters",[])]
        if len(chapters) != min(limit,max(0,int(data["total"])-offset)) or len({c["chapter_id"] for c in chapters}) != len(chapters):
            raise UpstreamError("upstream_chapter_unavailable")
        return {"data":{"chapters":chapters,"total":data["total"],"offset":offset}}
    except UpstreamError as error:
        raise HTTPException(502, error.reason) from None
