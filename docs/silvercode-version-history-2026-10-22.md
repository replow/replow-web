# SilverCode Nexus — version history refresh (2026-10-22)

The original article [关于 SilverCode Nexus](https://www.replow.org/post/%E5%85%B3%E4%BA%8Esilvercode-nexus/) is maintained in the production database via `api.4z.ink` and is embedded in public pages during Astro static builds. This document records the safe release-triggering update; it does not duplicate any private article database export.

## Historical and recent releases

- Retained all 23 original historical items covering the legacy v1.1–v3.5 PHP/XML implementation.
- Added 18 evidence-backed modern milestones spanning v26.9.7-u6 through the planned publication at v26.10.22-u12.
- Differentiated Firefly-era (September–early October) and Astro-Koharu-era (mid-October onward) versions.
- Documented the migration to independent API/admin/account apps; web navigation and visual changes; Fanqie downloader; EPUB reader; comment/reply/image support; GitHub Actions static builds; content freshness updates; and sanitized open-source copies.
- Distinguished verified release directory markers from GH commit-level evidence; did not invent changelogs for every patch number.

## Rebuild & verification

This GitHub push runs the existing `astro-build.yml` workflow and regenerates all public article HTML from the live API. The Azure deployer must validate checksums, perform an atomic symlink switch, verify the origin, and purge Cloudflare CDN cache. The pre-edit article was backed up privately at `/www/wwwroot/backup/silvercode-changelog-20261022/` with SHA-256 validation, and must not be pushed into the public repo.

Expected target release on Azure: `v26.10.22-u12`. Confirm the deployed release matches before calling this complete.
