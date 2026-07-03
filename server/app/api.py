from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from server.app.database import db_session
from server.app.schemas import (
    Transaction,
    TransactionCreate,
    TransactionSummary,
    TransactionUpdate,
)
from server.app.storage import (
    create_transaction,
    delete_transaction,
    get_transaction,
    list_transactions,
    summarize_transactions,
    update_transaction,
)

router = APIRouter(prefix="/api")


def get_db():
    yield from db_session()


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/transactions", response_model=Transaction, status_code=status.HTTP_201_CREATED)
def create(payload: TransactionCreate, conn: Connection = Depends(get_db)):
    return create_transaction(conn, payload)


@router.get("/transactions", response_model=list[Transaction])
def list_all(
    status: str | None = None,
    owner: str | None = None,
    search: str | None = None,
    project: str | None = None,
    conn: Connection = Depends(get_db),
):
    return list_transactions(conn, status=status, owner=owner, search=search, project=project)


@router.get("/transactions/summary", response_model=TransactionSummary)
def summary(conn: Connection = Depends(get_db)):
    return summarize_transactions(conn)


class BatchUpdateItem(BaseModel):
    id: str
    title: str | None = None
    status: str | None = None
    owner: str | None = None
    next_action: str | None = None
    suggested_follow_up_at: str | None = None
    notes: str | None = None
    project: str | None = None
    folder_path: str | None = None


@router.patch("/transactions/batch")
def batch_update(items: list[BatchUpdateItem], conn: Connection = Depends(get_db)):
    results = []
    for item in items:
        update_kwargs = {k: v for k, v in item.model_dump(exclude_unset=True, exclude={"id"}).items() if v is not None}
        if not update_kwargs:
            results.append({"error": "no_fields_to_update", "id": item.id})
            continue
        payload = TransactionUpdate(**update_kwargs)
        result = update_transaction(conn, item.id, payload)
        if result is None:
            results.append({"error": "transaction_not_found", "id": item.id})
        else:
            results.append(result)
    return results


@router.get("/transactions/{transaction_id}", response_model=Transaction)
def get_one(transaction_id: str, conn: Connection = Depends(get_db)):
    result = get_transaction(conn, transaction_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("transaction_not_found", "Transaction not found"),
        )
    return result


@router.patch("/transactions/{transaction_id}", response_model=Transaction)
def update(transaction_id: str, payload: TransactionUpdate, conn: Connection = Depends(get_db)):
    if not payload.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error("no_fields_to_update", "At least one field is required"),
        )
    result = update_transaction(conn, transaction_id, payload)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("transaction_not_found", "Transaction not found"),
        )
    return result


@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(transaction_id: str, conn: Connection = Depends(get_db)):
    if not delete_transaction(conn, transaction_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("transaction_not_found", "Transaction not found"),
        )
