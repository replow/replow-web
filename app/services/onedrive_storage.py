"""Authenticated local bridge; the API process never reads OneDrive OAuth credentials."""
from app.services.quickxor import QuickXor
import os

import httpx


class OneDriveStorageError(RuntimeError):
    pass


def od_call(action, **payload):
    secret = os.getenv("OD_BRIDGE_KEY", "")
    if len(secret) < 32:
        raise OneDriveStorageError("media_onedrive_not_configured")
    try:
        response = httpx.post(
            "http://127.0.0.1:8812/internal/od",
            headers={"Authorization": "Bearer " + secret},
            json={"action": action, **payload}, timeout=45,
            follow_redirects=False, trust_env=False)
        if response.status_code != 200:
            raise OneDriveStorageError("media_onedrive_operation_failed")
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise OneDriveStorageError("media_onedrive_unavailable") from None


def put_file(key, path):
    size = path.stat().st_size
    prepared = od_call("prepare", key=key, size=size)
    digest = QuickXor()
    try:
        with path.open("rb") as source, httpx.Client(
                timeout=180, follow_redirects=False, trust_env=False) as client:
            offset = 0
            while offset < size:
                chunk = source.read(prepared["chunk_size"])
                digest.update(chunk)
                response = client.put(prepared["upload_url"], content=chunk, headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Range": f"bytes {offset}-{offset+len(chunk)-1}/{size}"})
                if response.status_code not in (200, 201, 202):
                    raise OneDriveStorageError("media_onedrive_upload_failed")
                offset += len(chunk)
        info = od_call("inspect", key=key)
        if info.get("size") != size or str(info.get("hashes", {}).get("quickXorHash", "")) != digest.base64():
            raise OneDriveStorageError("media_onedrive_integrity_failed")
    except (httpx.HTTPError, KeyError, ValueError, OneDriveStorageError):
        try:
            od_call("delete", key=key)
        except OneDriveStorageError:
            pass
        raise OneDriveStorageError("media_onedrive_upload_failed") from None
