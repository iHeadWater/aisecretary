# Transaction Manager Tool Contract

This contract maps Hermes transaction intents to the current MVP API.

The base URL is environment-specific. For the Mac mini runtime, when Hermes and the API run on the same machine, use:

```text
http://127.0.0.1:8000
```

## Data Shape

Transaction response:

```json
{
  "id": "string",
  "title": "string",
  "status": "new | in_progress | waiting_feedback | done",
  "next_action": "string or null",
  "owner": "string",
  "suggested_follow_up_at": "ISO-8601 datetime string or null",
  "created_at": "ISO-8601 datetime string",
  "updated_at": "ISO-8601 datetime string",
  "notes": "string or null"
}
```

Status values:

- `new`: 新建
- `in_progress`: 进行中
- `waiting_feedback`: 等待反馈
- `done`: 已完成

## Create Transaction

Use when the user clearly asks Hermes to record, create, add, remember, or track a transaction.

```http
POST /transactions
Content-Type: application/json
```

Body:

```json
{
  "title": "string, required",
  "status": "new",
  "next_action": "string or null",
  "owner": "string, defaults to unassigned",
  "suggested_follow_up_at": "ISO-8601 datetime string or null",
  "notes": "string or null"
}
```

Rules:

- If `title` is missing, ask the user for it before calling the API.
- If `status` is missing, send `new`.
- If `owner` is missing, omit it and let the API use `unassigned`.
- If follow-up time is understandable, convert it to an ISO-8601 datetime before sending.
- If follow-up time is not understandable, send `null` or omit the field.

Success response: `201` with a transaction response.

Missing or invalid required fields return validation errors from FastAPI/Pydantic, usually HTTP `422`.

## List Transactions

Use when the user asks what transactions exist, what is currently being tracked, or asks for the current list.

```http
GET /transactions
```

Success response: `200` with an array of transaction responses. Empty list is `[]`.

## Get Transaction

Use when the user asks about a known transaction by ID.

```http
GET /transactions/{id}
```

Success response: `200` with a transaction response.

Not found response:

```json
{
  "detail": {
    "code": "transaction_not_found",
    "message": "Transaction not found"
  }
}
```

## Update Transaction

Use when the user asks to change a known transaction.

```http
PATCH /transactions/{id}
Content-Type: application/json
```

Body contains only fields to change:

```json
{
  "title": "string",
  "status": "new | in_progress | waiting_feedback | done",
  "next_action": "string or null",
  "owner": "string or null",
  "suggested_follow_up_at": "ISO-8601 datetime string or null",
  "notes": "string or null"
}
```

Rules:

- Do not send an empty body.
- If the user did not provide an ID, ask a follow-up question or list transactions to help identify the target.
- Only include fields the user actually wants to change.
- Map natural-language status to the enum exactly:
  - 新建 -> `new`
  - 进行中 -> `in_progress`
  - 等待反馈 -> `waiting_feedback`
  - 已完成 -> `done`

Success response: `200` with the updated transaction response.

Empty update response:

```json
{
  "detail": {
    "code": "no_fields_to_update",
    "message": "At least one transaction field is required"
  }
}
```

Not found response uses `transaction_not_found`.

## Summarize Transactions

Use when the user asks for a summary, overview, count, or current transaction status.

```http
GET /transactions/summary
```

Success response:

```json
{
  "total": 0,
  "by_status": {}
}
```

`by_status` only contains statuses currently present in the database.
