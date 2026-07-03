#!/usr/bin/env python3
"""
aisecretary CLI — thin HTTP client like `gh`.

All commands call the aisecretary REST API. Default base URL:
  http://localhost:8000/api

Override with AISECRETARY_URL environment variable:
  export AISECRETARY_URL=http://aisecretary:8000/api

Usage:
  aisecretary create --title "..." [--owner "..."] [--status new] [--next-action "..."] [--follow-up "ISO-8601"] [--notes "..."] [--project "..."] [--folder-path "..."]
  aisecretary list [--status "..."] [--owner "..."] [--search "..."] [--project "..."]
  aisecretary get <id>
  aisecretary update <id> [--title "..."] [--status "..."] [--owner "..."] [--next-action "..."] [--follow-up "ISO-8601"] [--notes "..."] [--project "..."] [--folder-path "..."]
  aisecretary delete <id>
  aisecretary summary

Output is always JSON. Errors print {"error": "<code>"} to stdout and exit 1.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("AISECRETARY_URL", "http://localhost:8000/api")

VALID_STATUSES = {"new", "in_progress", "waiting_feedback", "done"}


def unquote(s):
    """Strip surrounding single or double quotes passed literally by Windows cmd.exe."""
    if s and len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def err(code, message=None):
    out = {"error": code}
    if message:
        out["message"] = message
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1)


def _request(method, path, body=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 204:
                return {"deleted": True}
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read().decode("utf-8"))
        if isinstance(detail, dict) and "detail" in detail:
            inner = detail["detail"]
            if isinstance(inner, dict) and "code" in inner:
                err(inner["code"], inner.get("message"))
            if isinstance(inner, list):
                err("validation_error", str(inner))
        err("http_error", str(e))
    except urllib.error.URLError as e:
        err("connection_error", f"Cannot reach aisecretary at {BASE_URL}: {e.reason}")


def cmd_create(args):
    if args.status and args.status not in VALID_STATUSES:
        err("invalid_status", f"status must be one of: {', '.join(VALID_STATUSES)}")
    body = {
        "title": args.title,
        "status": args.status or "new",
        "owner": args.owner or "unassigned",
    }
    if args.next_action:
        body["next_action"] = args.next_action
    if args.follow_up:
        body["suggested_follow_up_at"] = args.follow_up
    if args.notes:
        body["notes"] = args.notes
    if args.project:
        body["project"] = args.project
    if args.folder_path:
        body["folder_path"] = args.folder_path
    result = _request("POST", "/transactions", body)
    print(json.dumps(result, ensure_ascii=False))


def cmd_list(args):
    params = {}
    if args.status:
        params["status"] = args.status
    if args.owner:
        params["owner"] = args.owner
    if args.search:
        params["search"] = args.search
    if args.project:
        params["project"] = args.project
    qs = urllib.parse.urlencode(params) if params else ""
    path = f"/transactions?{qs}" if qs else "/transactions"
    result = _request("GET", path)
    print(json.dumps(result, ensure_ascii=False))


def cmd_get(args):
    result = _request("GET", f"/transactions/{args.id}")
    print(json.dumps(result, ensure_ascii=False))


def cmd_update(args):
    if args.status is not None and args.status not in VALID_STATUSES:
        err("invalid_status", f"status must be one of: {', '.join(VALID_STATUSES)}")
    body = {}
    if args.title is not None:
        body["title"] = args.title
    if args.status is not None:
        body["status"] = args.status
    if args.next_action is not None:
        body["next_action"] = args.next_action or None
    if args.owner is not None:
        body["owner"] = args.owner
    if args.follow_up is not None:
        body["suggested_follow_up_at"] = args.follow_up
    if args.notes is not None:
        body["notes"] = args.notes
    if args.project is not None:
        body["project"] = args.project
    if args.folder_path is not None:
        body["folder_path"] = args.folder_path
    if not body:
        err("no_fields_to_update")
    result = _request("PATCH", f"/transactions/{args.id}", body)
    print(json.dumps(result, ensure_ascii=False))


def cmd_delete(args):
    result = _request("DELETE", f"/transactions/{args.id}")
    print(json.dumps(result, ensure_ascii=False))


def cmd_summary(_):
    result = _request("GET", "/transactions/summary")
    print(json.dumps(result, ensure_ascii=False))


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
    p.add_argument("--project", type=unquote)
    p.add_argument("--folder-path", dest="folder_path", type=unquote)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("list")
    p.add_argument("--status", type=unquote)
    p.add_argument("--owner", type=unquote)
    p.add_argument("--search", type=unquote)
    p.add_argument("--project", type=unquote)
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
    p.add_argument("--project", type=unquote)
    p.add_argument("--folder-path", dest="folder_path", type=unquote)
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("delete")
    p.add_argument("id", type=unquote)
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("summary")
    p.set_defaults(func=cmd_summary)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
