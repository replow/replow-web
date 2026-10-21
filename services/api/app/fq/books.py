from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import uuid
import time
from threading import BoundedSemaphore
import urllib.parse
from .artifacts import RETENTION_SECONDS, find_artifact, add_artifact, finish_job
from .covers import cover_url
import zipfile

from .client import UpstreamError


_cover_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fq-cover")
_cover_slots = BoundedSemaphore(2)


def start_cover(config, book_id, url):
    """Keep original publisher bytes/format handling in covers.py, off the critical path."""
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        trusted = (parsed.scheme == 'https' and parsed.port in (None,443) and
            not parsed.username and not parsed.password and not any(x in url for x in '\r\n') and
            any(host == suffix or host.endswith('.'+suffix) for suffix in
                ['fqnovelpic.com','byteimg.com','pstatp.com','douyinpic.com']))
        if not trusted:
            return '', None
    except (ValueError, TypeError):
        return '', None
    if not _cover_slots.acquire(blocking=False):
        return url, None
    try:
        future = _cover_pool.submit(cover_url, config, book_id, url)
        future.add_done_callback(lambda _future: _cover_slots.release())
        return url, future
    except Exception:
        _cover_slots.release()
        return url, None


def atomic_json(path, data):
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_text(text):
    text = re.sub(r"<(?:br|/p|/div)[^>]*>", "\n", text, flags=re.I)
    return html.unescape(re.sub(r"<[^>]*>", "", text)).strip()


def chapter_record(data, book_id, chapter_id):
    if str(data.get("bookId")) != book_id or str(data.get("chapterId")) != chapter_id:
        raise UpstreamError("chapter_identity_mismatch")
    raw = data.get("txtContent")
    if not isinstance(raw, str):
        raise UpstreamError("chapter_body_missing")
    body = normalize_text(raw)
    title = str(data.get("title") or chapter_id)
    front_matter = bool(re.fullmatch(r"版权(?:信息|页|信息页)?", title.strip()))
    try:
        declared = int(data.get("wordCount") or 0)
    except (ValueError, TypeError):
        raise UpstreamError("chapter_word_count_invalid") from None
    # A few original private-use glyphs occur in classical editions. Reject
    # widespread undecoded font substitution, while preserving isolated glyphs.
    private_chars = len(re.findall(r"[\ue000-\uf8ff]", body))
    if len(body) < max(8 if front_matter else 80, declared * .75) or (len(body) == 200 and not front_matter) or private_chars > max(3, len(body) * .01):
        raise UpstreamError("chapter_incomplete_or_unreadable")
    if any(part in body[:100] for part in ("章节内容获取失败", "本章下载失败", "本章节暂无内容", "请打开番茄小说APP")):
        raise UpstreamError("chapter_placeholder_rejected")
    if data.get("isChapterLock") or len(re.findall(r"[\u4e00-\u9fffA-Za-z]", body)) < (5 if front_matter else 20):
        raise UpstreamError("chapter_incomplete_or_unreadable")
    return {"chapter_id": chapter_id, "title": title, "text": body, "characters": len(body), "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}


def cached_chapter(folder, chapter_id):
    path = folder / (chapter_id + ".json")
    try:
        if path.stat().st_mtime + RETENTION_SECONDS <= time.time(): return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["chapter_id"] != chapter_id or hashlib.sha256(data["text"].encode("utf-8")).hexdigest() != data["sha256"]:
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def xml_text(text):
    valid = re.sub(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", "", str(text))
    return html.escape(valid, quote=True)


def xhtml(title, body):
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN" xml:lang="zh-CN">'
            '<head><meta charset="utf-8"/><title>' + xml_text(title) + '</title></head><body>' + body + '</body></html>')


def render_txt(path, folder, entries, metadata):
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(metadata["title"] + "\n" + ("作者：" + metadata["author"] + "\n" if metadata.get("author") else ""))
        for entry in entries:
            chapter = cached_chapter(folder, entry["item_id"])
            if chapter is None:
                raise UpstreamError("chapter_cache_missing")
            output.write("\n\n" + chapter["title"] + "\n\n" + chapter["text"])
        output.flush()
        os.fsync(output.fileno())


def render_epub(path, folder, entries, metadata):
    manifest, spine, navigation = [], [], []
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", '<?xml version="1.0" encoding="utf-8"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        for index, entry in enumerate(entries):
            chapter = cached_chapter(folder, entry["item_id"])
            if chapter is None:
                raise UpstreamError("chapter_cache_missing")
            name = "chapters/" + str(index + 1) + ".xhtml"
            paragraphs = "".join("<p>" + xml_text(line) + "</p>" for line in chapter["text"].splitlines() if line.strip())
            archive.writestr("EPUB/" + name, xhtml(chapter["title"], "<h1>" + xml_text(chapter["title"]) + "</h1>" + paragraphs))
            manifest.append('<item id="c' + str(index) + '" href="' + name + '" media-type="application/xhtml+xml"/>')
            spine.append('<itemref idref="c' + str(index) + '"/>')
            navigation.append('<li><a href="' + name + '">' + xml_text(chapter["title"]) + '</a></li>')
        archive.writestr("EPUB/nav.xhtml", xhtml("目录", '<nav epub:type="toc" id="toc"><h1>目录</h1><ol>' + "".join(navigation) + '</ol></nav>'))
        identifier = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "https://fanqienovel.com/page/" + metadata["book_id"] + "?range=" + str(metadata.get("range_start",1)) + "-" + str(metadata.get("range_end",len(entries)))))
        modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        package = '<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">' + identifier + '</dc:identifier><dc:title>' + xml_text(metadata["title"]) + '</dc:title><dc:language>zh-CN</dc:language><dc:creator>' + xml_text(metadata.get("author") or "佚名") + '</dc:creator><meta property="dcterms:modified">' + modified + '</meta></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>' + "".join(manifest) + '</manifest><spine>' + "".join(spine) + '</spine></package>'
        archive.writestr("EPUB/package.opf", package)
    with path.open("rb") as file:
        os.fsync(file.fileno())


def completed_cache(config, book_id, format):
    try:
        manifest = json.loads((config.state_dir / "books" / book_id / "manifest.json").read_text())
        output = manifest["outputs"][format]
        path = config.download_dir / (book_id + "." + format)
        if manifest["full_book_verified"] and manifest["verified_chapters"] == manifest["expected_chapters"] and path.is_file() and path.stat().st_size == output["size_bytes"] and file_hash(path) == output["sha256"]:
            return manifest, output
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def process_book(config, store, job, client):
    book_id, format = job["book_id"], job["format"]
    if not re.fullmatch(r"[0-9]{1,24}", book_id) or format not in ("txt", "epub"):
        raise UpstreamError("invalid_download_request", False)
    first, requested_last = int(job.get('start_chapter') or 1), job.get('end_chapter')
    old = find_artifact(store,book_id,format,first,requested_last)
    if old and not job['refresh']:
        finish_job(store,job['id'],old,reused=old['last']-old['first']+1)
        return
    if shutil.disk_usage(config.download_dir).free < 256 * 1024 * 1024:
        raise UpstreamError("insufficient_disk_space", False)
    directory = client.request("/api/toc/" + book_id, fresh=bool(job['refresh']))["data"]
    entries = [{"item_id": str(item["item_id"]), "title": str(item.get("title") or "")} for item in directory.get("item_data_list", [])]
    ids = [entry["item_id"] for entry in entries]
    if not ids or len(ids) != len(set(ids)) or any(not re.fullmatch(r"[0-9]{1,24}", item) for item in ids):
        raise UpstreamError("invalid_or_empty_directory", False)
    if directory.get("serial_count") is not None and int(directory["serial_count"]) != len(ids):
        raise UpstreamError("directory_count_mismatch")
    catalog_ids = ids[:]
    last = len(ids) if requested_last is None else int(requested_last)
    if first < 1 or first > last or last > len(ids):
        raise UpstreamError("chapter_range_out_of_bounds", False)
    folder = config.state_dir / "books" / book_id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = {"book_id": book_id, "title": "小说 " + book_id, "author": "", "cover_url":"", "range_start":first, "range_end":last}
    try:
        detail = client.request("/api/book/" + book_id)["data"]
        metadata.update(title=str(detail.get("bookName") or metadata["title"]), author=str(detail.get("author") or ""), cover_url=str(detail.get("coverUrl") or ""))
    except UpstreamError:
        raise
    metadata["cover_url"], cover_future = start_cover(config, book_id, metadata["cover_url"])
    atomic_json(folder / "catalog.json", {"entries": entries, "metadata": metadata})
    selected = entries[first-1:last]
    selected_ids = [x['item_id'] for x in selected]
    completed = set()
    for entry in selected:
        cached = cached_chapter(folder,entry['item_id'])
        if cached and re.sub(r"\s+", "", cached['title']) == re.sub(r"\s+", "", entry['title']):
            completed.add(entry['item_id'])
    reused = len(completed)
    store.update(job['id'], total=len(selected), done=reused, title=metadata['title'], author=metadata['author'],
        cover_url=metadata['cover_url'], catalog_total=len(catalog_ids),actual_end=last,reused_chapters=reused)
    missing = [i for i in range(first-1,last) if catalog_ids[i] not in completed]
    titles = {entry['item_id']: entry['title'] for entry in entries}
    last_progress = time.monotonic()

    def save_chapter(chapter, item):
        nonlocal last_progress
        if item in completed:
            raise UpstreamError('unexpected_or_duplicate_chapter', False)
        record = chapter_record(chapter, book_id, item)
        expected_title = titles[item]
        if expected_title and re.sub(r"\s+", "", record['title']) != re.sub(r"\s+", "", expected_title):
            raise UpstreamError('chapter_title_mismatch')
        atomic_json(folder / (item + '.json'), record)
        completed.add(item)
        if len(completed) == reused + 1 or time.monotonic() - last_progress >= .3:
            store.update(job['id'], done=len(completed), added_chapters=len(completed)-reused)
            last_progress = time.monotonic()

    try:
        if config.go_fetch_binary:
            from .parallel import download_shards
            download_shards(config, book_id, catalog_ids, missing, save_chapter)
        else:
            # Retained for rollback and existing protocol fixtures.
            groups=[]
            for position in missing:
                if groups and position==groups[-1][-1]+1 and len(groups[-1])<config.batch_size:groups[-1].append(position)
                else:groups.append([position])
            for positions in groups:
                start=positions[0];expected=[catalog_ids[i] for i in positions]
                batch=client.request('/api/batch/'+book_id,{'offset':start,'limit':len(positions)},allow_partial=True)
                data=batch.get('data') or {}
                if data.get('total')!=len(catalog_ids) or str(data.get('book_id'))!=book_id or data.get('offset')!=start:
                    raise UpstreamError('directory_changed_or_batch_mismatch')
                for chapter in data.get('chapters',[]):
                    item=str(chapter.get('chapterId'))
                    if item not in expected:raise UpstreamError('unexpected_chapter')
                    save_chapter(chapter,item)
                if any(item not in completed for item in expected):raise UpstreamError('upstream_chapter_unavailable')
    except UpstreamError as error:
        if config.metadata_fast and error.reason in (
                'directory_changed_or_batch_mismatch', 'unexpected_or_duplicate_chapter',
                'chapter_title_mismatch'):
            try:
                from .metadata import Metadata
                Metadata(config).invalidate_directory(book_id)
            except (OSError, UpstreamError):
                pass
            raise UpstreamError(error.reason, True) from None
        raise
    finally:
        store.update(job['id'], done=len(completed), added_chapters=len(completed)-reused)
    if cover_future is not None and cover_future.done():
        try:
            resolved = cover_future.result()
            if resolved:
                metadata['cover_url'] = resolved
                atomic_json(folder / 'catalog.json', {'entries': entries, 'metadata': metadata})
                store.update(job['id'], cover_url=resolved)
        except Exception:
            pass
    entries,ids = selected,selected_ids
    hashes = []
    characters = 0
    for item in ids:
        chapter = cached_chapter(folder, item)
        if chapter is None:
            raise UpstreamError("chapter_cache_missing")
        hashes.append(chapter["sha256"])
        characters += chapter["characters"]
    if len(set(hashes)) != len(ids):
        raise UpstreamError("duplicate_chapter_body", False)
    fingerprint=hashlib.sha256(json.dumps([metadata,ids,hashes],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    old=find_artifact(store,book_id,format,first,last,fingerprint)
    if old:
        finish_job(store,job['id'],old,len(completed)-reused,reused)
        return
    artifact_id=uuid.uuid4().hex
    filename=f"{book_id}-{first}-{last}-{artifact_id[:16]}.{format}"
    target=config.download_dir/filename
    temporary = config.download_dir / ("." + book_id + "-" + uuid.uuid4().hex + ".tmp")
    try:
        (render_txt if format == "txt" else render_epub)(temporary, folder, entries, metadata)
        result = {"sha256": file_hash(temporary), "size_bytes": temporary.stat().st_size}
        temporary.chmod(0o644)
        os.replace(temporary, target)
        now=time.time()
        artifact={"id":artifact_id,"book_id":book_id,"format":format,"first":first,"last":last,
            "catalog_total":len(catalog_ids),"title":metadata['title'],"author":metadata['author'],
            "cover_url":metadata['cover_url'],"filename":filename,**result,"fingerprint":fingerprint,
            "catalog_ids":json.dumps(catalog_ids),"created_at":now,"expires_at":now+RETENTION_SECONDS}
        os.utime(target,(now,now))
        add_artifact(store,artifact)
        finish_job(store,job['id'],artifact,len(completed)-reused,reused)
    finally:
        temporary.unlink(missing_ok=True)


def time_now():
    return datetime.now(timezone.utc).isoformat()
