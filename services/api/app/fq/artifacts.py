"""Immutable downloadable artifacts and fixed 31-day retention."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

RETENTION_SECONDS = 31 * 86400
PUBLIC_FILE = re.compile(r"[0-9]{1,24}(?:-[0-9]{1,6}-[0-9]{1,6}-[a-f0-9]{16})?\.(?:txt|epub)")


def find_artifact(store, book_id, format, first, last=None, fingerprint=None):
    with store.connection() as db:
        query="SELECT * FROM artifacts WHERE book_id=? AND format=? AND first=? AND expires_at>?"
        args=[book_id,format,first,time.time()]
        if last is not None:query+=" AND last=?";args.append(last)
        else:query+=" AND last=catalog_total"
        if fingerprint:query+=" AND fingerprint=?";args.append(fingerprint)
        rows=db.execute(query+" ORDER BY created_at DESC",args).fetchall()
    for row in rows:
        result=dict(row);path=store.config.download_dir/result['filename']
        if path.is_file() and path.stat().st_size==result['size_bytes']:
            digest=hashlib.sha256()
            with path.open('rb') as file:
                for chunk in iter(lambda:file.read(1024*1024),b''):digest.update(chunk)
            if digest.hexdigest()==result['sha256']:return result
    return None


def add_artifact(store, record):
    with store.connection() as db:
        db.execute("INSERT INTO artifacts ("+','.join(record)+") VALUES ("+','.join('?' for _ in record)+")",tuple(record.values()))


def finish_job(store, job_id, artifact, added=0, reused=0):
    count=artifact['last']-artifact['first']+1
    store.update(job_id,status='completed',total=count,done=count,title=artifact['title'],
        author=artifact['author'],cover_url=artifact['cover_url'],filename=artifact['filename'],
        sha256=artifact['sha256'],size_bytes=artifact['size_bytes'],expires_at=artifact['expires_at'],
        artifact_id=artifact['id'],catalog_total=artifact['catalog_total'],actual_end=artifact['last'],
        added_chapters=added,reused_chapters=reused,error=None)


def job_catalog_ids(store, job):
    if job.get('artifact_id'):
        with store.connection() as db:
            row=db.execute('SELECT catalog_ids FROM artifacts WHERE id=?',(job['artifact_id'],)).fetchone()
        if row:return json.loads(row['catalog_ids'])
    try:
        catalog=json.loads((store.config.state_dir/'books'/job['book_id']/'catalog.json').read_text())
        return [str(x['item_id']) for x in catalog['entries']][:job.get('catalog_total') or job['total']]
    except (OSError,ValueError,KeyError):return []


def cleanup(store, now=None):
    now=time.time() if now is None else now
    cutoff=now-RETENTION_SECONDS
    with store.connection() as db:
        active={r[0] for r in db.execute("SELECT book_id FROM jobs WHERE status='running'")}
    removed=0
    for path in store.config.download_dir.iterdir():
        if path.is_file() and PUBLIC_FILE.fullmatch(path.name) and path.stat().st_mtime<=cutoff:
            path.unlink(missing_ok=True);removed+=1
        elif path.name.startswith('.') and path.name.endswith('.tmp') and path.stat().st_mtime<now-86400:
            path.unlink(missing_ok=True)
    books=store.config.state_dir/'books'
    covers=store.config.download_dir/'covers'
    if covers.exists():
        for path in covers.glob('*.jpg'):
            if path.is_file() and path.stat().st_mtime<=cutoff:path.unlink(missing_ok=True)
    if books.exists():
        for folder in books.iterdir():
            if not folder.is_dir() or folder.name in active:continue
            for path in folder.glob('*.json'):
                if path.stat().st_mtime<=cutoff:path.unlink(missing_ok=True)
            if not any(folder.iterdir()):folder.rmdir()
    from .operations import cleanup_result
    cleanup_result(store, removed)
    return removed
