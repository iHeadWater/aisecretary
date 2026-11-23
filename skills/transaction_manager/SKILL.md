---
name: transaction_manager
description: Hermes transaction management via MCP tools — create, query, update, delete, batch-update, and summarize work items.
---

# Transaction Manager

Use this skill when the user asks Hermes to manage transactions, affairs, follow-ups, collaborations, reports, coordination items, or similar work items.

## How It Works

Hermes connects to the aisecretary MCP server. All 7 transaction tools are auto-discovered — no manual endpoint mapping needed. The MCP server runs as a Docker service alongside Hermes in the myopenclaw compose stack.

**MCP tools available:**

| Tool | Purpose |
|------|---------|
| `create_transaction` | Create a new work item |
| `list_transactions` | List items with optional filters (status, owner, search, project) |
| `get_transaction` | Get one item by ID |
| `update_transaction` | Change fields of an existing item |
| `delete_transaction` | Permanently remove an item |
| `link_transactions` | Link two items: part_of / blocks / related |
| `unlink_transactions` | Remove a link |
| `merge_transactions` | Merge a duplicate into the record that survives |
| `batch_update_transactions` | Update multiple items in one call |
| `summarize_transactions` | Count by status |

Do not modify Hermes source code. Do not store transaction state in the chat. Do not invent saved records without a successful tool response.

## Project Inference

When the user's context includes a project name or working directory:

- Infer `project` from the current project context (e.g., "myloop", "aisecretary").
- Set `folder_path` to the absolute path of the project directory when available.
- Both fields are optional and can be left unset.

## Supported Intents

### Create Transaction

Trigger examples:

- "记录一个事务：和清华团队推进合作，负责人 Owen，下一步确认下次会议时间。"
- "新增一个跟进事项：明天问 Alice 合同状态。"
- "帮我记一下和 X 的合作，下周三提醒我继续推进。"
- "Track this item..."

Action:

1. Extract `title`.
2. Extract optional `owner`, `next_action`, `suggested_follow_up_at` (as ISO-8601), `notes`, `project`, and `folder_path`.
3. Default `status` to `new`.
4. If `title` is missing, ask for the title before calling the tool.
5. Call `create_transaction`.
6. Reply only after the tool returns success.

### Query Transaction List

Trigger examples:

- "现在有哪些事务？"
- "列一下当前事项。"
- "查一下截止今天未完成的事务。"
- "Show my transactions."

Action:

1. Use `status`, `owner`, `search`, or `project` filters to narrow results.
2. For "unfinished" or "active" queries, use `status="new,in_progress,waiting_feedback"`.
3. If the response is empty, say there are no matching transactions.
4. Otherwise summarize the list with ID, title, status, owner, next action, and follow-up time.

### Update Transaction

Trigger examples:

- "把 ID 为 X 的事务改成等待反馈。"
- "把 ID 为 X 的事项标记为完成。"
- "更新 X 的下一步为等对方确认会议时间。"

Action:

1. Identify the transaction ID.
2. If there is no ID, call `list_transactions` to help disambiguate.
3. Extract only fields the user wants to change.
4. Call `update_transaction`.
5. If the tool returns `transaction_not_found`, tell the user.

### Batch Update Transactions

Trigger examples:

- "把这几条都标记为完成：ID1, ID2, ID3。"
- "我的进度更新：事务A完成了，事务B在等待反馈。"

Action:

1. Collect all IDs and the fields to update.
2. Construct a JSON array of update objects with `id` and fields to change.
3. Call `batch_update_transactions`.
4. Report results — note any failures with their IDs and reasons.

### Delete Transaction

Trigger examples:

- "删除 ID 为 X 的事务。"
- "Remove transaction X."

Action:

1. Identify the transaction ID.
2. Confirm with the user before calling the tool — deletion is irreversible.
3. Call `delete_transaction`.
4. If the tool returns `transaction_not_found`, tell the user.


### Link Transactions

Trigger examples:

- "把「资质材料」关联到「澜沧江投标」下面。"
- "这两件事是一起的：海外访学签证 和 联系国外导师。"
- "「交自查表」要等「财务给数」，把这个依赖记一下。"

Action:

1. Resolve both ids (call `list_transactions` if the user named them by title).
2. Pick the relation:
   - sub-task / belongs to → `part_of`
   - A must finish first → `blocks`
   - loosely connected → `related`
3. Call `link_transactions(from_id, to_id, relation)`.
4. Report the pair and the relation; if `created` is false, say it already existed.

**Only link when the user explicitly asks.** Do not infer relationships from similar wording, shared project, or adjacent deadlines — a graph nobody asked for is worse than none.

### Unlink Transactions

Trigger examples:

- "这两件事没关系了，取消关联。"
- "把它从那个父任务里拿掉。"

Action: call `unlink_transactions`. Omit `relation` only when the user wants every link between the pair gone.

### Merge Duplicate Transactions

Trigger examples:

- "这两条是同一件事，合并一下。"
- "把重复的那条并进主记录。"

Action:

1. Show both records and confirm which one should survive — **always ask before merging**, merging is not obviously reversible.
2. Call `merge_transactions(source_id, target_id)` where `source_id` is the duplicate.
3. Report what moved: the source's notes were appended to the target and its links were repointed.

Merged records are kept as history (`merged_into` points at the survivor) and disappear from `list_transactions` / `summarize_transactions` by default.

### Show Related Items

When the user asks "这件事还牵扯到什么", call `get_transaction` (its `links` field lists related items with title and status) or `list_transactions(linked_to=<id>)`.

### Summarize Transactions

Trigger examples:

- "汇总当前事务。"
- "现在事务状态怎么样？"

Action:

1. Call `summarize_transactions`.
2. Report `total` and `by_status`.

## Response Rules

- Transaction status questions must be answered from a tool call, never from memory: the
  assistant-level memory layer may hold stale statuses, the database is the source of truth.

- Never say "已记录" or "已更新" before tool success.
- Keep Feishu replies concise.
- Always include the transaction ID when reporting a created or updated transaction.
- Use the tool's status values internally, but present Chinese labels to the user when helpful:
   - `new`: 新建
   - `in_progress`: 进行中
   - `waiting_feedback`: 等待反馈
   - `done`: 已完成
- If the tool returns an error code:
   - `transaction_not_found` → tell user the item doesn't exist
   - `invalid_status` → tell user the status value isn't valid
   - `no_fields_to_update` → tell user to specify what to change
