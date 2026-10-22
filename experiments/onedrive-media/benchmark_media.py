"""Compare direct OD/R2 upload and public-link download from the API host.
No signed URLs, keys or OAuth credentials are written to output.
Run from API cwd/venv with the normal service environment already loaded.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--api-root", required=True)
parser.add_argument("--stage-services")
parser.add_argument("--output", required=True)
args = parser.parse_args()
sys.path.insert(0, args.api_root)
import app.services
if args.stage_services:
    app.services.__path__.insert(0, args.stage_services)
from app.db.session import SessionLocal
from app.services.media_storage import MediaStorageService
from app.services.quickxor import QuickXor


def download(client, url, expected):
    start = time.monotonic()
    digest = hashlib.sha256()
    received = 0
    with client.stream("GET", url, follow_redirects=True) as response:
        if response.status_code != 200:
            raise RuntimeError("public_download_failed")
        for chunk in response.iter_bytes():
            digest.update(chunk)
            received += len(chunk)
    elapsed = time.monotonic() - start
    if digest.hexdigest() != expected:
        raise RuntimeError("download_checksum_mismatch")
    return elapsed, received


results = []
with SessionLocal() as db, httpx.Client(timeout=120, follow_redirects=False) as client:
    service = MediaStorageService(db)
    original = service.config()
    for mib in (1, 8):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("fixture.bin", os.urandom(mib*1024*1024))
        data = buffer.getvalue()
        checksum = hashlib.sha256(data).hexdigest()
        quick = QuickXor(); quick.update(data)
        for repetition in (1, 2):
            for backend in ("od", "r2"):
                item = None
                prepared = None
                cfg = replace(original, storage_mode=backend+"_first", fallback_enabled=False)
                row = {"backend": backend, "sample_mib": mib, "bytes":len(data), "repeat":repetition}
                with patch.object(service, "config", return_value=cfg):
                    try:
                        started = time.monotonic()
                        prepared = service.prepare_direct_upload({
                            "filename":"benchmark.zip","category":"general",
                            "content_type":"application/zip","byte_size":len(data),
                            "sha256":checksum,"quickxor":quick.base64()},10000)
                        row["prepare_seconds"] = time.monotonic()-started
                        if prepared["backend"] != backend:
                            raise RuntimeError("wrong_upload_backend")
                        started = time.monotonic()
                        if backend == "od":
                            size = prepared["chunk_size"]
                            for offset in range(0,len(data),size):
                                chunk = data[offset:offset+size]
                                r = client.put(prepared["upload_url"], content=chunk, headers={
                                    "Content-Type":"application/octet-stream",
                                    "Content-Range":f"bytes {offset}-{offset+len(chunk)-1}/{len(data)}"})
                                if r.status_code not in (200,201,202):
                                    raise RuntimeError("onedrive_put_failed")
                        else:
                            r = client.put(prepared["upload_url"], content=data, headers={
                                "Content-Type":"application/zip","x-amz-meta-sha256":checksum,
                                "Cache-Control":"public, max-age=31536000, immutable"})
                            if r.status_code not in (200,201):
                                raise RuntimeError("r2_put_failed")
                        row["upload_seconds"] = time.monotonic()-started
                        started = time.monotonic()
                        item = service.confirm_direct_upload(prepared["ticket"],10000)
                        row["confirm_seconds"] = time.monotonic()-started
                        row["cold_download_seconds"], _ = download(client,item["public_url"],checksum)
                        row["warm_download_seconds"], _ = download(client,item["public_url"],checksum)
                        row["verified"] = True
                    except Exception as error:
                        # Exception strings could contain signed URLs: emit types/codes only.
                        row["error"] = (str(error) if type(error) is RuntimeError else getattr(error,"detail",type(error).__name__))
                    finally:
                        try:
                            if item:
                                service.delete(item["id"])
                                if backend == "r2":
                                    try:
                                        service._r2_client(cfg).head_object(
                                            Bucket=cfg.r2_bucket,Key=item["object_key"].decode() if isinstance(item["object_key"],bytes) else item["object_key"])
                                        raise RuntimeError("object_still_exists")
                                    except Exception as error:
                                        code = getattr(error,"response",{}).get("Error",{}).get("Code")
                                        if code not in ("404","NoSuchKey","NotFound"):
                                            raise
                                row["cleaned"] = True
                            elif prepared:
                                import jwt
                                payload=jwt.decode(prepared["ticket"],service._upload_signing_secret(),algorithms=["HS256"])
                                service._remove_object(cfg,backend,payload["key"])
                                row["cleaned"] = True
                        except Exception:
                            row["cleanup_error"] = True
                    results.append(row)
                    print(json.dumps(row), flush=True)
                    Path(args.output).write_text(json.dumps(results,indent=2))
if any(not r.get("verified") or not r.get("cleaned") for r in results):
    raise SystemExit(1)
