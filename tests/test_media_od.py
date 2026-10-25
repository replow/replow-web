"""OD/R2 policy and upload confirmation regressions. Never write production tables."""
import base64
import hashlib
import io
import os
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from app.services.media_storage import MediaStorageService, MediaStorageConfig, MediaError
from app.services.media_policy import backend_order
from app.services.quickxor import QuickXor
from app.services.onedrive_storage import OneDriveStorageError


class MediaODTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.execute.return_value.scalar.return_value = None
        self.s = MediaStorageService(self.db)
        self.s.repository = MagicMock()
        self.s.repository.media_storage_bytes.return_value = (0, 0, 0)
        self.s.repository.create_media.side_effect = lambda value: {"id": 1, **value}
        self.cfg = MediaStorageConfig(
            "a"*32, "fixture", "https://r2.example.invalid", "https://r2.example.invalid",
            "fixture", "fixture", 9_000_000_000, "/unused", "https://example.invalid",
            storage_mode="od_first", fallback_enabled=False)
        self.patches = [
            patch.object(self.s, "config", return_value=self.cfg),
            patch.object(self.s, "_upload_signing_secret", return_value="x"*64),
            patch.dict(os.environ, {"OD_BRIDGE_KEY": "fixture"*10}),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.data = b"OD file fixture\n"
        q = QuickXor(); q.update(self.data)
        self.q = q.base64()
        self.payload = {"filename": "fixture.txt", "category": "general",
                        "content_type": "text/plain", "byte_size": len(self.data),
                        "sha256": hashlib.sha256(self.data).hexdigest(), "quickxor": self.q}

    def prepare(self):
        with patch("app.services.media_storage.od_call",
                   return_value={"upload_url": "https://up.1drv.com/fixture", "chunk_size": 5242880}):
            return self.s.prepare_direct_upload(self.payload, 10000)

    def test_priorities_and_unavailable_fallback(self):
        self.assertEqual(backend_order("od_first",50,50,True,True), ["od","r2"])
        self.assertEqual(backend_order("r2_first",50,50,True,True), ["r2","od"])
        self.assertEqual(backend_order("od_first",50,50,False,True,False), [])
        self.assertEqual(backend_order("od_first",50,50,False,True,True), ["r2"])

    def test_balanced_weights_and_provider_availability(self):
        with patch("app.services.media_policy.secrets.randbelow", return_value=69):
            self.assertEqual(backend_order("balanced",70,30,True,True)[0], "od")
        with patch("app.services.media_policy.secrets.randbelow", return_value=70):
            self.assertEqual(backend_order("balanced",70,30,True,True)[0], "r2")
        self.assertEqual(backend_order("balanced",70,30,False,True), ["r2"])

    def test_quickxor_empty_and_streaming_match(self):
        empty = QuickXor()
        self.assertEqual(empty.base64(), "AAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        data = bytes(range(256))*7
        whole=QuickXor();whole.update(data)
        parts=QuickXor()
        for i in range(0,len(data),37):
            parts.update(data[i:i+37])
        self.assertEqual(parts.base64(), whole.base64())
        changed=QuickXor();changed.update(data+b"x")
        self.assertNotEqual(changed.base64(), whole.base64())

    def test_prepare_upload_selects_od_without_exposing_oauth(self):
        value = self.prepare()
        self.assertEqual(value["backend"], "od")
        self.assertNotIn("access_token", value)
        self.assertNotIn("refresh_token", value)

    def test_prepare_failure_falls_back_to_r2_only_when_enabled(self):
        self.s.config.return_value = replace(self.cfg, fallback_enabled=True)
        self.s._r2_client = MagicMock()
        self.s._r2_client.return_value.generate_presigned_url.return_value = "https://r2.example.invalid/upload"
        with patch("app.services.media_storage.od_call", side_effect=OneDriveStorageError("fixture")):
            result = self.s.prepare_direct_upload(self.payload,10000)
        self.assertEqual(result["backend"],"r2")

    def test_confirm_correct_od_returns_permanent_url(self):
        prepared=self.prepare()
        with patch("app.services.media_storage.od_call", return_value={
                "size":len(self.data),"hashes":{"quickXorHash":self.q},
                "header":base64.b64encode(self.data).decode()}):
            item=self.s.confirm_direct_upload(prepared["ticket"],10000)
        self.assertEqual(item["storage_backend"],"od")
        self.assertEqual(item["uploader_id"], 10000)
        self.assertTrue(item["public_url"].startswith("https://drive.4z.ink/media/site/"))
        self.assertNotIn("?", item["public_url"])

    def test_bad_checksum_rejects_and_removes_object(self):
        prepared=self.prepare()
        with patch("app.services.media_storage.od_call", return_value={
                "size":len(self.data),"hashes":{"quickXorHash":"bad"},
                "header":base64.b64encode(self.data).decode()}), \
             patch.object(self.s,"_remove_object") as remove:
            with self.assertRaises(MediaError):
                self.s.confirm_direct_upload(prepared["ticket"],10000)
            remove.assert_called_once()

    def test_wrong_actor_never_calls_cloud(self):
        prepared=self.prepare()
        with patch("app.services.media_storage.od_call") as call:
            with self.assertRaises(MediaError):
                self.s.confirm_direct_upload(prepared["ticket"],10001)
            call.assert_not_called()

    def test_soft_delete_uses_trash_without_cloud_deletion(self):
        from app.services.media_trash import MediaTrash
        with patch.object(MediaTrash, "item", return_value={"deleted_at": None}), \
             patch.object(MediaTrash, "references", return_value={"total": 0, "items": []}), \
             patch("app.services.media_storage.od_call") as cloud:
            self.assertTrue(self.s.delete(1))
        cloud.assert_not_called()
        self.s.repository.delete_media.assert_not_called()
        self.db.commit.assert_called_once()

    def test_od_purge_failure_keeps_database_record(self):
        self.s.repository.get_media.return_value={"storage_backend":"od","object_key":b"media/site/fixture.txt"}
        with patch("app.services.media_storage.od_call", side_effect=OneDriveStorageError("fixture")):
            with self.assertRaises(MediaError):
                self.s.purge(1)
        self.s.repository.delete_media.assert_not_called()

    def test_od_purge_success_removes_database_record(self):
        self.s.repository.get_media.return_value={"storage_backend":"od","object_key":b"media/site/fixture.txt"}
        self.s.repository.delete_media.return_value = True
        with patch("app.services.media_storage.od_call") as cloud:
            self.assertTrue(self.s.purge(1))
        cloud.assert_called_once_with("delete", key="media/site/fixture.txt")
        self.s.repository.delete_media.assert_called_once_with(1)

    def test_pdf_and_archive_allowed_but_executable_blocked(self):
        self.assertEqual(self.s._direct_content_type("application/pdf","fixture.pdf"),"application/pdf")
        self.assertTrue(self.s._check_signature("application/pdf",b"%PDF-1.7"))
        self.assertTrue(self.s._check_signature("application/zip",b"PK\x03\x04"))
        with self.assertRaises(MediaError):
            self.s._direct_content_type("application/x-msdownload","fixture.exe")


if __name__ == "__main__":
    unittest.main()
