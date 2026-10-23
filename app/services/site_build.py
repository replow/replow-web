"""A fixed file request; only the operator-configured worker can deploy."""
import fcntl
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import text

STATE_DIR = Path(os.environ.get('SITE_BUILD_STATE_DIR', '/data/replow-next/build-state'))
STATUS_FILE = STATE_DIR / 'status.json'
REQUEST_FILE = STATE_DIR / 'request'
UNIT = os.environ.get('SITE_BUILD_UNIT', 'replow-koharu-build.service')


def _read(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def site_build_status(db=None):
    data = _read(STATUS_FILE)
    result = {key: data.get(key, '') for key in
              ('status', 'version', 'error', 'started_at', 'finished_at', 'run_url', 'commit', 'stage')}
    result['status'] = result['status'] or 'idle'
    result['environment'] = os.environ.get('APP_ENV', 'staging')
    result['site_url'] = os.environ.get('SITE_PUBLIC_URL', 'https://www.replow.org')
    deployed = _read(STATE_DIR / 'deployed.json')
    result['last_published_at'] = deployed.get('finished_at') or (data.get('finished_at') if data.get('status') == 'success' else '')
    result['published_version'] = deployed.get('version', '')
    if db is not None:
        saved = db.execute(text("SELECT MAX(updated_at) FROM articles WHERE status='published'")).scalar()
        result['content_saved_at'] = saved.isoformat() + 'Z' if hasattr(saved, 'isoformat') else str(saved or '')
        published_through = deployed.get('content_cutoff_at') or deployed.get('started_at') or ''
        try:
            cutoff = datetime.fromisoformat(published_through.replace('Z', '+00:00')).replace(tzinfo=None)
            result['has_unpublished_changes'] = bool(saved and saved > cutoff)
        except (ValueError, TypeError):
            result['has_unpublished_changes'] = bool(saved)
    return result


def start_site_build():
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / 'request.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = site_build_status()
            if current['status'] in {'queued', 'building', 'deploying'}:
                return current
            active = subprocess.run(['/usr/bin/systemctl', 'is-active', UNIT],
                                    capture_output=True, text=True, timeout=5, check=False).stdout.strip()
            if active in ('active', 'activating'):
                return current
            now = datetime.now(timezone.utc).isoformat()
            current.update(status='queued', stage='queued', error='', started_at=now,
                           finished_at='', version='', commit='', run_url='')
            temp = STATUS_FILE.with_suffix('.tmp')
            temp.write_text(json.dumps(current)); temp.replace(STATUS_FILE)
            REQUEST_FILE.write_text(now + '\n')
            return current
    except (OSError, subprocess.SubprocessError) as error:
        raise HTTPException(503, 'site_build_unavailable') from error
