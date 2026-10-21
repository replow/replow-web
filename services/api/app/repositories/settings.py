from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class SettingsRepository:
    """Persistence helpers for namespaced and encrypted application settings."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, namespace: str, key: str) -> Optional[str]:
        row = self.db.execute(
            text(
                """
                SELECT setting_value
                FROM settings
                WHERE namespace = :namespace AND setting_key = :setting_key
                LIMIT 1
                """
            ),
            {"namespace": namespace, "setting_key": key},
        ).mappings().first()
        return str(row["setting_value"]) if row and row["setting_value"] is not None else None

    def namespace(self, namespace: str) -> dict[str, str]:
        rows = self.db.execute(
            text(
                """
                SELECT setting_key, setting_value
                FROM settings
                WHERE namespace = :namespace
                ORDER BY setting_key ASC
                """
            ),
            {"namespace": namespace},
        ).mappings().all()
        return {
            str(row["setting_key"]): str(row["setting_value"] or "")
            for row in rows
        }

    def upsert(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        is_secret: bool = False,
        commit: bool = True,
    ) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO settings(namespace, setting_key, setting_value, is_secret, updated_at)
                VALUES (:namespace, :setting_key, :setting_value, :is_secret, NOW())
                ON DUPLICATE KEY UPDATE
                    setting_value = :setting_value,
                    is_secret = :is_secret,
                    updated_at = NOW()
                """
            ),
            {
                "namespace": namespace,
                "setting_key": key,
                "setting_value": str(value),
                "is_secret": int(is_secret),
            },
        )
        if commit:
            self.db.commit()

    def get_secure(self, key: str) -> Optional[str]:
        row = self.db.execute(
            text(
                """
                SELECT encrypted_value
                FROM secure_settings
                WHERE setting_key = :setting_key
                LIMIT 1
                """
            ),
            {"setting_key": key},
        ).mappings().first()
        return str(row["encrypted_value"]) if row else None

    def upsert_secure(
        self,
        key: str,
        encrypted_value: str,
        actor_id: Optional[int],
        *,
        commit: bool = True,
    ) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO secure_settings(setting_key, encrypted_value, updated_by, updated_at)
                VALUES (:setting_key, :encrypted_value, :actor_id, NOW())
                ON DUPLICATE KEY UPDATE
                    encrypted_value = :encrypted_value,
                    updated_by = :actor_id,
                    updated_at = NOW()
                """
            ),
            {
                "setting_key": key,
                "encrypted_value": encrypted_value,
                "actor_id": actor_id,
            },
        )
        if commit:
            self.db.commit()

    def delete_secure(self, key: str, *, commit: bool = True) -> None:
        self.db.execute(
            text("DELETE FROM secure_settings WHERE setting_key = :setting_key"),
            {"setting_key": key},
        )
        if commit:
            self.db.commit()
