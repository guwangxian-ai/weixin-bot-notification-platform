# Weixin Bot Notification Platform — Agent Rules

## Scope

- This repository is a shared, multi-company notification service.
- Every business record and authorization path must remain tenant-scoped by `company_id`.
- Seed tenants are examples only; the platform must support arbitrary companies.
- Keep changes focused and preserve backward-compatible APIs unless a migration plan is included.

## Security invariants

- Never expose Weixin tokens, context tokens, Bot secrets, password hashes, signing keys, encryption keys, service tokens, or complete Weixin user/chat identifiers through APIs, HTML, logs, Skill output, tests, or Git.
- Resolve recipients by stable internal IDs. Never infer recipients from display names.
- All mutations require authenticated RBAC authorization, CSRF protection where applicable, and backend tenant checks.
- User deletion is soft deletion; preserve historical assets, deliveries, and audit records.
- Real Weixin delivery is permitted only through encrypted, independently bound Bot credentials and the dedicated Bot worker. Never reuse an unrelated management Bot token.
- Platform-maintainer credentials must not be distributed to business clients. Business integrations use tenant-scoped API clients and only documented endpoints.
- Deterministic platform commands must not invoke an LLM. AI-assisted actions, if added, must be explicit and auditable.

## Workflow and release gates

- Use Alembic migrations for schema changes and tests for behavior changes.
- Before release run pytest, Ruff, MyPy, frontend lint/tests/build, an Alembic upgrade against a fresh database, health checks, and browser verification.
- Before production deployment back up the source revision, SQLite database through its online backup API, uploads, environment configuration, systemd units, and Nginx configuration. Verify hashes and SQLite integrity before switching versions.
- Run `nginx -t` before every Nginx reload. Preserve an existing public route unless a compatibility redirect is verified.
- Never commit `.env`, databases, WAL/SHM files, uploads, logs, backups, frontend dependencies, generated assets, caches, virtual environments, or internal deployment records.

## Stack and commands

- Stack: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite WAL, React, TypeScript, Vite, Uvicorn, systemd, Nginx.
- Install: `uv sync --frozen --dev` and `npm --prefix web ci`.
- Lint/type/test: `.venv/bin/ruff check app tests alembic scripts skill/employee-video-notification/scripts/client.py`, `.venv/bin/mypy app`, `.venv/bin/pytest -q`, `npm --prefix web run lint`, `npm --prefix web run test`.
- Build: `npm --prefix web run build`.
- Migrate: `.venv/bin/alembic upgrade head`; create `data/` first for the default SQLite URL.
- Local start: `.venv/bin/uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8091`.
- Release verification: `scripts/verify-release.sh`.

## Runtime boundaries

- The application listens on `127.0.0.1:8091` by default. Production exposure must use an HTTPS reverse proxy.
- Never infer live-delivery readiness from configuration alone. Verify `/api/v1/health`, active bindings, the API service, the Bot worker, and sanitized logs.
- `sent` requires a successful upstream send result; `confirmed` additionally requires user confirmation.
- Every Bot token must have only one active local consumer.
