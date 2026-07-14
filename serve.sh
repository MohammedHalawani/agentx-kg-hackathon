#!/usr/bin/env bash
# Build the frontend, then serve the whole app (UI + API) from FastAPI on :8000.
# Needs .env filled in at the repo root (Neo4j creds + LLM key, at minimum).
set -euo pipefail
cd "$(dirname "$0")"

( cd frontend && npm install && npm run build )
exec uv run --project chat uvicorn --app-dir backend main:app --host 127.0.0.1 --port 8000
