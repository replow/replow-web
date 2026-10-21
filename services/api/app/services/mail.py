from dataclasses import dataclass
from email.message import EmailMessage
import smtplib
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.secret_store import decrypt_secret, encrypt_secret
from app.repositories.settings import SettingsRepository


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    sender_name: str
    use_tls: bool
    use_ssl: bool

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_email)


def _as_bool(value: Optional[str], fallback: bool) -> bool:
    if value is None or value == "":
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


class MailService:
    """SMTP delivery with environment defaults and encrypted DB overrides."""

    namespace = "mail"
    password_key = "mail.smtp_password"

    def __init__(self, db: Session):
        self.db = db
        self.settings = SettingsRepository(db)

    def config(self) -> MailConfig:
        app_settings = get_settings()
        values = self.settings.namespace(self.namespace)
        encrypted_password = self.settings.get_secure(self.password_key)
        password = app_settings.mail_smtp_password
        if encrypted_password:
            try:
                password = decrypt_secret(encrypted_password)
            except RuntimeError:
                password = ""
        return MailConfig(
            host=values.get("smtp_host") or app_settings.mail_smtp_host,
            port=int(values.get("smtp_port") or app_settings.mail_smtp_port),
            username=values.get("smtp_username") or app_settings.mail_smtp_username,
            password=password,
            from_email=values.get("from_email") or app_settings.mail_from or values.get("smtp_username", ""),
            sender_name=values.get("sender_name") or app_settings.mail_sender_name,
            use_tls=_as_bool(values.get("use_tls"), app_settings.mail_use_tls),
            use_ssl=_as_bool(values.get("use_ssl"), app_settings.mail_use_ssl),
        )

    def public_config(self) -> dict[str, object]:
        config = self.config()
        return {
            "smtp_host": config.host,
            "smtp_port": config.port,
            "smtp_username": config.username,
            "from_email": config.from_email,
            "sender_name": config.sender_name,
            "use_tls": config.use_tls,
            "use_ssl": config.use_ssl,
            "configured": config.configured,
            "password_configured": bool(config.password),
        }

    def update_config(self, payload: dict, actor_id: int) -> dict[str, object]:
        values = {
            "smtp_host": str(payload.get("smtp_host", "")).strip(),
            "smtp_port": str(int(payload.get("smtp_port", 465) or 465)),
            "smtp_username": str(payload.get("smtp_username", "")).strip(),
            "from_email": str(payload.get("from_email", "")).strip(),
            "sender_name": str(payload.get("sender_name", "SilverCode")).strip() or "SilverCode",
            "use_tls": "1" if bool(payload.get("use_tls", True)) else "0",
            "use_ssl": "1" if bool(payload.get("use_ssl", True)) else "0",
        }
        for key, value in values.items():
            self.settings.upsert(self.namespace, key, value, is_secret=False, commit=False)

        if bool(payload.get("clear_password")):
            self.settings.delete_secure(self.password_key, commit=False)
        elif str(payload.get("smtp_password") or ""):
            self.settings.upsert_secure(
                self.password_key,
                encrypt_secret(str(payload["smtp_password"])),
                actor_id,
                commit=False,
            )

        self.db.commit()
        return self.public_config()

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        config = self.config()
        if not config.configured:
            raise RuntimeError("mail_not_configured")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{config.sender_name} <{config.from_email}>"
        message["To"] = recipient
        message.set_content(body)

        if config.use_ssl:
            with smtplib.SMTP_SSL(config.host, config.port, timeout=15) as smtp:
                if config.username:
                    smtp.login(config.username, config.password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(config.host, config.port, timeout=15) as smtp:
            smtp.ehlo()
            if config.use_tls:
                smtp.starttls()
                smtp.ehlo()
            if config.username:
                smtp.login(config.username, config.password)
            smtp.send_message(message)

    def send_verification_code(self, *, recipient: str, code: str, purpose: str) -> None:
        labels = {
            "register": "注册验证",
            "login": "登录验证",
            "reset": "重置密码",
            "email_change": "邮箱变更",
            "friend_link": "友情链接验证",
        }
        label = labels.get(purpose, "安全验证")
        self.send(
            recipient=recipient,
            subject=f"SilverCode {label}码",
            body=(
                f"您好，\n\n您的 SilverCode {label}码是：{code}\n"
                "验证码 10 分钟内有效。若不是您本人操作，请忽略本邮件。\n\n"
                "SilverCode Nexus"
            ),
        )

    def send_friend_link_verification(
        self,
        *,
        recipient: str,
        site_name: str,
        verification_url: str,
        expires_hours: int = 24,
    ) -> None:
        self.send(
            recipient=recipient,
            subject="SilverCode 友情链接邮箱认证",
            body=(
                "您好，\n\n"
                f"您正在为站点「{site_name or '未命名站点'}」申请 SilverCode Nexus 友情链接。\n"
                "请打开下面的认证地址完成邮箱认证：\n\n"
                f"{verification_url}\n\n"
                f"认证地址 {expires_hours} 小时内有效。打开后该友情链接将自动通过并公开展示。\n"
                "如果不是您本人提交的申请，请忽略本邮件。\n\n"
                "SilverCode Nexus"
            ),
        )
