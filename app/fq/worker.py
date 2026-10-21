from __future__ import annotations

import fcntl
import json
import signal
import time

from .books import process_book
from .client import Client, UpstreamError
from .config import get_config
from .store import Store
from .artifacts import cleanup


def run():
    config = get_config()
    if not config.upstream_token:
        raise SystemExit("FQ upstream credential is not configured")
    store, client = Store(config), Client(config)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (config.state_dir / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another FQ worker is already running")
        store.recover()
        last_cleanup = 0
        while not stopping:
            if time.time()-last_cleanup>3600:
                cleanup(store);last_cleanup=time.time()
            (config.state_dir / "worker.heartbeat").write_text(str(time.time()))
            job = store.claim()
            if job is None:
                time.sleep(1)
                continue
            try:
                process_book(config, store, job, client)
                print(json.dumps({"job_id": job["id"], "event": "completed"}), flush=True)
            except UpstreamError as error:
                store.fail(job, error.reason, error.retryable)
                print(json.dumps({"job_id": job["id"], "event": "retry" if error.retryable else "failed", "reason": error.reason}), flush=True)
            except Exception:
                # Log neither request headers nor arbitrary upstream exception text.
                store.fail(job, "download_processing_failed")
                print(json.dumps({"job_id": job["id"], "event": "retry", "reason": "download_processing_failed"}), flush=True)


if __name__ == "__main__":
    run()
