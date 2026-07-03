import sqlite3
from collections.abc import Iterator
from pathlib import Path

from server.app.config import settings


# 后续给已存在的表补列时的期望结构：列名 -> 建列 DDL 片段。
# 新增列统一走这里（幂等迁移），不要写进 CREATE TABLE，避免两处定义不一致。
EXPECTED_COLUMNS = {
    "project": "TEXT",
    "folder_path": "TEXT",
}


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
        _sync_columns(connection)


def _sync_columns(connection: sqlite3.Connection) -> None:
    """给已存在的老表补齐缺失的列（幂等，可重复执行）。

    CREATE TABLE IF NOT EXISTS 对已存在的表会整句跳过，无法给老库加列；
    这里用 PRAGMA 查出实际列，缺哪列就 ALTER TABLE ADD COLUMN 补哪列。
    ADD COLUMN 不支持 IF NOT EXISTS，故必须先检查再加。
    """
    existing = {
        row["name"] for row in connection.execute("PRAGMA table_info(transactions)")
    }
    for name, ddl in EXPECTED_COLUMNS.items():
        if name not in existing:
            connection.execute(
                f"ALTER TABLE transactions ADD COLUMN {name} {ddl}"
            )


def db_session() -> Iterator[sqlite3.Connection]:
    with get_connection() as connection:
        yield connection

