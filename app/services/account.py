from datetime import datetime, timedelta
import hashlib
import hmac
import re
import secrets
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.password_policy import valid_new_password
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_signup_token,
    decode_token,
    password_hasher,
    verify_password,
)
from app.repositories.admin import AdminRepository
from app.repositories.public import PublicRepository
from app.repositories.users import UserRepository
from app.services.mail import MailService


class AccountError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


EMAIL_PATTERN = re.compile(r"^[^@\s]{1,160}@[^@\s]{1,80}\.[^@\s]{2,32}$")
USERNAME_PATTERN = re.compile(r"^[\w.-]{3,32}$", re.UNICODE)
PURPOSES = {"register", "login", "reset", "friend_link"}

# Code login doubles as sign-up, so an account may be created before the person
# has chosen anything. It still needs a valid unique username to exist in the
# meantime; these two word lists give something friendlier than a bare hex id.
_USERNAME_ADJECTIVES = (
    "swift", "calm", "bright", "lucky", "quiet", "silver", "amber", "cosmic",
    "gentle", "brave", "vivid", "noble", "sunny", "misty", "polar", "royal",
)
_USERNAME_NOUNS = (
    "otter", "falcon", "maple", "comet", "panda", "river", "ember", "cedar",
    "heron", "willow", "lynx", "orbit", "pixel", "raven", "tide", "koala",
)


def _clean_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise AccountError("invalid_email", 422)
    return email


def _clean_username(value: Any) -> str:
    username = str(value or "").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise AccountError("invalid_username", 422)
    return username


def _bool_value(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class AccountService:
    """SilverCode accounts: email verification, password and passwordless login."""

    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.public = PublicRepository(db)
        self.admin = AdminRepository(db)
        self.mail = MailService(db)
        self.settings = get_settings()

    def _generate_unique_username(self) -> str:
        """Pick a readable username that is not taken yet.

        Falls back to a hex suffix if the friendly space keeps colliding, so
        account creation can never fail just because of unlucky randomness.
        """
        for _ in range(12):
            candidate = (
                f"{secrets.choice(_USERNAME_ADJECTIVES)}_"
                f"{secrets.choice(_USERNAME_NOUNS)}{secrets.randbelow(9000) + 1000}"
            )
            if not self.users.username_exists(candidate):
                return candidate
        return f"user_{secrets.token_hex(5)}"

    def _email_verification_enabled(self) -> bool:
        value = self.public.settings(["email_verification_enabled"]).get(
            "email_verification_enabled"
        )
        return _bool_value(value, True)

    def _registration_enabled(self) -> bool:
        value = self.public.settings(["registration_enabled"]).get("registration_enabled")
        return _bool_value(value, True)

    @staticmethod
    def _identity_hash(action: str, identity: str) -> str:
        return hashlib.sha256(f"{action}:{identity}".encode("utf-8")).hexdigest()

    def _code_hash(self, email: str, purpose: str, code: str) -> str:
        secret = self.settings.jwt_secret.encode("utf-8")
        message = f"{purpose}:{email}:{code}".encode("utf-8")
        return hmac.new(secret, message, hashlib.sha256).hexdigest()

    def _verify_code(self, email: str, purpose: str, code: str) -> None:
        record = self.users.get_verification(email, purpose)
        if not record:
            raise AccountError("verification_code_invalid", 422)
        expires_at = record.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at <= datetime.utcnow():
            self.users.consume_verification(int(record["id"]))
            raise AccountError("verification_code_expired", 422)
        if int(record.get("attempts") or 0) >= 5:
            self.users.consume_verification(int(record["id"]))
            raise AccountError("verification_code_locked", 429)
        expected = self._code_hash(email, purpose, code.strip())
        if not hmac.compare_digest(expected, str(record.get("code_hash") or "")):
            self.users.increment_verification_attempts(int(record["id"]))
            raise AccountError("verification_code_invalid", 422)
        if not self.users.consume_verification(int(record["id"])):
            raise AccountError("verification_code_invalid", 422)

    def request_code(
        self,
        *,
        email: str,
        purpose: str,
        ip: Optional[str],
        username: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> dict[str, Any]:
        if purpose not in PURPOSES:
            raise AccountError("invalid_verification_purpose", 422)
        if not self._email_verification_enabled():
            raise AccountError("email_verification_disabled", 403)
        email = _clean_email(email)

        user = self.users.find_by_email(email)
        if purpose == "register":
            if not self._registration_enabled():
                raise AccountError("registration_disabled", 403)
            if not username:
                raise AccountError("username_required", 422)
            username = _clean_username(username)
            if self.users.username_exists(username):
                raise AccountError("username_already_exists", 409)
            if user:
                raise AccountError("email_already_exists", 409)
            display_name = str(display_name or username).strip()[:80] or username
        elif purpose == "friend_link":
            # Friend-link applications come from the public site, so the sender
            # does not need an account yet -- one is created when the code is
            # verified. But creating it requires registration to be open, and
            # saying so now is better than sending a code that cannot be used.
            if not user and not self._registration_enabled():
                raise AccountError("registration_disabled", 403)
            username = str(user["username"]) if user else ""
        elif not user:
            # Code login doubles as sign-up: an unknown email gets an account
            # the moment the code is verified, so the code has to be sent.
            # `reset` (and login while registration is closed) stays silent, so
            # we never reveal whether an address is registered.
            if purpose == "login" and self._registration_enabled():
                username = ""
            else:
                return {"success": True, "accepted": True, "expires_in": 600}
        else:
            username = str(user["username"])

        if not self.users.check_rate_limit(
            "email_code_email",
            self._identity_hash("email", email),
            limit=5,
            window_seconds=3600,
        ) or not self.users.check_rate_limit(
            "email_code_ip",
            self._identity_hash("ip", ip or "unknown"),
            limit=20,
            window_seconds=3600,
        ):
            raise AccountError("too_many_verification_requests", 429)

        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        self.users.create_verification(
            email=email,
            username=str(username or ""),
            purpose=purpose,
            code_hash=self._code_hash(email, purpose, code),
            expires_at=expires_at,
            requested_ip=ip,
        )
        try:
            self.mail.send_verification_code(recipient=email, code=code, purpose=purpose)
        except Exception as error:
            self.users.delete_verification(email, purpose)
            if isinstance(error, RuntimeError) and str(error) == "mail_not_configured":
                raise AccountError("mail_not_configured", 503) from error
            raise AccountError("mail_delivery_failed", 502) from error
        return {"success": True, "accepted": True, "expires_in": 600}

    def register_by_code(
        self,
        *,
        username: str,
        email: str,
        code: str,
        display_name: Optional[str],
    ) -> dict[str, Any]:
        email = _clean_email(email)
        username = _clean_username(username)
        if not code or len(code.strip()) != 6:
            raise AccountError("verification_code_invalid", 422)
        if not self._registration_enabled():
            raise AccountError("registration_disabled", 403)
        self._verify_code(email, "register", code)
        if self.users.username_exists(username):
            raise AccountError("username_already_exists", 409)
        if self.users.email_exists(email):
            raise AccountError("email_already_exists", 409)
        try:
            user = self.users.create_verified_user(
                username=username,
                email=email,
                display_name=str(display_name or username).strip()[:80] or username,
            )
        except IntegrityError as error:
            self.db.rollback()
            raise AccountError("account_already_exists", 409) from error
        if not user:
            raise AccountError("account_create_failed", 500)
        return {
            "success": True,
            "requiresPasswordSetup": True,
            "signupToken": create_signup_token(int(user["uid"])),
            "user": self.user_summary(user),
        }

    def set_signup_password(self, token: str, password: str) -> dict[str, Any]:
        if not valid_new_password(password):
            raise AccountError("invalid_password", 422)
        try:
            claims = decode_token(token, expected_kind="signup")
        except HTTPException as error:
            raise AccountError("signup_session_invalid", 401) from error
        user = self.users.get_by_id(int(claims["sub"]))
        if not user or user.get("status") != "active":
            raise AccountError("account_unavailable", 401)
        if not self.users.update_password(int(user["uid"]), password_hasher.hash(password)):
            raise AccountError("password_update_failed", 500)
        updated = self.users.get_by_id(int(user["uid"])) or user
        return self.issue_tokens(updated)

    def _create_code_login_user(self, email: str) -> dict[str, Any]:
        """Create the account that a first-time code login implies.

        The username is a random readable placeholder and the password is left
        unset; the account console asks the person to finish both right after
        signing in. ``setup_completed = 0`` is what drives that prompt.
        """
        username = self._generate_unique_username()
        try:
            user = self.users.create_verified_user(
                username=username,
                email=email,
                display_name=username,
                setup_completed=False,
            )
        except IntegrityError:
            # Another request won the race for this email; use its row.
            self.db.rollback()
            user = self.users.find_by_email(email) or {}
        if not user:
            raise AccountError("account_create_failed", 500)
        return user

    def login_by_code(self, *, email: str, code: str) -> dict[str, Any]:
        email = _clean_email(email)
        if not code or len(code.strip()) != 6:
            raise AccountError("verification_code_invalid", 422)
        user = self.users.find_by_email(email)
        if not user:
            if not self._registration_enabled():
                raise AccountError("registration_disabled", 403)
            # Verify first: an unverified email must not be able to create an
            # account just by asking for a code.
            self._verify_code(email, "login", code)
            user = self._create_code_login_user(email)
        else:
            if user.get("status") != "active":
                raise AccountError("account_unavailable", 401)
            self._verify_code(email, "login", code)
        self.users.mark_login(int(user["uid"]))
        result = self.issue_tokens(user, new_session=True)
        result["requiresSetup"] = not bool(user.get("setup_completed"))
        return result

    def complete_setup(
        self,
        *,
        user: dict[str, Any],
        username: str,
        password: str,
        display_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Finish the account created by a first-time code login."""
        if not valid_new_password(password):
            raise AccountError("invalid_password", 422)
        username = _clean_username(username)
        user_id = int(user["uid"])
        current_username = str(user["username"])
        if username.lower() != current_username.lower() and self.users.username_exists(username):
            raise AccountError("username_already_exists", 409)
        if username != current_username and not self.users.update_username(user_id, username):
            raise AccountError("username_update_failed", 500)
        if not self.users.update_password(user_id, password_hasher.hash(password)):
            raise AccountError("password_update_failed", 500)

        # Display name defaults to the username. Only fill it in when it is
        # still the untouched auto-generated value, so a customised name set
        # later from the profile page is never clobbered.
        current_display = str(user.get("display_name") or "")
        wanted_display = str(display_name or "").strip()[:80]
        if not wanted_display and current_display in {"", current_username}:
            wanted_display = username
        if wanted_display and wanted_display != current_display:
            self.users.update_display_name(user_id, wanted_display)

        self.users.mark_setup_completed(user_id)
        updated = self.users.get_by_id(user_id) or user
        result = self.issue_tokens(updated)
        result["requiresSetup"] = False
        return result

    def skip_setup(self, *, user: dict[str, Any]) -> dict[str, Any]:
        """Dismiss the setup dialog, keeping the generated username.

        The account keeps the random username it was created with and stays
        password-less, but is never asked again. A password can still be added
        later from the security section (no old password required, because
        ``change_password`` treats the unset sentinel as "no password yet").
        """
        user_id = int(user["uid"])
        self.users.mark_setup_completed(user_id)
        updated = self.users.get_by_id(user_id) or user
        result = self.issue_tokens(updated)
        result["requiresSetup"] = False
        return result

    def verify_reset_code(self, *, email: str, code: str, ip: Optional[str]) -> dict[str, Any]:
        email = _clean_email(email)
        user = self.users.find_by_email(email)
        if not user or user.get("status") != "active":
            raise AccountError("account_unavailable", 401)
        self._verify_code(email, "reset", code)
        raw_token = secrets.token_urlsafe(32)
        self.users.create_password_reset_token(
            user_id=int(user["uid"]),
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(minutes=20),
            requested_ip=ip,
        )
        return {"success": True, "resetToken": raw_token, "expiresIn": 1200}

    def reset_password(self, *, token: str, password: str) -> dict[str, Any]:
        if not valid_new_password(password):
            raise AccountError("invalid_password", 422)
        user_id = self.users.consume_password_reset_token(
            hashlib.sha256(token.encode("utf-8")).hexdigest()
        )
        if not user_id or not self.users.update_password(user_id, password_hasher.hash(password)):
            raise AccountError("reset_session_invalid", 401)
        user = self.users.get_by_id(user_id)
        if not user:
            raise AccountError("account_unavailable", 401)
        self.users.mark_login(user_id)
        return self.issue_tokens(user, new_session=True)

    def change_password(
        self,
        *,
        user: dict[str, Any],
        new_password: str,
        code: str,
    ) -> dict[str, Any]:
        if not valid_new_password(new_password):
            raise AccountError("invalid_password", 422)
        account = self.users.get_by_id(int(user["uid"]))
        if not account or account.get("status") != "active":
            raise AccountError("account_unavailable", 401)
        self._verify_code(_clean_email(account["email"]), "reset", code)
        if not self.users.update_password(
            int(account["uid"]), password_hasher.hash(new_password)
        ):
            raise AccountError("password_update_failed", 500)
        updated = self.users.get_by_id(int(user["uid"])) or user
        return self.issue_tokens(updated)

    def request_password_change_code(self, *, user: dict[str, Any], ip: Optional[str]) -> dict[str, Any]:
        account = self.users.get_by_id(int(user["uid"]))
        if not account or account.get("status") != "active":
            raise AccountError("account_unavailable", 401)
        return self.request_code(email=account["email"], purpose="reset", ip=ip)

    def issue_tokens(self, user: dict[str, Any], session_id=None, previous_version=None, new_session=False) -> dict[str, Any]:
        role = str(user.get("role") or "user")
        from app.services.sessions import SessionService
        access_token, refresh_token, expires = SessionService(self.db).issue(
            user, session_id, previous_version, new_session
        )
        return {
            "success": True,
            "data": {
                "accessToken": access_token,
                "refreshToken": refresh_token,
                "expires": expires,
                "avatar": str(user.get("avatar_url") or ""),
                "username": str(user["username"]),
                "nickname": str(user.get("display_name") or user["username"]),
                "roles": [role],
                "permissions": ["*:*:*"] if role == "admin" else [],
            },
        }

    @staticmethod
    def user_summary(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "uid": int(user["uid"]),
            "username": str(user["username"]),
            "email": str(user["email"]),
            "display_name": str(user.get("display_name") or user["username"]),
            "avatar_url": str(user.get("avatar_url") or ""),
            "role": str(user.get("role") or "user"),
            "status": str(user.get("status") or "active"),
            "setup_completed": bool(user.get("setup_completed", True)),
        }

    def admin_settings(self) -> dict[str, Any]:
        values = self.public.settings(
            ["registration_enabled", "email_verification_enabled"]
        )
        return {
            "registration_enabled": _bool_value(
                values.get("registration_enabled"), True
            ),
            "email_verification_enabled": _bool_value(
                values.get("email_verification_enabled"), True
            ),
            "mail": self.mail.public_config(),
        }

    def update_admin_settings(self, payload: dict[str, Any], actor_id: int) -> dict[str, Any]:
        if "registration_enabled" in payload:
            self.admin.update_setting(
                "registration_enabled", bool(payload["registration_enabled"]), actor_id
            )
        if "email_verification_enabled" in payload:
            self.admin.update_setting(
                "email_verification_enabled",
                bool(payload["email_verification_enabled"]),
                actor_id,
            )
        mail_payload = payload.get("mail")
        if isinstance(mail_payload, dict):
            self.mail.update_config(mail_payload, actor_id)
        return self.admin_settings()

    def send_test_mail(self, recipient: str) -> dict[str, Any]:
        recipient = _clean_email(recipient)
        self.mail.send(
            recipient=recipient,
            subject="SilverCode 邮件配置测试",
            body="这是一封来自 SilverCode Nexus 的测试邮件。\n邮件配置正常。",
        )
        return {"success": True, "recipient": recipient}
