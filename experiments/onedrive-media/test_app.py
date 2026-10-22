import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import app

URL = "https://example.files.1drv.com/public-test?token=fixture"
PARENT = {"driveId": "fixture-drive", "id": "fixture-root"}

class PolicyTests(unittest.TestCase):
    def test_unicode_and_spaces(self):
        self.assertEqual(app.normalize("封面/测试 1.webp"), "封面/测试 1.webp")

    def test_path_escape_and_hidden_paths(self):
        for path in ("", "../backup", "x/../a", ".env", "x//a", "x\\a",
                     "x/%2e%2e/a", "x/\x00a", "/x", "x/", "x:y", "x/.git/a"):
            with self.subTest(path=repr(path)), self.assertRaises(app.Failure):
                app.normalize(path)

    def test_download_hosts_are_restricted(self):
        self.assertTrue(app.safe_url(URL))
        for url in ("http://example.files.1drv.com/a", "https://1drv.com.evil.invalid/",
                    "https://127.0.0.1/", "https://user:pass@1drv.com/a",
                    "https://1drv.com:8443/a", "//example.files.1drv.com/a"):
            with self.subTest(url=url):
                self.assertFalse(app.safe_url(url))

    def test_expiry_margin_and_unknown_expiry_bound(self):
        self.assertEqual(app.expiry(URL, 1000), 1000 + app.TTL)
        self.assertEqual(app.expiry(URL + "&exp=1100", 1000), 1070)
        self.assertEqual(app.expiry(URL + "&exp=900", 1000), 1000)

class ResolverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [patch.object(app, "DRIVE", "fixture-drive"),
                        patch.object(app, "ROOT", "fixture-root")]
        for p in self.patches:
            p.start()
        self.requests = []
        self.graph_replies = []
        self.dead_urls = set()
        self.down_status = 200
        self.item = {"id": "fixture-file", "file": {"mimeType": "image/webp"},
                     "parentReference": PARENT,
                     "@microsoft.graph.downloadUrl": URL}
        async def handle(request):
            self.requests.append(request)
            if request.url.host == "graph.microsoft.com":
                await asyncio.sleep(0)
                if self.graph_replies:
                    status, data, headers = self.graph_replies.pop(0)
                    return httpx.Response(status, json=data, headers=headers)
                return httpx.Response(200, json=self.item)
            return httpx.Response(403 if str(request.url) in self.dead_urls else self.down_status)
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        self.media = app.Media(self.client)
        async def token(force=False):
            return "fixture-secret"
        self.media.token = token

    async def asyncTearDown(self):
        await self.client.aclose()
        for p in self.patches:
            p.stop()

    async def test_cache_hit_avoids_graph_and_checks_link(self):
        self.assertEqual((await self.media.resolve("a.webp"))[1], "MISS")
        self.assertEqual((await self.media.resolve("a.webp"))[1], "HIT")
        self.assertEqual(self.media.graph_count, 1)
        download = [r for r in self.requests if r.url.host != "graph.microsoft.com"]
        self.assertEqual(len(download), 2)
        self.assertTrue(all(r.method == "HEAD" for r in download))
        self.assertTrue(all("authorization" not in r.headers for r in download))

    async def test_concurrent_miss_fetches_once(self):
        result = await asyncio.gather(*(self.media.resolve("a.webp") for _ in range(12)))
        self.assertEqual(self.media.graph_count, 1)
        self.assertEqual(len(result), 12)

    async def test_expired_cache_is_refetched(self):
        await self.media.resolve("a.webp")
        self.media.cache["a.webp"].expires = 0
        await self.media.resolve("a.webp")
        self.assertEqual(self.media.graph_count, 2)

    async def test_refresh_before_expiry(self):
        await self.media.resolve("a.webp")
        self.media.cache["a.webp"].refresh = 0
        await self.media.resolve("a.webp")
        self.assertEqual(self.media.graph_count, 2)

    async def test_early_revocation_invalidates_cached_link(self):
        await self.media.resolve("a.webp")
        self.dead_urls.add(URL)
        fresh_url = URL + "-new"
        self.item = {**self.item, "@microsoft.graph.downloadUrl": fresh_url}
        self.assertEqual((await self.media.resolve("a.webp"))[0], fresh_url)
        self.assertEqual(self.media.graph_count, 2)

    async def test_deleted_file_does_not_keep_old_link_after_refresh(self):
        await self.media.resolve("a.webp")
        self.media.cache["a.webp"].refresh = 0
        self.graph_replies = [(404, {}, {})]
        with self.assertRaises(app.Failure) as result:
            await self.media.resolve("a.webp")
        self.assertEqual(result.exception.status, 404)
        self.assertNotIn("a.webp", self.media.cache)

    async def test_shared_or_outside_files_are_rejected(self):
        for item in ({**self.item, "remoteItem": {"id": "other"}},
                     {**self.item, "parentReference": {"driveId": "other", "id": "elsewhere"}},
                     {**self.item, "file": None}):
            self.item = item
            with self.assertRaises(app.Failure) as result:
                await self.media.resolve("a.webp")
            self.assertEqual(result.exception.status, 404)

    async def test_nested_folder_ancestry(self):
        item = {**self.item, "parentReference": {"driveId": "fixture-drive", "id": "sub"}}
        folder = {"id": "sub", "folder": {}, "parentReference": PARENT}
        self.graph_replies = [(200, item, {}), (200, folder, {})]
        self.assertEqual((await self.media.resolve("sub/a.webp"))[0], URL)

    async def test_background_refresh_runs_without_new_requests(self):
        await self.media.resolve("a.webp")
        self.media.cache["a.webp"].refresh = 0
        calls = 0
        async def one_tick(delay):
            nonlocal calls
            if delay == 0:
                return
            calls += 1
            if calls > 1:
                raise asyncio.CancelledError()
        with patch.object(app.asyncio, "sleep", one_tick):
            with self.assertRaises(asyncio.CancelledError):
                await self.media.refresh_loop()
        self.assertEqual(self.media.graph_count, 2)
        self.assertGreater(self.media.cache["a.webp"].refresh, time.time())

    async def test_idle_entries_are_not_refreshed_forever(self):
        await self.media.resolve("a.webp")
        self.media.cache["a.webp"].last_used = time.time() - 601
        calls = 0
        async def one_tick(delay):
            nonlocal calls
            if delay == 0:
                return
            calls += 1
            if calls > 1:
                raise asyncio.CancelledError()
        with patch.object(app.asyncio, "sleep", one_tick):
            with self.assertRaises(asyncio.CancelledError):
                await self.media.refresh_loop()
        self.assertNotIn("a.webp", self.media.cache)
        self.assertEqual(self.media.graph_count, 1)

    async def test_unknown_download_host_is_never_contacted(self):
        self.item = {**self.item, "@microsoft.graph.downloadUrl": "https://127.0.0.1/admin"}
        with self.assertRaises(app.Failure):
            await self.media.resolve("a.webp")
        self.assertEqual(len(self.requests), 1)

    async def test_throttle_honors_retry_and_does_not_storm_graph(self):
        self.graph_replies = [(429, {}, {"Retry-After": "120"})]
        for _ in range(5):
            with self.assertRaises(app.Failure) as result:
                await self.media.resolve("a.webp")
            self.assertEqual(result.exception.code, "upstream_busy")
        self.assertEqual(self.media.graph_count, 1)

    async def test_transient_error_does_not_serve_unchecked_link(self):
        await self.media.resolve("a.webp")
        self.down_status = 503
        with self.assertRaises(app.Failure):
            await self.media.resolve("a.webp")

    async def test_expired_fresh_url_is_rejected(self):
        self.item = {**self.item, "@microsoft.graph.downloadUrl": URL + "&exp=1"}
        with self.assertRaises(app.Failure):
            await self.media.resolve("a.webp")

class TokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_rotates_token_and_saves_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "TOKEN_FILE", Path(directory) / "token.json"):
                app.atomic_token({"client_id": "fixture-app", "refresh_token": "old",
                                  "access_token": "expired", "expires_at": 0})
                calls = []
                async def handle(request):
                    calls.append(request)
                    return httpx.Response(200, json={"access_token": "new",
                        "refresh_token": "rotated", "expires_in": 3600})
                async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                    media = app.Media(client)
                    self.assertEqual(await media.token(), "new")
                    self.assertEqual(await media.token(), "new")
                self.assertEqual(len(calls), 1)
                data = app.json.loads(app.TOKEN_FILE.read_text())
                self.assertEqual(data["refresh_token"], "rotated")
                self.assertEqual(app.TOKEN_FILE.stat().st_mode & 0o777, 0o600)

    async def test_revoked_authorization_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "TOKEN_FILE", Path(directory) / "token.json"):
                app.atomic_token({"client_id": "fixture-app", "refresh_token": "old",
                                  "expires_at": 0})
                async def handle(request):
                    return httpx.Response(400, json={"error": "invalid_grant"})
                async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                    with self.assertRaises(app.Failure) as result:
                        await app.Media(client).token()
                    self.assertEqual(result.exception.code, "authorization_required")

class EndpointTests(unittest.TestCase):
    def test_unconfigured_service_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "TOKEN_FILE", Path(directory) / "missing.json"):
                with TestClient(app.app) as client:
                    self.assertFalse(client.get("/healthz").json()["authorized"])
                    response = client.get("/image.webp")
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()["error"], "authorization_required")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertNotIn("location", response.headers)

    def test_redirect_is_temporary_and_not_browser_cached(self):
        with TestClient(app.app) as client:
            media = client.app.state.media
            media.configured = lambda: True
            async def resolve(path):
                return URL, "HIT"
            media.resolve = resolve
            for method in ("GET", "HEAD"):
                response = client.request(method, "/image.webp", follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["location"], URL)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertNotIn("fixture-secret", str(response.headers))

if __name__ == "__main__":
    unittest.main()
