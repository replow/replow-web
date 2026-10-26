"""Bounded homepage metadata, with DNS pinned to validated public addresses."""
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

_cache = {}
_lock = threading.Lock()
_slots = threading.BoundedSemaphore(4)


class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.site = ""
        self.title = ""
        self.icon = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta" and (a.get("property") or a.get("name") or "").lower() in ("og:site_name", "application-name"):
            self.site = a.get("content", "")[:160]
        if tag == "link" and "icon" in a.get("rel", "").lower().split() and not self.icon:
            self.icon = a.get("href", "")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title = (self.title + data)[:200]


def origin_url(value):
    p = urlsplit(value)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("invalid_url")
    if p.port not in (None, 80, 443):
        raise ValueError("invalid_port")
    return urlunsplit((p.scheme, p.netloc, "/", "", ""))


def public_address(host, port):
    addresses = [row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("non_public_address")
    return addresses[0]


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, parsed, address):
        super().__init__(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), timeout=3)
        self.address = address
        self.tls = parsed.scheme == "https"

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), timeout=self.timeout)
        if self.tls:
            self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)


def parse_metadata(text, page_url):
    parser = SiteParser()
    parser.feed(text)
    icon = urljoin(page_url, parser.icon or "/favicon.ico")
    p = urlsplit(icon)
    if p.scheme not in ("http", "https") or p.username or p.password:
        icon = urljoin(page_url, "/favicon.ico")
    return {"name": re.sub(r"\s+", " ", parser.site or parser.title).strip()[:160], "icon": icon}


def fetch_metadata(value):
    origin = origin_url(value)
    with _lock:
        cached = _cache.get(origin)
        if cached and time.monotonic() - cached[0] < 3600:
            return dict(cached[1])
    if not _slots.acquire(blocking=False):
        return {}
    result = {}
    try:
        url = origin
        for _ in range(4):
            p = urlsplit(url)
            # Check every redirect and pin the actual connection to the checked IP.
            origin_url(url)
            address = public_address(p.hostname, p.port or (443 if p.scheme == "https" else 80))
            connection = PinnedConnection(p, address)
            try:
                connection.request("GET", urlunsplit(("", "", p.path or "/", p.query, "")), headers={"Host": p.netloc, "User-Agent": "Silune-SiteInfo/1.0", "Accept": "text/html", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.getheader("Location") or "")
                    continue
                if response.status != 200 or "html" not in response.getheader("Content-Type", "").lower():
                    break
                payload = response.read(262144)
                match = re.search(r"charset=([\w-]+)", response.getheader("Content-Type", ""), re.I)
                encoding = match.group(1) if match else "utf-8"
                result = parse_metadata(payload.decode(encoding, errors="replace"), url)
                break
            finally:
                connection.close()
    except (OSError, ValueError, http.client.HTTPException, LookupError):
        result = {}
    finally:
        _slots.release()
    with _lock:
        if len(_cache) >= 256:
            _cache.pop(next(iter(_cache)))
        _cache[origin] = (time.monotonic(), dict(result))
    return result
