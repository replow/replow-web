"""Convert trusted publisher cover images to broadly supported cached JPEGs."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import os
import time
import urllib.parse
import urllib.request
import uuid

from PIL import Image
from pillow_heif import register_heif_opener
from .artifacts import RETENTION_SECONDS

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 20_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*_args,**_kwargs):return None


def cover_url(config, book_id, url):
    try:
        parsed=urllib.parse.urlparse(url)
        host=(parsed.hostname or '').lower()
        if parsed.scheme!='https' or parsed.port not in (None,443) or parsed.username or parsed.password:return ''
        if not any(host==suffix or host.endswith('.'+suffix) for suffix in ['fqnovelpic.com','byteimg.com','pstatp.com','douyinpic.com','bytecdn.cn']):return ''
        if not str(book_id).isdigit() or len(str(book_id))>24:return ''
        identity=hashlib.sha256((host+parsed.path).encode()).hexdigest()[:16]
        filename=str(book_id)+'-'+identity+'.jpg'
        folder=config.download_dir/'covers';folder.mkdir(mode=0o755,exist_ok=True);folder.chmod(0o755)
        target=folder/filename
        if not target.is_file() or target.stat().st_mtime+RETENTION_SECONDS<=time.time():
            request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://fanqienovel.com/'})
            with urllib.request.build_opener(NoRedirect).open(request,timeout=8) as response:
                if not response.headers.get('Content-Type','').startswith('image/'):return ''
                data=response.read(2_000_001)
                if len(data)>2_000_000:return ''
            temporary=folder/('.'+uuid.uuid4().hex+'.tmp')
            try:
                with Image.open(BytesIO(data)) as original:
                    original.thumbnail((500,700));image=original.convert('RGB');image.save(temporary,format='JPEG',quality=85,optimize=True)
                temporary.chmod(0o644);os.replace(temporary,target)
            finally:temporary.unlink(missing_ok=True)
        return config.public_base+'/covers/'+filename
    except Exception:
        # Never log signed publisher URLs or expose arbitrary exception text.
        return ''


def prepare_book_cover(config,book):
    if isinstance(book,dict):book['coverUrl']=cover_url(config,str(book.get('bookId') or ''),str(book.get('coverUrl') or ''))
    return book


def prepare_search_covers(config,books):
    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(lambda book:prepare_book_cover(config,book),books))
