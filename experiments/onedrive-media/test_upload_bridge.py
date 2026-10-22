import os
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app import Failure, safe_url
from upload_bridge import register_upload_routes


class BridgeSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = FastAPI()
        @self.api.exception_handler(Failure)
        async def fail(request, error):
            return JSONResponse({"error":error.code},status_code=error.status)
        register_upload_routes(self.api,"fixture-drive","fixture-root",safe_url,Failure)
        self.media = AsyncMock()
        self.media.token.return_value = "fixture-token"
        self.api.state.media = self.media
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.api,client=("127.0.0.1",1234)),
            base_url="http://localhost")
        self.env = patch.dict(os.environ, {"OD_BRIDGE_KEY":"x"*64})
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        await self.client.aclose()

    async def test_missing_and_wrong_secret_never_reach_graph(self):
        for headers in ({},{"Authorization":"Bearer wrong"}):
            r=await self.client.post("/internal/od",json={"action":"prepare"},headers=headers)
            self.assertEqual(r.status_code,404)
        self.media.token.assert_not_awaited()

    async def test_traversal_and_arbitrary_keys_rejected(self):
        for key in ("../private.txt","media/site/../../private","private.txt",
                    "media/site/"+"a"*32+".html/secret"):
            r=await self.client.post("/internal/od",json={"action":"prepare","key":key,"size":10},
                                    headers={"Authorization":"Bearer "+"x"*64})
            self.assertEqual(r.status_code,422)
        self.media.token.assert_not_awaited()

    async def test_oversize_session_rejected_before_cloud(self):
        r=await self.client.post("/internal/od",json={
            "action":"prepare","key":"media/site/"+"a"*32+".zip","size":101*1024*1024},
            headers={"Authorization":"Bearer "+"x"*64})
        self.assertEqual(r.status_code,413)
        self.media.token.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
