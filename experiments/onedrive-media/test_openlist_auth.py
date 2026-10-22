import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import app
from openlist_auth import ACCESS_REUSE_SECONDS, OnlineAuthError, renew, validate_account

class OnlineAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_real_protocol_and_bounded_expiry(self):
        async def handler(request):
            self.assertEqual(str(request.url).split("?")[0],
                             "https://api.oplist.org/onedrive/renewapi")
            self.assertEqual(request.method, "GET")
            self.assertEqual(parse_qs(request.url.query.decode()),
                             {"refresh_ui": ["old-fixture"], "server_use": ["true"],
                              "driver_txt": ["onedrive_pr"]})
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, json={"access_token": "access-fixture",
                                             "refresh_token": "rotated-fixture"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            data = await renew(client, "old-fixture")
        self.assertEqual(data["provider"], "openlist")
        self.assertEqual(data["refresh_token"], "rotated-fixture")
        self.assertLess(abs(data["expires_at"]-time.time()-ACCESS_REUSE_SECONDS), 2)

    async def test_empty_or_malformed_success_is_rejected(self):
        for body in ({}, {"refresh_token": "fixture"}, {"access_token": "fixture"},
                     {"access_token": "bad\nvalue", "refresh_token": "fixture"}, []):
            async def handler(request):
                return httpx.Response(200, json=body)
            with self.subTest(body=body):
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    with self.assertRaises(OnlineAuthError):
                        await renew(client, "fixture")

    async def test_api_error_text_never_escapes_exception(self):
        async def handler(request):
            return httpx.Response(500, json={"text": "private-fixture-never-print"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(OnlineAuthError) as result:
                await renew(client, "private-refresh-fixture")
        self.assertEqual(str(result.exception), "authorization_unavailable")
        self.assertNotIn("private", str(result.exception))

    async def test_redirect_cannot_forward_refresh_token(self):
        calls = []
        async def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"Location": "https://untrusted.invalid/"})
        # Even if caller enables redirects, the adapter must not follow them.
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     follow_redirects=True) as client:
            with self.assertRaises(OnlineAuthError):
                await renew(client, "fixture")
        self.assertEqual(len(calls), 1)

    async def test_retry_after_is_preserved(self):
        async def handler(request):
            return httpx.Response(429, headers={"Retry-After": "120"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(OnlineAuthError) as result:
                await renew(client, "fixture")
        self.assertEqual(result.exception.retry, 120)
        self.assertEqual(result.exception.code, "authorization_busy")

    async def test_wrong_account_is_rejected_before_folder_lookup(self):
        calls = []
        async def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"id": "other", "driveType": "personal"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(OnlineAuthError) as result:
                await validate_account(client, "fixture", "expected", "folder")
        self.assertEqual(result.exception.code, "wrong_onedrive_account")
        self.assertEqual(len(calls), 1)

    async def test_only_dedicated_local_folder_is_accepted(self):
        folders = [
            {"folder": {}, "parentReference": {"driveId": "fixture-drive"}},
            {"folder": {}, "root": {}, "parentReference": {"driveId": "fixture-drive"}},
            {"folder": {}, "remoteItem": {"id": "remote"},
             "parentReference": {"driveId": "fixture-drive"}},
            {"folder": {}, "parentReference": {"driveId": "other"}},
        ]
        for index, folder in enumerate(folders):
            async def handler(request):
                if request.url.path.endswith("/me/drive"):
                    return httpx.Response(200, json={"id": "fixture-drive", "driveType": "personal"})
                return httpx.Response(200, json=folder)
            with self.subTest(index=index):
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    if index == 0:
                        await validate_account(client, "fixture", "fixture-drive", "folder")
                    else:
                        with self.assertRaises(OnlineAuthError):
                            await validate_account(client, "fixture", "fixture-drive", "folder")

    async def test_refresh_is_locked_and_rotated_token_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "TOKEN_FILE", Path(directory)/"token.json"), \
                 patch.object(app, "DRIVE", "fixture-drive"), patch.object(app, "ROOT", "fixture-root"):
                app.atomic_token({"provider": "openlist", "refresh_token": "old",
                    "drive_id": "fixture-drive", "root_item_id": "fixture-root", "expires_at": 0})
                calls = []
                async def handler(request):
                    calls.append(request)
                    await asyncio.sleep(0)
                    return httpx.Response(200, json={"access_token": "access",
                                                     "refresh_token": "rotated"})
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    media = app.Media(client)
                    tokens = await asyncio.gather(*(media.token() for _ in range(8)))
                self.assertEqual(tokens, ["access"]*8)
                self.assertEqual(len(calls), 1)
                saved = json.loads(app.TOKEN_FILE.read_text())
                self.assertEqual(saved["refresh_token"], "rotated")
                self.assertEqual(saved["drive_id"], "fixture-drive")
                self.assertEqual(app.TOKEN_FILE.stat().st_mode & 0o777, 0o600)

    async def test_provider_cooldown_stops_repeated_refresh_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "TOKEN_FILE", Path(directory)/"token.json"), \
                 patch.object(app, "DRIVE", "fixture-drive"), patch.object(app, "ROOT", "fixture-root"):
                app.atomic_token({"provider": "openlist", "refresh_token": "old",
                    "drive_id": "fixture-drive", "root_item_id": "fixture-root", "expires_at": 0})
                calls = []
                async def handler(request):
                    calls.append(request)
                    return httpx.Response(429, headers={"Retry-After": "120"})
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    media = app.Media(client)
                    for _ in range(5):
                        with self.assertRaises(app.Failure):
                            await media.token()
                self.assertEqual(len(calls), 1)
                self.assertGreater(json.loads(app.TOKEN_FILE.read_text())["retry_after"], time.time())

    async def test_cached_token_cannot_be_repurposed_for_another_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "TOKEN_FILE", Path(directory)/"token.json"):
                app.atomic_token({"provider": "openlist", "access_token": "fixture",
                    "drive_id": "other", "root_item_id": "other", "expires_at": time.time()+3600})
                async def handler(request):
                    self.fail("Mismatched credentials should not trigger any network request")
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    with self.assertRaises(app.Failure):
                        await app.Media(client).token()

if __name__ == "__main__":
    unittest.main()
