# Sanitized source release — Account

This branch root contains the complete **pre-build Vue / Vite account-center source**, including src/, public assets, TypeScript/Vite config and pnpm lockfile.

- Production .env files, personal user data, caches, dist/, and deployment secrets were excluded.
- Copy .env.example to .env and configure a separate development-only API endpoint.
- Build: pnpm install --frozen-lockfile && pnpm build.
- Real production hostnames have been replaced by example.com values.

Never commit real secrets or connect this public clone to a production database.
