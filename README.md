# FastAPI service source (sanitized)

Install: `python -m pip install -r requirements.txt`. Configure a local-only database and settings with a new `.env` based on `.env.example`.

Local development: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`.

`alembic.ini` points to a disposable local SQLite file by default; configure a dedicated development MySQL database and migrations as appropriate before applying them. Production connection strings, uploaded content, OAuth signing keys, and well-known verification files are intentionally not included.

**Never run database migrations against the production database from this clone.**
