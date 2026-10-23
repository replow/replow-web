# fqapp Vercel preview verification

Verified 2026-10-23 UTC.

- Parser source commit: c018f8417b616bc2a1f89939d6699e71fb81acd4.
- Deployment: dpl_Cd4dN5Fi1cGPhx98NZYjGSgDnwQJ (READY, preview).
- Parser: https://fanqie-api-replow-o17xjoaad-system6623-9072.vercel.app (private service authentication required).
- User-facing preview: https://www.preview.replow.org/fanqie/.
- Production fq.4z.ink remains on dpl_HCNcZVeW4nPMG3rJX7WuTgPrKfYH; confirmed after preview activation.

## Live checks

| Check | Result |
| --- | --- |
| Parser health without credential | 401 |
| Authenticated health | 200, fqapp-rust |
| Search | 200; multiple matching books |
| Metadata and directory | 200; 1,928 catalog entries in test book |
| Single chapter | 200; 2,124 characters |
| Three-chapter batch | 200; 2,124 / 2,475 / 2,549 characters; no failed IDs |
| Go worker to TXT | completed; 3 chapters; 20,976 bytes |
| EPUB from shared chapter cache | completed; reused 3 chapters; 13,680 bytes |
| EPUB validation | valid ZIP, mimetype, XML and 3 spine entries |
| Preview page | 200 |
| Preview session/search without login | 401 |
| Preview file route | 200 with attachment header for temporary fixture |
| File directory / hidden file | 404 / 403 |
| Isolated preview worker | active, fresh heartbeat |

Download verification used a temporary isolated SQLite store and download directory, removed afterwards. No user history or accounts were created. Chapter content and credentials are excluded from this report. Timings are individual smoke-test measurements, not throughput benchmarks.

## Preview operations

Preview API and worker read their existing private EnvironmentFile. Set FQ_UPSTREAM_BASE to the preview parser, FQ_UPSTREAM_TOKEN to its private API token, FQ_METADATA_FAST=0, and FQ_GO_FETCH_BINARY to the existing bounded Go downloader. FQ_STATE_DIR and FQ_DOWNLOAD_DIR must point to isolated preview paths. FQ_PUBLIC_BASE points to the preview /fq-files route.

The preview worker service is replow-preview-fq-worker.service; the API service is replow-preview-api.service. Nginx serves only filenames matching the immutable artifact and cover patterns from the preview download directory. Directory listing is disabled. The snapshot API remains service authenticated and separate from user login.

The authenticated browser login-to-download flow has not been exercised with a real user session; server-side generation, public route delivery, and unauthenticated access controls were checked independently. The existing 31-day cleanup policy is retained.
