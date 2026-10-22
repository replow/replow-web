"""OpenList's published OneDrive Online API adapter; no OpenList daemon."""
import time
from urllib.parse import quote

AUTH_PAGE = "https://api.oplist.org/"
RENEW_URL = "https://api.oplist.org/onedrive/renewapi"
LOGIN_URL = "https://api.oplist.org/onedrive/requests"
GRAPH = "https://graph.microsoft.com/v1.0"
ACCESS_REUSE_SECONDS = 900

class OnlineAuthError(Exception):
    def __init__(self, code="authorization_required", retry=30):
        self.code = code
        self.retry = retry
        super().__init__(code)

def token_value(value):
    if not isinstance(value, str) or not value or len(value) > 32768:
        raise OnlineAuthError()
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise OnlineAuthError()
    return value

def status_check(response):
    if response.status_code in (429, 503):
        try:
            retry = max(1, min(3600, int(response.headers.get("Retry-After", "30"))))
        except ValueError:
            retry = 30
        raise OnlineAuthError("authorization_busy", retry)
    if response.status_code != 200:
        raise OnlineAuthError("authorization_unavailable" if response.status_code >= 500
                              or 300 <= response.status_code < 400 else "authorization_required")

async def renew(client, refresh_token):
    """Provider requires GET query parameters; never log request URLs or exceptions."""
    token_value(refresh_token)
    response = await client.get(
        RENEW_URL, params={"refresh_ui": refresh_token, "server_use": "true",
                           "driver_txt": "onedrive_pr"},
        follow_redirects=False)
    status_check(response)
    try:
        data = response.json()
        access = token_value(data.get("access_token"))
        refresh = token_value(data.get("refresh_token"))
    except (ValueError, AttributeError):
        raise OnlineAuthError() from None
    # Official endpoint omits expires_in; bound local reuse and recover on Graph 401.
    return {"provider": "openlist", "access_token": access,
            "refresh_token": refresh, "expires_at": time.time() + ACCESS_REUSE_SECONDS}

async def validate_account(client, access_token, drive_id, root_id):
    """Pin the correct personal drive and a dedicated local public-media folder."""
    if not drive_id or not root_id:
        raise OnlineAuthError("media_root_required")
    headers = {"Authorization": "Bearer " + token_value(access_token)}
    me = await client.get(GRAPH + "/me/drive", headers=headers, follow_redirects=False)
    status_check(me)
    try:
        drive = me.json()
        if str(drive.get("id", "")).lower() != drive_id.lower() or drive.get("driveType") != "personal":
            raise OnlineAuthError("wrong_onedrive_account")
        if root_id == drive.get("root", {}).get("id"):
            raise OnlineAuthError("media_root_required")
        root = await client.get(
            GRAPH + "/drives/" + quote(drive_id, safe="") + "/items/" + quote(root_id, safe=""),
            headers=headers, follow_redirects=False)
        status_check(root)
        folder = root.json()
        if ("folder" not in folder or folder.get("remoteItem") or "root" in folder
                or str(folder.get("parentReference", {}).get("driveId", "")).lower() != drive_id.lower()):
            raise OnlineAuthError("invalid_media_root")
    except (ValueError, AttributeError):
        raise OnlineAuthError("invalid_graph_response") from None
