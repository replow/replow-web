"""OneDrive media redirect service. Never proxy file bytes or expose Graph credentials."""
import asyncio
import contextlib
import json
import os
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

DRIVE = os.getenv("OD_DRIVE_ID", "")
ROOT = os.getenv("OD_ROOT_ITEM_ID", "")
TOKEN_FILE = Path(os.getenv("OD_TOKEN_FILE", str(Path.home() / ".local/state/replow-od-preview/token.json")))
TTL = max(15, min(300, int(os.getenv("OD_LINK_TTL", "120"))))
LIMIT = 2048
GRAPH = "https://graph.microsoft.com/v1.0"
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
           "X-Content-Type-Options": "nosniff", "Access-Control-Allow-Origin": "*"}

class Failure(Exception):
    def __init__(self, status=503, code="upstream_unavailable", retry=30):
        self.status, self.code, self.retry = status, code, retry

def normalize(path):
    if not path or len(path) > 1024:
        raise Failure(404, "not_found")
    parts = path.split("/")
    if len(parts) > 20 or any(not s or s.startswith(".") or
            any(ord(c) < 32 or ord(c) == 127 or c in "\\%:" for c in s)
            for s in parts):
        raise Failure(404, "not_found")
    return "/".join(parts)

def safe_url(url):
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
        suffixes = ("1drv.com", "onedrive.com", "onedrive.live.com",
                    "livefilestore.com", "sharepoint.com",
                    "microsoftpersonalcontent.com", "storage.live.com")
        return (u.scheme == "https" and not u.username and not u.password
                and u.port in (None, 443) and
                any(host == s or host.endswith("." + s) for s in suffixes))
    except (ValueError, TypeError):
        return False

def expiry(url, now):
    """No documented universal expiry: bound reuse and validate before redirect."""
    deadline = now + TTL
    q = parse_qs(urlsplit(url).query)
    for k in ("exp", "expires", "se"):
        for value in q.get(k, []):
            try:
                stamp = float(value) if value.isdigit() else datetime.fromisoformat(
                    value.replace("Z", "+00:00")).timestamp()
                deadline = min(deadline, stamp - 30)
            except (ValueError, OverflowError):
                pass
    return max(now, deadline)

def atomic_token(data):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, TOKEN_FILE)

@dataclass
class Entry:
    url: str
    expires: float
    refresh: float
    last_used: float

class Media:
    def __init__(self, client):
        self.client = client
        self.cache = OrderedDict()
        self.locks = [asyncio.Lock() for _ in range(128)]
        self.token_lock = asyncio.Lock()
        self.gate = asyncio.Semaphore(8)
        self.cooldown = 0.
        self.graph_count = 0

    def configured(self):
        return bool(DRIVE and ROOT and TOKEN_FILE.is_file())

    async def token(self, force=False):
        async with self.token_lock:
            try:
                data = json.loads(TOKEN_FILE.read_text())
            except (OSError, ValueError):
                raise Failure(503, "authorization_required")
            if not force and data.get("expires_at", 0) > time.time() + 90:
                return data["access_token"]
            if not data.get("refresh_token") or not data.get("client_id"):
                raise Failure(503, "authorization_required")
            r = await self.client.post(
                "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                data={"client_id": data["client_id"], "grant_type": "refresh_token",
                      "refresh_token": data["refresh_token"],
                      "scope": "https://graph.microsoft.com/Files.Read offline_access"})
            if r.status_code != 200:
                raise Failure(503, "authorization_required")
            new = r.json()
            data.update(access_token=new["access_token"],
                        refresh_token=new.get("refresh_token", data["refresh_token"]),
                        expires_at=time.time() + new.get("expires_in", 3600))
            atomic_token(data)
            return data["access_token"]

    async def graph(self, path):
        if self.cooldown > time.time():
            raise Failure(503, "upstream_busy", max(1, int(self.cooldown-time.time())))
        async with self.gate:
            if self.cooldown > time.time():
                raise Failure(503, "upstream_busy", max(1, int(self.cooldown-time.time())))
            for attempt in range(2):
                token = await self.token(force=attempt > 0)
                self.graph_count += 1
                r = await self.client.get(GRAPH + path, headers={"Authorization": "Bearer " + token})
                if r.status_code == 401 and attempt == 0:
                    continue
                if r.status_code == 404:
                    raise Failure(404, "not_found")
                if r.status_code in (429, 503):
                    try:
                        delay = max(1, min(3600, int(r.headers.get("Retry-After", "30"))))
                    except ValueError:
                        delay = 30
                    self.cooldown = time.time() + delay
                    raise Failure(503, "upstream_busy", delay)
                if r.status_code in (401, 403):
                    raise Failure(503, "authorization_required")
                if r.status_code != 200:
                    raise Failure()
                return r.json()
        raise Failure(503, "authorization_required")

    async def scoped(self, item):
        if item.get("file") is None or item.get("remoteItem") or item.get("deleted"):
            raise Failure(404, "not_found")
        # Validate ancestry, including nested paths, to exclude shared shortcuts.
        parent = item.get("parentReference", {})
        for _ in range(21):
            if str(parent.get("driveId", "")).lower() != DRIVE.lower():
                raise Failure(404, "not_found")
            if parent.get("id") == ROOT:
                return
            pid = parent.get("id")
            if not pid:
                break
            folder = await self.graph("/drives/" + quote(DRIVE, safe="") + "/items/" +
                                      quote(pid, safe=""))
            if folder.get("remoteItem") or "folder" not in folder:
                break
            parent = folder.get("parentReference", {})
        raise Failure(404, "not_found")

    async def fresh(self, path):
        item = await self.graph("/drives/" + quote(DRIVE, safe="") + "/items/" +
                                quote(ROOT, safe="") + ":/" + quote(path, safe="/"))
        await self.scoped(item)
        url = item.get("@microsoft.graph.downloadUrl", "")
        if not safe_url(url):
            raise Failure()
        now = time.time()
        end = expiry(url, now)
        if end <= now + 5:
            raise Failure()
        previous = self.cache.get(path)
        entry = Entry(url, end, now + (end-now)*0.7, previous.last_used if previous else now)
        self.cache[path] = entry
        self.cache.move_to_end(path)
        while len(self.cache) > LIMIT:
            self.cache.popitem(last=False)
        return entry

    async def valid(self, url):
        # Never send OAuth headers to download hosts or follow unvalidated redirects.
        for _ in range(4):
            if not safe_url(url):
                raise Failure()
            r = await self.client.head(url)
            if r.status_code in (301, 302, 303, 307, 308):
                url = r.headers.get("Location", "")
                continue
            if r.status_code in (401, 403, 404, 410):
                return False
            if r.status_code == 405:
                async with self.client.stream("GET", url, headers={"Range": "bytes=0-0"}) as resp:
                    if resp.status_code in (401, 403, 404, 410):
                        return False
                    if resp.status_code not in (200, 206):
                        raise Failure()
                    return True
            if r.status_code not in (200, 206):
                raise Failure()
            return True
        raise Failure()

    async def resolve(self, path):
        path = normalize(path)
        async with self.locks[hash(path) % len(self.locks)]:
            old = self.cache.get(path)
            now = time.time()
            if old:
                old.last_used = now
            if old and old.expires > now:
                if old.refresh <= now:
                    try:
                        old = await self.fresh(path)
                    except Failure as exc:
                        if exc.code != "upstream_busy":
                            self.cache.pop(path, None)
                            raise
                        # Safe to reuse only while bounded deadline and HEAD are valid.
                if old.expires > time.time() and await self.valid(old.url):
                    self.cache.move_to_end(path)
                    return old.url, "HIT"
                self.cache.pop(path, None)
            for _ in range(2):
                entry = await self.fresh(path)
                if await self.valid(entry.url):
                    return entry.url, "MISS"
                self.cache.pop(path, None)
            raise Failure()

    async def refresh_loop(self):
        # Proactively refresh only recently requested entries; no drive scans.
        while True:
            await asyncio.sleep(5)
            now = time.time()
            for path, entry in list(self.cache.items()):
                if entry.expires <= now or entry.last_used + 600 <= now:
                    self.cache.pop(path, None)
                elif entry.refresh <= now:
                    async with self.locks[hash(path) % len(self.locks)]:
                        if self.cache.get(path) is not entry:
                            continue
                        try:
                            await self.fresh(path)
                        except Failure as exc:
                            if exc.code in ("not_found", "authorization_required"):
                                self.cache.pop(path, None)
                            # Global cooldown protects against retries on every entry.
                        except (httpx.HTTPError, OSError, ValueError):
                            pass

@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5),
                                 follow_redirects=False,
                                 limits=httpx.Limits(max_connections=16)) as client:
        app.state.media = Media(client)
        worker = asyncio.create_task(app.state.media.refresh_loop())
        try:
            yield
        finally:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

@app.exception_handler(Failure)
async def failure(request, exc):
    h = dict(HEADERS)
    if exc.status == 503:
        h["Retry-After"] = str(exc.retry)
    return JSONResponse({"error": exc.code}, status_code=exc.status, headers=h)

@app.get("/healthz")
async def health(request: Request):
    media = request.app.state.media
    return JSONResponse({"service": "onedrive-media", "version": "v26.10.22-u1",
                         "authorized": media.configured()}, headers=HEADERS)

@app.api_route("/{path:path}", methods=["GET", "HEAD"])
async def media(path: str, request: Request):
    if not path:
        raise Failure(404, "not_found")
    if not request.app.state.media.configured():
        raise Failure(503, "authorization_required")
    try:
        url, state = await request.app.state.media.resolve(path)
        return RedirectResponse(url, status_code=302,
                                headers={**HEADERS, "X-OD-Cache": state})
    except Failure:
        raise
    except (httpx.HTTPError, OSError, ValueError, KeyError):
        raise Failure()
