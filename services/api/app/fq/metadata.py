"""Public metadata fast path and a private, bounded cache shared by API/worker.

Only book descriptions and chapter lists use the publisher's public website.
Chapter bodies keep the existing authenticated parser and integrity checks.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import uuid

from .client import UpstreamError, exclusive_file

ID = re.compile(r"^[0-9]{1,24}$")
BOOK_SECONDS = 3600
TOC_SECONDS = 45
SEARCH_SECONDS = 300
MAX_BYTES = 4_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def public_read(url):
    # All callers construct fixed publisher URLs. Never attach service tokens.
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/html", "Referer": "https://fanqienovel.com/"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
        raw = response.read(MAX_BYTES + 1)
        if response.status != 200 or len(raw) > MAX_BYTES:
            raise ValueError("public_metadata_unavailable")
        return raw.decode("utf-8")



def public_search(params):
    """Bounded catalog-only search; the signed Java parser remains fallback.

    Publisher's public catalog metadata is unrelated to user tokens and never
    retrieves chapter content. Never follow redirects or arbitrary URLs.
    """
    import html
    parameters = params or {}
    query = str(parameters.get("key") or "").strip()
    page = int(parameters.get("page", 1))
    size = int(parameters.get("size", 10))
    if not query or len(query) > 100 or page < 1 or page > 1000 or size != 10:
        raise ValueError("invalid_catalog_search")
    url = "https://novel.snssdk.com/api/novel/channel/homepage/search/search/v1/?" + urllib.parse.urlencode({
        "device_platform": "android", "parent_enterfrom": "novel_channel_search.tab.",
        "offset": str((page - 1) * 10), "aid": "1967", "q": query,
    })
    request = urllib.request.Request(url, headers={
        "User-Agent": "com.ss.android.article.news/7.0.3 (Linux; U; Android 12; zh_CN; Pixel 6)",
        "Accept": "application/json",
    })
    with urllib.request.build_opener(NoRedirect).open(request, timeout=4) as response:
        if response.status != 200:
            raise ValueError("catalog_upstream_unavailable")
        raw = response.read(512_001)
    if len(raw) > 512_000:
        raise ValueError("catalog_response_too_large")
    payload = json.loads(raw)
    data = payload.get("data") if isinstance(payload, dict) else None
    if payload.get("code") != 0 or not isinstance(data, dict):
        raise ValueError("catalog_invalid_response")
    items = data.get("ret_data")
    if not isinstance(items, list):
        raise ValueError("catalog_invalid_books")
    def clean(value, limit):
        text = html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()
        return text[:limit]
    books = []
    seen = set()
    for book in items[:20]:
        if not isinstance(book, dict):
            continue
        book_id = str(book.get("book_id") or "")
        title = clean(book.get("title"), 300)
        if not ID.fullmatch(book_id) or not title or book_id in seen:
            continue
        seen.add(book_id)
        books.append({
            "bookId": book_id, "bookName": title,
            "author": clean(book.get("author"), 160),
            "category": clean(book.get("category"), 160),
            "coverUrl": str(book.get("thumb_url") or "")[:2048],
            "description": clean(book.get("abstract"), 2500),
            "lastChapterTitle": "", "wordCount": 0,
        })
        if len(books) >= 10:
            break
    if items and not books:
        raise ValueError("catalog_unusable_result")
    return {"code": 0, "data": {
        "books": books, "hasMore": bool(data.get("has_more")),
        "total": None, "searchId": None,
    }}


def directory(ids, volumes, declared=None):
    if not isinstance(ids, list) or not ids or len(ids) > 100000 or not isinstance(volumes, list):
        raise ValueError("invalid_public_directory")
    ids = [str(item) for item in ids]
    if any(not ID.fullmatch(item) for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("invalid_public_directory")
    titles = {}
    for volume in volumes:
        if not isinstance(volume, list):
            raise ValueError("invalid_public_directory")
        for item in volume:
            identity = str(item.get("itemId", ""))
            if identity in titles or not isinstance(item.get("title"), str) or not item["title"].strip():
                raise ValueError("invalid_public_directory")
            titles[identity] = item["title"]
    if set(titles) != set(ids) or declared is not None and int(declared) != len(ids):
        raise ValueError("public_directory_count_mismatch")
    return {"code": 0, "data": {"serial_count": len(ids), "item_data_list": [
        {"item_id": item, "title": titles[item]} for item in ids]}}


def public_directory(book_id):
    raw = json.loads(public_read("https://fanqienovel.com/api/reader/directory/detail?bookId=" + book_id))
    if raw.get("code") != 0:
        raise ValueError("public_directory_failed")
    data = raw["data"]
    return directory(data["allItemIds"], data["chapterListWithVolume"])


def public_bundle(book_id):
    page = public_read("https://fanqienovel.com/page/" + book_id)
    marker = "window.__INITIAL_STATE__="
    position = page.find(marker)
    if position < 0:
        raise ValueError("public_metadata_changed")
    state, _ = json.JSONDecoder().raw_decode(page[position + len(marker):].lstrip())
    data = state["page"]
    if str(data.get("bookId")) != book_id or not isinstance(data.get("bookName"), str) or not data["bookName"].strip():
        raise ValueError("public_book_identity_mismatch")
    book = {"code": 0, "data": {"bookId": book_id, "bookName": data["bookName"],
        "author": str(data.get("authorName") or data.get("author") or ""),
        "coverUrl": str(data.get("thumbUrl") or ""),
        "abstract": str(data.get("abstract") or ""),
        "description": str(data.get("abstract") or data.get("description") or ""),
        "totalChapters": int(data.get("chapterTotal") or 0),
        "wordCount": data.get("wordNumber"), "status": data.get("creationStatus")}}
    toc = None
    try:
        volumes = data.get("chapterListWithVolume")
        toc = directory(data.get("itemIds"), volumes, data.get("chapterTotal"))
        # The page's itemIds lists newest chapters first. Reading order is the
        # volume/chapter order; validate the complete ID set before reordering.
        titles = {item['item_id']: item for item in toc['data']['item_data_list']}
        toc['data']['item_data_list'] = [titles[str(item['itemId'])] for volume in volumes for item in volume]
    except (ValueError, TypeError, KeyError):
        pass
    return book, toc


def validate(kind, book_id, result):
    if not isinstance(result, dict) or result.get("code") != 0 or not isinstance(result.get("data"), dict):
        raise ValueError("invalid_cached_metadata")
    data = result["data"]
    if kind == "book":
        if str(data.get("bookId", book_id)) != book_id or not str(data.get("bookName") or "").strip():
            raise ValueError("invalid_cached_book")
    elif kind == "toc":
        entries = data.get("item_data_list")
        if not isinstance(entries, list) or not entries or len(entries) > 100000:
            raise ValueError("invalid_cached_directory")
        ids = [str(item["item_id"]) for item in entries]
        if len(ids) != len(set(ids)) or any(not ID.fullmatch(item) for item in ids):
            raise ValueError("invalid_cached_directory")
        if data.get("serial_count") is not None and int(data["serial_count"]) != len(ids):
            raise ValueError("invalid_cached_directory")
    return result


class Metadata:
    def __init__(self, config):
        self.config = config
        self.folder = config.state_dir / "metadata-v2"
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, key):
        digest = hashlib.sha256((self.config.upstream_base + "\n" + key).encode()).hexdigest()
        return self.folder / (digest + ".json")

    def lock(self, path):
        # Fixed stripes bound lock-file inode use even for many search queries.
        return self.folder / ("lock-" + str(int(path.stem[:4], 16) % 64))

    def load(self, path):
        try:
            if path.stat().st_size > MAX_BYTES:
                return {}
            data = json.loads(path.read_text())
            return data if data.get("version") == 1 else {}
        except (OSError, ValueError, AttributeError):
            return {}

    def save(self, path, data):
        temporary = path.with_name("." + uuid.uuid4().hex + ".tmp")
        try:
            raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
            if len(raw) > MAX_BYTES:
                return
            with temporary.open("wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, path)
            # Bound cached bytes and entry count, including older catalog lists.
            files = sorted(self.folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            used = 0
            for index, file in enumerate(files):
                size = file.stat().st_size
                if index >= 256 or used + size > 32 * 1024 * 1024:
                    file.unlink(missing_ok=True)
                else:
                    used += size
        except OSError:
            pass  # A cache write must never make a valid response fail.
        finally:
            temporary.unlink(missing_ok=True)

    def hit(self, cached, kind, book_id):
        if cached.get(kind + "_expires", 0) <= time.time():
            return None
        try:
            return validate(kind, book_id, cached[kind])
        except (KeyError, ValueError, TypeError):
            return None

    def get(self, kind, book_id, fetch, fresh=False):
        if kind not in ("book", "toc") or not ID.fullmatch(book_id):
            raise ValueError("invalid_metadata_key")
        path = self.path("book:" + book_id)
        cached = self.load(path)
        if not fresh:
            result = self.hit(cached, kind, book_id)
            if result is not None:
                return result
        # API confirmation and worker share this lock and the same cache bytes.
        with exclusive_file(self.lock(path), timeout=20):
            cached = self.load(path)
            if not fresh:
                result = self.hit(cached, kind, book_id)
                if result is not None:
                    return result
            if kind == "toc" and cached.get("toc_upstream_until", 0) > time.time():
                try:
                    result = validate(kind, book_id, fetch())
                except (ValueError, KeyError, TypeError):
                    raise UpstreamError("invalid_upstream_metadata") from None
                cached.update(toc=result, toc_expires=time.time() + TOC_SECONDS, version=1)
                self.save(path, cached)
                return result
            try:
                if kind == "toc" and (fresh or self.hit(cached, "book", book_id) is not None):
                    toc = public_directory(book_id)
                    cached.update(toc=toc, toc_expires=time.time() + TOC_SECONDS)
                else:
                    book, toc = public_bundle(book_id)
                    cached.update(book=book, book_expires=time.time() + BOOK_SECONDS)
                    if toc is not None and cached.get("toc_upstream_until", 0) <= time.time():
                        cached.update(toc=toc, toc_expires=time.time() + TOC_SECONDS)
                    if kind == "toc" and toc is None:
                        cached.update(toc=public_directory(book_id), toc_expires=time.time() + TOC_SECONDS)
                result = validate(kind, book_id, cached[kind])
            except Exception:
                # Public layout or networking can change. Preserve the original
                # authenticated parser as fallback, without serving stale TOCs.
                try:
                    result = validate(kind, book_id, fetch())
                except (ValueError, KeyError, TypeError):
                    raise UpstreamError("invalid_upstream_metadata") from None
                cached[kind] = result
                cached[kind + "_expires"] = time.time() + (TOC_SECONDS if kind == "toc" else BOOK_SECONDS)
            cached.update(version=1)
            self.save(path, cached)
            return result

    def invalidate_directory(self, book_id):
        if not ID.fullmatch(book_id):
            return
        path = self.path("book:" + book_id)
        with exclusive_file(self.lock(path), timeout=20):
            cached = self.load(path)
            cached.pop("toc", None)
            cached["toc_expires"] = 0
            # A different upstream ordering must use its own catalog on retry.
            cached["toc_upstream_until"] = time.time() + BOOK_SECONDS
            cached['version'] = 1
            self.save(path, cached)

    def search(self, params, fetch):
        key = "search:" + urllib.parse.urlencode(sorted((params or {}).items()))
        path = self.path(key)
        def hit(data):
            result = data.get("result")
            if data.get("expires", 0) > time.time() and isinstance(result, dict) and result.get("code") == 0:
                return result
            return None
        result = hit(self.load(path))
        if result is not None:
            return result
        with exclusive_file(self.lock(path), timeout=20):
            result = hit(self.load(path))
            if result is not None:
                return result
            if os.environ.get("FQ_SEARCH_FAST", "1").lower() in ("1", "true", "yes"):
                try:
                    result = public_search(params)
                except Exception:
                    # Preserve established, token-protected Java catalog on
                    # network faults, rate limits or publisher schema changes.
                    result = fetch()
            else:
                result = fetch()
            if isinstance(result, dict) and result.get("code") == 0:
                self.save(path, {"version": 1, "expires": time.time() + SEARCH_SECONDS, "result": result})
            return result
