"""Return search text immediately; resolve bounded cover hints on demand."""
import json
import os
import re
import time
from threading import BoundedSemaphore
import urllib.parse
import uuid

from .client import Client
from .covers import prepare_book_cover

_slots = BoundedSemaphore(4)
_id = re.compile(r'^[0-9]{1,24}$')
_ttl = 3600


class CoverBusy(Exception):
    pass


def trusted(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or '').lower()
        return (parsed.scheme == 'https' and parsed.port in (None, 443) and
                not parsed.username and not parsed.password and not any(c in url for c in '\r\n') and
                any(host == suffix or host.endswith('.' + suffix) for suffix in
                    ['fqnovelpic.com', 'byteimg.com', 'pstatp.com', 'douyinpic.com', 'bytecdn.cn']))
    except (ValueError, TypeError):
        return False


def search_text(config, result):
    """Only the ten visible results are remembered; no image work here."""
    data = result.get('data') or {}
    books = data.get('books') or []
    output = []
    folder = config.state_dir / 'cover-hints-v1'
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        pass
    for book in books[:10]:
        if not isinstance(book, dict):
            continue
        identity = str(book.get('bookId') or book.get('book_id') or '')
        url = str(book.get('coverUrl') or book.get('cover_url') or '')
        pending = bool(_id.fullmatch(identity) and trusted(url))
        if pending:
            temporary = folder / ('.' + uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_text(json.dumps({'bookId': identity, 'coverUrl': url,
                    'expires': time.time() + _ttl}, separators=(',', ':')))
                temporary.chmod(0o600)
                os.replace(temporary, folder / (identity + '.json'))
            except OSError:
                pass
            finally:
                temporary.unlink(missing_ok=True)
        output.append({**book, 'coverUrl': '', 'cover_url': '', 'coverPending': pending})
    try:
        files = sorted(folder.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        for index, path in enumerate(files):
            if index >= 512 or path.stat().st_mtime + _ttl < time.time():
                path.unlink(missing_ok=True)
    except OSError:
        pass
    return {**result, 'data': {**data, 'books': output, 'pageSize': 10,
        'hasMore': bool(data.get('hasMore') or len(books) > 10)}}


def resolve_cover(config, book_id):
    if not _slots.acquire(blocking=False):
        raise CoverBusy()
    try:
        hint = None
        try:
            path = config.state_dir / 'cover-hints-v1' / (book_id + '.json')
            if path.stat().st_size <= 16384:
                candidate = json.loads(path.read_text())
                if candidate.get('bookId') == book_id and candidate.get('expires', 0) > time.time() and trusted(candidate.get('coverUrl')):
                    hint = candidate
        except (OSError, ValueError, TypeError, AttributeError):
            pass

        # Search metadata sometimes supplies p*-tt.bytecdn.cn thumbnails that
        # return HTTP 403 to the server. Do not cache their empty conversion:
        # fall back to the signed, public-detail cover URL for this book.
        if hint is not None:
            preview = prepare_book_cover(config, dict(hint))
            if preview.get('coverUrl'):
                return {'code': 0, 'data': {'bookId': book_id, 'coverUrl': preview['coverUrl']}}

        detail = Client(config).request('/api/book/' + book_id)['data']
        result = prepare_book_cover(config, dict(detail))
        return {'code': 0, 'data': {'bookId': book_id, 'coverUrl': str(result.get('coverUrl') or '')}}
    finally:
        _slots.release()
