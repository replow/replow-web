"""Small, bounded RSS/Atom reader used for public friend-link previews."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from threading import Lock
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


RSS_CACHE_SECONDS = 15 * 60
RSS_MAX_BYTES = 1_000_000
RSS_TIMEOUT_SECONDS = 5

_cache: dict[str, tuple[float, dict[str, str]]] = {}
_cache_lock = Lock()
# URLs with a background refresh in flight, so a burst of requests spawns one
# thread per feed instead of one per request.
_refreshing: set[str] = set()


def _is_public_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return False
    try:
        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, ValueError):
        return False
    return bool(addresses) and all(address.is_global for address in addresses)


def default_rss_url(website_url: Optional[str]) -> str:
    """Return the conventional RSS location for a friend-link website."""
    value = str(website_url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, "/rss.xml", "", ""))


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        if not _is_public_url(newurl):
            return None
        return super().redirect_request(request, file, code, message, headers, newurl)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split()).strip()


def _first_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) != name:
            continue
        return _clean_text("".join(child.itertext()))
    return ""


def _first_link(element: ET.Element) -> str:
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        href = _clean_text(child.attrib.get("href"))
        if href:
            return href
        value = _clean_text("".join(child.itertext()))
        if value:
            return value
    return ""


def _read_latest(payload: bytes) -> dict[str, str]:
    root = ET.fromstring(payload)
    entries = [
        element
        for element in root.iter()
        if _local_name(element.tag) in {"item", "entry"}
    ]
    if not entries:
        return {}
    entry = entries[0]
    title = _first_text(entry, "title")
    if not title:
        return {}
    return {"title": title, "url": _first_link(entry)}


def _resolve_url(rss_url: Optional[str], website_url: Optional[str]) -> str:
    return str(rss_url or "").strip() or default_rss_url(website_url)


def _fetch_latest(url: str) -> dict[str, str]:
    """Fetch and parse one feed. Never raises; returns {} on any failure.

    Everything slow lives here — DNS (``_is_public_url`` calls
    ``getaddrinfo``, which has no timeout of its own), the socket connect, and
    the body read — so callers can decide whether to pay for it inline.
    """
    if not url or not _is_public_url(url):
        return {}
    try:
        request = Request(
            url,
            headers={
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
                "User-Agent": "Replow-Friend-RSS/1.0",
            },
        )
        with build_opener(_SafeRedirectHandler()).open(
            request, timeout=RSS_TIMEOUT_SECONDS
        ) as response:
            return _read_latest(response.read(RSS_MAX_BYTES))
    except (ET.ParseError, HTTPError, OSError, URLError, TimeoutError, ValueError):
        return {}


def latest_article(
    rss_url: Optional[str], website_url: Optional[str] = None
) -> dict[str, str]:
    """Blocking variant. Only for callers that can afford to wait."""
    url = _resolve_url(rss_url, website_url)
    if not url:
        return {}

    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(url)
        if cached and now - cached[0] < RSS_CACHE_SECONDS:
            return dict(cached[1])

    result = _fetch_latest(url)
    with _cache_lock:
        _cache[url] = (time.monotonic(), dict(result))
    return result


def latest_article_cached(
    rss_url: Optional[str], website_url: Optional[str] = None
) -> dict[str, str]:
    """Never-blocking variant: serve the cache, refresh it in the background.

    The friends endpoint used to call the blocking variant for every link in
    turn, so one slow or unreachable third-party feed held the whole public
    request open (measured: 30s+ timeouts, and the page fell back to placeholder
    content while waiting). Request paths must not do third-party I/O; they read
    whatever is cached and hand the refresh to a daemon thread.

    Trade-off: the first response after a cold start carries no "latest article"
    data — it appears once the background refresh lands.
    """
    url = _resolve_url(rss_url, website_url)
    if not url:
        return {}

    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(url)
        if cached and now - cached[0] < RSS_CACHE_SECONDS:
            return dict(cached[1])
        # Stale value (or nothing) is what we answer with; never wait.
        stale = dict(cached[1]) if cached else {}
        if url in _refreshing:
            return stale
        _refreshing.add(url)

    def _worker() -> None:
        try:
            result = _fetch_latest(url)
            with _cache_lock:
                _cache[url] = (time.monotonic(), dict(result))
        finally:
            with _cache_lock:
                _refreshing.discard(url)

    threading.Thread(target=_worker, name="rss-refresh", daemon=True).start()
    return stale
