from datetime import datetime, timedelta
import hashlib
import secrets
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.repositories.account import AccountRepository
from app.services.account import AccountError, AccountService, _clean_email


FRIEND_LINK_VERIFY_BASE = "https://account.example.com/?friend_verify="
FRIEND_LINK_VERIFY_SECONDS = 24 * 60 * 60


class PortalService:
    def __init__(self, db: Session):
        self.db = db
        self.account = AccountService(db)
        self.repository = AccountRepository(db)

    def _send_authenticated_code(
        self,
        *,
        user: dict[str, Any],
        email: str,
        purpose: str,
        ip: Optional[str],
    ) -> dict[str, Any]:
        email = _clean_email(email)
        user_id = int(user["uid"])
        if purpose == "email_change":
            if self.account.users.email_exists(email, exclude_user_id=user_id):
                raise AccountError("email_already_exists", 409)
        else:
            raise AccountError("invalid_verification_purpose", 422)

        if not self.account.users.check_rate_limit(
            f"{purpose}_email",
            self.account._identity_hash("email", email),
            limit=5,
            window_seconds=3600,
        ) or not self.account.users.check_rate_limit(
            f"{purpose}_ip",
            self.account._identity_hash("ip", ip or "unknown"),
            limit=20,
            window_seconds=3600,
        ):
            raise AccountError("too_many_verification_requests", 429)

        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        self.account.users.create_verification(
            email=email,
            username=str(user.get("username") or ""),
            purpose=purpose,
            code_hash=self.account._code_hash(email, purpose, code),
            expires_at=expires_at,
            requested_ip=ip,
        )
        try:
            self.account.mail.send_verification_code(
                recipient=email, code=code, purpose=purpose
            )
        except Exception as error:
            self.account.users.delete_verification(email, purpose)
            if isinstance(error, RuntimeError) and str(error) == "mail_not_configured":
                raise AccountError("mail_not_configured", 503) from error
            raise AccountError("mail_delivery_failed", 502) from error

        return {"success": True, "accepted": True, "expires_in": 600}

    def request_email_change_code(
        self,
        *,
        user: dict[str, Any],
        new_email: str,
        ip: Optional[str],
    ) -> dict[str, Any]:
        email = _clean_email(new_email)
        if email == str(user.get("email") or "").strip().lower():
            raise AccountError("email_unchanged", 422)
        return self._send_authenticated_code(
            user=user, email=email, purpose="email_change", ip=ip
        )

    def confirm_email_change(
        self,
        *,
        user: dict[str, Any],
        new_email: str,
        code: str,
    ) -> dict[str, Any]:
        email = _clean_email(new_email)
        if self.account.users.email_exists(email, exclude_user_id=int(user["uid"])):
            raise AccountError("email_already_exists", 409)
        self.account._verify_code(email, "email_change", code)
        profile = self.repository.update_email(int(user["uid"]), email)
        if not profile:
            raise AccountError("profile_update_failed", 500)
        return profile

    def request_friend_link_verification(
        self,
        *,
        user: dict[str, Any],
        application_id: int,
        ip: Optional[str],
    ) -> dict[str, Any]:
        user_id = int(user["uid"])
        email = _clean_email(str(user.get("email") or ""))
        application = self.repository.get_friend_application(user_id, application_id)
        if not application:
            raise AccountError("friend_application_not_found", 404)
        if str(application.get("status")) == "approved":
            return {"success": True, "approved": True}
        if str(application.get("status")) != "pending_email":
            raise AccountError("friend_application_not_pending", 409)

        if not self.account.users.check_rate_limit(
            "friend_link_verify_email",
            self.account._identity_hash("email", email),
            limit=5,
            window_seconds=3600,
        ) or not self.account.users.check_rate_limit(
            "friend_link_verify_ip",
            self.account._identity_hash("ip", ip or "unknown"),
            limit=20,
            window_seconds=3600,
        ):
            raise AccountError("too_many_verification_requests", 429)

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = datetime.utcnow() + timedelta(seconds=FRIEND_LINK_VERIFY_SECONDS)
        if not self.repository.set_friend_verification(
            user_id,
            application_id,
            token_hash=token_hash,
            expires_at=expires_at,
        ):
            raise AccountError("friend_application_not_pending", 409)

        verification_url = FRIEND_LINK_VERIFY_BASE + token
        try:
            self.account.mail.send_friend_link_verification(
                recipient=email,
                site_name=str(application.get("site_name") or ""),
                verification_url=verification_url,
                expires_hours=24,
            )
        except Exception as error:
            self.repository.set_friend_verification(
                user_id,
                application_id,
                token_hash=None,
                expires_at=None,
            )
            if isinstance(error, RuntimeError) and str(error) == "mail_not_configured":
                raise AccountError("mail_not_configured", 503) from error
            raise AccountError("mail_delivery_failed", 502) from error

        return {
            "success": True,
            "accepted": True,
            "expires_in": FRIEND_LINK_VERIFY_SECONDS,
        }

    def confirm_friend_link_token(self, *, token: str) -> dict[str, Any]:
        token = str(token or "").strip()
        if len(token) < 32 or len(token) > 256:
            raise AccountError("friend_verification_invalid", 422)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        application = self.repository.get_friend_application_by_token(token_hash)
        if not application:
            raise AccountError("friend_verification_invalid_or_used", 404)
        if str(application.get("status")) != "pending_email":
            raise AccountError("friend_application_not_pending", 409)

        expires_at = application.get("verification_expires_at")
        if not expires_at or expires_at <= datetime.utcnow():
            self.repository.set_friend_verification(
                int(application["user_id"]),
                int(application["id"]),
                token_hash=None,
                expires_at=None,
            )
            raise AccountError("friend_verification_expired", 410)

        try:
            return self.repository.approve_friend_application(
                int(application["user_id"]), int(application["id"])
            )
        except ValueError as error:
            detail = str(error)
            status_code = 404 if detail == "friend_application_not_found" else 409
            raise AccountError(detail, status_code) from error

    # ── 主站友链页的内嵌申请（无需先登录）────────────────────────────────
    # 流程：发验证码 → 填站点资料 + 验证码提交 → 该邮箱没有账号就自动建号
    #      → 建申请 → 自动通过并上线。
    # 与账号中心里那条流程的区别只是"门"不同：那边要求先登录、再用邮件里的
    # 认证链接；这边面向匿名访客，用 6 位验证码，并顺带把账号建出来。

    def send_friend_link_application_code(
        self, *, email: str, ip: Optional[str]
    ) -> dict[str, Any]:
        """给任意邮箱发友链申请的验证码（复用统一验证码通道与限流）。"""
        return self.account.request_code(email=email, purpose="friend_link", ip=ip)

    def apply_friend_link(
        self,
        *,
        email: str,
        code: str,
        site_name: str,
        website_url: str,
        avatar_url: str,
        language: str,
        rss_url: str,
        description: str,
        applicant_note: str,
        ip: Optional[str],
    ) -> dict[str, Any]:
        email = _clean_email(email)
        if not code or len(code.strip()) != 6:
            raise AccountError("verification_code_invalid", 422)

        # 先做不需要账号的检查：网址已经是友链时没必要白耗一个验证码。
        if self.repository.friend_link_url_exists(website_url):
            raise AccountError("friend_link_exists", 409)

        user = self.account.users.find_by_email(email)
        if user and str(user.get("status")) != "active":
            raise AccountError("account_unavailable", 401)
        if user:
            user_id = int(user["uid"])
            if self.repository.active_friend_count(user_id) >= 3:
                raise AccountError("friend_link_limit_reached", 409)
            if self.repository.friend_application_url_exists(user_id, website_url):
                raise AccountError("friend_application_exists", 409)

        # 验证码是这道门：先验码，再建号、建申请 —— 顺序不能反，
        # 否则任何人都能靠"提交一次申请"把账号造出来。
        self.account._verify_code(email, "friend_link", code)

        account_created = False
        if not user:
            if not self.account._registration_enabled():
                raise AccountError("registration_disabled", 403)
            user = self.account._create_code_login_user(email)
            account_created = True

        user_id = int(user["uid"])
        try:
            application = self.repository.create_friend_application(
                user_id,
                site_name=site_name,
                website_url=website_url,
                avatar_url=avatar_url,
                language=language,
                rss_url=rss_url,
                description=description,
                applicant_note=applicant_note,
            )
        except ValueError as error:
            raise AccountError(str(error), 409) from error

        try:
            approved = self.repository.approve_friend_application(
                user_id, int(application["id"])
            )
        except ValueError as error:
            detail = str(error)
            raise AccountError(
                detail, 404 if detail == "friend_application_not_found" else 409
            ) from error

        self.account.users.mark_login(user_id)
        return {
            "success": True,
            "auto_approved": True,
            "account_created": account_created,
            # 自动建号的账号还没设用户名/密码，账号中心会引导补设
            "requires_setup": not bool(user.get("setup_completed")),
            "data": approved,
        }
