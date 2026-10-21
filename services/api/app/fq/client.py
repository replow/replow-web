from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import Config


class UpstreamError(Exception):
    def __init__(self, reason="upstream_unavailable", retryable=True):
        self.reason = reason
        self.retryable = retryable
        super().__init__(reason)


@contextmanager
def exclusive_file(path, timeout=25):
    with path.open("a+") as lock:
        until = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= until:
                    raise UpstreamError("upstream_busy")
                time.sleep(.1)
        try:
            yield lock
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Client:
    def __init__(self, config: Config):
        self.config = config
        config.prepare()
        # Never send the service credential to arbitrary redirect targets.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, path, params=None, allow_partial=False, fresh=False):
        if not self.config.upstream_token:
            raise UpstreamError("upstream_not_configured", False)
        if self.config.metadata_fast:
            from .metadata import Metadata
            match = re.fullmatch(r"/api/(book|toc)/([0-9]{1,24})", path)
            try:
                if match:
                    return Metadata(self.config).get(match[1], match[2],
                        lambda: self._request_upstream(path, params, allow_partial), fresh=fresh)
                if path == "/api/search":
                    return Metadata(self.config).search(params,
                        lambda: self._request_upstream(path, params, allow_partial))
            except OSError:
                pass
        return self._request_upstream(path, params, allow_partial)

    def _request_upstream(self, path, params=None, allow_partial=False):
        if not self.config.upstream_token:
            raise UpstreamError("upstream_not_configured", False)
        if not path.startswith("/api/") or ".." in path:
            raise ValueError("invalid upstream path")
        url = self.config.upstream_base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"Authorization": "Bearer " + self.config.upstream_token, "Accept": "application/json"})
        with exclusive_file(self.config.state_dir / "upstream.lock") as lock:
            lock.seek(0)
            try:
                last = float(lock.read() or 0)
            except ValueError:
                last = 0
            delay = self.config.request_interval - max(0, time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
            lock.seek(0)
            lock.truncate()
            lock.write(str(time.monotonic()))
            lock.flush()
        try:
            try:
                response = self.opener.open(request, timeout=85)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status = response.code
                raw = response.read(4_000_001)
                if status in (401, 403):
                    raise UpstreamError("upstream_authentication_failed", False)
                if len(raw) > 4_000_000:
                    raise UpstreamError("upstream_response_too_large")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("invalid upstream JSON")
                if status == 502 and allow_partial and data.get("code") == "PARTIAL_BATCH":
                    return data
                if status != 200 or data.get("code") != 0:
                    raise UpstreamError("upstream_response_failed")
                return data
        except UpstreamError:
            raise
        except (OSError, ValueError, urllib.error.URLError):
            raise UpstreamError("upstream_unavailable") from None
