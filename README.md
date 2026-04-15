# Hermes Transaction Layer

Minimal FastAPI + SQLite transaction API for a Hermes capability layer.

The intended deployment flow is:

1. Develop and verify on Windows.
2. Commit and push changes to git.
3. Pull the repository on the Mac mini.
4. Run the local API on the Mac mini.
5. Let Hermes on the Mac mini load the skill/prompt and call the local API.

## Windows Development / Verification

From the repository root on Windows:

```powershell
uv sync
uv run pytest
```

Optional local API run for development checks:

```powershell
uv run uvicorn server.app.main:app --host 127.0.0.1 --port 8000 --reload
```

The Windows run is for development verification only. Do not assume Hermes is running on Windows.

## Mac Mini Runtime / Hermes Wiring

On the Mac mini, pull the repository and start the API:

```bash
cd ~/code/aisecretary
git pull
uv sync
uv run uvicorn server.app.main:app --host 127.0.0.1 --port 8000
```

The local API base URL is:

```text
http://127.0.0.1:8000
```

Configure Hermes on the Mac mini to use that base URL, then load or copy these relative-path wiring files into the Hermes-side skill/prompt configuration:

```text
skills/transaction_manager/SKILL.md
skills/transaction_manager/tool_contract.md
prompts/task_secretary_rules.md
```

Example macOS paths if the repository is checked out under `~/code/aisecretary`:

```text
~/code/aisecretary/skills/transaction_manager/SKILL.md
~/code/aisecretary/skills/transaction_manager/tool_contract.md
~/code/aisecretary/prompts/task_secretary_rules.md
```

Keep API keys, Feishu tokens, and local Hermes config out of git.

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

## Hermes Natural Language Smoke Test

After the API is running on the Mac mini and Hermes has loaded the skill/prompt, send this in Feishu:

```text
记录一个事务：和清华团队推进合作，负责人 Owen，下一步确认下次会议时间。
```

Hermes should call:

```http
POST /transactions
```

With a body equivalent to:

```json
{
  "title": "和清华团队推进合作",
  "status": "new",
  "owner": "Owen",
  "next_action": "确认下次会议时间"
}
```

Expected Feishu reply after API success:

```text
已记录事务：
ID：{id}
事务：和清华团队推进合作
状态：新建
负责人：Owen
下一步：确认下次会议时间
建议跟进：未设置
```

Then verify the remaining MVP intents:

```text
现在有哪些事务？
```

```text
把 ID 为 {id} 的事务改成等待反馈，下一步是等对方确认会议时间。
```

```text
汇总当前事务。
```

Hermes should map those to:

```http
GET /transactions
PATCH /transactions/{id}
GET /transactions/summary
```

Do not add board, reminder, authentication, multi-user, or automation-framework behavior to this MVP wiring.
