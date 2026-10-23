"""Private durable device identity store for the Vercel parser.

This route has its own service credential; browser sessions cannot access it.
Snapshots merge under a process/file lock so separate Vercel instances cannot
overwrite one another's freshly registered devices. No request bodies are logged.
"""
import fcntl
import hmac
import json
import os
from pathlib import Path
import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/fq/internal", include_in_schema=False)
MAX_BYTES = 262144


def merge_pool(previous, incoming, removed):
    if not isinstance(incoming, dict) or not isinstance(incoming.get("android"), list):
        raise ValueError("invalid_pool")
    if not isinstance(removed, list) or len(removed) > 20 or any(not isinstance(i, str) or not re.fullmatch(r"[0-9]{1,24}", i) for i in removed):
        raise ValueError("invalid_removals")
    pool = {d["device_id"]: d for d in previous.get("android", []) if d["device_id"] not in removed}
    devices = incoming["android"]
    if len(devices) > 20:
        raise ValueError("too_many_devices")
    for d in devices:
        if not isinstance(d, dict) or any(not isinstance(d.get(k), str) or not re.fullmatch(r"[0-9]{1,24}", d[k]) for k in ("device_id", "install_id")):
            raise ValueError("invalid_device")
        if not isinstance(d.get("secret_key"), str) or not 8 <= len(d["secret_key"]) <= 512:
            raise ValueError("invalid_device_key")
        # Older warm instances must not roll usage metadata backwards.
        old = pool.get(d["device_id"])
        if not old or int(d.get("use_count", 0)) >= int(old.get("use_count", 0)):
            pool[d["device_id"]] = d
    kept = sorted(pool.values(), key=lambda d: d.get("last_used", ""), reverse=True)[:20]
    return {"android": kept, "last_update": incoming.get("last_update", "")}


def authenticate(request):
    expected = os.environ.get("FQAPP_STATE_TOKEN", "")
    given = request.headers.getlist("authorization")
    if len(expected) < 32 or len(given) != 1 or not hmac.compare_digest(given[0], "Bearer " + expected):
        raise HTTPException(401, "service_authentication_required")


def storage():
    root = Path(os.environ.get("FQAPP_STATE_DIR", "/data/replow-preview/fqapp-state"))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def read_pool(root):
    try:
        return json.loads((root / "devices.json").read_text())
    except FileNotFoundError:
        return {"android": [], "last_update": ""}


@router.api_route("/fqapp-state", methods=["GET", "POST"])
async def device_state(request: Request):
    authenticate(request)
    data = None
    if request.method == "POST":
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise HTTPException(413, "snapshot_too_large")
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, "invalid_snapshot") from None
    root = storage()
    with (root / "state.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = read_pool(root)
        if data is not None:
            try:
                current = merge_pool(current, data.get("pool"), data.get("removed", []))
            except (ValueError, TypeError, KeyError):
                raise HTTPException(400, "invalid_snapshot") from None
            tmp = root / ("snapshot-" + secrets.token_hex(8))
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "w") as file:
                    json.dump(current, file)
                    file.flush()
                    os.fsync(file.fileno())
                tmp.replace(root / "devices.json")
            finally:
                tmp.unlink(missing_ok=True)
    return JSONResponse(current, headers={"Cache-Control": "private, no-store", "CDN-Cache-Control": "no-store"})
