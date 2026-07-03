# aisecretary

Transaction database service for Hermes AI agent. MCP tools for CRUD + summary, Docker-packaged with persistent SQLite storage.

## Architecture

```
┌─ myopenclaw docker-compose ───────────────────────┐
│                                                    │
│  Hermes ──MCP/SSE──► aisecretary:8000              │
│                      ├─ 6 MCP tools (self-desc)    │
│                      ├─ REST API /api/*             │
│                      └─ GET /health                 │
│                         │                          │
│                    volume: SQLite (persistent)      │
└────────────────────────────────────────────────────┘
```

- **MCP**: Hermes auto-discovers tools — no manual contract maintenance
- **REST API**: Thin CLI (`aisecretary`) calls `/api/*` like `gh` calls GitHub API
- **/health**: Docker healthcheck + myopenclaw monitoring
- **Data**: SQLite file at `~/.myagentdata/aisecretary/transactions.sqlite`, volume-mounted

## Quick Start

```bash
# Build and start
docker compose up -d

# Verify
curl http://localhost:8000/health
# → {"status":"ok"}

# CLI (optional — for host-side debugging)
python3 scripts/aisecretary_cli.py list
python3 scripts/aisecretary_cli.py create --title "测试事务" --owner "Owen"
python3 scripts/aisecretary_cli.py summary
```

Environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_PATH` | `/data/transactions.sqlite` | SQLite file path (inside container) |
| `AISECRETARY_URL` | `http://localhost:8000/api` | API base URL (for CLI) |

## MCP Tools

Hermes connects to `http://aisecretary:8000/mcp` (SSE transport) and discovers:

| Tool | Description |
|------|-------------|
| `create_transaction` | Create a new work item |
| `list_transactions` | List all items, newest first |
| `get_transaction` | Get one item by ID |
| `update_transaction` | Change fields of an existing item |
| `delete_transaction` | Permanently remove an item |
| `summarize_transactions` | Count by status |

See `skills/transaction_manager/SKILL.md` for Hermes usage examples.

## Data & Backup

Database: `~/.myagentdata/aisecretary/transactions.sqlite` (mounted into container at `/data/`).

Backup managed by [myopenclaw](https://github.com/OuyangWenyu/myopenclaw) `backup-cron` container. This repo does not manage backups.

## Development

```bash
# Install
uv sync
uv pip install mcp

# Run locally (without Docker)
uv run uvicorn server.app.main:app --host 127.0.0.1 --port 8000 --reload

# Test
uv run pytest server/tests/ -v
```
