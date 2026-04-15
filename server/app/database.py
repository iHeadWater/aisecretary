import sqlite3
from collections.abc import Iterator
from pathlib import Path

from server.app.config import settings


def get_database_path() -> Path:
    return settings.database_path


def get_connection() -> sqlite3.Connection:
    database_path = get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                next_action TEXT,
                owner TEXT,
                suggested_follow_up_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                notes TEXT
            )
            """
        )


def db_session() -> Iterator[sqlite3.Connection]:
    with get_connection() as connection:
        yield connection

