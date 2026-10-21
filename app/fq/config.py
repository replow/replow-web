from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path


@dataclass(frozen=True)
class Config:
    state_dir: Path
    download_dir: Path
    upstream_base: str
    upstream_token: str
    jwt_secret: str
    public_base: str
    token_seconds: int = 900
    request_interval: float = 2.0
    batch_size: int = 20
    go_fetch_binary: str = ""
    download_concurrency: int = 2
    shard_size: int = 20
    shard_interval_ms: int = 300
    shard_retries: int = 3
    metadata_fast: bool = False

    def prepare(self):
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.download_dir.mkdir(parents=True, exist_ok=True, mode=0o755)


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config(
        state_dir=Path(os.environ.get("FQ_STATE_DIR", "/data/fq-state")),
        download_dir=Path(os.environ.get("FQ_DOWNLOAD_DIR", "/data/fq-download")),
        upstream_base=os.environ.get("FQ_UPSTREAM_BASE", "https://fq.example.com").rstrip("/"),
        upstream_token=os.environ.get("FQ_UPSTREAM_TOKEN", ""),
        jwt_secret=os.environ.get("FQ_RELAY_JWT_SECRET", ""),
        public_base=os.environ.get("FQ_PUBLIC_BASE", "https://down.example.com/fq").rstrip("/"),
        token_seconds=max(60, min(3600, int(os.environ.get("FQ_TOKEN_SECONDS", "900")))),
        request_interval=max(0, float(os.environ.get("FQ_REQUEST_INTERVAL", "2"))),
        batch_size=max(1, min(30, int(os.environ.get("FQ_BATCH_SIZE", "20")))),
        go_fetch_binary=os.environ.get("FQ_GO_FETCH_BINARY", ""),
        download_concurrency=max(1, min(8, int(os.environ.get("FQ_DOWNLOAD_CONCURRENCY", "2")))),
        shard_size=max(1, min(30, int(os.environ.get("FQ_SHARD_SIZE", "20")))),
        shard_interval_ms=max(0, min(5000, int(os.environ.get("FQ_SHARD_INTERVAL_MS", "300")))),
        shard_retries=max(1, min(5, int(os.environ.get("FQ_SHARD_RETRIES", "3")))),
        metadata_fast=os.environ.get("FQ_METADATA_FAST", "1").lower() in ("1", "true", "yes"),
    )
