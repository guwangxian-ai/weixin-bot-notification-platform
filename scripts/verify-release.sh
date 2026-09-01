#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
UV_BIN=${UV_BIN:-uv}
if ! command -v "$UV_BIN" >/dev/null 2>&1 && [[ -x .venv/bin/uv ]]; then
  UV_BIN=.venv/bin/uv
fi
"$UV_BIN" sync --frozen --dev
npm --prefix web ci --no-audit --no-fund
.venv/bin/ruff check app tests alembic scripts skill/employee-video-notification/scripts/client.py
.venv/bin/mypy app
.venv/bin/pytest -q
npm --prefix web run lint
npm --prefix web run test
npm --prefix web run build

RELEASE_DB=$(mktemp "${TMPDIR:-/tmp}/weixin-bot-platform.XXXXXX.db")
trap 'rm -f "$RELEASE_DB"' EXIT
APP_DATABASE_URL="sqlite:///$RELEASE_DB" .venv/bin/alembic upgrade head
