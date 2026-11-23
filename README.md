# aisecretary

Hermes 秘书服务：事务（transaction）管理 + PowerPoint 单页真实渲染/解读，MCP over Streamable HTTP，Docker 打包，SQLite 持久化。

## Architecture

```
┌─ myopenclaw docker-compose ───────────────────────┐
│                                                    │
│  Hermes ──MCP/HTTP──► aisecretary:8000             │
│                       ├─ 15 MCP tools (self-desc)  │
│                       ├─ REST API /api/*            │
│                       └─ GET /health                │
│                          │                         │
│                     volume: SQLite (persistent)     │
└────────────────────────────────────────────────────┘
```

- **MCP Streamable HTTP**: Hermes auto-discovers 15 tools via `http://aisecretary:8000/mcp`
- **PPT**: LibreOffice 真实渲染（单页切片 → PDF → `pdftoppm` → PNG），python-pptx 只负责文本/表格/备注
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
| `PPT_CACHE_MAX_AGE_DAYS` | `7` | 缓存 PNG 与切片保留天数，渲染时顺带清理；`<=0` 关闭 |
| `PPT_BATCH_MAX` | `8` | 一次渲染最多合并多少连续页：省掉重复的 LO 启动，又限制峰值内存 |
| `PPT_SLICE_ENABLED` | `true` | 先裁成「只含目标页」的切片再渲染；`false` 时回退整本 deck + PageRange |

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
| `ppt_render_pages` | 多页一次渲染（`5-8` / `5,6,9`），连续页合并成一次 LO 运行 |
| `link_transactions` | 建立事务关联（part_of / blocks / related） |
| `unlink_transactions` | 删除关联 |
| `merge_transactions` | 把重复事务合并进主事务，保留历史 |

### Filter Examples

```
list_transactions(status="new,in_progress,waiting_feedback")  # 未完成事务
list_transactions(owner="Owen")                                 # 按负责人
list_transactions(search="关键词")                               # 搜索标题和备注
list_transactions(project="myproject")                          # 按项目
```

See `skills/transaction_manager/SKILL.md` for Hermes usage patterns and trigger examples.

## PPT (真渲染：单页 / 多页)

Hermes 说「把第 N 页发我一张截图」时，aisecretary 用 LibreOffice 真实渲染该页，而不是按形状坐标重绘。

```
Hermes ──MCP──► aisecretary
                 ├─ slice       : 只含目标页的临时 pptx（0.8MB，替代整本 158MB）
                 ├─ python-pptx : 文本 / 表格 / 备注
                 ├─ soffice     : 切片 → PDF
                 └─ pdftoppm    : PDF → PNG（150dpi → 2001×1125）
```

**为什么要切片**：LibreOffice 渲染任意一页都会先把整本 deck 载入。实测 158MB / 64 页：

| 输入 | 峰值内存 | 单页耗时 |
|---|---|---|
| 整本 deck（PageRange 只导一页） | 1.3–2.0 GB | 9–11 s |
| 只含目标页的切片 | **236 MB** | **0.6 s** |

**多页怎么切**：`PPT_BATCH_MAX`（默认 8）控制一次合并渲染几页。一次请求里的连续页
合成一个切片、只起一次 soffice：

| 请求 | 分页渲染 | 合并渲染 |
|---|---|---|
| 1 页 | 1.0 s | 1.0 s |
| 4 页连续 | ~4.2 s | **~2.8 s** |
| 8 页连续 | ~8.4 s | **~5.2 s** |

上限 8 页是因为内存随页数上涨（8 页 318 MB / 16 页 353 MB / 32 页 528 MB），
再大时间收益也消失。超过 8 页会自动分批；单次调用最多 32 页。

典型调用：

```text
ppt_use_deck(path="/opt/data/tmp/xdsh/9-主题介绍-….pptx")   → slide_count=64
ppt_render_slide(page=5)                                     → {"path": "/opt/data/tmp/pptpage/…-p5-150.png", …}
ppt_render_pages(pages="5-8")                                → [{path, page, width, height}, …]
ppt_get_slide(page=8)                                        → 文本 / 表格 / 备注
ppt_outline()                                                → 每页标题 + 首行
```

Hermes 收到结果后用 `MEDIA:<path>` 回复，飞书即发图片消息。

> 生产状态：v0.2.1 已在飞书端实测通过（单页 9.4–9.7s，2001×1125）；v0.2.3 起走切片，
> 单页约 0.6–1.0s、峰值约 236MB。

要求与约束：

- **两个容器必须把同一批宿主目录挂在同一绝对路径**（`~/.hermes/tmp/xdsh → /opt/data/tmp/xdsh` 只读、`~/.hermes/tmp/pptpage → /opt/data/tmp/pptpage` 可写），否则 `MEDIA:` 路径在 Hermes 侧不存在。
- 镜像需 `libreoffice-impress` + `fonts-noto-cjk` + `poppler-utils`（已写进 Dockerfile，镜像约 +400MB）。
- 内存：切片后 LibreOffice 单页渲染峰值约 236MB（批量 8 页约 318MB），渲染仍全局单并发；不再需要为单页预留 2GB。
- 字体：镜像只带 Noto CJK，`微软雅黑/等线/黑体 → Noto Sans CJK SC`、`宋体 → Noto Serif CJK SC` 由 `docker/fonts/99-cjk-alias.conf` 做替换。要与 PowerPoint 像素级一致需自行挂载已授权字体。
- 不做整本转换（导出全部 64 页）；单次最多 32 页。渲染失败只影响该次调用，事务工具不受影响。
- 切片会写进 `PPT_OUT_DIR/.slices/<deck key>/`，与 PNG 一起按 `PPT_CACHE_MAX_AGE_DAYS` 清理。

冒烟（真实 deck，第 5/6/8 页 + 批量 5-8 页，阈值 20s）：

```bash
docker build --target test -t aisecretary:test .
docker run --rm \
  -v ~/.hermes/tmp/xdsh:/opt/data/tmp/xdsh:ro \
  -v ~/.hermes/tmp/pptpage:/opt/data/tmp/pptpage \
  aisecretary:test .venv/bin/python scripts/ppt_smoke.py \
  --deck "/opt/data/tmp/xdsh/9-主题介绍-人工智能驱动的水利科学研究.pptx"
```

See `skills/ppt_secretary/SKILL.md` for Hermes-side trigger rules.

## 事务关联与合并

事务默认是孤立的。当几件事之间存在「子任务 / 阻塞 / 相关」关系时，用 `link_transactions` 显式建边：

| relation | 方向 | 含义 |
|----------|------|------|
| `part_of` | 有向 | from 是 to 的子任务（反向自动读作 `has_part`） |
| `blocks` | 有向 | from 未完成时 to 推进不了（反向自动读作 `blocked_by`） |
| `related` | 无向 | 弱相关，只存一条边 |

```python
link_transactions(from_id=A, to_id=B, relation="part_of")
get_transaction(A)          # 返回里带 links: [{id, title, status, relation, direction}]
list_transactions(linked_to=A)                   # A 的所有关联方
unlink_transactions(from_id=A, to_id=B)          # 不传 relation 则删掉两者之间所有边
```

设计约定：

- **只在你明确要求时建边**，不做自动推断，避免生成没人维护的垃圾图。
- 幂等：重复建同一条边返回 `created: false`。
- 禁止自环；两个 id 都必须存在，否则返回 `invalid_link`。
- 删除事务时其关联边一并清理，不留悬空引用。
- 边只存一条，反向语义在查询时推导，所以 `part_of` 与 `has_part` 不会各存一份。

**合并重复事务**用 `merge_transactions(source_id, target_id)`：source 的 notes 追加到 target、关联边重指向 target、source 写 `merged_into` 指向 target。source 不被删除，保留为历史记录，但默认不出现在 `list_transactions` 和 `summarize_transactions` 里（`include_merged=true` 可显式查看）。

## REST API

For CLI and direct HTTP access:

```bash
# List with filters
GET /api/transactions?status=new,in_progress&owner=Owen&project=myloop&search=keyword

# Batch update
PATCH /api/transactions/batch
[{"id": "xxx", "status": "done"}, {"id": "yyy", "owner": "Owen"}]

# Links
GET    /api/transactions/{id}/links
POST   /api/transactions/{id}/links            {"to_id": "...", "relation": "part_of"}
DELETE /api/transactions/{id}/links/{to_id}?relation=related

# Merge a duplicate into the record that survives
POST   /api/transactions/{id}/merge            {"target_id": "..."}

# List filters
GET /api/transactions?linked_to=<id>&include_merged=true
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

**版本号只走 patch**：即使新增了功能（如新的 MCP 工具），也发 `0.2.x`，不主动跳 minor。这是本仓库的既定约定，`0.3.0` 之类的 minor 号不使用。

```bash
git tag v0.2.2
git push origin v0.2.2
gh release create v0.2.2 --title v0.2.2 --notes "..."
```

No PyPI publishing: releases are git tags + GitHub Releases, and the deployable artifact is the Docker image built from that tag.

## Project Files

| Path | Purpose |
|------|---------|
| `server/app/main.py` | FastAPI app: MCP mount + REST router + /health |
| `server/app/mcp_server.py` | 15 MCP tool definitions |
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
