import json
from pathlib import Path

from server.app import config
from server.app.database import init_db
from server.app.mcp_server import (
    tool_batch_update_transactions,
    tool_create_transaction,
    tool_delete_transaction,
    tool_get_transaction,
    tool_list_transactions,
    tool_summarize_transactions,
    tool_update_transaction,
)


class TestMcpTools:
    """MCP tool tests — each tool wraps a storage function."""

    def setup_method(self) -> None:
        config.settings.database_path = Path("/tmp/test_aisecretary_mcp.sqlite")
        if config.settings.database_path.exists():
            config.settings.database_path.unlink()
        init_db()

    def test_create_and_list(self) -> None:
        result = json.loads(
            tool_create_transaction(title="Test from MCP", owner="Owen", project="myloop")
        )
        assert result["title"] == "Test from MCP"
        assert result["status"] == "new"
        assert result["owner"] == "Owen"
        assert result["project"] == "myloop"
        assert "id" in result

        transactions = json.loads(tool_list_transactions())
        assert len(transactions) == 1
        assert transactions[0]["id"] == result["id"]

    def test_create_invalid_status(self) -> None:
        result = json.loads(
            tool_create_transaction(title="Bad status", status="invalid_status")
        )
        assert result["error"] == "invalid_status"

    def test_get_found_and_missing(self) -> None:
        created = json.loads(tool_create_transaction(title="Find me"))
        found = json.loads(tool_get_transaction(created["id"]))
        assert found["id"] == created["id"]

        missing = json.loads(tool_get_transaction("nonexistent-id"))
        assert missing["error"] == "transaction_not_found"

    def test_update_fields(self) -> None:
        created = json.loads(tool_create_transaction(title="Original"))
        updated = json.loads(
            tool_update_transaction(created["id"], title="Updated", status="in_progress")
        )
        assert updated["title"] == "Updated"
        assert updated["status"] == "in_progress"

    def test_update_empty_returns_error(self) -> None:
        created = json.loads(tool_create_transaction(title="No changes"))
        result = json.loads(tool_update_transaction(created["id"]))
        assert result["error"] == "no_fields_to_update"

    def test_update_missing(self) -> None:
        result = json.loads(tool_update_transaction("missing-id", title="Won't work"))
        assert result["error"] == "transaction_not_found"

    def test_delete_existing_and_missing(self) -> None:
        created = json.loads(tool_create_transaction(title="Delete me"))
        result = json.loads(tool_delete_transaction(created["id"]))
        assert result["deleted"] is True
        assert result["id"] == created["id"]

        check = json.loads(tool_get_transaction(created["id"]))
        assert check["error"] == "transaction_not_found"

        missing = json.loads(tool_delete_transaction(created["id"]))
        assert missing["error"] == "transaction_not_found"

    def test_summary(self) -> None:
        json.loads(tool_create_transaction(title="Task A", status="new"))
        json.loads(tool_create_transaction(title="Task B", status="new"))
        json.loads(tool_create_transaction(title="Task C", status="done"))
        summary = json.loads(tool_summarize_transactions())
        assert summary["total"] == 3
        assert summary["by_status"]["new"] == 2
        assert summary["by_status"]["done"] == 1

    def test_full_crud_flow(self) -> None:
        created = json.loads(
            tool_create_transaction(
                title="MCP flow test",
                owner="Owen",
                next_action="Verify behavior",
                notes="Integration test",
                project="test-proj",
            )
        )
        assert created["owner"] == "Owen"
        assert created["project"] == "test-proj"

        found = json.loads(tool_get_transaction(created["id"]))
        assert found["notes"] == "Integration test"

        updated = json.loads(
            tool_update_transaction(created["id"], status="done", notes="Updated note")
        )
        assert updated["status"] == "done"
        assert updated["notes"] == "Updated note"

        summary = json.loads(tool_summarize_transactions())
        assert summary["total"] >= 1
        assert summary["by_status"]["done"] >= 1

        deleted = json.loads(tool_delete_transaction(created["id"]))
        assert deleted["deleted"] is True

    # ── Filter tests ──

    def test_list_filter_by_status(self) -> None:
        json.loads(tool_create_transaction(title="A", status="new"))
        json.loads(tool_create_transaction(title="B", status="done"))
        json.loads(tool_create_transaction(title="C", status="in_progress"))
        result = json.loads(tool_list_transactions(status="new,in_progress"))
        titles = {r["title"] for r in result}
        assert titles == {"A", "C"}

    def test_list_filter_by_owner(self) -> None:
        json.loads(tool_create_transaction(title="Mine", owner="Owen"))
        json.loads(tool_create_transaction(title="Theirs", owner="Alice"))
        result = json.loads(tool_list_transactions(owner="Owen"))
        assert len(result) == 1
        assert result[0]["title"] == "Mine"

    def test_list_filter_by_search(self) -> None:
        json.loads(tool_create_transaction(title="Buy milk"))
        json.loads(tool_create_transaction(title="Sell car"))
        result = json.loads(tool_list_transactions(search="milk"))
        assert len(result) == 1
        assert result[0]["title"] == "Buy milk"

    def test_list_filter_by_project(self) -> None:
        json.loads(tool_create_transaction(title="P1", project="myloop"))
        json.loads(tool_create_transaction(title="P2"))
        result = json.loads(tool_list_transactions(project="myloop"))
        assert len(result) == 1
        assert result[0]["project"] == "myloop"

    # ── Batch update tests ──

    def test_batch_update(self) -> None:
        a = json.loads(tool_create_transaction(title="Batch A"))
        b = json.loads(tool_create_transaction(title="Batch B"))
        results = json.loads(
            tool_batch_update_transactions(
                updates=json.dumps([
                    {"id": a["id"], "status": "done"},
                    {"id": b["id"], "status": "waiting_feedback", "owner": "Owen"},
                ])
            )
        )
        assert len(results) == 2
        assert results[0]["status"] == "done"
        assert results[1]["status"] == "waiting_feedback"
        assert results[1]["owner"] == "Owen"

    def test_batch_update_missing(self) -> None:
        results = json.loads(
            tool_batch_update_transactions(
                updates=json.dumps([{"id": "no-such-id", "status": "done"}])
            )
        )
        assert results[0]["error"] == "transaction_not_found"

    def test_batch_update_invalid_json(self) -> None:
        result = json.loads(tool_batch_update_transactions(updates="not json"))
        assert result["error"] == "invalid_json"
