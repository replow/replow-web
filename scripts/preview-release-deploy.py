#!/usr/bin/env python3
"""Deploy signed-by-checksum preview builds while keeping the legacy preview builder."""

import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

BASE = Path('/data/replow-preview')
RELEASES = BASE / 'releases'
WWW = BASE / 'www'
LOCK = BASE / 'build-state' / 'worker.lock'
API = 'https://api.github.com/repos/replow/replow-web/releases?per_page=30'
ARCHIVE = 'preview-astro.tar.gz'
MAX_COMPRESSED = 250 * 1024 * 1024
MAX_UNPACKED = 650 * 1024 * 1024
REPLACEMENTS = {
    'https://www.replow.org': 'https://www.preview.replow.org',
    'https://account.replow.org': 'https://account.preview.replow.org',
    'https://admin.replow.org': 'https://admin.preview.replow.org',
    'https://api.4z.ink': 'https://www.preview.replow.org',
}


def fetch(url, target=None):
    headers = {'User-Agent': 'replow-preview-deployer/1.0'}
    headers['Accept'] = 'application/vnd.github+json' if 'api.github.com' in url else 'application/octet-stream'
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=55) as response:
        if target is None:
            return response.read(2 * 1024 * 1024)
        length = 0
        with target.open('wb') as file:
            while chunk := response.read(1024 * 1024):
                length += len(chunk)
                if length > MAX_COMPRESSED:
                    raise ValueError('Preview archive is unexpectedly large')
                file.write(chunk)


def origin(path):
    process = subprocess.run(
        ['curl', '--noproxy', '*', '--silent', '--show-error', '--fail',
         '--max-time', '15', '--resolve', 'www.preview.replow.org:443:127.0.0.1',
         'https://www.preview.replow.org' + path, '-o', '/dev/null'],
        capture_output=True, text=True, timeout=20,
    )
    return process.returncode == 0


def safe_extract(archive, destination):
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        if len(members) > 45000 or sum(m.size for m in members) > MAX_UNPACKED:
            raise ValueError('Preview archive exceeds extraction limits')
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):
                raise ValueError('Unsafe archive member: ' + member.name)
        tar.extractall(destination, members=members)


def isolate(root):
    for file in root.rglob('*'):
        if file.is_file() and file.suffix in ('.html', '.js', '.json', '.xml', '.css'):
            value = file.read_text()
            for production, preview in REPLACEMENTS.items():
                value = value.replace(production, preview)
            if file.suffix == '.html' and '</head>' in value:
                value = value.replace('</head>', '<meta name="robots" content="noindex,nofollow"></head>')
            file.write_text(value)


def latest_preview_release():
    releases = json.loads(fetch(API))
    candidates = [
        release for release in releases
        if release.get('prerelease') and not release.get('draft')
        and re.fullmatch(r'preview-build-[0-9]+', release.get('tag_name', ''))
    ]
    return max(candidates, key=lambda item: int(item['tag_name'].rsplit('-', 1)[1]), default=None)


def main():
    RELEASES.mkdir(exist_ok=True)
    LOCK.parent.mkdir(exist_ok=True)
    with LOCK.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Legacy preview build in progress; will retry next poll')
            return 0

        release = latest_preview_release()
        if not release:
            print('No verified preview builds published yet')
            return 0
        tag = release['tag_name']
        active = WWW.resolve(strict=True)
        marker = active / '.preview-source-release'
        if marker.exists():
            previous_tag = marker.read_text().strip()
            previous_number = re.fullmatch(r'preview-build-([0-9]+)', previous_tag)
            next_number = int(tag.rsplit('-', 1)[1])
            if previous_number and int(previous_number.group(1)) > next_number:
                print('Refusing to downgrade active preview')
                return 0
            if previous_tag == tag:
                print('Already deployed:', tag)
                return 0

        assets = {asset['name']: asset['browser_download_url'] for asset in release.get('assets', [])}
        if ARCHIVE not in assets or ARCHIVE + '.sha256' not in assets:
            raise ValueError('Preview release has no verified archive or checksum')
        manifest = fetch(assets[ARCHIVE + '.sha256']).decode('ascii').strip()
        match = re.fullmatch(r'([0-9a-f]{64})\s+\*?preview-astro\.tar\.gz', manifest)
        if not match:
            raise ValueError('Invalid preview SHA-256 manifest')
        if not origin('/'):
            raise RuntimeError('Preview origin preflight failed')
        if subprocess.run(['sudo', '-n', 'nginx', '-t'], capture_output=True).returncode:
            raise RuntimeError('nginx config check failed')

        dest = RELEASES / ('gh-' + tag) / 'dist'
        if dest.exists():
            raise ValueError('Release directory exists without an active marker; investigate before retry')
        with tempfile.TemporaryDirectory(prefix='.preview-release-incoming-', dir=RELEASES) as tmp:
            temp = Path(tmp)
            archive = temp / ARCHIVE
            fetch(assets[ARCHIVE], archive)
            hasher = hashlib.sha256()
            with archive.open('rb') as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b''):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            if digest != match.group(1):
                raise ValueError('Preview archive checksum mismatch')
            staging = temp / 'dist'
            staging.mkdir()
            safe_extract(archive, staging)
            needed = ('index.html', '404.html', 'reading/index.html',
                      'fanqie/index.html', 'friends/index.html', 'pagefind/pagefind.js')
            if any(not (staging / path).is_file() for path in needed) or not (staging / '_astro').is_dir():
                raise ValueError('Incomplete static preview archive')
            isolate(staging)
            (staging / '.preview-source-release').write_text(tag + '\n')
            dest.parent.mkdir()
            os.replace(staging, dest)

        replacement = BASE / '.www-release-next'
        switched = False
        try:
            if replacement.is_symlink():
                replacement.unlink()
            replacement.symlink_to(dest)
            os.replace(replacement, WWW)
            switched = True
            if not all(origin(path) for path in ('/', '/reading/', '/fanqie/')):
                raise RuntimeError('Preview smoke check failed')
            print('Deployed', tag, 'sha256', digest[:16], 'at', dt.datetime.now(dt.timezone.utc))
        except Exception:
            if switched:
                if replacement.is_symlink():
                    replacement.unlink()
                replacement.symlink_to(active)
                os.replace(replacement, WWW)
                print('Preview rolled back to', active, file=sys.stderr)
            raise
        finally:
            if replacement.is_symlink():
                replacement.unlink()
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('Preview deployment safely rejected:', error, file=sys.stderr)
        sys.exit(1)
