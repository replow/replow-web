# Replow Services (Sanitized Open-Source Copies)

This directory contains development-time source snapshots, not compiled deployment builds:

- `admin/` — Vue + Vite administrative console (derived from pure-admin; MIT license retained).
- `account/` — Vue + Vite account portal.
- `api/` — FastAPI server, Alembic migrations, and tests.

Security: These folders intentionally exclude production .env files, database exports,
secrets, private keys, uploaded content, local storage, logs, node_modules, Python
virtual environments, and compiled bundles. Public-facing example domains use
`example.com` and development APIs default to `http://localhost:8000`.
Copy each `.env.example` to `.env` and configure new, development-only
credentials. NEVER point a public development clone at the production database.
Do not use default/example credentials in production.

## Build / development

- Admin: `cd services/admin && pnpm install --frozen-lockfile && pnpm build`.
- Account: `cd services/account && pnpm install --frozen-lockfile && pnpm build`.
- API: `cd services/api && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`.
  Configure development environment and database before running FastAPI/Alembic.
  Production startup, migration, and deployment configurations are intentionally excluded.

The admin project includes its original MIT license; examine the repository-wide
license and third-party dependencies before distributing derivative works.
The snapshot is provided for source reference; it is not a backup of operational secrets.
