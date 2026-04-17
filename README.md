# Hermes 事务管理接口层

轻量级 FastAPI + SQLite 事务 API，为 Hermes 助手提供事务管理能力。

## 部署流程

1. 在 Windows 上开发调试
2. 提交并推送到 Git
3. 在 Mac mini 上拉取代码
4. 在 Mac mini 上启动本地 API
5. 让 Mac mini 上的 Hermes 加载 skill/prompt 并调用本地 API

## Windows 开发 / 验证

在 Windows 仓库根目录执行：

```powershell
uv sync
uv run pytest
```

可选：启动本地 API 进行开发调试：

```powershell
uv run uvicorn server.app.main:app --host 127.0.0.1 --port 8000 --reload
```

注意：Windows 开发仅用于验证，Hermes 并非运行在 Windows 上。

## Mac mini 运行环境 / Hermes 接线

在 Mac mini 上拉取仓库并启动 API：

```bash
cd ~/code/aisecretary
git pull
uv sync
uv run uvicorn server.app.main:app --host 127.0.0.1 --port 8000
```

本地 API 基础地址：

```
http://127.0.0.1:8000
```

在 Mac mini 上配置 Hermes 使用上述基础地址，然后将以下接线文件复制到 Hermes 的 skill/prompt 配置中：

```
skills/transaction_manager/SKILL.md
skills/transaction_manager/tool_contract.md
prompts/task_secretary_rules.md
```

示例 macOS 路径（假设仓库克隆到 `~/code/aisecretary`）：

```
~/code/aisecretary/skills/transaction_manager/SKILL.md
~/code/aisecretary/skills/transaction_manager/tool_contract.md
~/code/aisecretary/prompts/task_secretary_rules.md
```

注意：API 密钥、Feishu 令牌等敏感配置请勿提交到 Git。

## API 手动验证

服务启动后运行以下命令进行验证。

### 健康检查

```bash
curl http://127.0.0.1:8000/health
```

预期返回：

```json
{"status":"ok"}
```

### 创建事务

```bash
curl -X POST http://127.0.0.1:8000/transactions \
  -H "Content-Type: application/json" \
  -d '{"title":"合作伙伴跟进","owner":"Owen","next_action":"确认下次会议时间"}'
```

预期返回：`201 Created`，返回的事务对象中包含 `id`，请保存该 ID 供后续使用。

### 查询事务列表

```bash
curl http://127.0.0.1:8000/transactions
```

预期返回：`200 OK`，返回数组。无事务时为 `[]`。

### 获取单个事务

将 `generated-id` 替换为创建事务时返回的 ID：

```bash
curl http://127.0.0.1:8000/transactions/generated-id
```

预期返回：`200 OK`，返回事务对象。

### 更新事务

将 `generated-id` 替换为要更新的事务 ID：

```bash
curl -X PATCH http://127.0.0.1:8000/transactions/generated-id \
  -H "Content-Type: application/json" \
  -d '{"status":"waiting_feedback","next_action":"等待对方确认会议时间"}'
```

预期返回：`200 OK`，返回更新后的事务对象。

### 汇总事务

```bash
curl http://127.0.0.1:8000/transactions/summary
```

预期返回：`200 OK`，返回汇总数据：

```json
{
  "total": 1,
  "by_status": {
    "waiting_feedback": 1
  }
}
```

## Hermes 自然语言测试

API 在 Mac mini 上运行且 Hermes 已加载 skill/prompt 后，在飞书中发送：

```
记录一个事务：和清华团队推进合作，负责人 Owen，下一步确认下次会议时间。
```

Hermes 应调用：

```
POST /transactions
```

请求体大致如下：

```json
{
  "title": "和清华团队推进合作",
  "status": "new",
  "owner": "Owen",
  "next_action": "确认下次会议时间"
}
```

API 成功后飞书回复：

```
已记录事务：
ID：{id}
事务：和清华团队推进合作
状态：新建
负责人：Owen
下一步：确认下次会议时间
建议跟进：未设置
```

继续验证其余意图：

```
现在有哪些事务？
```

```
把 ID 为 {id} 的事务改成等待反馈，下一步是等对方确认会议时间。
```

```
汇总当前事务。
```

Hermes 应分别映射到：

```
GET /transactions
PATCH /transactions/{id}
GET /transactions/summary
```

## Mac 快速配置

### 首次配置（全新 Mac）

前置条件：Hermes 已安装并初始化，Feishu 已配置。

```bash
git clone <仓库地址> ~/code/aisecretary
cd ~/code/aisecretary
bash scripts/bootstrap_hermes.sh
bash scripts/start_local_api.sh   # 前台运行，需打开新终端
```

### 更新现有配置

拉取新版本后：

```bash
cd ~/code/aisecretary
git pull
bash scripts/bootstrap_hermes.sh   # 幂等操作，可安全重复执行
```

如 API 已在运行，需重启：

```bash
bash scripts/start_local_api.sh
```

### 验证接线

```bash
bash scripts/verify_hermes_wiring.sh
```

预期输出：4 passed, 0 failed。若有失败，脚本会输出修复命令。

## Windows (WSL2) 快速配置

> 注意：Hermes 不支持原生 Windows，需在 WSL2 中运行。

### 首次配置（全新 WSL2）

前置条件：WSL2 已安装，Ubuntu 或其他 Linux 发行版已就绪。

```bash
# 1. 进入 WSL 终端
wsl

# 2. 克隆仓库
# 如果 WSL2 的 Git SSH 未配置，可从 Windows 本地克隆后复制到 WSL：
#   git clone <仓库地址> 
#   cp -r /mnt/e/code/aisecretary ~/code/aisecretary
# 或者重新配置 WSL2 的 Git SSH
git clone <仓库地址> ~/code/aisecretary
cd ~/code/aisecretary

# 3. 转换脚本换行符（Windows 仓库默认 CRLF）
sed -i 's/\r$//' scripts/*.sh

# 4. 启动 API
bash scripts/start_local_api.sh   # 前台运行，需打开新终端
```

### 更新现有配置

拉取新版本后：

```bash
cd ~/code/aisecretary
git pull

# 重新转换脚本换行符（如果 Windows 端有更新）
sed -i 's/\r$//' scripts/*.sh

# 重启 API
bash scripts/start_local_api.sh
```

### 注意事项

1. **换行符问题**：从 Windows Git 拉取的脚本文件换行符为 CRLF (`\r\n`)，需要转换为 LF (`\n`) 才能在 WSL2 中运行
2. **Hermes 安装**：如需在 WSL2 中运行完整 Hermes，参考官方文档执行安装命令