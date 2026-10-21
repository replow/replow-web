# Sanitized source release — Admin

This branch's repository root contains the complete **pre-build Vue / PureAdmin source snapshot** for the management console.

- Includes src/, build/, public/, tests/, Vite/TypeScript configs, pnpm lockfile, Dockerfile and upstream MIT license.
- Deliberately excludes production .env credentials, real user content, compiled dist/, caches, and rollback data.
- Development config: copy .env.example to .env and use only local test credentials.
- Build: pnpm install --frozen-lockfile && pnpm build.
- Production domain strings were replaced with example.com placeholders. Configure development API URLs before running.
- This is not an export of live users, databases, or production deployment credentials.

Never commit real secrets or use production databases in a public clone.
