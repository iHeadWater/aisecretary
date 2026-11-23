import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from server.app.models import INVERSE_RELATION, SYMMETRIC_RELATIONS, RelationType
from server.app.schemas import TransactionCreate, TransactionUpdate


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "next_action": row["next_action"],
        "owner": row["owner"],
        "suggested_follow_up_at": row["suggested_follow_up_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "notes": row["notes"],
        "project": row["project"],
        "folder_path": row["folder_path"],
        "merged_into": row["merged_into"],
    }


def create_transaction(
    connection: sqlite3.Connection, payload: TransactionCreate
) -> dict:
    now = _utc_now()
    transaction = {
        "id": str(uuid4()),
        "title": payload.title,
        "status": payload.status.value,
        "next_action": payload.next_action,
        "owner": payload.owner,
        "suggested_follow_up_at": _serialize_datetime(payload.suggested_follow_up_at),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "notes": payload.notes,
        "project": payload.project,
        "folder_path": payload.folder_path,
    }
    connection.execute(
        """
        INSERT INTO transactions (
            id, title, status, next_action, owner, suggested_follow_up_at,
            created_at, updated_at, notes, project, folder_path
        ) VALUES (
            :id, :title, :status, :next_action, :owner, :suggested_follow_up_at,
            :created_at, :updated_at, :notes, :project, :folder_path
        )
        """,
        transaction,
    )
    connection.commit()
    return transaction


def list_transactions(
    connection: sqlite3.Connection,
    status: str | None = None,
    owner: str | None = None,
    search: str | None = None,
    project: str | None = None,
    linked_to: str | None = None,
    include_merged: bool = False,
) -> list[dict]:
    """List transactions with optional filters.

    Args:
        status: Comma-separated status values to include (e.g. "new,in_progress").
        owner: Filter by owner name (partial match).
        search: Search title and notes (case-insensitive partial match).
        project: Filter by exact project name.
        linked_to: Only return transactions linked to this id (either direction).
        include_merged: Include records already merged into another one.
    """
    conditions = []
    params: list[str] = []

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            conditions.append(f"status IN ({placeholders})")
            params.extend(statuses)

    if owner:
        conditions.append("owner LIKE ?")
        params.append(f"%{owner}%")

    if search:
        conditions.append("(title LIKE ? OR notes LIKE ?)")
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    if project is not None:
        conditions.append("project = ?")
        params.append(project)

    # 被合并的记录默认不出现在列表里，除非显式要求
    if not include_merged:
        conditions.append("merged_into IS NULL")

    if linked_to:
        conditions.append(
            "id IN ("
            "SELECT from_id FROM transaction_links WHERE to_id = ? "
            "UNION SELECT to_id FROM transaction_links WHERE from_id = ?"
            ")"
        )
        params.extend([linked_to, linked_to])

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    rows = connection.execute(
        f"""
        SELECT id, title, status, next_action, owner, suggested_follow_up_at,
               created_at, updated_at, notes, project, folder_path, merged_into
        FROM transactions
        {where}
        ORDER BY updated_at DESC
        """,
        params,
    ).fetchall()
    return [_parse_row(row) for row in rows]


def summarize_transactions(connection: sqlite3.Connection) -> dict:
    rows = connection.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM transactions
        WHERE merged_into IS NULL
        GROUP BY status
        """
    ).fetchall()
    by_status = {row["status"]: row["count"] for row in rows}
    total = sum(by_status.values())
    return {"total": total, "by_status": by_status}


def get_transaction(connection: sqlite3.Connection, transaction_id: str) -> dict | None:
    row = connection.execute(
        """
        SELECT id, title, status, next_action, owner, suggested_follow_up_at,
               created_at, updated_at, notes, project, folder_path, merged_into
        FROM transactions
        WHERE id = ?
        """,
        (transaction_id,),
    ).fetchone()
    return _parse_row(row) if row else None


def delete_transaction(connection: sqlite3.Connection, transaction_id: str) -> bool:
    cursor = connection.execute(
        "DELETE FROM transactions WHERE id = ?",
        (transaction_id,),
    )
    # 关联边一并清掉，避免留下悬空引用
    connection.execute(
        "DELETE FROM transaction_links WHERE from_id = ? OR to_id = ?",
        (transaction_id, transaction_id),
    )
    connection.commit()
    return cursor.rowcount > 0


def update_transaction(
    connection: sqlite3.Connection,
    transaction_id: str,
    payload: TransactionUpdate,
) -> dict | None:
    existing = get_transaction(connection, transaction_id)
    if existing is None:
        return None

    update_values = payload.model_dump(exclude_unset=True)
    if not update_values:
        return existing

    if "status" in update_values and update_values["status"] is not None:
        update_values["status"] = update_values["status"].value
    if "suggested_follow_up_at" in update_values:
        update_values["suggested_follow_up_at"] = _serialize_datetime(
            update_values["suggested_follow_up_at"]
        )
    update_values["updated_at"] = _utc_now().isoformat()

    assignments = ", ".join(f"{field} = :{field}" for field in update_values)
    connection.execute(
        f"UPDATE transactions SET {assignments} WHERE id = :id",
        {"id": transaction_id, **update_values},
    )
    connection.commit()
    return get_transaction(connection, transaction_id)


# ---------------------------------------------------------------------------
# 事务关联（link）与合并（merge）
# ---------------------------------------------------------------------------


def _relation_value(relation: str | RelationType) -> str:
    try:
        return RelationType(str(relation)).value
    except ValueError as exc:
        valid = ", ".join(r.value for r in RelationType)
        raise ValueError(f"无效的关联类型：{relation}（可选：{valid}）") from exc


def _require_transaction(connection: sqlite3.Connection, transaction_id: str) -> dict:
    row = get_transaction(connection, transaction_id)
    if row is None:
        raise ValueError(f"事务不存在：{transaction_id}")
    return row


def link_transactions(
    connection: sqlite3.Connection,
    from_id: str,
    to_id: str,
    relation: str | RelationType = RelationType.RELATED,
) -> dict:
    """建立一条关联边。幂等：重复关联返回 created=False。"""
    relation = _relation_value(relation)
    if from_id == to_id:
        raise ValueError("不能把事务关联到它自己")
    _require_transaction(connection, from_id)
    _require_transaction(connection, to_id)

    cursor = connection.execute(
        "INSERT OR IGNORE INTO transaction_links (from_id, to_id, relation, created_at) "
        "VALUES (?, ?, ?, ?)",
        (from_id, to_id, relation, _utc_now().isoformat()),
    )
    connection.commit()
    return {
        "from_id": from_id,
        "to_id": to_id,
        "relation": relation,
        "created": cursor.rowcount > 0,
    }


def unlink_transactions(
    connection: sqlite3.Connection,
    from_id: str,
    to_id: str,
    relation: str | RelationType | None = None,
) -> dict:
    """删除关联。relation 为空时删掉两者之间的所有边。"""
    if relation is None:
        cursor = connection.execute(
            "DELETE FROM transaction_links "
            "WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)",
            (from_id, to_id, to_id, from_id),
        )
    else:
        relation_value = _relation_value(relation)
        if RelationType(relation_value) in SYMMETRIC_RELATIONS:
            cursor = connection.execute(
                "DELETE FROM transaction_links "
                "WHERE relation = ? AND ("
                "(from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)"
                ")",
                (relation_value, from_id, to_id, to_id, from_id),
            )
        else:
            cursor = connection.execute(
                "DELETE FROM transaction_links "
                "WHERE from_id = ? AND to_id = ? AND relation = ?",
                (from_id, to_id, relation_value),
            )
    connection.commit()
    return {"removed": cursor.rowcount}


def get_links(connection: sqlite3.Connection, transaction_id: str) -> list[dict]:
    """返回某事务的全部关联，带出对方的标题和状态，省掉二次查询。

    direction='out' 表示这条边从本事务出发（如「我是某事的子任务」）；
    direction='in' 表示别人指向本事务，relation 已翻译成反向语义
    （如别人 part_of 我 → 我看到 has_part）。
    """
    rows = connection.execute(
        """
        SELECT l.relation, l.to_id AS other_id, t.title, t.status, 'out' AS direction
        FROM transaction_links l
        JOIN transactions t ON t.id = l.to_id
        WHERE l.from_id = ?
        UNION ALL
        SELECT l.relation, l.from_id AS other_id, t.title, t.status, 'in' AS direction
        FROM transaction_links l
        JOIN transactions t ON t.id = l.from_id
        WHERE l.to_id = ?
        """,
        (transaction_id, transaction_id),
    ).fetchall()

    links: list[dict] = []
    for row in rows:
        raw = row["relation"]
        if row["direction"] == "in":
            relation = INVERSE_RELATION.get(RelationType(raw), raw)
        else:
            relation = raw
        links.append(
            {
                "id": row["other_id"],
                "title": row["title"],
                "status": row["status"],
                "relation": relation,
                "direction": row["direction"],
            }
        )
    links.sort(key=lambda item: (item["relation"], item["title"] or ""))
    return links


def merge_transactions(
    connection: sqlite3.Connection, source_id: str, target_id: str
) -> dict:
    """把 source 合并进 target：notes 追加、关联边重指向、source 标记 merged_into。

    source 不会被删除，保留为历史记录，但不再出现在默认列表与汇总里。
    """
    if source_id == target_id:
        raise ValueError("不能把事务合并到它自己")
    source = _require_transaction(connection, source_id)
    target = _require_transaction(connection, target_id)
    if source["merged_into"]:
        raise ValueError(f"事务已合并到 {source['merged_into']}，不能再次合并")

    now = _utc_now().isoformat()
    note_lines = [f"合并自「{source['title']}」({source_id})"]
    if source["notes"]:
        note_lines.append(source["notes"])
    merged_note = "\n".join(note_lines)
    new_notes = f"{target['notes']}\n\n{merged_note}" if target["notes"] else merged_note

    # 关联边重指向：先把 source 的边搬到 target，冲突的自环丢弃
    edges = connection.execute(
        "SELECT from_id, to_id, relation, created_at FROM transaction_links "
        "WHERE from_id = ? OR to_id = ?",
        (source_id, source_id),
    ).fetchall()
    repointed = 0
    for edge in edges:
        new_from = target_id if edge["from_id"] == source_id else edge["from_id"]
        new_to = target_id if edge["to_id"] == source_id else edge["to_id"]
        if new_from == new_to:
            continue
        connection.execute(
            "INSERT OR IGNORE INTO transaction_links (from_id, to_id, relation, created_at) "
            "VALUES (?, ?, ?, ?)",
            (new_from, new_to, edge["relation"], edge["created_at"]),
        )
        repointed += 1
    connection.execute(
        "DELETE FROM transaction_links WHERE from_id = ? OR to_id = ?",
        (source_id, source_id),
    )

    connection.execute(
        "UPDATE transactions SET merged_into = ?, updated_at = ? WHERE id = ?",
        (target_id, now, source_id),
    )
    connection.execute(
        "UPDATE transactions SET notes = ?, updated_at = ? WHERE id = ?",
        (new_notes, now, target_id),
    )
    connection.commit()

    return {
        "merged": True,
        "source_id": source_id,
        "target_id": target_id,
        "repointed_links": repointed,
        "target": get_transaction(connection, target_id),
    }
