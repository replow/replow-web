from __future__ import annotations

import hashlib
import base64
import time

import jwt
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.media_policy import FILE_TYPES, MODES, backend_order, od_ready
from app.services.onedrive_storage import od_call, OneDriveStorageError
from app.core.config import get_settings

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

    storage_mode: str = "od_first"
    od_weight: int = 50
    r2_weight: int = 50
    fallback_enabled: bool = True
    od_enabled: bool = True
    od_public_base_url: str = "https://drive.4z.ink"

    @property
    def od_configured(self) -> bool:
        return self.od_enabled and od_ready()

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
            storage_mode=str(values.get("storage_mode") or "od_first"),
            od_weight=int(values.get("od_weight") or 50),
            r2_weight=int(values.get("r2_weight") or 50),
            fallback_enabled=values.get("fallback_enabled", "true") == "true",
            od_enabled=values.get("od_enabled", "true") == "true",
            local_root=str(values.get("local_root") or "./data/media").strip(),
            local_public_base_url=str(
                values.get("local_public_base_url") or "https://www.replow.org/v1/public/media"
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
            "od_configured": cfg.od_configured,
            "od_public_base_url": cfg.od_public_base_url,
            "storage_mode": cfg.storage_mode,
            "od_weight": cfg.od_weight,
            "r2_weight": cfg.r2_weight,
            "fallback_enabled": cfg.fallback_enabled,
            "od_enabled": cfg.od_enabled,
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

        previous = self.settings.namespace(self.namespace)
        mode = str(payload.get("storage_mode", previous.get("storage_mode", "od_first")))
        if mode not in MODES:
            raise MediaError("media_invalid_storage_mode")
        try:
            od_weight = int(payload.get("od_weight", previous.get("od_weight", 50)))
            r2_weight = int(payload.get("r2_weight", previous.get("r2_weight", 50)))
        except (TypeError, ValueError):
            raise MediaError("media_invalid_storage_weights") from None
        if not (1 <= od_weight <= 100 and 1 <= r2_weight <= 100):
            raise MediaError("media_invalid_storage_weights")
        fallback = payload.get("fallback_enabled", previous.get("fallback_enabled", "true") == "true")
        od_enabled = payload.get("od_enabled", previous.get("od_enabled", "true") == "true")
        if not isinstance(fallback, bool) or not isinstance(od_enabled, bool):
            raise MediaError("media_invalid_storage_policy")
        values = {
            "storage_mode": mode, "od_weight": str(od_weight), "r2_weight": str(r2_weight),
            "fallback_enabled": str(fallback).lower(), "od_enabled": str(od_enabled).lower(),
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
            "od_configured": cfg.od_configured,
            "od_bytes": int(self.db.execute(text(
                "SELECT COALESCE(SUM(byte_size),0) FROM media_objects WHERE storage_backend='od'"
            )).scalar() or 0),
            "storage_mode": cfg.storage_mode,
            "next_backend": ("balanced" if cfg.storage_mode == "balanced" else
                             (self._backend_order(cfg, 1) or ["unavailable"])[0]),
        }

    def _backend_order(self, cfg, byte_size):
        if os.getenv("APP_ENV") == "preview" and os.getenv("PREVIEW_LOCAL_UPLOADS") == "true":
            return ["local"]
        used, _, _ = self.repository.media_storage_bytes()
        return backend_order(cfg.storage_mode, cfg.od_weight, cfg.r2_weight,
                             cfg.od_configured,
                             cfg.r2_configured and used + byte_size <= cfg.r2_limit_bytes,
                             cfg.fallback_enabled)

    def upload(self, upload_file: Any, category: str, actor_id: int) -> dict[str, Any]:
        category = self._normalize_category(category)
        filename = str(getattr(upload_file, "filename", "") or "")
        temp_path = None
        try:
            temp_path, byte_size, checksum = self._stage_upload(
                getattr(upload_file, "file", upload_file))
            content_type = str(getattr(upload_file, "content_type", "") or "").lower().strip()
            if Path(filename).suffix.lower() in FILE_TYPES:
                content_type = self._direct_content_type(content_type, filename)
                with temp_path.open("rb") as source:
                    if not self._check_signature(content_type, source.read(64)):
                        raise MediaError("media_file_type_not_allowed", 415)
            else:
                content_type = self._image_type(content_type, filename, temp_path)
            cfg = self.config()
            key = self._object_key(category, filename)
            order = self._backend_order(cfg, byte_size)
            if not order:
                raise MediaError("media_storage_unavailable", 503)
            backend = None
            for candidate in order:
                try:
                    if candidate == "od":
                        from app.services.onedrive_storage import put_file
                        put_file(key, temp_path)
                    elif candidate == "local":
                        self._put_local(cfg, key, temp_path)
                    else:
                        self._put_r2(cfg, key, temp_path, content_type)
                    backend = candidate
                    break
                except (MediaError, OneDriveStorageError):
                    if not cfg.fallback_enabled:
                        raise MediaError("media_storage_upload_failed", 502) from None
            if not backend:
                raise MediaError("media_storage_upload_failed", 502)
            base_url = cfg.local_public_base_url if backend == "local" else cfg.od_public_base_url if backend == "od" else cfg.r2_public_base_url
            try:
                return self.repository.create_media({
                    "object_key": key, "public_url": self._public_url(base_url, key),
                    "original_name": filename[:255], "mime_type": content_type,
                    "byte_size": byte_size, "category": category,
                    "storage_backend": backend, "sha256": checksum, "uploader_id": actor_id,
                })
            except Exception:
                self._remove_object(cfg, backend, key)
                raise
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    # Browser-to-R2 PUT; the API never receives the image body.
    DIRECT_UPLOAD_TTL_SECONDS = 15 * 60

    @staticmethod
    def _direct_content_type(content_type: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        suffix_types = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif",
            ".webp": "image/webp", ".avif": "image/avif",
            ".bmp": "image/bmp", ".heic": "image/heic",
            ".heif": "image/heif",
        }
        expected = suffix_types.get(suffix)
        actual = str(content_type or "").lower().strip()
        expected = expected or FILE_TYPES.get(suffix)
        if expected not in ALLOWED_IMAGE_TYPES | set(FILE_TYPES.values()) or actual not in ("", "application/octet-stream", expected):
            raise MediaError("media_image_type_not_allowed", 415)
        return expected

    @staticmethod
    def _check_signature(mime_type: str, header: bytes) -> bool:
        if mime_type == "image/png":
            return header.startswith(bytes.fromhex("89504e470d0a1a0a"))
        if mime_type == "image/jpeg":
            return header.startswith(bytes.fromhex("ffd8ff"))
        if mime_type == "image/gif":
            return header.startswith((b"GIF87a", b"GIF89a"))
        if mime_type == "image/webp":
            return len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        if mime_type == "image/bmp":
            return header.startswith(b"BM")
        if mime_type in ("image/avif", "image/heic", "image/heif"):
            if len(header) < 16 or header[4:8] != b"ftyp":
                return False
            brands = [header[i:i + 4] for i in range(8, len(header) - 3, 4) if i != 12]
            if mime_type == "image/avif":
                return any(brand in (b"avif", b"avis") for brand in brands)
            return any(brand in HEIF_BRANDS for brand in brands) and not any(
                brand in (b"avif", b"avis") for brand in brands
            )
        if mime_type == "application/pdf":
            return header.startswith(b"%PDF-")
        if mime_type in ("application/zip", "application/epub+zip"):
            return header.startswith(b"PK")
        if mime_type == "text/plain":
            return b"\\x00" not in header and not header.lstrip().lower().startswith((b"<html", b"<!doctype", b"<script"))
        if mime_type == "audio/mpeg":
            return header.startswith(b"ID3") or (len(header) > 1 and header[0] == 255 and header[1] & 224 == 224)
        if mime_type == "video/mp4":
            return header[4:8] == b"ftyp"
        if mime_type == "video/webm":
            return header.startswith(bytes.fromhex("1a45dfa3"))
        if mime_type == "audio/ogg":
            return header.startswith(b"OggS")
        if mime_type == "audio/wav":
            return header.startswith(b"RIFF") and header[8:12] == b"WAVE"
        if mime_type == "audio/flac":
            return header.startswith(b"fLaC")
        return False

    @staticmethod
    def _upload_signing_secret() -> str:
        secret = get_settings().jwt_secret
        if len(secret) < 32:
            raise MediaError("media_upload_signing_not_ready", 503)
        return secret

    def prepare_direct_upload(self, payload: dict[str, Any], actor_id: int) -> dict[str, Any]:
        filename = str(payload.get("filename") or "")[:255]
        category = self._normalize_category(str(payload.get("category") or "general"))
        content_type = self._direct_content_type(str(payload.get("content_type") or ""), filename)
        try:
            byte_size = int(payload.get("byte_size"))
        except (ValueError, TypeError):
            raise MediaError("media_file_size_invalid") from None
        if byte_size <= 0 or byte_size > MAX_UPLOAD_BYTES:
            raise MediaError("media_file_too_large", 413)
        checksum = str(payload.get("sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise MediaError("media_checksum_invalid")

        cfg = self.config()
        quickxor = str(payload.get("quickxor") or "")
        key = self._object_key(category, filename)
        destination = None
        selected = None
        for backend in self._backend_order(cfg, byte_size):
            try:
                if backend == "od":
                    if not re.fullmatch(r"[A-Za-z0-9+/]{27}=", quickxor):
                        raise MediaError("media_hash_required")
                    destination = od_call("prepare", key=key, size=byte_size)
                else:
                    destination = {"upload_url": self._r2_client(cfg).generate_presigned_url(
                        "put_object", Params={
                            "Bucket": cfg.r2_bucket, "Key": key, "ContentType": content_type,
                            "Metadata": {"sha256": checksum},
                            "CacheControl": "public, max-age=31536000, immutable"},
                        ExpiresIn=self.DIRECT_UPLOAD_TTL_SECONDS, HttpMethod="PUT")}
                selected = backend
                break
            except MediaError as error:
                if error.detail == "media_hash_required" or not cfg.fallback_enabled:
                    raise
            except Exception:
                if not cfg.fallback_enabled:
                    raise MediaError("media_storage_prepare_failed", 502) from None
        if not selected:
            raise MediaError("media_storage_unavailable", 503)
        now = int(time.time())
        ticket = jwt.encode({
            "kind": "media_direct_upload", "uid": int(actor_id),
            "key": key, "filename": filename, "category": category,
            "mime": content_type, "size": byte_size, "sha256": checksum, "quickxor": quickxor,
            "backend": selected,
            "iat": now, "exp": now + self.DIRECT_UPLOAD_TTL_SECONDS,
        }, self._upload_signing_secret(), algorithm="HS256")
        return {**destination, "backend": selected, "ticket": ticket,
                "content_type": content_type, "sha256": checksum,
                "expires_in": self.DIRECT_UPLOAD_TTL_SECONDS}

    def confirm_direct_upload(self, ticket: str, actor_id: int) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                str(ticket), self._upload_signing_secret(), algorithms=["HS256"],
                options={"require": ["exp", "iat", "kind", "uid", "key", "category",
                                      "filename", "mime", "size", "sha256"]},
            )
        except jwt.PyJWTError:
            raise MediaError("media_direct_ticket_invalid", 401) from None
        if payload.get("kind") != "media_direct_upload" or payload.get("uid") != int(actor_id):
            raise MediaError("media_direct_ticket_invalid", 403)
        key = str(payload["key"])
        category = self._normalize_category(str(payload["category"]))
        mime_type = self._direct_content_type(str(payload["mime"]), str(payload["filename"]))
        checksum = str(payload["sha256"])
        byte_size = int(payload["size"])
        if (not key.startswith(f"media/{category}/")
                or not re.fullmatch(r"[0-9a-f]{64}", checksum)
                or byte_size <= 0 or byte_size > MAX_UPLOAD_BYTES):
            raise MediaError("media_direct_ticket_invalid", 403)

        existing = self.db.execute(
            text("SELECT id FROM media_objects WHERE object_key=:key LIMIT 1"),
            {"key": key},
        ).scalar()
        if existing:
            return self.repository.get_media(int(existing)) or {}

        cfg = self.config()
        backend = payload.get("backend", "r2")
        if backend == "od":
            try:
                info = od_call("inspect", key=key)
            except OneDriveStorageError:
                raise MediaError("media_onedrive_validation_failed", 502) from None
            expected_hash = str(payload.get("quickxor", ""))
            actual_hash = str(info.get("hashes", {}).get("quickXorHash", ""))
            if (info.get("size") != byte_size
                    or not re.fullmatch(r"[A-Za-z0-9+/]{27}=", expected_hash)
                    or actual_hash != expected_hash
                    or not self._check_signature(mime_type, base64.b64decode(info.get("header", "")))):
                self._remove_object(cfg, "od", key)
                raise MediaError("media_direct_object_mismatch", 422)
            return self.repository.create_media({
                "object_key": key, "public_url": self._public_url(cfg.od_public_base_url, key),
                "original_name": str(payload["filename"])[:255], "mime_type": mime_type,
                "byte_size": byte_size, "category": category, "storage_backend": "od",
                "sha256": checksum, "uploader_id": actor_id,
            })
        if backend != "r2":
            raise MediaError("media_direct_ticket_invalid", 403)
        if not cfg.r2_configured:
            raise MediaError("media_r2_direct_not_configured", 503)
        client = self._r2_client(cfg)
        try:
            info = client.head_object(Bucket=cfg.r2_bucket, Key=key)
        except Exception as error:
            raise MediaError("media_direct_object_not_found", 409) from error
        if (int(info.get("ContentLength", -1)) != byte_size
                or str(info.get("ContentType") or "").lower() != mime_type
                or str(info.get("Metadata", {}).get("sha256") or "") != checksum):
            self._remove_object(cfg, "r2", key)
            raise MediaError("media_direct_object_mismatch", 422)

        try:
            obj = client.get_object(Bucket=cfg.r2_bucket, Key=key, Range="bytes=0-63")
            try:
                header = obj["Body"].read(64)
            finally:
                obj["Body"].close()
        except Exception as error:
            raise MediaError("media_direct_validation_failed", 502) from error
        if not self._check_signature(mime_type, header):
            self._remove_object(cfg, "r2", key)
            raise MediaError("media_image_type_not_allowed", 415)

        current_r2_bytes, _, _ = self.repository.media_storage_bytes()
        if current_r2_bytes + byte_size > cfg.r2_limit_bytes:
            self._remove_object(cfg, "r2", key)
            raise MediaError("media_r2_direct_limit_reached", 507)
        return self.repository.create_media({
            "object_key": key,
            "public_url": self._public_url(cfg.r2_public_base_url, key),
            "original_name": str(payload["filename"])[:255],
            "mime_type": mime_type, "byte_size": byte_size,
            "category": category, "storage_backend": "r2", "sha256": checksum, "uploader_id": actor_id,
        })

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
        if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".heic", ".heif"} | set(FILE_TYPES):
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
            raise MediaError("media_r2_upload_failed", 502) from error

    @staticmethod
    def _put_local(cfg: MediaStorageConfig, object_key: str, path: Path) -> None:
        root = Path(cfg.local_root).expanduser().resolve()
        target = (root / object_key).resolve()
        if root not in target.parents:
            raise MediaError("media_invalid_local_object_key", 500)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def _remove_object(self, cfg: MediaStorageConfig, backend: str, object_key: str) -> bool:
        try:
            if backend == "r2" and cfg.r2_configured:
                self._r2_client(cfg).delete_object(Bucket=cfg.r2_bucket, Key=object_key)
            elif backend == "od":
                od_call("delete", key=object_key)
            elif backend == "local":
                root = Path(cfg.local_root).expanduser().resolve()
                target = (root / object_key).resolve()
                if root in target.parents:
                    target.unlink(missing_ok=True)
            else:
                return False
            return True
        except Exception:
            # Prepare/confirmation cleanup remains best-effort. Delete callers
            # must check this result before removing the database record.
            return False

    def list_owned(self, actor_id: int, limit: int, offset: int) -> tuple[list[dict], int]:
        return self.repository.media_owned(actor_id, limit, offset)

    def rename_owned(self, media_id: int, actor_id: int, name: str) -> dict:
        item = self.repository.get_media(media_id)
        if not item or int(item.get("uploader_id") or -1) != actor_id:
            raise MediaError("media_not_found", 404)
        name = str(name or "").strip()
        if (not name or len(name) > 255 or
                any(ord(c) < 32 or ord(c) == 127 for c in name) or
                "/" in name or "\\" in name or name in {".", ".."}):
            raise MediaError("media_name_invalid", 422)
        original = str(item.get("original_name") or "")
        # The display name may change, but the actual stored bytes/type do not.
        original_ext = Path(original).suffix.lower()
        if original_ext and Path(name).suffix.lower() != original_ext:
            raise MediaError("media_extension_cannot_change", 422)
        updated = self.repository.rename_owned_media(media_id, actor_id, name)
        if not updated:
            raise MediaError("media_not_found", 404)
        return updated

    def delete(self, media_id: int, actor_id: Optional[int] = None) -> bool:
        from app.services.media_trash import MediaTrash
        return MediaTrash(self.db, actor_id).trash(media_id, actor_id)

    def purge(self, media_id: int, actor_id: Optional[int] = None) -> bool:
        item = self.repository.get_media(media_id)
        if not item:
            return False
        if actor_id is not None and int(item.get("uploader_id") or -1) != actor_id:
            # Return the same result as a nonexistent ID; avoid leaking metadata.
            return False
        cfg = self.config()
        backend = str(item.get("storage_backend") or "legacy")
        if backend == "od":
            key = item.get("object_key") or ""
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            try:
                od_call("delete", key=str(key))
            except OneDriveStorageError:
                raise MediaError("media_onedrive_delete_failed", 502) from None
        if backend in {"r2", "local"}:
            object_key = item.get("object_key") or ""
            # The legacy MySQL column is VARBINARY; str(bytes) adds a b'...' wrapper.
            if isinstance(object_key, bytes):
                object_key = object_key.decode("utf-8")
            if not self._remove_object(cfg, backend, str(object_key)):
                raise MediaError("media_storage_delete_failed", 502)
        return self.repository.delete_media(media_id)
