"""Production-compatible regression checks using connection-local temporary tables."""
import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from fastapi import HTTPException
from app.db.session import engine, get_db
from app.main import app
from app.core.moderation import enforce, restrictions
from app.core.email_policy import allowed, normalize_domains, DEFAULT_DOMAINS
from app.core.audit_details import sanitize
from app.core.security import password_hasher
from app.repositories.users import UserRepository
from app.services.sessions import SessionService
from app.services.account import AccountService, AccountError
from app.services.auth import AuthService
from app.services.moderation import deliver_pending as drain_outbox


class ModerationTest(unittest.TestCase):
    tables = ["users", "user_uid_sequences", "auth_sessions", "oauth_tokens", "oauth_authorization_codes",
              "admin_audit_logs", "site_settings", "settings", "secure_settings"]

    @classmethod
    def setUpClass(cls):
        cls.connection = engine.connect()
        for table in cls.tables:
            ddl = cls.connection.exec_driver_sql(f"SHOW CREATE TABLE {table}").one()[1]
            ddl = ddl.replace("CREATE TABLE", "CREATE TEMPORARY TABLE", 1)
            ddl = "\n".join(line for line in ddl.splitlines() if "CONSTRAINT " not in line and "FULLTEXT " not in line)
            ddl = re.sub(r",\n\)", "\n)", ddl)
            cls.connection.exec_driver_sql(ddl)
        columns = {r[0] for r in cls.connection.exec_driver_sql("SHOW COLUMNS FROM users")}
        for kind in ("ban", "mute", "publish"):
            if kind + "_started_at" not in columns:
                cls.connection.exec_driver_sql(f"ALTER TABLE users ADD {kind}_started_at DATETIME NULL, ADD {kind}_until DATETIME NULL, ADD {kind}_reason VARCHAR(1000) NULL")
        columns = {r[0] for r in cls.connection.exec_driver_sql("SHOW COLUMNS FROM admin_audit_logs")}
        if "request_details" not in columns:
            cls.connection.exec_driver_sql("ALTER TABLE admin_audit_logs ADD request_details LONGTEXT NULL, ADD target_name VARCHAR(500) NULL")
        cls.connection.exec_driver_sql("CREATE TEMPORARY TABLE moderation_mail_outbox (id BIGINT PRIMARY KEY AUTO_INCREMENT, recipient VARCHAR(254),subject VARCHAR(200),body TEXT,attempts INT DEFAULT 0,created_at DATETIME,sent_at DATETIME,next_attempt_at DATETIME)")
        cls.connection.commit()
        cls.db = Session(bind=cls.connection, expire_on_commit=False)
        app.dependency_overrides[get_db] = lambda: cls.db
        cls.audit = patch("app.api.audit_route.SessionLocal", lambda: cls.db)
        cls.mail = patch("app.services.moderation.deliver_pending")
        cls.audit.start(); cls.mail.start()
        cls.client = TestClient(app, base_url="https://admin.replow.org")

    @classmethod
    def tearDownClass(cls):
        cls.client.close(); cls.audit.stop(); cls.mail.stop(); app.dependency_overrides.clear()
        cls.db.close()
        for table in ["moderation_mail_outbox"] + list(reversed(cls.tables)):
            cls.connection.exec_driver_sql(f"DROP TEMPORARY TABLE IF EXISTS {table}")
        cls.connection.close()

    def setUp(self):
        self.db.rollback()
        for table in ["moderation_mail_outbox"] + list(reversed(self.tables)):
            self.db.execute(text(f"DELETE FROM {table}"))
        self.db.execute(text("INSERT INTO user_uid_sequences VALUES (1,10001)"))
        for uid, name, role in [(10000, "fixture_admin", "admin"), (10001, "fixture_user", "user")]:
            self.db.execute(text("INSERT INTO users (uid,username,email,password_hash,display_name,role,status,session_version,created_at,updated_at) VALUES (:uid,:name,:email,:password,:name,:role,'active',0,NOW(),NOW())"),
                {"uid": uid, "name": name, "email": name+"@example.invalid", "role": role, "password": password_hasher.hash("Fixture123!")})
        self.db.commit(); self.client.cookies.clear()
        self.admin = UserRepository(self.db).get_by_id(10000)
        self.user = UserRepository(self.db).get_by_id(10001)
        self.access, _, _ = SessionService(self.db).issue(self.admin, new_session=True)
        self.user_access, self.user_refresh, _ = SessionService(self.db).issue(self.user, new_session=True)
        self.headers = {"Authorization": "Bearer " + self.access}
        self.user_headers = {"Authorization": "Bearer " + self.user_access}

    def moderate(self, kind, enabled=True, uid=10001, **extra):
        return self.client.put(f"/v1/admin/users/{uid}/restrictions", headers=self.headers,
            json={"kind": kind, "enabled": enabled, "reason": "Fixture moderation reason", "until": (datetime.utcnow()+timedelta(days=1)).isoformat()+"Z", "confirmed": True, **extra})

    def test_ban_revokes_access_refresh_password_and_code_sessions(self):
        self.assertEqual(self.moderate("ban").status_code, 200)
        for url in ["/v1/auth/me", "/v1/account/restrictions"]:
            r = self.client.get(url, headers=self.user_headers)
            self.assertEqual(r.status_code, 401, r.text)
            for label in ["账号封禁", "开始日期", "解封/解除日期", "Fixture moderation reason"]:
                self.assertIn(label, r.json()["detail"])
            self.assertIn("Max-Age=0", r.headers.get("set-cookie", ""))
        for url, payload in [("/v1/auth/refresh", {"refreshToken": self.user_refresh}),
                             ("/v1/auth/login", {"username": "fixture_user", "password": "Fixture123!"})]:
            self.assertEqual(self.client.post(url, json=payload).status_code, 401)
        with patch.object(AccountService, "_verify_code"):
            with self.assertRaises(HTTPException):
                AccountService(self.db).login_by_code(email="fixture_user@example.invalid", code="123456")
        self.assertEqual(self.db.execute(text("SELECT COUNT(*) FROM auth_sessions WHERE user_uid=10001 AND revoked_at IS NULL")).scalar(), 0)
        body = self.db.execute(text("SELECT body FROM moderation_mail_outbox LIMIT 1")).scalar()
        self.assertIn("Fixture moderation reason", body); self.assertIn("北京时间", body)
        self.assertEqual(self.moderate("ban", False).status_code, 200)
        self.assertEqual(self.client.get("/v1/auth/me", headers=self.user_headers).status_code, 401)
        self.assertIsNotNone(AuthService(self.db).authenticate("fixture_user", "Fixture123!"))

    def test_mute_and_publish_are_independent_keep_session(self):
        self.assertEqual(self.moderate("mute").status_code, 200)
        self.assertEqual(self.client.get("/v1/auth/me", headers=self.user_headers).status_code, 200)
        r = self.client.post("/v1/account/comments", headers=self.user_headers, json={"article_id": 1,"body_markdown": "fixture comment"})
        self.assertEqual(r.status_code, 403, r.text); self.assertIn("禁言", r.text)
        self.assertEqual(self.moderate("publish").status_code, 200)
        for method, url in [("post", "/v1/account/articles"), ("put", "/v1/account/articles/1"), ("post", "/v1/account/articles/1/versions/1/restore")]:
            r = getattr(self.client, method)(url, headers=self.user_headers, json={})
            self.assertEqual(r.status_code, 403, r.text); self.assertIn("禁止发布文章", r.text)
        r = self.client.get("/v1/account/restrictions", headers=self.user_headers)
        self.assertEqual({i["kind"] for i in r.json()["items"]}, {"mute", "publish"})
        self.assertEqual(self.db.execute(text("SELECT session_version FROM users WHERE uid=10001")).scalar(), 0)
        self.assertEqual(self.moderate("mute", False).status_code, 200)
        self.assertEqual(len(self.client.get("/v1/account/restrictions", headers=self.user_headers).json()["items"]), 1)

    def test_authorization_validation_expiry_permanent(self):
        r = self.client.put("/v1/admin/users/10000/restrictions", headers=self.user_headers, json={})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.moderate("ban", uid=10000).status_code, 409)
        self.assertEqual(self.moderate("ban", reason="").status_code, 422)
        self.assertEqual(self.moderate("ban", until="2020-01-01T00:00:00Z").status_code, 422)
        self.assertEqual(self.moderate("ban", until=None).status_code, 200)
        self.assertIsNone(restrictions(UserRepository(self.db).get_by_id(10001))[0]["until"])
        self.db.execute(text("UPDATE users SET ban_until=:past WHERE uid=10001"), {"past":datetime.utcnow()-timedelta(seconds=1)})
        self.db.commit()
        self.assertEqual(restrictions(UserRepository(self.db).get_by_id(10001)), [])
        self.assertIsNotNone(AuthService(self.db).authenticate("fixture_user", "Fixture123!"))

    def test_registration_all_creation_paths_and_existing_login(self):
        service = AccountService(self.db)
        self.assertIn("qq.com", service.registration_domains())
        for email in ["x@evilqq.com", "x@qq.com.evil.org", "x@sub.qq.com"]:
            self.assertFalse(allowed(email, DEFAULT_DOMAINS))
        for purpose in ["register", "login", "friend_link"]:
            with self.assertRaises(AccountError) as caught:
                service.request_code(email="new@example.invalid", purpose=purpose, ip="127.0.0.1", username="fixture_new")
            self.assertEqual(caught.exception.detail, "registration_email_not_allowed")
        with self.assertRaises(AccountError):
            service.register_by_code(email="new@example.invalid", username="fixture_new", code="123456", display_name="Fixture")
        with self.assertRaises(AccountError):
            service._create_code_login_user("new@example.invalid")
        with patch.object(AccountService, "_verify_code"):
            self.assertTrue(service.login_by_code(email="fixture_user@example.invalid", code="123456")["success"])
        self.assertEqual(normalize_domains("@QQ.COM, gmail.com\noutlook.com,qq.com"), ["qq.com","gmail.com","outlook.com"])
        with self.assertRaises(ValueError): normalize_domains([])

    def test_audit_readable_request_and_redaction(self):
        self.moderate("mute")
        result = self.client.get("/v1/admin/audit-logs", headers=self.headers).json()["items"][0]
        self.assertEqual(result["description"], "调整用户限制")
        self.assertIn("fixture_user", result["target_name"])
        self.assertEqual(result["request_details"]["actor"]["username"], "fixture_admin")
        self.assertEqual(result["request_details"]["payload"]["reason"], "Fixture moderation reason")
        value = sanitize({"mail":{"smtp_password":"fixture-secret"},"api_key":"key", "reason":"fixture", "nested":[{"refreshToken":"token"}]})
        self.assertNotIn("fixture-secret", str(value)); self.assertNotIn("'token'", str(value))
        self.assertEqual(value["reason"], "fixture")

    def test_notification_is_retried_then_marked_sent(self):
        self.assertEqual(self.moderate("mute").status_code, 200)
        with patch("app.db.session.SessionLocal", lambda: self.db), patch("app.services.mail.MailService.send", side_effect=RuntimeError("fixture outage")):
            drain_outbox()
        row = self.db.execute(text("SELECT * FROM moderation_mail_outbox LIMIT 1")).mappings().one()
        self.assertIsNone(row["sent_at"]); self.assertEqual(row["attempts"], 1)
        self.db.execute(text("UPDATE moderation_mail_outbox SET next_attempt_at=:now"), {"now": datetime.utcnow()-timedelta(seconds=1)})
        self.db.commit()
        with patch("app.db.session.SessionLocal", lambda: self.db), patch("app.services.mail.MailService.send") as send:
            drain_outbox()
        self.assertEqual(send.call_count, 1)
        row = self.db.execute(text("SELECT * FROM moderation_mail_outbox LIMIT 1")).mappings().one()
        self.assertIsNotNone(row["sent_at"]); self.assertEqual(row["attempts"], 2)


if __name__ == "__main__": unittest.main()
