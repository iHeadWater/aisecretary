from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from sqlite3 import Connection

from fastapi import Depends, FastAPI, HTTPException, status

from server.app.database import db_session, init_db
from server.app.schemas import (
    Transaction,
    TransactionCreate,
    TransactionSummary,
    TransactionUpdate,
)
from server.app.storage import (
    create_transaction,
    get_transaction,
    list_transactions,
    summarize_transactions,
    update_transaction,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(
    title="Hermes Transaction Layer",
    version="0.1.0",
    lifespan=lifespan,
)


def get_db() -> Iterator[Connection]:
    yield from db_session()


def error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/transactions",
    response_model=Transaction,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction_endpoint(
    payload: TransactionCreate,
    connection: Connection = Depends(get_db),
) -> dict:
    return create_transaction(connection, payload)


@app.get("/transactions", response_model=list[Transaction])
def list_transactions_endpoint(connection: Connection = Depends(get_db)) -> list[dict]:
    return list_transactions(connection)


@app.get("/transactions/summary", response_model=TransactionSummary)
def summarize_transactions_endpoint(
    connection: Connection = Depends(get_db),
) -> dict:
    return summarize_transactions(connection)


@app.get("/transactions/{transaction_id}", response_model=Transaction)
def get_transaction_endpoint(
    transaction_id: str,
    connection: Connection = Depends(get_db),
) -> dict:
    transaction = get_transaction(connection, transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                "transaction_not_found",
                "Transaction not found",
            ),
        )
    return transaction


@app.patch("/transactions/{transaction_id}", response_model=Transaction)
def update_transaction_endpoint(
    transaction_id: str,
    payload: TransactionUpdate,
    connection: Connection = Depends(get_db),
) -> dict:
    if not payload.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(
                "no_fields_to_update",
                "At least one transaction field is required",
            ),
        )

    transaction = update_transaction(connection, transaction_id, payload)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                "transaction_not_found",
                "Transaction not found",
            ),
        )
    return transaction
