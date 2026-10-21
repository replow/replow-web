"""Stream Go shard results into the existing validated, atomic chapter cache."""
import json
import os
import re
import selectors
import subprocess
import time

from .client import UpstreamError


def download_shards(config, book_id, catalog_ids, positions, save):
    # Prioritize the first uncached chapter rather than making users wait for
    # a full 20-chapter upstream batch before the first visible progress event.
    # The following shards still run concurrently in the same bounded Go pool.
    groups = [[positions[0]]] if positions else []
    for position in positions[1:]:
        if (len(groups) > 1 and position == groups[-1][-1] + 1
                and len(groups[-1]) < config.shard_size):
            groups[-1].append(position)
        else:
            groups.append([position])
    if not groups:
        return
    plan = {"book_id": book_id, "total": len(catalog_ids), "shards": [
        {"offset": group[0], "ids": [catalog_ids[i] for i in group]} for group in groups]}
    expected = {i: catalog_ids[i] for i in positions}
    environment = {"PATH": os.defpath, "FQ_UPSTREAM_BASE": config.upstream_base,
        "FQ_UPSTREAM_TOKEN": config.upstream_token,
        "FQ_DOWNLOAD_CONCURRENCY": str(config.download_concurrency),
        "FQ_SHARD_INTERVAL_MS": str(config.shard_interval_ms),
        "FQ_SHARD_RETRIES": str(config.shard_retries)}
    try:
        process = subprocess.Popen([config.go_fetch_binary], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment)
    except OSError:
        raise UpstreamError("go_download_engine_unavailable") from None
    finished, received, buffer = False, set(), b""
    try:
        # The Go reader consumes stdin before emitting data; this cannot deadlock.
        process.stdin.write(json.dumps(plan, separators=(",", ":")).encode())
        process.stdin.close()
        selector = selectors.DefaultSelector()
        try:
            selector.register(process.stdout, selectors.EVENT_READ)
            last_event = time.monotonic()
            while True:
                ready = selector.select(timeout=1)
                if not ready:
                    if time.monotonic() - last_event > 120:
                        raise UpstreamError("go_download_engine_stalled")
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if len(line) > 4_100_000:
                        raise UpstreamError("go_download_protocol_error", False)
                    event = json.loads(line)
                    last_event = time.monotonic()
                    kind = event.get("type")
                    if finished:
                        raise UpstreamError("go_download_protocol_error", False)
                    if kind == "heartbeat":
                        continue
                    if kind == "error":
                        reason = event.get("reason", "")
                        if not isinstance(reason, str) or not re.fullmatch(r"[a-z_]{1,80}", reason):
                            reason = "go_download_failed"
                        raise UpstreamError(reason, event.get("retryable") is True)
                    if kind == "complete":
                        if event.get("done") != len(expected) or len(received) != len(expected):
                            raise UpstreamError("go_download_incomplete")
                        finished = True
                        continue
                    if kind != "chapter":
                        raise UpstreamError("go_download_protocol_error", False)
                    offset = event.get("offset", 0)
                    chapter = event.get("chapter")
                    if not isinstance(offset, int) or offset not in expected or offset in received or not isinstance(chapter, dict) or str(chapter.get("chapterId")) != expected[offset]:
                        raise UpstreamError("unexpected_or_duplicate_chapter", False)
                    save(chapter, expected[offset])
                    received.add(offset)
                if len(buffer) > 4_100_000:
                    raise UpstreamError("go_download_protocol_error", False)
        finally:
            selector.close()
        if process.wait(timeout=10) != 0 or not finished or buffer:
            raise UpstreamError("go_download_incomplete")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise UpstreamError("go_download_engine_failed") from None
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if not process.stdin.closed:
            process.stdin.close()
        process.stdout.close()
