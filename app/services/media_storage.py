from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.core.secret_store import decrypt_secret, encrypt_secret
from app.repositories.admin import AdminRepository
from app.repositories.settings import SettingsRepository


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
# Use decimal GB and stop below the provider's free allowance with margin;
# this is deliberately not 9 GiB (which would be larger than 9 GB).
DEFAULT_R2_LIMIT_BYTES = 9_000_000_000
# UI picker names are aliases for the existing media_objects category enum.
MEDIA_CATEGORY_ALIASES = {
    "general": "site",
    "wallpaper": "site",
    "site-avatar": "site",
    "article-cover": "article",
    "friend-avatar": "friend",
}
MEDIA_CATEGORIES = {"site", "avatar", "article", "music", "friend"}

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/avif",
    "image/bmp",
    "image/heic",
    "image/heif",
}

HEIF_SUFFIX_TYPES = {".heic": "image/heic", ".heif": "image/heif"}
HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


class MediaError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class MediaStorageConfig:
    r2_account_id: str
    r2_bucket: str
    r2_public_base_url: str
    r2_endpoint_url: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_limit_bytes: int
    local_root: str
    local_public_base_url: str

    @property
    def r2_configured(self) -> bool:
        return bool(
            self.r2_account_id
            and self.r2_bucket
            and self.r2_public_base_url
            and self.r2_access_key_id
            and self.r2_secret_access_key
        )


class MediaStorageService:
    namespace = "media_storage"
    access_key_name = "media_storage.r2_access_key_id"
    secret_key_name = "media_storage.r2_secret_access_key"

    def __init__(self, db: Session):
        self.db = db
        self.settings = SettingsRepository(db)
        self.repository = AdminRepository(db)

    def config(self) -> MediaStorageConfig:
        values = self.settings.namespace(self.namespace)
        access_key = self._decrypt(self.settings.get_secure(self.access_key_name))
        secret_key = self._decrypt(self.settings.get_secure(self.secret_key_name))
        account_id = str(values.get("r2_account_id") or "").strip()
        endpoint = str(values.get("r2_endpoint_url") or "").strip()
        if not endpoint and account_id:
            endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        try:
            limit = int(values.get("r2_limit_bytes") or DEFAULT_R2_LIMIT_BYTES)
        except (TypeError, ValueError):
            limit = DEFAULT_R2_LIMIT_BYTES
        return MediaStorageConfig(
            r2_account_id=account_id,
            r2_bucket=str(values.get("r2_bucket") or "").strip(),
            r2_public_base_url=str(values.get("r2_public_base_url") or "").strip().rstrip("/"),
            r2_endpoint_url=endpoint.rstrip("/"),
            r2_access_key_id=access_key,
            r2_secret_access_key=secret_key,
            r2_limit_bytes=max(1, limit),
            local_root=str(values.get("local_root") or "./data/media").strip(),
            local_public_base_url=str(
                values.get("local_public_base_url") or "https://www.example.com/v1/public/media"
            ).strip().rstrip("/"),
        )

    @staticmethod
    def _decrypt(value: Optional[str]) -> str:
        if not value:
            return ""
        try:
            return decrypt_secret(value)
        except RuntimeError:
            return ""

    def public_config(self) -> dict[str, Any]:
        cfg = self.config()
        return {
            "r2_account_id": cfg.r2_account_id,
            "r2_bucket": cfg.r2_bucket,
            "r2_public_base_url": cfg.r2_public_base_url,
            "r2_endpoint_url": cfg.r2_endpoint_url,
            "r2_limit_bytes": cfg.r2_limit_bytes,
            "local_root": cfg.local_root,
            "local_public_base_url": cfg.local_public_base_url,
            "r2_access_key_configured": bool(cfg.r2_access_key_id),
            "r2_secret_key_configured": bool(cfg.r2_secret_access_key),
            "r2_configured": cfg.r2_configured,
        }

    def update_config(self, payload: dict[str, Any], actor_id: int) -> dict[str, Any]:
        account_id = str(payload.get("r2_account_id") or "").strip()
        bucket = str(payload.get("r2_bucket") or "").strip()
        public_base = str(payload.get("r2_public_base_url") or "").strip().rstrip("/")
        endpoint = str(payload.get("r2_endpoint_url") or "").strip().rstrip("/")
        local_root = str(payload.get("local_root") or "").strip()
        local_public = str(payload.get("local_public_base_url") or "").strip().rstrip("/")

        if account_id and not re.fullmatch(r"[a-fA-F0-9]{16,64}", account_id):
            raise MediaError("media_invalid_r2_account_id")
        if any((account_id, bucket, public_base)) and not all((account_id, bucket, public_base)):
            raise MediaError("media_r2_config_incomplete")
        if public_base and not re.match(r"^https?://[^\s]+$", public_base, re.I):
            raise MediaError("media_invalid_r2_public_url")
        if endpoint and not re.match(r"^https?://[^\s]+$", endpoint, re.I):
            raise MediaError("media_invalid_r2_endpoint")
        if not local_root:
            raise MediaError("media_local_root_required")
        if not local_public or not re.match(r"^https?://[^\s]+$", local_public, re.I):
            raise MediaError("media_invalid_local_public_url")

        try:
            limit_bytes = int(payload.get("r2_limit_bytes") or DEFAULT_R2_LIMIT_BYTES)
        except (TypeError, ValueError) as error:
            raise MediaError("media_invalid_r2_limit") from error
        if limit_bytes != DEFAULT_R2_LIMIT_BYTES:
            raise MediaError("media_r2_limit_must_be_9_gb")

        values = {
            "r2_account_id": account_id,
            "r2_bucket": bucket,
            "r2_public_base_url": public_base,
            "r2_endpoint_url": endpoint,
            "r2_limit_bytes": str(DEFAULT_R2_LIMIT_BYTES),
            "local_root": local_root,
            "local_public_base_url": local_public,
        }
        for key, value in values.items():
            self.settings.upsert(self.namespace, key, value, is_secret=False, commit=False)

        if bool(payload.get("clear_r2_credentials")):
            self.settings.delete_secure(self.access_key_name, commit=False)
            self.settings.delete_secure(self.secret_key_name, commit=False)
        else:
            access_key = str(payload.get("r2_access_key_id") or "").strip()
            secret_key = str(payload.get("r2_secret_access_key") or "").strip()
            if access_key:
                self.settings.upsert_secure(
                    self.access_key_name, encrypt_secret(access_key), actor_id, commit=False
                )
            if secret_key:
                self.settings.upsert_secure(
                    self.secret_key_name, encrypt_secret(secret_key), actor_id, commit=False
                )
        self.db.commit()
        return self.public_config()

    def status(self) -> dict[str, Any]:
        cfg = self.config()
        r2_bytes, local_bytes, total_bytes = self.repository.media_storage_bytes()
        limit = cfg.r2_limit_bytes
        return {
            "r2_configured": cfg.r2_configured,
            "r2_bytes": r2_bytes,
            "r2_limit_bytes": limit,
            "r2_used_percent": round((r2_bytes / limit) * 100, 2) if limit else 0,
            "r2_remaining_bytes": max(0, limit - r2_bytes),
            "local_bytes": local_bytes,
            "total_bytes": total_bytes,
            "next_backend": "r2" if cfg.r2_configured and r2_bytes < limit else "local",
        }

    def upload(self, upload_file: Any, category: str, actor_id: int) -> dict[str, Any]:
        category = self._normalize_category(category)
        content_type = str(getattr(upload_file, "content_type", "") or "").lower().strip()
        filename = str(getattr(upload_file, "filename", "") or "")

        temp_path: Optional[Path] = None
        try:
            temp_path, byte_size, checksum = self._stage_upload(
                getattr(upload_file, "file", upload_file)
            )
            content_type = self._image_type(content_type, filename, temp_path)
            cfg = self.config()
            current_r2_bytes, _, _ = self.repository.media_storage_bytes()
            use_r2 = cfg.r2_configured and current_r2_bytes + byte_size <= cfg.r2_limit_bytes
            backend = "r2" if use_r2 else "local"
            object_key = self._object_key(category, filename)

            if backend == "r2":
                self._put_r2(cfg, object_key, temp_path, content_type)
                public_url = self._public_url(cfg.r2_public_base_url, object_key)
            else:
                self._put_local(cfg, object_key, temp_path)
                public_url = self._public_url(cfg.local_public_base_url, object_key)

            try:
                item = self.repository.create_media(
                    {
                        "object_key": object_key,
                        "public_url": public_url,
                        "original_name": str(getattr(upload_file, "filename", "") or "")[:255],
                        "mime_type": content_type,
                        "byte_size": byte_size,
                        "category": category,
                        "storage_backend": backend,
                        "sha256": checksum,
                    }
                )
            except Exception:
                self._remove_object(cfg, backend, object_key)
                raise
            return item
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _image_type(content_type: str, filename: str, path: Path) -> str:
        """Preserve HEIF bytes, verify the ISO-BMFF signature and canonicalize MIME."""
        suffix = Path(filename).suffix.lower()
        heif_type = HEIF_SUFFIX_TYPES.get(suffix)
        if heif_type or content_type in HEIF_SUFFIX_TYPES.values():
            if not heif_type or content_type not in {
                "", "application/octet-stream", "image/heic", "image/heif"
            }:
                raise MediaError("media_image_type_not_allowed", 415)
            with path.open("rb") as source:
                header = source.read(64)
            if len(header) < 16 or header[4:8] != b"ftyp":
                raise MediaError("media_image_type_not_allowed", 415)
            brands = [header[i:i + 4] for i in range(8, len(header) - 3, 4) if i != 12]
            if not any(brand in HEIF_BRANDS for brand in brands) or any(
                brand in {b"avif", b"avis"} for brand in brands
            ):
                raise MediaError("media_image_type_not_allowed", 415)
            return heif_type
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise MediaError("media_image_type_not_allowed", 415)
        return content_type

    @staticmethod
    def _stage_upload(file_obj: BinaryIO) -> tuple[Path, int, str]:
        handle, raw_path = tempfile.mkstemp(prefix="replow-media-", suffix=".upload")
        os.close(handle)
        path = Path(raw_path)
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("wb") as target:
                while True:
                    chunk = file_obj.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise MediaError("media_file_too_large", 413)
                    digest.update(chunk)
                    target.write(chunk)
            if size <= 0:
                raise MediaError("media_file_empty")
            return path, size, digest.hexdigest()
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _normalize_category(category: str) -> str:
        value = str(category or "general").strip().lower()
        value = MEDIA_CATEGORY_ALIASES.get(value, value)
        if value not in MEDIA_CATEGORIES:
            raise MediaError("media_invalid_category")
        return value

    @staticmethod
    def _object_key(category: str, original_name: str) -> str:
        safe_category = re.sub(r"[^a-z0-9_-]+", "-", category.lower()).strip("-") or "general"
        suffix = Path(original_name).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".heic", ".heif"}:
            suffix = ".bin"
        return f"media/{safe_category}/{uuid.uuid4().hex}{suffix}"

    @staticmethod
    def _public_url(base_url: str, object_key: str) -> str:
        return f"{base_url.rstrip('/')}/{quote(object_key, safe='/')}"

    @staticmethod
    def _r2_client(cfg: MediaStorageConfig) -> Any:
        try:
            import boto3
        except ImportError as error:
            raise MediaError("media_r2_sdk_not_installed", 503) from error
        return boto3.client(
            "s3",
            endpoint_url=cfg.r2_endpoint_url,
            aws_access_key_id=cfg.r2_access_key_id,
            aws_secret_access_key=cfg.r2_secret_access_key,
            region_name="auto",
        )

    def _put_r2(self, cfg: MediaStorageConfig, object_key: str, path: Path, content_type: str) -> None:
        try:
            with path.open("rb") as source:
                self._r2_client(cfg).upload_fileobj(
                    source,
                    cfg.r2_bucket,
                    object_key,
                    ExtraArgs={"ContentType": content_type, "CacheControl": "public, max-age=31536000, immutable"},
                )
        except MediaError:
            raise
        except Exception as error:
            raise MediaError(f"media_r2_upload_failed: {error}", 502) from error

    @staticmethod
    def _put_local(cfg: MediaStorageConfig, object_key: str, path: Path) -> None:
        root = Path(cfg.local_root).expanduser().resolve()
        target = (root / object_key).resolve()
        if root not in target.parents:
            raise MediaError("media_invalid_local_object_key", 500)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def _remove_object(self, cfg: MediaStorageConfig, backend: str, object_key: str) -> None:
        try:
            if backend == "r2" and cfg.r2_configured:
                self._r2_client(cfg).delete_object(Bucket=cfg.r2_bucket, Key=object_key)
            elif backend == "local":
                root = Path(cfg.local_root).expanduser().resolve()
                target = (root / object_key).resolve()
                if root in target.parents:
                    target.unlink(missing_ok=True)
        except Exception:
            # The original database error is more useful to the caller. A
            # later storage reconciliation can remove an orphan object.
            pass

    def delete(self, media_id: int) -> bool:
        item = self.repository.get_media(media_id)
        if not item:
            return False
        cfg = self.config()
        backend = str(item.get("storage_backend") or "legacy")
        if backend in {"r2", "local"}:
            object_key = item.get("object_key") or ""
            # The legacy MySQL column is VARBINARY; str(bytes) adds a b'...' wrapper.
            if isinstance(object_key, bytes):
                object_key = object_key.decode("utf-8")
            self._remove_object(cfg, backend, str(object_key))
        return self.repository.delete_media(media_id)
