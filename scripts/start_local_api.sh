#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

echo "Syncing dependencies..."
uv sync

echo "Starting API at http://127.0.0.1:8000"
exec uv run uvicorn server.app.main:app --host 127.0.0.1 --port 8000
