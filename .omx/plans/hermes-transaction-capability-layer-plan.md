# Hermes 事务秘书系统能力层 Plan

## Requirements Summary

目标是建立一个独立 git 仓库，作为 Hermes 的事务管理能力层，而不是 Hermes fork。Hermes 继续作为长期运行的 Agent 和飞书入口，本仓库提供 prompts、skills、tools/API、数据模型、部署脚本和后续看板扩展基础。

约束：
- 不修改 Hermes 官方源码。
- 本仓库通过 skills / tools / prompt 接入 Hermes。
- 配置与密钥不得进入 git。
- 第一版使用 Python + FastAPI + SQLite。
- 支持 Mac M 系列本地开发和换电脑快速恢复。
- MVP 优先事务记录、状态更新、下一步建议、事务汇总。

## A. System Boundaries

### Hermes 负责什么

- 接收飞书消息，并维持现有对话入口。
- 理解用户自然语言意图，例如“帮我记录一个合作事项”“把 XX 改成等待反馈”“今天有哪些要跟进”。
- 按 prompt 约束把自然语言转换为结构化 tool/skill 调用参数。
- 调用本仓库提供的 skill/tool/API。
- 将后端返回的数据转成适合飞书阅读的回复。
- 在不确定时向用户追问最少必要信息。

Hermes 不负责：
- 持久化事务状态。
- 直接读写 SQLite。
- 管理数据库迁移。
- 承担看板后端。
- 保存 API keys 或本仓库配置。

### 本仓库负责什么

- 定义事务管理领域模型。
- 提供 FastAPI 服务，暴露事务 CRUD 和查询汇总 API。
- 提供 SQLite 数据存储和迁移脚本。
- 提供 Hermes skills/tools 调用说明和 prompt 模板。
- 提供本地启动、初始化、备份、恢复脚本。
- 提供后续 cron 提醒和领导看板的扩展边界。

### Agent 内能力

放在 prompts / skills 层：
- 意图识别：判断用户是新增、更新、查询、总结还是建议下一步。
- 参数抽取：标题、负责人、状态、下一步动作、跟进时间、备注。
- 输出约束：统一返回“已记录 / 当前状态 / 下一步 / 建议跟进时间”。
- 澄清策略：缺少标题或动作时追问，缺少负责人可默认“未指定”。
- 调用策略：优先调用 API，不在对话中臆造已保存结果。

### 后端服务能力

放在 server/API 层：
- 创建事务。
- 更新事务状态、下一步动作、负责人、建议跟进时间、备注。
- 查询单个事务。
- 按状态、负责人、时间窗口查询事务列表。
- 生成当前事务汇总数据。
- 提供健康检查。
- 未来提供提醒任务扫描 API 和看板 API。

## B. Repository Structure

```text
hermes-transaction-layer/
  README.md
  pyproject.toml
  .gitignore
  .env.example

  prompts/
    hermes-system.md
    transaction-intent.md
    response-format.md

  skills/
    transaction_manager/
      SKILL.md
      examples.md
      tool_contract.md

  server/
    app/
      main.py
      api/
        transactions.py
        health.py
      core/
        config.py
      db/
        session.py
        migrations/
      models/
        transaction.py
      schemas/
        transaction.py
      services/
        transaction_service.py
    tests/
      test_transactions_api.py
      test_transaction_service.py

  scripts/
    bootstrap.sh
    dev.sh
    migrate.sh
    backup_db.sh
    restore_db.sh

  templates/
    env.example
    feishu-reply-summary.md
    feishu-reply-transaction.md

  docs/
    architecture.md
    hermes-integration.md
    local-development.md
    migration-and-backup.md
    api.md

  data/
    .gitkeep

  dashboard/
    README.md
```

目录职责：
- `prompts/`：Hermes 行为约束、意图抽取规则、飞书回复格式。
- `skills/`：Hermes 可加载的能力说明，定义何时调用 API、参数格式、错误处理。
- `server/`：FastAPI 后端，承担事务持久化和查询。
- `scripts/`：本地初始化、启动、迁移、备份、恢复。
- `templates/`：`.env` 示例和飞书回复模板。
- `docs/`：架构、接入、开发、迁移和 API 文档。
- `data/`：本地 SQLite 数据库目录，只保留 `.gitkeep`，数据库文件不进 git。
- `dashboard/`：看板预留目录，MVP 只放说明，不实现。

## C. MVP Development Roadmap

### Phase 1: 最小骨架

目标：
- 建立独立仓库结构。
- 能在新 Mac 上一条命令初始化开发环境。
- 明确配置、数据、密钥边界。

交付内容：
- `pyproject.toml`
- `.gitignore`
- `.env.example`
- `server/app/main.py`
- `GET /health`
- `scripts/bootstrap.sh`
- `scripts/dev.sh`
- `docs/local-development.md`

不做什么：
- 不接 Hermes。
- 不接飞书。
- 不做看板。
- 不设计复杂权限。
- 不引入 Postgres、Redis、消息队列。

### Phase 2: 事务 API

目标：
- 后端可以独立完成事务记录、更新、查询和汇总。

交付内容：
- SQLite 初始化。
- 事务数据模型。
- `POST /transactions`
- `GET /transactions`
- `GET /transactions/{id}`
- `PATCH /transactions/{id}`
- `GET /transactions/summary`
- 基础单元测试和 API 测试。
- `docs/api.md`

不做什么：
- 不做复杂全文搜索。
- 不做多租户。
- 不做审批流。
- 不做关系图谱。
- 不做自动状态推理写库。

### Phase 3: Hermes 接入

目标：
- Hermes 可通过 skill/tool 调用后端 API，完成真实事务管理。

交付内容：
- `skills/transaction_manager/SKILL.md`
- `skills/transaction_manager/tool_contract.md`
- `prompts/hermes-system.md`
- `prompts/transaction-intent.md`
- `prompts/response-format.md`
- Hermes 调用示例。
- `docs/hermes-integration.md`

不做什么：
- 不改 Hermes 源码。
- 不在 Hermes 内实现数据库逻辑。
- 不把 API key 写进 prompt。
- 不做复杂多轮规划 Agent。

### Phase 4: 飞书真实使用

目标：
- 用户在飞书里对 Hermes 说自然语言，Hermes 能调用事务 API 并返回稳定格式。

交付内容：
- 飞书场景测试清单。
- 常用指令样例：
  - “记录一个事务：和 A 推进 B 合作，负责人张三，明天跟进。”
  - “把 B 合作改成等待反馈。”
  - “今天要跟进什么？”
  - “汇总当前进行中的事务。”
- 错误回复模板。
- `templates/feishu-reply-*.md`

不做什么：
- 不做复杂按钮交互。
- 不做飞书审批流。
- 不做主动群发提醒。
- 不做领导看板。

### Phase 5: 看板

目标：
- 给领导提供只读综合事务视图。

交付内容：
- 看板需求文档。
- 看板 API 设计。
- 简单 Web 页面或静态原型。
- 按状态、负责人、建议跟进时间展示事务。

不做什么：
- 不做复杂 BI。
- 不做细粒度权限系统。
- 不做移动端专项优化。
- 不做跨组织数据隔离。

## D. Data Model

第一版只定义一个核心实体：事务。

字段：
- `id`: 系统生成唯一 ID。
- `title`: 标题，必填。
- `status`: 状态，枚举：`new` / `in_progress` / `waiting_feedback` / `done`。
- `next_action`: 下一步动作，可为空但建议填写。
- `owner`: 负责人，可为空或为“未指定”。
- `suggested_follow_up_at`: 建议跟进时间，可为空。
- `created_at`: 创建时间，系统生成。
- `updated_at`: 更新时间，系统维护。
- `notes`: 备注，可为空。

状态中文映射：
- `new`: 新建
- `in_progress`: 进行中
- `waiting_feedback`: 等待反馈
- `done`: 已完成

建议 SQLite 表：

```text
transactions
  id TEXT PRIMARY KEY
  title TEXT NOT NULL
  status TEXT NOT NULL
  next_action TEXT
  owner TEXT
  suggested_follow_up_at TEXT
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL
  notes TEXT
```

第一版不拆分：
- 评论表。
- 事件流表。
- 参与人表。
- 标签表。
- 项目表。
- 附件表。

## E. Hermes Integration Design

### 通过 skills 调用 API

`skills/transaction_manager/SKILL.md` 定义 Hermes 可用能力：
- `create_transaction`
- `update_transaction`
- `list_transactions`
- `get_transaction`
- `summarize_transactions`

每个能力都对应 FastAPI endpoint。Hermes 不需要知道数据库，只需要按 tool contract 发 HTTP 请求。

示例数据流：
1. 用户在飞书说：“记录一个事务，和清华团队推进合作，负责人 Owen，下周三跟进。”
2. Hermes 根据 prompt 识别为 `create_transaction`。
3. Hermes 提取结构化参数：
   - `title`: 和清华团队推进合作
   - `owner`: Owen
   - `status`: new
   - `suggested_follow_up_at`: 下周三对应日期
   - `next_action`: 跟进合作进展
4. Hermes 调用 `POST /transactions`。
5. 后端写入 SQLite 并返回事务对象。
6. Hermes 按飞书回复模板返回：“已记录：...”

### 通过 prompt 约束 Hermes 输出结构

Prompt 约束重点：
- 不允许 Hermes 声称“已保存”，除非 API 返回成功。
- 缺少核心字段时追问：
  - 缺标题：必须追问。
  - 缺状态：默认新建。
  - 缺负责人：默认未指定。
  - 缺跟进时间：允许为空，但回复中提示“未设置跟进时间”。
- 输出固定结构：
  - 事务
  - 状态
  - 下一步
  - 负责人
  - 建议跟进
  - 备注

### Hermes 与后端的数据流

写入流：
```text
Feishu user message
  -> Hermes intent extraction
  -> transaction_manager skill
  -> FastAPI
  -> SQLite
  -> API response
  -> Hermes formatted reply
  -> Feishu
```

查询流：
```text
Feishu user query
  -> Hermes query classification
  -> list/summarize API
  -> FastAPI reads SQLite
  -> summary JSON
  -> Hermes concise natural-language summary
  -> Feishu
```

未来提醒流：
```text
cron
  -> reminder scan API or script
  -> due transactions
  -> Hermes/Feishu notification path
```

## F. Local Development and Multi-Machine Migration

### 新电脑恢复流程

1. `git clone` 仓库。
2. 安装 Python 版本管理工具，例如 `uv` 或 `pyenv`。
3. 运行 `scripts/bootstrap.sh` 安装依赖并创建虚拟环境。
4. 复制 `.env.example` 为 `.env`。
5. 填写本地配置，例如数据库路径、服务端口、Hermes API token。
6. 如果有历史数据，运行 `scripts/restore_db.sh path/to/backup.sqlite`。
7. 运行 `scripts/dev.sh` 启动 FastAPI。
8. 访问 `GET /health` 验证服务。

### 进入 git 的文件

- 源码。
- prompts。
- skills。
- docs。
- scripts。
- tests。
- `.env.example`。
- `data/.gitkeep`。

### 不进入 git 的文件

- `.env`
- SQLite 数据库文件，例如 `data/transactions.sqlite`
- 数据库备份，例如 `backups/*.sqlite`
- API keys
- 飞书 token
- Hermes 本地运行配置
- 虚拟环境目录
- 日志文件

### 是否需要 bootstrap 脚本

需要。`bootstrap.sh` 是换电脑快速恢复的关键。

第一版脚本职责：
- 检查 Python 版本。
- 安装依赖。
- 创建必要目录：`data/`、`logs/`、`backups/`。
- 如果 `.env` 不存在，从 `.env.example` 复制。
- 输出下一步启动命令。

## G. 第一版绝对不要做的事情

1. 不要 fork 或修改 Hermes 官方源码。
2. 不要把事务状态存在 Hermes prompt 或对话记忆里。
3. 不要把 API key、飞书 token、数据库文件提交到 git。
4. 不要一开始做多租户、RBAC、组织权限。
5. 不要一开始上 Postgres、Redis、Celery、Kafka。
6. 不要设计复杂工作流引擎或 BPMN。
7. 不要做过度抽象的插件系统。
8. 不要让 Hermes 直接操作 SQLite 文件。
9. 不要在第一版做复杂前端看板。
10. 不要引入向量数据库做事务检索。
11. 不要做自动状态推断后直接写库，必须先可解释。
12. 不要做“所有消息自动入库”，只记录明确事务。
13. 不要把自然语言解析逻辑塞进后端第一版。
14. 不要做复杂提醒规则，先保留单一建议跟进时间。
15. 不要为了未来扩展牺牲 MVP 的可读性和可维护性。

## Acceptance Criteria

- 仓库边界清楚：Hermes、skills/prompts、FastAPI、SQLite 各自职责明确。
- MVP 阶段划分清楚，每阶段有目标、交付内容和明确不做事项。
- 数据模型只包含第一版必要字段。
- Hermes 接入设计不依赖修改官方源码。
- 配置、密钥、数据库文件的 git 边界明确。
- 新电脑恢复流程可执行。
- 后续 cron 和看板可以扩展，不需要推翻事务 API 和数据模型。

## Verification Steps for Next Implementation

- `GET /health` 返回成功。
- SQLite 数据库可自动初始化。
- `POST /transactions` 可创建事务。
- `PATCH /transactions/{id}` 可更新状态和下一步。
- `GET /transactions/summary` 可返回按状态分组的摘要。
- Hermes skill 示例请求能用 curl 或 HTTP client 复现。
- `.gitignore` 能防止 `.env`、SQLite 文件和备份入库。
- 新机器按 `docs/local-development.md` 能从零启动服务。

## Risks and Mitigations

- 风险：Hermes 调用 API 时自然语言解析不稳定。
  缓解：用 prompt 固定参数抽取规则，失败时追问，不自动猜测关键字段。

- 风险：SQLite 文件丢失。
  缓解：第一版提供 `backup_db.sh` 和 `restore_db.sh`，并在 docs 中明确备份路径。

- 风险：后端承担过多 Agent 决策逻辑。
  缓解：后端只做确定性事务管理，Agent 负责意图和表达。

- 风险：看板需求提前污染 MVP。
  缓解：Phase 5 前只保留 summary API，不做 dashboard 复杂功能。

- 风险：配置泄漏。
  缓解：`.env.example` 只放占位符，`.gitignore` 明确排除本地配置和数据。

## Recommended Next Execution Plan

1. 生成仓库骨架和基础配置。
2. 实现 FastAPI health check。
3. 实现 SQLite transaction model 和 API。
4. 添加 tests。
5. 编写 Hermes skill 和 prompt。
6. 用 curl 验证 API，再用 Hermes 做飞书端试用。

