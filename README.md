# aisecretary

Hermes 秘书服务：事务（transaction）管理 + PowerPoint 单页真实渲染/解读，MCP over Streamable HTTP，Docker 打包，SQLite 持久化。

## Architecture

```
┌─ myopenclaw docker-compose ───────────────────────┐
│                                                    │
│  Hermes ──MCP/HTTP──► aisecretary:8000             │
│                       ├─ 12 MCP tools (self-desc)  │
│                       ├─ REST API /api/*            │
│                       └─ GET /health                │
│                          │                         │
│                     volume: SQLite (persistent)     │
└────────────────────────────────────────────────────┘
```

- **MCP Streamable HTTP**: Hermes auto-discovers 12 tools via `http://aisecretary:8000/mcp`
- **PPT**: LibreOffice 单页渲染（`soffice` PageRange → PDF → `pdftoppm` → PNG），python-pptx 只负责文本/表格/备注
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
| `PPT_ROOTS` | `/opt/data/tmp/xdsh` | 允许访问的 deck 根目录（逗号分隔，`resolve()` 后必须落在其中） |
| `PPT_OUT_DIR` | `/opt/data/tmp/pptpage` | PNG 输出目录（必须与 Hermes 用同一绝对路径挂载） |
| `PPT_DPI` | `150` | 默认渲染 dpi（72–300） |
| `PPT_TIMEOUT` | `60` | 单页渲染预算（秒），需小于 Hermes MCP 的 timeout |
| `PPT_CACHE_MAX_AGE_DAYS` | `7` | 缓存 PNG 保留天数，渲染时顺带清理；`<=0` 关闭 |

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
| `ppt_use_deck` | 校验并记住当前 deck，返回页数/大小 |
| `ppt_get_deck` | 返回当前 deck |
| `ppt_outline` | 每页标题 + 首行正文 |
| `ppt_get_slide` | 单页文本/表格/备注/图片数 |
| `ppt_render_slide` | 单页真实渲染为 PNG，返回绝对路径 |

### Filter Examples

```
list_transactions(status="new,in_progress,waiting_feedback")  # 未完成事务
list_transactions(owner="Owen")                                 # 按负责人
list_transactions(search="关键词")                               # 搜索标题和备注
list_transactions(project="myproject")                          # 按项目
```

See `skills/transaction_manager/SKILL.md` for Hermes usage patterns and trigger examples.

## PPT (single-slide render)

Hermes 说「把第 N 页发我一张截图」时，aisecretary 用 LibreOffice 真实渲染该页，而不是按形状坐标重绘。

```
Hermes ──MCP──► aisecretary
                 ├─ python-pptx : 文本 / 表格 / 备注
                 ├─ soffice     : PageRange 只导第 N 页 → PDF（整本转换会 OOM）
                 └─ pdftoppm    : PDF → PNG（150dpi → 2001×1125）
```

典型调用：

```text
ppt_use_deck(path="/opt/data/tmp/xdsh/9-主题介绍-….pptx")   → slide_count=64
ppt_render_slide(page=5)                                     → {"path": "/opt/data/tmp/pptpage/…-p5-150.png", …}
ppt_get_slide(page=8)                                        → 文本 / 表格 / 备注
ppt_outline()                                                → 每页标题 + 首行
```

Hermes 收到结果后用 `MEDIA:<path>` 回复，飞书即发图片消息。

> 生产状态（v0.2.1）：已在飞书端实测通过 —— 「第 N 页截图」返回图片消息；真实 157.9MB / 64 页 deck，第 5/6/8 页均 2001×1125，耗时 9.4–9.7s。

要求与约束：

- **两个容器必须把同一批宿主目录挂在同一绝对路径**（`~/.hermes/tmp/xdsh → /opt/data/tmp/xdsh` 只读、`~/.hermes/tmp/pptpage → /opt/data/tmp/pptpage` 可写），否则 `MEDIA:` 路径在 Hermes 侧不存在。
- 镜像需 `libreoffice-impress` + `fonts-noto-cjk` + `poppler-utils`（已写进 Dockerfile，镜像约 +400MB）。
- 内存：python-pptx 解析 165MB deck 峰值约 265MB，LibreOffice 单页渲染峰值约 2GB → compose 给 3G / 2 CPU，渲染全局单并发。
- 字体：镜像只带 Noto CJK，`微软雅黑/等线/黑体 → Noto Sans CJK SC`、`宋体 → Noto Serif CJK SC` 由 `docker/fonts/99-cjk-alias.conf` 做替换。要与 PowerPoint 像素级一致需自行挂载已授权字体。
- 只做单页；没有整本转换工具。渲染失败只影响该次调用，事务工具不受影响。

冒烟（真实 deck，第 5/6/8 页，阈值 20s）：

```bash
docker build --target test -t aisecretary:test .
docker run --rm \
  -v ~/.hermes/tmp/xdsh:/opt/data/tmp/xdsh:ro \
  -v ~/.hermes/tmp/pptpage:/opt/data/tmp/pptpage \
  aisecretary:test .venv/bin/python scripts/ppt_smoke.py \
  --deck "/opt/data/tmp/xdsh/9-主题介绍-人工智能驱动的水利科学研究.pptx"
```

See `skills/ppt_secretary/SKILL.md` for Hermes-side trigger rules.

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

# Run locally (without Docker)
uv run uvicorn server.app.main:app --host 127.0.0.1 --port 8000 --reload

# Test
uv run pytest server/tests/ -v
```

## Versioning

The version comes from **git tags** — never write a version string by hand.

```bash
uv run python -c "import server.app as a; print(a.__version__)"
```

| Situation | Version |
|-----------|---------|
| On tag `vX.Y.Z` | `X.Y.Z` |
| N commits after a tag | `X.Y.{Z+1}.devN` |
| No git metadata (e.g. tarball build) | `0.0.1` (fallback) |

How it works: [hatch-vcs](https://github.com/ofek/hatch-vcs) reads `git describe` at build time (`[tool.hatch.version]` in `pyproject.toml`) and generates `server/app/_version.py`, which is gitignored and must not be committed. `server/app/main.py` and `server/app/mcp_server.py` both report `server.app.__version__`, so the FastAPI docs and the MCP `serverInfo` always agree with the tag.

Docker builds ship `.git` into the build context (~2 MB) and the builder stage installs `git`, so `hatch-vcs` can read the tag; the runtime stage contains only the venv, without `git`, `uv`, or the repo. Building from a tarball falls back to `0.0.1`.

### Release

```bash
git tag v0.1.1
git push origin v0.1.1
gh release create v0.1.1 --title v0.1.1 --notes "..."
```

No PyPI publishing: releases are git tags + GitHub Releases, and the deployable artifact is the Docker image built from that tag.

## Project Files

| Path | Purpose |
|------|---------|
| `server/app/main.py` | FastAPI app: MCP mount + REST router + /health |
| `server/app/mcp_server.py` | 12 MCP tool definitions |
| `server/app/ppt/` | PPT 能力：路径校验 / 内容提取 / 单页渲染 / 状态 |
| `server/app/api.py` | REST /api/* endpoints (for CLI) |
| `server/app/storage.py` | Business logic — all tools call this |
| `server/app/database.py` | SQLite connection + idempotent schema migration |
| `server/app/schemas.py` | Pydantic models |
| `scripts/aisecretary_cli.py` | Thin HTTP client CLI |
| `skills/transaction_manager/SKILL.md` | Hermes 事务 skill |
| `skills/ppt_secretary/SKILL.md` | Hermes PPT skill |
| `docker/fonts/99-cjk-alias.conf` | 微软字体 → Noto CJK 的 fontconfig 别名 |
| `scripts/ppt_smoke.py` | 真实 deck 单页渲染冒烟 |
| `Dockerfile` | 多阶段：osdeps(LO+字体) / builder / runtime / test |
| `docker-compose.yml` | Volume mount + healthcheck |
