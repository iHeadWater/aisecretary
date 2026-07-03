# aisecretary

Transaction database service for Hermes AI agent. MCP tools for CRUD + summary + batch update, Docker-packaged with persistent SQLite storage.

## Architecture

```
┌─ myopenclaw docker-compose ───────────────────────┐
│                                                    │
│  Hermes ──MCP/HTTP──► aisecretary:8000             │
│                       ├─ 7 MCP tools (self-desc)   │
│                       ├─ REST API /api/*            │
│                       └─ GET /health                │
│                          │                         │
│                     volume: SQLite (persistent)     │
└────────────────────────────────────────────────────┘
```

- **MCP Streamable HTTP**: Hermes auto-discovers 7 tools via `http://aisecretary:8000/mcp`
- **REST API**: Thin CLI (`aisecretary`) calls `/api/*` like `gh` calls GitHub API
- **/health**: Docker healthcheck + myopenclaw monitoring
- **Data**: SQLite file at `~/.myagentdata/aisecretary/transactions.sqlite`, volume-mounted into `/data/`

## Quick Start

```bash
# Build and start
docker compose up -d

# Verify
curl http://localhost:8000/health
# → {"status":"ok"}

# CLI (optional — for host-side debugging)
python3 scripts/aisecretary_cli.py list
python3 scripts/aisecretary_cli.py list --status "new,in_progress,waiting_feedback"
python3 scripts/aisecretary_cli.py create --title "测试事务" --owner "Owen" --project "myproject"
python3 scripts/aisecretary_cli.py summary
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_PATH` | `/data/transactions.sqlite` | SQLite file path (inside container) |
| `AISECRETARY_URL` | `http://localhost:8000/api` | API base URL (for CLI) |

## MCP Tools

Hermes connects to `http://aisecretary:8000/mcp` (Streamable HTTP transport) and discovers:

| Tool | Description |
|------|-------------|
| `create_transaction` | Create a new work item (supports project/folder_path) |
| `list_transactions` | List items with optional filters: status, owner, search, project |
| `get_transaction` | Get one item by ID |
| `update_transaction` | Change fields of an existing item |
| `delete_transaction` | Permanently remove an item |
| `batch_update_transactions` | Update multiple items in one call |
| `summarize_transactions` | Count by status |

### Filter Examples

```
list_transactions(status="new,in_progress,waiting_feedback")  # 未完成事务
list_transactions(owner="Owen")                                 # 按负责人
list_transactions(search="关键词")                               # 搜索标题和备注
list_transactions(project="myproject")                          # 按项目
```

See `skills/transaction_manager/SKILL.md` for Hermes usage patterns and trigger examples.

## REST API

For CLI and direct HTTP access:

```bash
# List with filters
GET /api/transactions?status=new,in_progress&owner=Owen&project=myloop&search=keyword

# Batch update
PATCH /api/transactions/batch
[{"id": "xxx", "status": "done"}, {"id": "yyy", "owner": "Owen"}]
```

Full endpoint reference in `server/app/api.py`.

## Data & Backup

Database: `~/.myagentdata/aisecretary/transactions.sqlite` (mounted into container at `/data/`).

Migration: new columns (`project`, `folder_path`) are added idempotently via `PRAGMA table_info` on startup — no manual migration needed. Existing data is never modified.

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

## Project Files

| Path | Purpose |
|------|---------|
| `server/app/main.py` | FastAPI app: MCP mount + REST router + /health |
| `server/app/mcp_server.py` | 7 MCP tool definitions |
| `server/app/api.py` | REST /api/* endpoints (for CLI) |
| `server/app/storage.py` | Business logic — all tools call this |
| `server/app/database.py` | SQLite connection + idempotent schema migration |
| `server/app/schemas.py` | Pydantic models |
| `scripts/aisecretary_cli.py` | Thin HTTP client CLI |
| `skills/transaction_manager/SKILL.md` | Hermes skill contract |
| `Dockerfile` | Python 3.12-slim image |
| `docker-compose.yml` | Volume mount + healthcheck |
