# Hermes Transaction Layer

Minimal FastAPI + SQLite transaction API for a Hermes capability layer.

## Run locally

```bash
cp .env.example .env
uv sync
uv run uvicorn server.app.main:app --reload
```

The local API base URL is:

```text
http://127.0.0.1:8000
```

## Manual API Verification

Run these commands after the service starts.

### GET /health

```bash
curl http://127.0.0.1:8000/health
```

Expected result:

```json
{"status":"ok"}
```

### POST /transactions

```bash
curl -X POST http://127.0.0.1:8000/transactions \
  -H "Content-Type: application/json" \
  -d '{"title":"Partnership follow-up","owner":"Owen","next_action":"Confirm next meeting time"}'
```

Expected result: `201 Created` with a transaction object. Save the returned `id` for later commands.

```json
{
  "id": "generated-id",
  "title": "Partnership follow-up",
  "status": "new",
  "next_action": "Confirm next meeting time",
  "owner": "Owen",
  "suggested_follow_up_at": null,
  "created_at": "ISO-8601 datetime",
  "updated_at": "ISO-8601 datetime",
  "notes": null
}
```

### GET /transactions

```bash
curl http://127.0.0.1:8000/transactions
```

Expected result: `200 OK` with an array. It is `[]` when no transactions exist.

```json
[
  {
    "id": "generated-id",
    "title": "Partnership follow-up",
    "status": "new",
    "next_action": "Confirm next meeting time",
    "owner": "Owen",
    "suggested_follow_up_at": null,
    "created_at": "ISO-8601 datetime",
    "updated_at": "ISO-8601 datetime",
    "notes": null
  }
]
```

### GET /transactions/{id}

Replace `generated-id` with the ID returned by `POST /transactions`.

```bash
curl http://127.0.0.1:8000/transactions/generated-id
```

Expected result: `200 OK` with one transaction object.

If the ID does not exist:

```json
{
  "detail": {
    "code": "transaction_not_found",
    "message": "Transaction not found"
  }
}
```

### PATCH /transactions/{id}

Replace `generated-id` with the ID returned by `POST /transactions`.

```bash
curl -X PATCH http://127.0.0.1:8000/transactions/generated-id \
  -H "Content-Type: application/json" \
  -d '{"status":"waiting_feedback","next_action":"Wait for partner feedback"}'
```

Expected result: `200 OK` with the updated transaction object.

```json
{
  "id": "generated-id",
  "title": "Partnership follow-up",
  "status": "waiting_feedback",
  "next_action": "Wait for partner feedback",
  "owner": "Owen",
  "suggested_follow_up_at": null,
  "created_at": "ISO-8601 datetime",
  "updated_at": "ISO-8601 datetime",
  "notes": null
}
```

### GET /transactions/summary

```bash
curl http://127.0.0.1:8000/transactions/summary
```

Expected result: `200 OK` with minimal summary data.

```json
{
  "total": 1,
  "by_status": {
    "waiting_feedback": 1
  }
}
```

## Natural Language Mapping Examples

These examples prepare the next Hermes wiring step. They match `skills/transaction_manager/tool_contract.md` and `prompts/task_secretary_rules.md`.

### Create Transaction

User:

```text
记录一个事务：和清华团队推进合作，负责人 Owen，下一步确认下次会议时间。
```

Hermes should extract:

```json
{
  "title": "和清华团队推进合作",
  "status": "new",
  "owner": "Owen",
  "next_action": "确认下次会议时间",
  "suggested_follow_up_at": null,
  "notes": null
}
```

API call:

```http
POST /transactions
```

Expected reply after success:

```text
已记录事务：
ID：{id}
事务：和清华团队推进合作
状态：新建
负责人：Owen
下一步：确认下次会议时间
建议跟进：未设置
```

### Update Transaction

User:

```text
把 ID 为 {id} 的事务改成等待反馈，下一步是等对方确认会议时间。
```

Hermes should extract:

```json
{
  "status": "waiting_feedback",
  "next_action": "等对方确认会议时间"
}
```

API call:

```http
PATCH /transactions/{id}
```

Expected reply after success:

```text
已更新事务：
ID：{id}
状态：等待反馈
下一步：等对方确认会议时间
```

### Query Transaction List

User:

```text
现在有哪些事务？
```

Hermes should extract:

```json
{}
```

API call:

```http
GET /transactions
```

Expected reply after success:

```text
当前事务：
1. {title}
   ID：{id}
   状态：{中文状态}
   负责人：{owner}
   下一步：{next_action 或 未设置}
   建议跟进：{suggested_follow_up_at 或 未设置}
```

If the API returns `[]`:

```text
当前没有已记录的事务。
```

### Summarize Transactions

User:

```text
汇总当前事务。
```

Hermes should extract:

```json
{}
```

API call:

```http
GET /transactions/summary
```

Expected reply after success:

```text
事务汇总：
总数：{total}
新建：{by_status.new 或 0}
进行中：{by_status.in_progress 或 0}
等待反馈：{by_status.waiting_feedback 或 0}
已完成：{by_status.done 或 0}
```

Do not mention overdue or upcoming counts in the MVP response.

## Hermes Wiring Preparation

Before wiring Hermes:

1. Start this API service locally.
2. Manually verify the API commands above.
3. Confirm `skills/transaction_manager/tool_contract.md` matches the live API behavior.
4. Load or copy `prompts/task_secretary_rules.md` into the Hermes-side prompt configuration.
5. Configure Hermes with the API base URL, for example `http://127.0.0.1:8000`.
6. Keep API keys, Feishu tokens, and local Hermes config out of git.

## Test

```bash
uv run pytest
```
