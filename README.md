# Replow Web (Astro)

This repository contains **only** the public Astro/Koharu frontend of Replow Web, including the reader, EPUB bookshelf, gallery, and Fanqie interface.

**Not included:** `admin.replow.org`, `account.replow.org`, FastAPI services, backend databases, environment credentials, internal deployment data, and server backups.

## Build

- Node.js >= 22.20.0
- pnpm 10.28.2
- `pnpm install --frozen-lockfile`
- `pnpm check`
- `API_BASE_URL=https://api.4z.ink REPLOW_RELEASE=v26.10.21-u4 pnpm build`

GitHub Actions checks the Astro code and builds an artifact on each push to `main` and via manual dispatch. It **does not automatically deploy** the production website or expose deployment credentials. EPUB books remain in users' browser storage.

Based on the upstream [astro-koharu](https://github.com/cosZone/astro-koharu) project, with custom Replow frontend features.
