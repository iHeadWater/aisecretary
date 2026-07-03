import json
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from server.app.config import settings
from server.app.database import get_connection, init_db
from server.app.models import TransactionStatus
from server.app.storage import (
    create_transaction,
    delete_transaction,
    get_transaction,
    list_transactions,
    summarize_transactions,
    update_transaction,
)
from server.app.schemas import TransactionCreate, TransactionUpdate

mcp = FastMCP(
    "aisecretary",
    host="0.0.0.0",
    streamable_http_path="/",
    instructions="Hermes transaction database service — create, query, update, delete, and summarize work items.",
)

STATUS_DESC = """
Status values:
- new: 新建
- in_progress: 进行中
- waiting_feedback: 等待反馈
- done: 已完成
"""


@mcp.tool(
    name="create_transaction",
    description="Create a new transaction. Fields except title are optional. "
    "Use project to associate with a project name, folder_path for the project directory.",
)
def tool_create_transaction(
    title: str,
    status: str = "new",
    owner: str = "unassigned",
    next_action: str | None = None,
    notes: str | None = None,
    follow_up: str | None = None,
    project: str | None = None,
    folder_path: str | None = None,
) -> str:
    """Create a transaction and return the created record as JSON."""
    if status not in {s.value for s in TransactionStatus}:
        valid = ", ".join(s.value for s in TransactionStatus)
        return json.dumps({"error": "invalid_status", "message": f"Must be one of: {valid}"})

    init_db()
    with get_connection() as conn:
        try:
            payload = TransactionCreate(
                title=title,
                status=TransactionStatus(status),
                owner=owner,
                next_action=next_action,
                notes=notes,
                suggested_follow_up_at=datetime.fromisoformat(follow_up) if follow_up else None,
                project=project,
                folder_path=folder_path,
            )
        except ValueError as e:
            return json.dumps({"error": "validation_error", "message": str(e)})

        result = create_transaction(conn, payload)
        result = _serialize_result(result)
        return json.dumps(result, ensure_ascii=False)


@mcp.tool(
    name="list_transactions",
    description="List transactions ordered by last updated, with optional filters. "
    "Use status to filter by comma-separated status values (e.g. 'new,in_progress' for unfinished). "
    "Use owner for partial name match. Use search for keyword search in title and notes. "
    "Use project to filter by exact project name. "
    "Without filters, returns all transactions. Returns JSON array — empty array [] if none.",
)
def tool_list_transactions(
    status: str | None = None,
    owner: str | None = None,
    search: str | None = None,
    project: str | None = None,
) -> str:
    """List transactions with optional filters."""
    init_db()
    with get_connection() as conn:
        results = list_transactions(conn, status=status, owner=owner, search=search, project=project)
        results = [_serialize_result(r) for r in results]
        return json.dumps(results, ensure_ascii=False)


@mcp.tool(
    name="get_transaction",
    description="Get a single transaction by its UUID id. Returns the transaction JSON or error code 'transaction_not_found'.",
)
def tool_get_transaction(transaction_id: str) -> str:
    """Get a transaction by ID."""
    init_db()
    with get_connection() as conn:
        result = get_transaction(conn, transaction_id)
        if result is None:
            return json.dumps({"error": "transaction_not_found"})
        return json.dumps(_serialize_result(result), ensure_ascii=False)


@mcp.tool(
    name="update_transaction",
    description="Update fields of a transaction by ID. Only pass fields you want to change. "
    "Pass empty string to clear nullable fields. Supports project and folder_path fields.",
)
def tool_update_transaction(
    transaction_id: str,
    title: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    next_action: str | None = None,
    notes: str | None = None,
    follow_up: str | None = None,
    project: str | None = None,
    folder_path: str | None = None,
) -> str:
    """Update a transaction."""
    if status is not None and status not in {s.value for s in TransactionStatus}:
        valid = ", ".join(s.value for s in TransactionStatus)
        return json.dumps({"error": "invalid_status", "message": f"Must be one of: {valid}"})

    init_db()
    with get_connection() as conn:
        update_kwargs = {}
        if title is not None:
            update_kwargs["title"] = title
        if status is not None:
            update_kwargs["status"] = TransactionStatus(status)
        if owner is not None:
            update_kwargs["owner"] = owner if owner else None
        if next_action is not None:
            update_kwargs["next_action"] = next_action if next_action else None
        if notes is not None:
            update_kwargs["notes"] = notes if notes else None
        if project is not None:
            update_kwargs["project"] = project if project else None
        if folder_path is not None:
            update_kwargs["folder_path"] = folder_path if folder_path else None
        if follow_up is not None:
            try:
                update_kwargs["suggested_follow_up_at"] = (
                    datetime.fromisoformat(follow_up) if follow_up else None
                )
            except ValueError:
                return json.dumps(
                    {"error": "validation_error", "message": f"Invalid ISO-8601 datetime: {follow_up}"}
                )

        if not update_kwargs:
            return json.dumps({"error": "no_fields_to_update"})

        payload = TransactionUpdate(**update_kwargs)
        result = update_transaction(conn, transaction_id, payload)
        if result is None:
            return json.dumps({"error": "transaction_not_found"})
        return json.dumps(_serialize_result(result), ensure_ascii=False)


@mcp.tool(
    name="delete_transaction",
    description="Delete a transaction permanently by ID. Always confirm with user before calling.",
)
def tool_delete_transaction(transaction_id: str) -> str:
    """Delete a transaction."""
    init_db()
    with get_connection() as conn:
        deleted = delete_transaction(conn, transaction_id)
        if not deleted:
            return json.dumps({"error": "transaction_not_found"})
        return json.dumps({"deleted": True, "id": transaction_id})


@mcp.tool(
    name="summarize_transactions",
    description="Get a count summary of transactions grouped by status.",
)
def tool_summarize_transactions() -> str:
    """Summarize transactions by status."""
    init_db()
    with get_connection() as conn:
        result = summarize_transactions(conn)
        return json.dumps(result, ensure_ascii=False)


@mcp.tool(
    name="batch_update_transactions",
    description="Update multiple transactions at once. Pass a JSON array of update objects, "
    "each with 'id' (required) and any fields to change. Fields: title, status, owner, "
    "next_action, follow_up, notes, project, folder_path. "
    "Example: [{\"id\":\"xxx\",\"status\":\"done\"},{\"id\":\"yyy\",\"status\":\"in_progress\"}]. "
    "Returns results array — each is either the updated transaction or {\"error\":\"...\",\"id\":\"...\"}.",
)
def tool_batch_update_transactions(updates: str) -> str:
    """Batch update multiple transactions."""
    try:
        items = json.loads(updates)
    except json.JSONDecodeError as e:
        return json.dumps({"error": "invalid_json", "message": str(e)})

    if not isinstance(items, list) or len(items) == 0:
        return json.dumps({"error": "invalid_input", "message": "updates must be a non-empty JSON array"})

    init_db()
    results = []
    with get_connection() as conn:
        for item in items:
            if not isinstance(item, dict) or "id" not in item:
                results.append({"error": "missing_id", "id": str(item)})
                continue

            tx_id = item["id"]
            update_kwargs = {}
            for field in ("title", "owner", "next_action", "notes", "follow_up", "status", "project", "folder_path"):
                if field in item:
                    val = item[field]
                    if field == "status" and val is not None:
                        if val not in {s.value for s in TransactionStatus}:
                            results.append({"error": "invalid_status", "id": tx_id, "message": f"Invalid status: {val}"})
                            continue
                        update_kwargs["status"] = TransactionStatus(val)
                    elif field == "follow_up":
                        try:
                            update_kwargs["suggested_follow_up_at"] = (
                                datetime.fromisoformat(val) if val else None
                            )
                        except ValueError:
                            results.append({"error": "invalid_date", "id": tx_id, "message": f"Invalid ISO-8601: {val}"})
                            continue
                    elif field == "owner":
                        update_kwargs["owner"] = val if val else None
                    elif field in ("next_action", "notes", "project", "folder_path"):
                        update_kwargs[field] = val if val else None
                    elif field == "title":
                        update_kwargs["title"] = val

            if not update_kwargs:
                results.append({"error": "no_fields_to_update", "id": tx_id})
                continue

            try:
                payload = TransactionUpdate(**update_kwargs)
                result = update_transaction(conn, tx_id, payload)
                if result is None:
                    results.append({"error": "transaction_not_found", "id": tx_id})
                else:
                    results.append(_serialize_result(result))
            except Exception as e:
                results.append({"error": "update_failed", "id": tx_id, "message": str(e)})

    return json.dumps(results, ensure_ascii=False)


def _serialize_result(result: dict) -> dict:
    """Convert datetime objects in result dict to ISO format strings for JSON serialization."""
    serialized = dict(result)
    for key in ("created_at", "updated_at", "suggested_follow_up_at"):
        value = serialized.get(key)
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
    if "status" in serialized and hasattr(serialized["status"], "value"):
        serialized["status"] = serialized["status"].value
    if "by_status" in serialized:
        serialized["by_status"] = {
            (k.value if hasattr(k, "value") else k): v
            for k, v in serialized["by_status"].items()
        }
    return serialized
