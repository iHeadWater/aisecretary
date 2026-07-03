# Transaction Manager Tool Contract

Hermes calls `aisecretary_cli.py` on the host machine via SSH. All commands are run as:

```bash
ssh aisecretary-host "aisecretary <subcommand> [args]"
```

`aisecretary-host` is an SSH alias configured in `~/.ssh/config` inside the Hermes container (see `scripts/setup_ssh_access.sh`).

## Windows SSH 注意事项

- **编码**：SSH 输出已强制 UTF-8（`chcp 65001`），直接按 UTF-8 解析即可。
- **引号**：Windows cmd.exe 不识别单引号，字符串参数必须用双引号。内层双引号用 `\"` 转义：
  ```bash
  ssh aisecretary-host "aisecretary create --title \"标题\" --owner \"Owen\""
  ```
  不要用单引号包裹参数值，否则单引号会被原样存入数据库。

## Data Shape

All commands output JSON. A transaction looks like:

```json
{
  "id": "string (UUID)",
  "title": "string",
  "status": "new | in_progress | waiting_feedback | done",
  "next_action": "string or null",
  "owner": "string (default: unassigned)",
  "suggested_follow_up_at": "ISO-8601 datetime string or null",
  "created_at": "ISO-8601 datetime string",
  "updated_at": "ISO-8601 datetime string",
  "notes": "string or null",
  "project": "string or null (project key, e.g. from myloop configs/projects.toml)",
  "folder_path": "string or null (associated local folder path)"
}
```

Status values:

- `new`: 新建
- `in_progress`: 进行中
- `waiting_feedback`: 等待反馈
- `done`: 已完成

Errors output `{"error": "<code>", "message": "..."}` and exit with code 1.

## Create Transaction

Use when the user asks to record, create, add, remember, or track a transaction.

```bash
ssh aisecretary-host "aisecretary create \
  --title '<title>' \
  [--status 'new|in_progress|waiting_feedback|done'] \
  [--owner '<owner>'] \
  [--next-action '<next_action>'] \
  [--follow-up '<ISO-8601 datetime>'] \
  [--notes '<notes>'] \
  [--project '<project key>'] \
  [--folder-path '<local folder path>']"
```

Rules:

- `--title` is required. If missing, ask before calling.
- `--status` defaults to `new` if omitted.
- `--owner` defaults to `unassigned` if omitted.
- Convert natural-language follow-up times to ISO-8601 before passing to `--follow-up`.
- `--project` / `--folder-path` are optional. Infer `project` from context (email, conversation, explicit mention); leave empty rather than guessing.
- Output on success: the created transaction JSON.

## List Transactions

Use when the user asks what transactions exist or asks for the current list.

```bash
ssh aisecretary-host "aisecretary list [--project '<project key>']"
```

Output: JSON array of transactions ordered by `updated_at` DESC. Empty list is `[]`.
Pass `--project` to return only transactions belonging to that project.

## Get Transaction

Use when the user asks about a specific transaction by ID.

```bash
ssh aisecretary-host "aisecretary get '<id>'"
```

Error code on missing record: `transaction_not_found`.

## Update Transaction

Use when the user asks to change a known transaction.

```bash
ssh aisecretary-host "aisecretary update '<id>' \
  [--title '<title>'] \
  [--status 'new|in_progress|waiting_feedback|done'] \
  [--owner '<owner>'] \
  [--next-action '<next_action>'] \
  [--follow-up '<ISO-8601 datetime>'] \
  [--notes '<notes>'] \
  [--project '<project key>'] \
  [--folder-path '<local folder path>']"
```

Rules:

- Pass only fields the user wants to change.
- To clear a nullable field, pass an empty string: `--next-action ''` (also works for `--project ''` / `--folder-path ''`).
- Do not call with no optional flags (error code: `no_fields_to_update`).
- If no ID is provided, ask or call `list` first to disambiguate.

Status mapping:

- 新建 → `new`
- 进行中 → `in_progress`
- 等待反馈 → `waiting_feedback`
- 已完成 → `done`

Error codes: `transaction_not_found`, `no_fields_to_update`, `invalid_status`.

## Delete Transaction

Use when the user asks to delete or remove a transaction by ID.

```http
DELETE /transactions/{id}
```

Success response: `204 No Content` (empty body).

Not found response:

```json
{
  "detail": {
    "code": "transaction_not_found",
    "message": "Transaction not found"
  }
}
```

Rules:

- Do not call this without a confirmed ID.
- Always confirm with the user before deleting, since the operation is irreversible.

## Summarize Transactions

Use when the user asks for a summary, overview, or count.

```bash
ssh aisecretary-host "aisecretary summary"
```

Output:

```json
{
  "total": 0,
  "by_status": {}
}
```

`by_status` only contains statuses currently present in the database.
