"""One-time operator authorization, never an anonymous website endpoint."""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import app

PENDING = app.TOKEN_FILE.with_name("device-flow.json")
AUTH = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
SCOPE = "https://graph.microsoft.com/Files.Read offline_access"

def save_pending(data):
    PENDING.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(PENDING, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream)

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "poll"))
    parser.add_argument("--client-id", help="Your own registered public-client application ID")
    args = parser.parse_args()
    if not app.DRIVE or not app.ROOT:
        parser.error("Set OD_DRIVE_ID and OD_ROOT_ITEM_ID before authorization.")
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        if args.action == "start":
            if not args.client_id:
                parser.error("--client-id is required for start")
            response = await client.post(AUTH + "/devicecode",
                                         data={"client_id": args.client_id, "scope": SCOPE})
            if response.status_code != 200:
                print("Could not start authorization; check the app registration and public-client setting.")
                return 1
            flow = response.json()
            flow.update(client_id=args.client_id,
                        expires_at=time.time() + flow["expires_in"],
                        next_poll=time.time() + flow.get("interval", 5))
            save_pending(flow)
            print(flow["message"])
            print("After completing Microsoft's sign-in, run: python authorize.py poll")
            return 0
        try:
            flow = json.loads(PENDING.read_text())
        except (OSError, ValueError):
            print("No pending authorization. Start a new flow.")
            return 1
        if flow["expires_at"] <= time.time():
            PENDING.unlink(missing_ok=True)
            print("The sign-in request expired. Start a new flow.")
            return 1
        if time.time() < flow.get("next_poll", 0):
            print("Please wait before polling again.")
            return 2
        response = await client.post(AUTH + "/token", data={
            "client_id": flow["client_id"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": flow["device_code"]})
        data = response.json()
        if response.status_code != 200:
            error = data.get("error")
            if error in ("authorization_pending", "slow_down"):
                interval = flow.get("interval", 5) + (5 if error == "slow_down" else 0)
                flow.update(interval=interval, next_poll=time.time()+interval)
                save_pending(flow)
                print("Authorization is still pending.")
                return 2
            PENDING.unlink(missing_ok=True)
            print("Authorization failed or was declined. Start a new flow if needed.")
            return 1
        headers = {"Authorization": "Bearer " + data["access_token"]}
        response = await client.get(app.GRAPH + "/me/drive", headers=headers)
        if response.status_code != 200 or str(response.json().get("id", "")).lower() != app.DRIVE.lower():
            PENDING.unlink(missing_ok=True)
            print("The signed-in OneDrive does not match the configured drive. No credentials saved.")
            return 1
        root = await client.get(app.GRAPH + "/drives/" + app.quote(app.DRIVE, safe="") +
                                "/items/" + app.quote(app.ROOT, safe=""), headers=headers)
        if root.status_code != 200 or "folder" not in root.json() or root.json().get("remoteItem"):
            PENDING.unlink(missing_ok=True)
            print("The configured media root is not an accessible local folder. No credentials saved.")
            return 1
        if not data.get("refresh_token"):
            PENDING.unlink(missing_ok=True)
            print("No offline refresh token was issued. No credentials saved.")
            return 1
        app.atomic_token({"client_id": flow["client_id"], "access_token": data["access_token"],
                          "refresh_token": data["refresh_token"],
                          "expires_at": time.time()+data.get("expires_in", 3600)})
        PENDING.unlink(missing_ok=True)
        print("Authorization saved privately. Tokens were not printed.")
        return 0

if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except (httpx.HTTPError, ValueError, OSError, KeyError):
        print("Authorization could not complete. Check connectivity and local state; no token output.")
        raise SystemExit(1)
