"""Private operator CLI for OpenList Online API authorization. Never paste tokens in chat."""
import argparse
import asyncio
import getpass
import json
import os
import warnings
from urllib.parse import parse_qs, urlsplit

import httpx
import app
from openlist_auth import AUTH_PAGE, LOGIN_URL, OnlineAuthError, renew, validate_account

def read_refresh_token():
    # Text-mode r+ requires seeking and rejects a valid terminal on Python 3.9.
    fd = os.open("/dev/tty", os.O_RDWR)
    os.close(fd)
    # Refuse getpass's echoing fallback if terminal access changes after the check.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass("Paste the OpenList refresh token (hidden): ").strip()
        except getpass.GetPassWarning:
            raise OSError("Hidden terminal input is unavailable") from None


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("probe", "import", "check"))
    args = parser.parse_args()
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5),
                                 follow_redirects=False) as client:
        if args.action == "probe":
            response = await client.get(LOGIN_URL, params={
                "driver_txt": "onedrive_pr", "server_use": "true", "server_set": "true"})
            if response.status_code != 200:
                print("Official authorization entry is unavailable.")
                return 1
            data = response.json()
            url = urlsplit(data.get("text", ""))
            if url.scheme != "https" or url.hostname != "login.microsoftonline.com":
                print("Official authorization entry did not return the expected Microsoft host.")
                return 1
            print("Official authorization entry reachable; Microsoft sign-in host verified.")
            print("Requested scopes:", " ".join(parse_qs(url.query).get("scope", [])))
            print("Open this page in your own browser:", AUTH_PAGE)
            print("Select OneDrive Personal and use OpenList-provided parameters.")
            print("The consent currently includes file read/write and offline access.")
            return 0

        if not app.DRIVE or not app.ROOT:
            parser.error("Configure OD_DRIVE_ID and OD_ROOT_ITEM_ID.")
        if args.action == "import":
            try:
                raw = read_refresh_token()
            except OSError:
                print("Use an interactive terminal for hidden token input.")
                return 1
            data = await renew(client, raw)
            await validate_account(client, data["access_token"], app.DRIVE, app.ROOT)
            data.update(drive_id=app.DRIVE, root_item_id=app.ROOT)
            app.atomic_token(data)
            del raw
            print("OneDrive account and dedicated folder verified; authorization saved privately.")
            return 0

        try:
            previous = json.loads(app.TOKEN_FILE.read_text())
        except (OSError, ValueError):
            print("No saved authorization. Import it first.")
            return 1
        if previous.get("provider") != "openlist":
            print("Saved authorization is not an OpenList Online API authorization.")
            return 1
        if previous.get("drive_id") != app.DRIVE or previous.get("root_item_id") != app.ROOT:
            print("Saved authorization does not match the configured media root.")
            return 1
        # Check uses the same locked persistence path as the runtime.
        # Force an actual renewal so this does not merely validate cached credentials.
        media = app.Media(client)
        access = await media.token(force=True)
        await validate_account(client, access, app.DRIVE, app.ROOT)
        print("Live token renewal and correct OneDrive media root verified.")
        return 0

if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except OnlineAuthError as error:
        print("Authorization not completed:", error.code)
        raise SystemExit(1)
    except app.Failure as error:
        print("Authorization not completed:", error.code)
        raise SystemExit(1)
    except (httpx.HTTPError, OSError, ValueError, KeyError, EOFError):
        print("Authorization could not complete. Credentials and upstream details were not printed.")
        raise SystemExit(1)
