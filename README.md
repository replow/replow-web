# Silune Fanqie Rust parser

Vercel Rust Functions adapter for the public GPL-3.0 `ch6vip/fqapp` novel core,
pinned to `ed7976913ff79f4b50eaa1ea6fc002993a007ef6`. See `UPSTREAM.md`,
`SOURCE_MANIFEST.json`, and `LICENSE` for origin and modifications.

This branch contains parser source only. It does not contain registered devices,
API credentials, account data, downloaded books, or production configuration.

## Runtime

- Official Vercel Rust Runtime 2.4.1, Tokyo region (`hnd1`).
- `FQ_API_TOKEN`: private service credential, at least 32 characters.
- `FQ_STATE_URL`: HTTPS URL for the authenticated durable device snapshot route.
- `FQ_STATE_TOKEN`: separate credential for that route, at least 32 characters.
- Temporary local device snapshots live under `/tmp/silune-fq`; successful
  requests persist updates to the private external snapshot store.
- No Flutter, Android SDK, Java, or unidbg dependency.

Only these authenticated GET/HEAD routes are exposed:

| Route | Existing protocol |
| --- | --- |
| `/health` or `/api/health` | Health and engine identifier |
| `/api/search?key=&page=1&size=10` | `data.books`, `data.hasMore` |
| `/api/book/{book_id}` | Book metadata |
| `/api/toc/{book_id}` | `data.item_data_list`, `serial_count` |
| `/api/chapter/{book_id}/{chapter_id}` | Validated chapter text |
| `/api/batch/{book_id}?offset=0&limit=20` | At most 30 chapters; partial errors retain valid chapters |

All responses disable CDN caching. Ciphertext, missing text, placeholders,
substantial private-use font substitution, and incomplete chapters are rejected.
Unrelated account import, media, comments, and local HTTP server modules have
been excluded from the vendored core.

The Azure business layer continues to own login, job queue, bounded parallel
fetching, TXT/EPUB output, download history, and 31-day artifact retention.
The companion `state-store/fqapp_state.py` mounts a service-authenticated route
inside the isolated preview API, using atomic file writes and bounded snapshot
merging. It is excluded from the Vercel source upload.

## Validation

```sh
cargo test --locked --lib
cargo test --lib --manifest-path vendor/fqapi_core/Cargo.toml
cargo build --locked --bin index
python -m unittest discover -s state-store -p 'test_*.py' -v
```

Use a Python environment with FastAPI for the snapshot-store tests.
Deployment verification must include real search, metadata, directory, chapter,
batch, and TXT/EPUB generation before changing an upstream URL. Keep the
production project domains on the previous deployment until that verification
passes. A Vercel `READY` status alone does not verify upstream availability.
