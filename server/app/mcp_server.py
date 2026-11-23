import json
from datetime import datetime

from mcp.server.mcpserver import MCPServer

from server.app import __version__, ppt
from server.app.config import settings
from server.app.database import get_connection, init_db
from server.app.models import TransactionStatus
from server.app.storage import (
    create_transaction,
    delete_transaction,
    get_links,
    get_transaction,
    link_transactions,
    list_transactions,
    merge_transactions,
    summarize_transactions,
    unlink_transactions,
    update_transaction,
)
from server.app.ppt import PptError
from server.app.schemas import TransactionCreate, TransactionUpdate

mcp = MCPServer(
    "aisecretary",
    instructions=(
        "Hermes secretary service — manage work items (create, query, update, delete, "
        "summarize) and inspect PowerPoint decks (outline, single-slide content, "
        "single-slide PNG rendering)."
    ),
    version=__version__,
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
    "Use linked_to to get only transactions linked to a given id. "
    "Merged records are hidden unless include_merged is true. "
    "Without filters, returns all transactions. Returns JSON array — empty array [] if none.",
)
def tool_list_transactions(
    status: str | None = None,
    owner: str | None = None,
    search: str | None = None,
    project: str | None = None,
    linked_to: str | None = None,
    include_merged: bool = False,
) -> str:
    """List transactions with optional filters."""
    init_db()
    with get_connection() as conn:
        results = list_transactions(
            conn,
            status=status,
            owner=owner,
            search=search,
            project=project,
            linked_to=linked_to,
            include_merged=include_merged,
        )
        results = [_serialize_result(r) for r in results]
        return json.dumps(results, ensure_ascii=False)


@mcp.tool(
    name="get_transaction",
    description="Get a single transaction by its UUID id, including its links to other "
    "transactions (each link has id, title, status, relation, direction). "
    "Returns error code 'transaction_not_found' if missing.",
)
def tool_get_transaction(transaction_id: str) -> str:
    """Get a transaction by ID, with its links."""
    init_db()
    with get_connection() as conn:
        result = get_transaction(conn, transaction_id)
        if result is None:
            return json.dumps({"error": "transaction_not_found"})
        payload = _serialize_result(result)
        payload["links"] = get_links(conn, transaction_id)
        return json.dumps(payload, ensure_ascii=False)


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


# ---------------------------------------------------------------------------
# PPT 工具：单页真实渲染 + 内容解读
# ---------------------------------------------------------------------------


def _ppt_json(func, *args, **kwargs) -> str:
    """PPT 工具统一出口：任何异常都收敛成 JSON 错误，不抛回协议层。"""
    try:
        return json.dumps(func(*args, **kwargs), ensure_ascii=False)
    except PptError as exc:
        return json.dumps(exc.to_dict(), ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 - 渲染链路的兜底，绝不让服务挂掉
        return json.dumps(
            {"error": "internal_error", "message": str(exc)[:300]}, ensure_ascii=False
        )


@mcp.tool(
    name="ppt_use_deck",
    description="Set the current PowerPoint deck and remember it for later calls. "
    "Path must be an existing .pptx under the allowed PPT_ROOTS directory. "
    "Returns path, file_name, slide_count, size_mb.",
)
def tool_ppt_use_deck(path: str) -> str:
    """Select the current deck."""
    return _ppt_json(ppt.use_deck, path)


@mcp.tool(
    name="ppt_get_deck",
    description="Return the currently selected deck (path, file_name, slide_count). "
    "Returns error code 'no_deck' when nothing is selected.",
)
def tool_ppt_get_deck() -> str:
    """Show the current deck."""
    return _ppt_json(ppt.get_deck)


@mcp.tool(
    name="ppt_outline",
    description="List every slide's title and first line of body text. "
    "Use for an overview of the whole deck. Omit path to use the current deck.",
)
def tool_ppt_outline(path: str | None = None, max_slides: int = 64) -> str:
    """Summarize deck structure."""
    return _ppt_json(ppt.outline, path, max_slides)


@mcp.tool(
    name="ppt_get_slide",
    description="Get one slide's content: title, text paragraphs, tables, speaker notes, "
    "image count, whether it has video, and layout name. Page is 1-based. "
    "Omit path to use the current deck. Returns 'slide_out_of_range' with slide_count when out of range.",
)
def tool_ppt_get_slide(page: int, path: str | None = None) -> str:
    """Read a single slide's content."""
    return _ppt_json(ppt.get_slide, page, path)


@mcp.tool(
    name="ppt_render_slide",
    description="Render exactly one slide to a real PNG via LibreOffice (not a redraw). "
    "Returns the absolute PNG path, width, height, page, slide_count, ms and cached flag. "
    "Page is 1-based; dpi is 72-300 (default 150). Omit path to use the current deck. "
    "The returned path can be sent by Hermes as 'MEDIA:<path>'.",
)
def tool_ppt_render_slide(
    page: int, path: str | None = None, dpi: int = 150
) -> str:
    """Render one slide to PNG."""
    return _ppt_json(ppt.render_slide, page, path, dpi)


# ---------------------------------------------------------------------------
# 事务关联与合并
# ---------------------------------------------------------------------------


@mcp.tool(
    name="link_transactions",
    description="Create a link between two transactions. relation must be one of: "
    "'part_of' (from_id is a sub-task of to_id), 'blocks' (from_id blocks to_id), "
    "'related' (symmetric, loosely related). Only call when the user explicitly asks "
    "to link items — do not guess relationships. Idempotent: returns created=false if it already exists.",
)
def tool_link_transactions(
    from_id: str, to_id: str, relation: str = "related"
) -> str:
    """Link two transactions."""
    init_db()
    with get_connection() as conn:
        try:
            return json.dumps(
                link_transactions(conn, from_id, to_id, relation), ensure_ascii=False
            )
        except ValueError as exc:
            return json.dumps(
                {"error": "invalid_link", "message": str(exc)}, ensure_ascii=False
            )


@mcp.tool(
    name="unlink_transactions",
    description="Remove a link between two transactions. Omit relation to remove every "
    "link between the pair. Returns the number of links removed.",
)
def tool_unlink_transactions(
    from_id: str, to_id: str, relation: str | None = None
) -> str:
    """Remove a link."""
    init_db()
    with get_connection() as conn:
        try:
            return json.dumps(
                unlink_transactions(conn, from_id, to_id, relation), ensure_ascii=False
            )
        except ValueError as exc:
            return json.dumps(
                {"error": "invalid_relation", "message": str(exc)}, ensure_ascii=False
            )


@mcp.tool(
    name="merge_transactions",
    description="Merge a duplicate transaction into the one that should be kept. "
    "source_id is the duplicate (kept as history, hidden from lists), target_id is the record "
    "that survives. The source's notes are appended to the target and its links are moved over. "
    "Always confirm with the user before merging.",
)
def tool_merge_transactions(source_id: str, target_id: str) -> str:
    """Merge a duplicate transaction into another."""
    init_db()
    with get_connection() as conn:
        try:
            result = merge_transactions(conn, source_id, target_id)
        except ValueError as exc:
            return json.dumps(
                {"error": "invalid_merge", "message": str(exc)}, ensure_ascii=False
            )
        result["target"] = _serialize_result(result["target"])
        return json.dumps(result, ensure_ascii=False)
