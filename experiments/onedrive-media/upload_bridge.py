"""Private loopback control plane for the existing media API; never expose OAuth tokens."""
import base64
import os
import re
import secrets
from urllib.parse import quote

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

KEY_PATTERN = re.compile(r"media/(site|avatar|article|music|friend)/[0-9a-f]{32}\.[a-z0-9]{1,8}$")


def register_upload_routes(api, drive, root, safe_url, failure_type):
    async def graph(media, method, path, **kwargs):
        for attempt in range(2):
            token = await media.token(force=attempt > 0)
            response = await media.client.request(
                method, "https://graph.microsoft.com/v1.0" + path,
                headers={"Authorization": "Bearer " + token}, timeout=httpx.Timeout(45, connect=5), **kwargs)
            if response.status_code == 401 and attempt == 0:
                continue
            if response.status_code in (429, 503):
                raise failure_type(503, "onedrive_busy", 30)
            if response.status_code == 404:
                raise failure_type(404, "not_found")
            if response.status_code not in (200, 201, 204):
                raise failure_type(503, "onedrive_graph_" + method.lower() + "_" + str(response.status_code))
            return response
        raise failure_type(503, "authorization_required")

    base = "/drives/" + quote(drive, safe="") + "/items/"
    root_path = base + quote(root, safe="")

    async def folder(media, parent_id, name):
        path = base + quote(parent_id, safe="") + ":/" + quote(name, safe="")
        try:
            info = (await graph(media, "GET", path)).json()
        except failure_type as exc:
            if exc.status != 404:
                raise
            # A simultaneous request may create the same fixed folder first.
            response = await media.client.post(
                "https://graph.microsoft.com/v1.0" + base +
                quote(parent_id, safe="") + "/children",
                headers={"Authorization": "Bearer " + await media.token()}, timeout=httpx.Timeout(45, connect=5),
                json={"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
            if response.status_code == 409:
                info = (await graph(media, "GET", path)).json()
            elif response.status_code in (200, 201):
                info = response.json()
            else:
                raise failure_type(503, "onedrive_folder_failed")
        if (info.get("remoteItem") or "folder" not in info or
                str(info.get("parentReference", {}).get("driveId", "")).lower() != drive.lower()
                or info.get("parentReference", {}).get("id") != parent_id):
            raise failure_type(503, "onedrive_folder_outside_root")
        return info["id"]

    async def item(media, key):
        info = (await graph(media, "GET", root_path + ":/" + quote(key, safe="/"))).json()
        await media.scoped(info)
        return info

    async def first_bytes(media, url):
        for _ in range(5):
            if not safe_url(url):
                raise failure_type(503, "onedrive_download_host_invalid")
            async with media.client.stream("GET", url, headers={"Range": "bytes=0-63"}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = response.headers.get("Location", "")
                    continue
                if response.status_code not in (200, 206):
                    raise failure_type(503, "onedrive_validation_failed")
                header = b""
                async for chunk in response.aiter_bytes():
                    header += chunk[:64-len(header)]
                    if len(header) >= 64:
                        break
                return base64.b64encode(header).decode()
        raise failure_type(503, "onedrive_validation_failed")

    @api.post("/internal/od")
    async def control(request: Request):
        secret = os.getenv("OD_BRIDGE_KEY", "")
        supplied = request.headers.get("Authorization", "")
        if (len(secret) < 32 or not request.client
                or request.client.host not in ("127.0.0.1", "::1")
                or not secrets.compare_digest(supplied, "Bearer " + secret)):
            return JSONResponse({"error": "not_found"}, status_code=404,
                                headers={"Cache-Control": "no-store"})
        try:
            payload = await request.json()
            action = payload.get("action")
            media = request.app.state.media
            if action == "status":
                return JSONResponse({"configured": media.configured()},
                                    headers={"Cache-Control": "no-store"})
            key = str(payload.get("key", ""))
            if not KEY_PATTERN.fullmatch(key):
                raise failure_type(422, "onedrive_invalid_object_key")
            if action == "prepare":
                size = int(payload.get("size", 0))
                if not 0 < size <= 100 * 1024 * 1024:
                    raise failure_type(413, "media_file_too_large")
                # Validate the pinned root even if the token is currently cached.
                root_info = (await graph(media, "GET", root_path)).json()
                if root_info.get("remoteItem") or "folder" not in root_info or root_info.get("root"):
                    raise failure_type(503, "onedrive_root_invalid")
                parts = key.split("/")
                parent = await folder(media, root, parts[0])
                parent = await folder(media, parent, parts[1])
                session = (await graph(
                    media, "POST", base + quote(parent, safe="") + ":/" +
                    quote(parts[2], safe="") + ":/createUploadSession",
                    json={"item": {"@microsoft.graph.conflictBehavior": "fail",
                                   "name": parts[2]}})).json()
                upload_url = session.get("uploadUrl", "")
                if not safe_url(upload_url):
                    raise failure_type(503, "onedrive_upload_host_invalid")
                result = {"upload_url": upload_url, "chunk_size": 5 * 1024 * 1024,
                          "expires_at": session.get("expirationDateTime")}
            elif action == "inspect":
                info = await item(media, key)
                result = {"size": info.get("size"), "id": info["id"],
                          "hashes": info.get("file", {}).get("hashes", {}),
                          "header": await first_bytes(
                              media, info.get("@microsoft.graph.downloadUrl", ""))}
            elif action == "delete":
                try:
                    info = await item(media, key)
                except failure_type as exc:
                    if exc.status != 404:
                        raise
                else:
                    await graph(media, "DELETE", base + quote(info["id"], safe=""))
                media.cache.pop(key, None)
                result = {"deleted": True}
            else:
                raise failure_type(422, "onedrive_invalid_action")
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except failure_type:
            raise
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
            raise failure_type(503, "onedrive_operation_failed") from None
