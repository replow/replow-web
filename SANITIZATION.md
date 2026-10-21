# Sanitized source release — API

This branch root contains the complete **pre-deployment FastAPI application source**, Alembic migrations, tests, HTML templates, and requirements.

- Excludes production .env credentials, OAuth signing secrets, user data, object uploads, caches, backups, rollback files and verification tokens.
- Development config: copy .env.example to .env, configure a separate test database, and generate new development-only secrets.
- Install: python -m venv .venv; activate your environment; pip install -r requirements.txt.
- Run development: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000.
- API endpoints and allowed origins use local/example placeholders where appropriate.

Never execute Alembic migrations against a production database from this branch.
