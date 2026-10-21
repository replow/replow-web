"""Fixed regression suite. All SQL writes use connection-local temporary tables.
Run with: .venv/bin/python -m unittest discover -s tests -p 'test_admin_security.py' -v
"""
import json
import sys
import os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.chdir(Path(__file__).resolve().parents[1])
import re
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import engine, get_db
from app.main import app
from app.core.security import decode_token
from app.core.request_context import request_context
from app.repositories.users import UserRepository
from app.repositories.sessions import SessionRepository
from app.repositories.audit import AuditRepository, user_changes, payload_fields
from app.services.sessions import SessionService
from app.services.auth import AuthService
from app.services.gallery import GalleryService

TABLES = ["users","user_uid_sequences","auth_sessions","admin_audit_logs",
          "media_objects","photo_albums","album_photos","dynamics"]


class AdminRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = engine.connect()
        for table in TABLES:
            ddl = cls.connection.exec_driver_sql(f"SHOW CREATE TABLE {table}").one()[1]
            ddl = ddl.replace("CREATE TABLE", "CREATE TEMPORARY TABLE", 1)
            ddl = "\n".join(line for line in ddl.splitlines() if "CONSTRAINT " not in line and "FULLTEXT " not in line)
            ddl = re.sub(r",\n\)", "\n)", ddl)
            cls.connection.exec_driver_sql(ddl)
        cls.connection.commit()
        cls.db = Session(bind=cls.connection, expire_on_commit=False)
        app.dependency_overrides[get_db] = lambda: cls.db
        cls.audit_patch = patch("app.api.audit_route.SessionLocal", lambda: cls.db)
        cls.audit_patch.start()
        cls.client = TestClient(app, base_url="https://admin.example.com")

    @classmethod
    def tearDownClass(cls):
        cls.client.close(); cls.audit_patch.stop(); app.dependency_overrides.clear()
        cls.db.close()
        for table in reversed(TABLES):
            cls.connection.exec_driver_sql(f"DROP TEMPORARY TABLE IF EXISTS {table}")
        cls.connection.close()

    def setUp(self):
        for table in reversed(TABLES):
            self.db.execute(text(f"DELETE FROM {table}"))
        self.db.execute(text("INSERT INTO user_uid_sequences VALUES (1,10001)"))
        for uid, name, role in [(10000,"fixture_admin","admin"),(10001,"fixture_user","user")]:
            self.db.execute(text("INSERT INTO users "
                "(uid,username,email,password_hash,display_name,role,status,session_version,created_at,updated_at) "
                "VALUES (:uid,:name,:email,'!password-unset!',:name,:role,'active',0,NOW(),NOW())"),
                {"uid":uid,"name":name,"email":name+"@example.invalid","role":role})
        self.db.commit()
        self.client.cookies.clear()
        self.actor = UserRepository(self.db).get_by_id(10000)
        self.access,self.refresh,_ = SessionService(self.db).issue(self.actor, new_session=True)
        self.headers = {"Authorization":"Bearer "+self.access}

    def put(self,uid,payload):
        return self.client.put(f"/v1/admin/users/{uid}",json=payload,headers=self.headers)

    def test_media_upload_categories_match_database_enum(self):
        from app.services.media_storage import MediaStorageService, MediaStorageConfig
        cfg = MediaStorageConfig("fixture", "fixture", "https://example.invalid",
            "https://example.invalid", "fixture", "fixture", 9000000000,
            "/unused", "https://example.invalid")
        expected = {"general": "site", "wallpaper": "site", "site-avatar": "site",
            "article-cover": "article", "friend-avatar": "friend",
            "site": "site", "avatar": "avatar", "article": "article",
            "music": "music", "friend": "friend"}
        with patch.object(MediaStorageService, "config", return_value=cfg), \
             patch.object(MediaStorageService, "_put_r2") as put:
            for value, stored in expected.items():
                with self.subTest(category=value):
                    response = self.client.post("/v1/admin/media/upload",
                        headers=self.headers, data={"category": value},
                        files={"file": ("fixture.png", b"fixture image", "image/png")})
                    self.assertEqual(response.status_code, 200, response.text)
                    item = response.json()["data"]
                    self.assertEqual(item["category"], stored)
                    self.assertEqual(item["storage_backend"], "r2")
                    self.assertTrue(item["object_key"].startswith("media/"+stored+"/"))
            self.assertEqual(put.call_count, len(expected))
            # Omitted category exercises the current frontend/API default.
            response = self.client.post("/v1/admin/media/upload", headers=self.headers,
                files={"file": ("fixture.png", b"fixture image", "image/png")})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["data"]["category"], "site")

    def test_media_delete_decodes_legacy_binary_object_key(self):
        from unittest.mock import MagicMock
        from app.services.media_storage import MediaStorageService, MediaStorageConfig
        from app.repositories.admin import AdminRepository
        cfg = MediaStorageConfig("fixture", "fixture", "https://example.invalid",
            "https://example.invalid", "fixture", "fixture", 9000000000,
            "/unused", "https://example.invalid")
        key = "media/site/fixture.png"
        item = AdminRepository(self.db).create_media({
            "object_key": key, "public_url": "https://example.invalid/"+key,
            "original_name": "fixture.png", "mime_type": "image/png", "byte_size": 1,
            "category": "site", "storage_backend": "r2", "sha256": "fixture"})
        self.assertIsInstance(item["object_key"], bytes)
        client = MagicMock()
        with patch.object(MediaStorageService, "config", return_value=cfg), \
             patch.object(MediaStorageService, "_r2_client", return_value=client):
            self.assertTrue(MediaStorageService(self.db).delete(item["id"]))
        client.delete_object.assert_called_once_with(Bucket="fixture", Key=key)
        self.assertIsNone(AdminRepository(self.db).get_media(item["id"]))

    def test_media_invalid_category_rejected_before_storage_write(self):
        from app.services.media_storage import MediaStorageService
        with patch.object(MediaStorageService, "_stage_upload") as stage, \
             patch.object(MediaStorageService, "_put_r2") as put:
            response = self.client.post("/v1/admin/media/upload", headers=self.headers,
                data={"category": "unknown-category"},
                files={"file": ("fixture.png", b"fixture image", "image/png")})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"], "media_invalid_category")
            stage.assert_not_called()
            put.assert_not_called()

    def test_dynamic_crud_draft_privacy_audit_and_nocache(self):
        payload = {"content": "Fixture **dynamic**", "images": [{"src":"https://example.invalid/image.png","alt":"Fixture"}],
            "location":"Fixture location", "pinned":False,"is_published":False,
            "published_at":"2026-01-01T08:00:00+08:00"}
        response = self.client.post("/v1/admin/dynamics",headers=self.headers,json=payload)
        self.assertEqual(response.status_code,200,response.text)
        item=response.json()["data"];mid=item["id"]
        self.assertEqual(item["published_at"],"2026-01-01T00:00:00Z")
        public=self.client.get("/v1/public/dynamics")
        self.assertEqual(public.status_code,200)
        self.assertEqual(public.json()["total"],0)
        self.assertIn("no-store",public.headers["cache-control"])
        self.assertEqual(self.client.get("/v1/public/dynamics/"+str(mid)).status_code,404)
        self.assertEqual(self.client.put("/v1/admin/dynamics/"+str(mid),headers=self.headers,
            json={"is_published":True,"pinned":True}).status_code,200)
        public=self.client.get("/v1/public/dynamics").json()
        self.assertEqual(public["total"],1)
        self.assertEqual(public["items"][0]["content"],payload["content"])
        self.assertEqual(public["items"][0]["images"],payload["images"])
        self.assertNotIn("legacy_id",public["items"][0])
        log=AuditRepository(self.db).list(1,0)["items"][0]
        self.assertEqual(log["resource"],"dynamics")
        self.assertEqual(log["target_id"],str(mid))
        self.assertEqual(self.client.put("/v1/admin/dynamics/"+str(mid),headers=self.headers,
            json={"is_published":False}).status_code,200)
        self.assertEqual(self.client.get("/v1/public/dynamics").json()["total"],0)
        self.assertEqual(self.client.delete("/v1/admin/dynamics/"+str(mid),headers=self.headers).status_code,200)
        self.assertEqual(self.client.get("/v1/admin/dynamics/"+str(mid),headers=self.headers).status_code,404)

    def test_dynamic_validation_authorization_and_schedule(self):
        for data in [{"content":""},{"content":"fixture","images":[{"src":"javascript:alert(1)"}]},
                     {"content":"fixture","images":[{"src":"https://user:pass@example.invalid/a.png"}]},
                     {"content":"fixture","images":["https://example.invalid/a.png"]*10},
                     {"content":"fixture","published_at":"2026-01-01T10:00:00"},
                     {"content":"fixture","is_published":"false"}]:
            response=self.client.post("/v1/admin/dynamics",headers=self.headers,json=data)
            self.assertEqual(response.status_code,422,response.text)
        from app.services.dynamics import DynamicsService
        service=DynamicsService(self.db)
        service.save({"content":"future fixture","is_published":True,"published_at":"2099-01-01T00:00:00Z"})
        one=service.save({"content":"normal fixture","is_published":True,"published_at":"2026-01-02T00:00:00Z"})
        two=service.save({"content":"older pinned fixture","is_published":True,"pinned":True,"published_at":"2026-01-01T00:00:00Z"})
        self.assertEqual([r["id"] for r in service.listing(public=True)["items"]],[two["id"],one["id"]])
        ordinary=SessionService(self.db).issue(UserRepository(self.db).get_by_id(10001),new_session=True)[0]
        self.assertEqual(self.client.get("/v1/admin/dynamics",headers={"Authorization":"Bearer "+ordinary}).status_code,403)

    def test_created_user_audit_contains_allocated_uid(self):
        response=self.client.post("/v1/admin/users",headers=self.headers,json={
            "username":"fixture_new","email":"fixture_new@example.invalid","role":"user","status":"active"})
        self.assertEqual(response.status_code,200)
        uid=response.json()["data"]["uid"]
        log=AuditRepository(self.db).list(1,0)["items"][0]
        self.assertEqual(log["target_id"],str(uid))

    def test_other_save_never_switches_identity(self):
        r=self.put(10001,{"display_name":"Fixture changed"})
        self.assertEqual(r.status_code,200);self.assertNotIn("session",r.json())
        self.assertNotIn("set-cookie",r.headers)
        self.assertEqual(self.client.get("/v1/auth/me",headers=self.headers).json()["data"]["uid"],10000)

    def test_other_password_only_revokes_target(self):
        r=self.put(10001,{"password":"Fixture-password-only9","confirm_sensitive":True})
        self.assertEqual(r.status_code,200);self.assertNotIn("session",r.json())
        self.assertEqual(UserRepository(self.db).get_by_id(10001)["session_version"],1)
        self.assertEqual(self.client.get("/v1/admin/dashboard",headers=self.headers).status_code,200)

    def test_sensitive_changes_require_confirmation(self):
        for data in [{"role":"admin"},{"status":"disabled"},{"password":"Fixture-password-only9"}]:
            self.assertEqual(self.put(10001,data).status_code,422)
        self.assertEqual(self.put(10001,{"uid":"10020","confirm_sensitive":True}).status_code,422)
        self.assertEqual(UserRepository(self.db).get_by_id(10001)["role"],"user")

    def test_self_edit_keeps_session_and_cookie(self):
        r=self.put(10000,{"display_name":"Fixture self"})
        self.assertEqual(r.status_code,200)
        session=r.json()["session"]
        self.assertEqual(decode_token(session["accessToken"])["sub"],"10000")
        self.assertEqual(decode_token(session["accessToken"])["sid"],decode_token(self.access)["sid"])
        self.assertIn("HttpOnly",r.headers["set-cookie"])

    def test_self_password_survives_refresh_and_revokes_others(self):
        old_other=SessionService(self.db).issue(self.actor,new_session=True)[1]
        r=self.put(10000,{"password":"Fixture-password-only9","confirm_sensitive":True})
        self.assertEqual(r.status_code,200)
        session=r.json()["session"]
        self.assertEqual(decode_token(session["accessToken"])["sv"],1)
        self.assertTrue(AuthService(self.db).refresh(session["refreshToken"])[0])
        self.assertFalse(AuthService(self.db).refresh(old_other)[0])

    def test_uid_override_is_explicit_and_counter_moves_forward(self):
        r=self.put(10001,{"uid":"10020","allow_uid_override":True,"confirm_sensitive":True})
        self.assertEqual(r.status_code,200);self.assertNotIn("session",r.json())
        self.assertEqual(self.db.execute(text("SELECT last_uid FROM user_uid_sequences WHERE id=1")).scalar(),10020)

    def test_self_access_cannot_be_removed(self):
        for data in [{"role":"user"},{"status":"disabled"}]:
            self.assertEqual(self.put(10000,{**data,"confirm_sensitive":True}).status_code,400)

    def test_delete_requires_confirmation_and_cannot_delete_self(self):
        self.assertEqual(self.client.delete("/v1/admin/users/10001",headers=self.headers).status_code,422)
        self.assertEqual(self.client.delete("/v1/admin/users/10000?confirmed=true",headers=self.headers).status_code,400)

    def test_audit_redacts_password_and_records_failure(self):
        self.put(10001,{"password":"Never-store-this-secret9","confirm_sensitive":True})
        self.put(10001,{"role":"admin"})
        logs=AuditRepository(self.db).list(20,0)["items"]
        self.assertEqual(len(logs),2)
        encoded=json.dumps(logs,default=str)
        self.assertNotIn("Never-store-this-secret9",encoded)
        self.assertIn("password",encoded)
        self.assertEqual({x["status_code"] for x in logs},{200,422})

    def test_revoke_single_device_blocks_access_and_refresh(self):
        other_access,other_refresh,_=SessionService(self.db).issue(self.actor,new_session=True)
        sid=decode_token(other_access)["sid"]
        r=self.client.delete("/v1/auth/sessions/"+sid,headers=self.headers)
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get("/v1/auth/me",headers={"Authorization":"Bearer "+other_access}).status_code,401)
        self.assertFalse(AuthService(self.db).refresh(other_refresh)[0])
        self.assertEqual(self.client.get("/v1/auth/me",headers=self.headers).status_code,200)

    def test_cannot_revoke_someone_elses_device(self):
        target=UserRepository(self.db).get_by_id(10001)
        target_token=SessionService(self.db).issue(target,new_session=True)[0]
        sid=decode_token(target_token)["sid"]
        self.assertEqual(self.client.delete("/v1/auth/sessions/"+sid,headers=self.headers).status_code,404)

    def test_revoke_others_preserves_current_and_blocks_legacy(self):
        other=SessionService(self.db).issue(self.actor,new_session=True)[0]
        from app.core.security import create_access_token
        legacy=create_access_token(10000,"admin",0)[0]
        r=self.client.post("/v1/auth/sessions/revoke-others",json={"confirmed":True},headers=self.headers)
        self.assertEqual(r.status_code,200)
        current=r.json()["data"]["accessToken"]
        self.assertEqual(self.client.get("/v1/auth/me",headers={"Authorization":"Bearer "+current}).status_code,200)
        for token in [other,legacy]:
            self.assertEqual(self.client.get("/v1/auth/me",headers={"Authorization":"Bearer "+token}).status_code,401)

    def test_unprivileged_user_cannot_edit_admin(self):
        target=UserRepository(self.db).get_by_id(10001)
        token=SessionService(self.db).issue(target,new_session=True)[0]
        self.assertEqual(self.client.put("/v1/admin/users/10000",json={},headers={"Authorization":"Bearer "+token}).status_code,403)

    def test_legacy_refresh_is_adopted_and_keeps_device_identity(self):
        from app.core.security import create_refresh_token
        legacy=create_refresh_token(10000,"admin",0)
        user,access,refresh,_=AuthService(self.db).refresh(legacy)
        self.assertTrue(user)
        sid=decode_token(access)["sid"]
        self.assertEqual(decode_token(refresh,"refresh")["sid"],sid)
        self.assertEqual(decode_token(AuthService(self.db).refresh(refresh)[1])["sid"],sid)

    def test_legacy_access_without_version_is_revoked_too(self):
        from app.core.security import _create_token
        legacy=_create_token("10000","admin","access",timedelta(minutes=10))
        response=self.client.post("/v1/auth/sessions/revoke-others",json={"confirmed":True},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get("/v1/auth/me",headers={"Authorization":"Bearer "+legacy}).status_code,401)

    def test_expired_device_cannot_access_or_refresh(self):
        sid=decode_token(self.access)["sid"]
        self.db.execute(text("UPDATE auth_sessions SET expires_at='2000-01-01' WHERE id=:sid"),{"sid":sid})
        self.db.commit()
        self.assertEqual(self.client.get("/v1/auth/me",headers=self.headers).status_code,401)
        self.assertFalse(AuthService(self.db).refresh(self.refresh)[0])

    def test_target_role_change_revokes_target_without_switching_actor(self):
        target=UserRepository(self.db).get_by_id(10001)
        target_access,target_refresh,_=SessionService(self.db).issue(target,new_session=True)
        result=self.put(10001,{"role":"admin","confirm_sensitive":True})
        self.assertEqual(result.status_code,200);self.assertNotIn("session",result.json())
        self.assertEqual(self.client.get("/v1/auth/me",headers={"Authorization":"Bearer "+target_access}).status_code,401)
        self.assertFalse(AuthService(self.db).refresh(target_refresh)[0])
        self.assertEqual(self.client.get("/v1/admin/dashboard",headers=self.headers).status_code,200)

    def test_public_gallery_success_and_error_responses_are_not_cached(self):
        for path in ["/v1/public/albums","/v1/public/albums/999"]:
            response=self.client.get(path)
            self.assertIn("no-store",response.headers.get("cache-control",""))
            self.assertEqual(response.headers.get("cloudflare-cdn-cache-control"),"no-store")

    def test_album_drafts_private_and_photo_order_saved(self):
        service=GalleryService(self.db)
        album=service.save({"title":"Fixture album","is_published":False})
        self.assertEqual(service.albums(public=True),[])
        with self.assertRaises(HTTPException):service.album(album["id"],public=True)
        for mid in [1,2]:
            self.db.execute(text("INSERT INTO media_objects "
                "(id,object_key,public_url,original_name,mime_type,byte_size,category,storage_backend,created_at) "
                "VALUES (:id,:key,:url,:key,'image/jpeg',1,'article','local',NOW())"),
                {"id":mid,"key":f"fixture{mid}.jpg","url":f"https://example.invalid/{mid}.jpg"})
        self.db.commit()
        service.save_photos(album["id"],[{"media_id":2,"caption":"Second first"},{"media_id":1}])
        service.save({"title":"Fixture album","is_published":True},album["id"])
        self.assertEqual([p["media_id"] for p in service.album(album["id"],public=True)["photos"]],[2,1])
        self.assertEqual(len(service.albums(public=True)),1)
        with self.assertRaises(HTTPException):
            service.save_photos(album["id"],[{"media_id":1},{"media_id":1}])
        self.assertEqual(len(service.album(album["id"])["photos"]),2)

    def test_album_rejects_invalid_sources_and_unauthorized_access(self):
        service=GalleryService(self.db)
        with self.assertRaises(HTTPException):service.save({"title":"Fixture","cover_url":"javascript:alert(1)"})
        album=service.save({"title":"Fixture"})
        with self.assertRaises(HTTPException):service.save_photos(album["id"],[{"media_id":999}])
        self.assertEqual(self.client.get("/v1/public/albums/"+str(album["id"])).status_code,404)


if __name__=="__main__":
    unittest.main()
