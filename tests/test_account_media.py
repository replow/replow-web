"""Regression: normal accounts may only enumerate and mutate media they uploaded."""
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.account import router
from app.core.security import current_user
from app.db.session import get_db
from app.services.media_storage import MediaStorageService


class AccountMediaPermissionsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with self.engine.begin() as db:
            db.execute(text("""
                CREATE TABLE media_objects (
                    id INTEGER PRIMARY KEY, object_key TEXT, public_url TEXT,
                    original_name TEXT, mime_type TEXT, byte_size INTEGER, category TEXT,
                    storage_backend TEXT, sha256 TEXT, uploader_id INTEGER, created_at TEXT
                )
            """))
            db.execute(text("""
                INSERT INTO media_objects (id,object_key,public_url,original_name,mime_type,
                                           byte_size,category,storage_backend,sha256,uploader_id,created_at)
                VALUES (1,'media/article/one.png','https://cdn.example/one.png','one.png',
                        'image/png',100,'article','legacy','',10000,'2026-10-23'),
                       (2,'media/article/two.png','https://cdn.example/two.png','two.png',
                        'image/png',100,'article','legacy','',10001,'2026-10-23')
            """))
        app = FastAPI()
        app.include_router(router)
        def db_session():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_db] = db_session
        app.dependency_overrides[current_user] = lambda: {"uid": 10000}
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_list_is_scoped_before_pagination(self):
        reply = self.client.get("/account/media?limit=1")
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json()["total"], 1)
        self.assertEqual([x["id"] for x in reply.json()["items"]], [1])
        reply = self.client.get("/account/media?limit=1&offset=1")
        self.assertEqual(reply.json()["items"], [])

    def test_cross_account_rename_and_delete_are_forbidden(self):
        self.assertEqual(self.client.patch("/account/media/2", json={"original_name": "stolen.png"}).status_code, 404)
        self.assertEqual(self.client.delete("/account/media/2").status_code, 404)
        with Session(self.engine) as db:
            self.assertEqual(db.execute(text("SELECT COUNT(*) FROM media_objects WHERE id=2")).scalar_one(), 1)

    def test_owned_rename_extension_validation_and_delete(self):
        self.assertEqual(self.client.patch("/account/media/1", json={"original_name":"renamed.jpg"}).status_code, 422)
        self.assertEqual(self.client.patch("/account/media/1", json={"original_name":"../evil.png"}).status_code, 422)
        reply = self.client.patch("/account/media/1", json={"original_name":"renamed.png"})
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json()["data"]["original_name"], "renamed.png")
        with patch.object(MediaStorageService, "config", return_value=object()):
            self.assertEqual(self.client.delete("/account/media/1").status_code, 200)
        self.assertEqual(self.client.get("/account/media").json()["total"], 0)

    def test_unapproved_media_category_rejected(self):
        reply = self.client.post("/account/media/direct/prepare", json={"category":"music"})
        self.assertEqual(reply.status_code, 422)
        self.assertEqual(reply.json()["detail"], "media_invalid_category")


if __name__ == "__main__":
    unittest.main()
