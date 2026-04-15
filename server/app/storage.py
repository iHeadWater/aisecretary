import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

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
    }
    connection.execute(
        """
        INSERT INTO transactions (
            id, title, status, next_action, owner, suggested_follow_up_at,
            created_at, updated_at, notes
        ) VALUES (
            :id, :title, :status, :next_action, :owner, :suggested_follow_up_at,
            :created_at, :updated_at, :notes
        )
        """,
        transaction,
    )
    connection.commit()
    return transaction


def list_transactions(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT id, title, status, next_action, owner, suggested_follow_up_at,
               created_at, updated_at, notes
        FROM transactions
        ORDER BY updated_at DESC
        """
    ).fetchall()
    return [_parse_row(row) for row in rows]


def summarize_transactions(connection: sqlite3.Connection) -> dict:
    rows = connection.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM transactions
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
               created_at, updated_at, notes
        FROM transactions
        WHERE id = ?
        """,
        (transaction_id,),
    ).fetchone()
    return _parse_row(row) if row else None


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
