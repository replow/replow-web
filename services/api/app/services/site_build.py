"""Fixed, authenticated entry point for the Koharu static build service."""
import json
import subprocess
import time
from pathlib import Path
from fastapi import HTTPException

STATUS_FILE = Path("/data/replow-next/build-state/status.json")
REQUEST_FILE = Path("/data/replow-next/build-state/request")
UNIT = "replow-koharu-build.service"

def site_build_status() -> dict:
    try:
        raw = json.loads(STATUS_FILE.read_text())
        return {key: raw.get(key, "") for key in ("status", "version", "error", "started_at", "finished_at")}
    except (OSError, ValueError):
        return {"status": "idle", "version": "", "error": ""}

def start_site_build() -> dict:
    try:
        active = subprocess.run(
            ["/usr/bin/systemctl", "is-active", UNIT],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
        if active in ("active", "activating"):
            return site_build_status()
        # systemd watches this fixed request file. The API keeps NoNewPrivileges
        # and can neither choose a unit nor supply a command or build arguments.
        REQUEST_FILE.write_text(str(time.time_ns()) + "\n")
        return {"status": "queued", "version": "", "error": ""}
    except (OSError, subprocess.SubprocessError) as error:
        raise HTTPException(status_code=503, detail="site_build_unavailable") from error
