# Public source export policy

Published from a **new isolated working copy**, without editing production directories or reusing production Git history.

## Kept

- Admin Vue source (`src/`), tests, static UI assets, build scripts, Dockerfile, lockfile, Vite/TS/ESLint configs and upstream attribution/license.
- Account Vue source (`src/`), assets, lockfile and build config.
- API Python application, migrations, tests, OAuth HTML templates and requirements.

## Deliberately withheld

- Real `.env*`, credentials, API/OAuth secrets, database passwords and exports.
- Runtime `storage`, uploads, logs, caches, Python virtual environments, node_modules, dist bundles and historical rollback/backup files.
- Site ownership verification tokens (for example `static/.well-known`), signing keys and internal operational scripts.
- Current production hostnames: client defaults and CORS samples now target `example.com` and development localhost.
- Real or representative long JWT strings from mock/SSO examples were replaced with inert placeholders.

Use only fresh local development secrets and databases. A separate scan is required for every future public update.

## Limitations

This is a sanitized source snapshot, not a production deployment bundle or operational backup. Some integrations require environment configuration and external services to run.
