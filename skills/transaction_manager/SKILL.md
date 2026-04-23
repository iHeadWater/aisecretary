---
description: Minimal Hermes skill contract for recording, querying, updating, and summarizing transactions through the local transaction API.
name: transaction_manager
---

# Transaction Manager

Use this skill when the user asks Hermes to manage transactions, affairs, follow-ups, collaborations, reports, coordination items, or similar work items.

This skill is a thin contract over the local FastAPI service. Do not modify Hermes source code. Do not store transaction state in the chat. Do not invent saved records without a successful API response.

API contract: see `tool_contract.md`.

## Base URL

Use the configured transaction API base URL. Hermes runs inside Docker; the API runs on the host machine:

```text
http://host.docker.internal:8000
```

## Supported Intents

### Create Transaction

Trigger examples:

- "记录一个事务：和清华团队推进合作，负责人 Owen，下一步确认下次会议时间。"
- "新增一个跟进事项：明天问 Alice 合同状态。"
- "帮我记一下和 X 的合作，下周三提醒我继续推进。"
- "Track this item..."

Action:

1. Extract `title`.
2. Extract optional `owner`, `next_action`, `suggested_follow_up_at`, and `notes`.
3. Default `status` to `new`.
4. If `title` is missing, ask for the title before calling the API.
5. Call `POST /transactions`.
6. Reply only after the API returns success.

### Query Transaction List

Trigger examples:

- "现在有哪些事务？"
- "列一下当前事项。"
- "Show my transactions."

Action:

1. Call `GET /transactions`.
2. If the response is empty, say there are no recorded transactions.
3. Otherwise summarize the list with ID, title, status, owner, next action, and follow-up time.

### Update Transaction

Trigger examples:

- "把 ID 为 X 的事务改成等待反馈。"
- "把 ID 为 X 的事项标记为完成。"
- "更新 X 的下一步为等对方确认会议时间。"

Action:

1. Identify the transaction ID.
2. If there is no ID, ask which transaction to update or call `GET /transactions` to help disambiguate.
3. Extract only fields the user wants to change.
4. Do not call the API with an empty update.
5. Call `PATCH /transactions/{id}`.
6. If the API returns `transaction_not_found`, tell the user the transaction was not found and ask whether to list current transactions.

### Summarize Transactions

Trigger examples:

- "汇总当前事务。"
- "现在事务状态怎么样？"
- "给我一个事务概览。"

Action:

1. Call `GET /transactions/summary`.
2. Report `total` and `by_status`.
3. Do not mention overdue or upcoming counts because the MVP API does not define them yet.

## Response Rules

- Never say "已记录" or "已更新" before API success.
- Keep Feishu replies concise.
- Always include the transaction ID when reporting a created or updated transaction.
- Use the API status values internally, but present Chinese labels to the user when helpful:
   - `new`: 新建
   - `in_progress`: 进行中
   - `waiting_feedback`: 等待反馈
   - `done`: 已完成

- If the API returns a structured error, use `detail.code` to decide the user-facing explanation.
