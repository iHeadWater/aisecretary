#!/usr/bin/env python
"""
CLI for Hermes to manage transactions via SSH on the host machine.

Usage:
  python3 aisecretary_cli.py create --title "..." [--owner "..."] [--next-action "..."] [--status new] [--follow-up "ISO-8601"] [--notes "..."]
  python3 aisecretary_cli.py list
  python3 aisecretary_cli.py get <id>
  python3 aisecretary_cli.py update <id> [--title "..."] [--status "..."] [--owner "..."] [--next-action "..."] [--follow-up "ISO-8601"] [--notes "..."]
  python3 aisecretary_cli.py summary

Output is always JSON. Errors print {"error": "<code>"} to stdout and exit 1.
DATABASE_PATH env var overrides the default db location.
"""

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

DB_PATH = os.path.expanduser(
    os.environ.get("DATABASE_PATH", "~/.myagentdata/aisecretary/transactions.sqlite")
)

VALID_STATUSES = {"new", "in_progress", "waiting_feedback", "done"}


def unquote(s):
    """Strip surrounding single or double quotes passed literally by Windows cmd.exe."""
    if s and len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id                   TEXT PRIMARY KEY,
            title                TEXT NOT NULL,
            status               TEXT NOT NULL DEFAULT 'new',
            next_action          TEXT,
            owner                TEXT NOT NULL DEFAULT 'unassigned',
            suggested_follow_up_at TEXT,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            notes                TEXT
        )
    """)
    conn.commit()
    return conn


def row_dict(row):
    return dict(row)


def err(code, message=None):
    out = {"error": code}
    if message:
        out["message"] = message
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1)


def cmd_create(args):
    if args.status and args.status not in VALID_STATUSES:
        err("invalid_status", f"status must be one of: {', '.join(VALID_STATUSES)}")
    conn = get_conn()
    tx_id = str(uuid.uuid4())
    now = now_iso()
    conn.execute(
        "INSERT INTO transactions (id, title, status, next_action, owner, suggested_follow_up_at, created_at, updated_at, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            tx_id,
            args.title,
            args.status or "new",
            args.next_action,
            args.owner or "unassigned",
            args.follow_up,
            now,
            now,
            args.notes,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    print(json.dumps(row_dict(row), ensure_ascii=False))


def cmd_list(args):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM transactions ORDER BY updated_at DESC").fetchall()
    print(json.dumps([row_dict(r) for r in rows], ensure_ascii=False))


def cmd_get(args):
    conn = get_conn()
    row = conn.execute("SELECT * FROM transactions WHERE id=?", (args.id,)).fetchone()
    if not row:
        err("transaction_not_found")
    print(json.dumps(row_dict(row), ensure_ascii=False))


def cmd_update(args):
    if args.status is not None and args.status not in VALID_STATUSES:
        err("invalid_status", f"status must be one of: {', '.join(VALID_STATUSES)}")
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM transactions WHERE id=?", (args.id,)).fetchone():
        err("transaction_not_found")
    fields = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.status is not None:
        fields["status"] = args.status
    if args.next_action is not None:
        fields["next_action"] = args.next_action or None
    if args.owner is not None:
        fields["owner"] = args.owner
    if args.follow_up is not None:
        fields["suggested_follow_up_at"] = args.follow_up or None
    if args.notes is not None:
        fields["notes"] = args.notes or None
    if not fields:
        err("no_fields_to_update")
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE transactions SET {set_clause} WHERE id=?",
        list(fields.values()) + [args.id],
    )
    conn.commit()
    row = conn.execute("SELECT * FROM transactions WHERE id=?", (args.id,)).fetchone()
    print(json.dumps(row_dict(row), ensure_ascii=False))


def cmd_summary(args):
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM transactions GROUP BY status"
    ).fetchall()
    by_status = {r["status"]: r["cnt"] for r in rows}
    print(json.dumps({"total": total, "by_status": by_status}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="aisecretary CLI")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("create")
    p.add_argument("--title", required=True, type=unquote)
    p.add_argument("--status", default="new", type=unquote)
    p.add_argument("--owner", type=unquote)
    p.add_argument("--next-action", dest="next_action", type=unquote)
    p.add_argument("--follow-up", dest="follow_up", type=unquote)
    p.add_argument("--notes", type=unquote)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("list")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("get")
    p.add_argument("id", type=unquote)
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("update")
    p.add_argument("id", type=unquote)
    p.add_argument("--title", type=unquote)
    p.add_argument("--status", type=unquote)
    p.add_argument("--owner", type=unquote)
    p.add_argument("--next-action", dest="next_action", type=unquote)
    p.add_argument("--follow-up", dest="follow_up", type=unquote)
    p.add_argument("--notes", type=unquote)
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("summary")
    p.set_defaults(func=cmd_summary)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
