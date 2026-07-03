from pathlib import Path

from fastapi.testclient import TestClient

from server.app import config
from server.app.database import init_db
from server.app.main import app


class TestApiEndpoints:
    """REST API endpoint tests — CRUD + summary + delete via /api/*"""

    def setup_method(self) -> None:
        config.settings.database_path = Path("/tmp/test_aisecretary_api.sqlite")
        if config.settings.database_path.exists():
            config.settings.database_path.unlink()
        init_db()
        self.client = TestClient(app)

    def test_health(self) -> None:
        response = self.client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        response = self.client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_empty_list(self) -> None:
        response = self.client.get("/api/transactions")
        assert response.status_code == 200
        assert response.json() == []

    def test_empty_summary(self) -> None:
        response = self.client.get("/api/transactions/summary")
        assert response.status_code == 200
        assert response.json() == {"total": 0, "by_status": {}}

    def test_create_requires_title(self) -> None:
        response = self.client.post("/api/transactions", json={"owner": "Owen"})
        assert response.status_code == 422

    def test_create_and_read(self) -> None:
        response = self.client.post(
            "/api/transactions",
            json={
                "title": "Partnership follow-up",
                "owner": "Owen",
                "next_action": "Confirm next meeting time",
                "project": "myloop",
                "folder_path": "/home/owen/projects/myloop",
            },
        )
        assert response.status_code == 201
        created = response.json()
        assert created["title"] == "Partnership follow-up"
        assert created["status"] == "new"
        assert created["owner"] == "Owen"
        assert created["project"] == "myloop"
        assert created["folder_path"] == "/home/owen/projects/myloop"

        list_response = self.client.get("/api/transactions")
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        get_response = self.client.get(f"/api/transactions/{created['id']}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == created["id"]

    def test_get_missing(self) -> None:
        response = self.client.get("/api/transactions/missing")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "transaction_not_found"

    def test_update_fields(self) -> None:
        created = self.client.post(
            "/api/transactions", json={"title": "Update test", "owner": "Owen"}
        ).json()
        response = self.client.patch(
            f"/api/transactions/{created['id']}",
            json={"status": "waiting_feedback", "next_action": "Wait for feedback"},
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["status"] == "waiting_feedback"
        assert updated["next_action"] == "Wait for feedback"

    def test_update_empty_returns_error(self) -> None:
        created = self.client.post(
            "/api/transactions", json={"title": "Empty update test"}
        ).json()
        response = self.client.patch(f"/api/transactions/{created['id']}", json={})
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "no_fields_to_update"

    def test_update_missing(self) -> None:
        response = self.client.patch("/api/transactions/missing", json={"status": "done"})
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "transaction_not_found"

    def test_summary(self) -> None:
        self.client.post("/api/transactions", json={"title": "Task A", "status": "new"})
        self.client.post("/api/transactions", json={"title": "Task B", "status": "done"})
        response = self.client.get("/api/transactions/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["by_status"]["new"] == 1
        assert data["by_status"]["done"] == 1

    # ── Delete tests ──

    def test_delete_transaction(self) -> None:
        created = self.client.post("/api/transactions", json={"title": "Delete me"}).json()
        response = self.client.delete(f"/api/transactions/{created['id']}")
        assert response.status_code == 204
        get_response = self.client.get(f"/api/transactions/{created['id']}")
        assert get_response.status_code == 404

    def test_delete_missing(self) -> None:
        response = self.client.delete("/api/transactions/nonexistent-id")
        assert response.status_code == 404

    # ── Data integrity tests ──

    def test_data_integrity_crud(self) -> None:
        payload = {
            "title": "Integrity test",
            "owner": "Owen",
            "status": "new",
            "next_action": "Verify all fields",
            "notes": "Check data integrity",
        }
        created = self.client.post("/api/transactions", json=payload).json()
        assert created["title"] == payload["title"]
        assert created["owner"] == payload["owner"]
        assert created["status"] == payload["status"]
        assert created["next_action"] == payload["next_action"]
        assert created["notes"] == payload["notes"]
        assert "id" in created

        updated = self.client.patch(
            f"/api/transactions/{created['id']}", json={"status": "done"}
        ).json()
        assert updated["title"] == payload["title"]
        assert updated["status"] == "done"

        self.client.delete(f"/api/transactions/{created['id']}")
        assert self.client.get(f"/api/transactions/{created['id']}").status_code == 404

    def test_data_integrity_multiple(self) -> None:
        ids = []
        for i in range(3):
            created = self.client.post(
                "/api/transactions", json={"title": f"Task {i}", "owner": f"Owner {i}"}
            ).json()
            ids.append(created["id"])
        assert len(self.client.get("/api/transactions").json()) == 3
        self.client.patch(f"/api/transactions/{ids[1]}", json={"status": "waiting_feedback"})
        t0 = self.client.get(f"/api/transactions/{ids[0]}").json()
        t1 = self.client.get(f"/api/transactions/{ids[1]}").json()
        t2 = self.client.get(f"/api/transactions/{ids[2]}").json()
        assert t0["status"] == "new"
        assert t1["status"] == "waiting_feedback"
        assert t2["status"] == "new"

    # ── Filter tests ──

    def test_list_filter_by_status(self) -> None:
        self.client.post("/api/transactions", json={"title": "A", "status": "new"})
        self.client.post("/api/transactions", json={"title": "B", "status": "done"})
        self.client.post("/api/transactions", json={"title": "C", "status": "in_progress"})
        result = self.client.get("/api/transactions?status=new,in_progress").json()
        titles = {r["title"] for r in result}
        assert titles == {"A", "C"}

    def test_list_filter_by_owner(self) -> None:
        self.client.post("/api/transactions", json={"title": "Owen task", "owner": "Owen"})
        self.client.post("/api/transactions", json={"title": "Alice task", "owner": "Alice"})
        result = self.client.get("/api/transactions?owner=Owen").json()
        assert len(result) == 1

    def test_list_filter_by_search(self) -> None:
        self.client.post("/api/transactions", json={"title": "Buy groceries", "notes": "milk"})
        self.client.post("/api/transactions", json={"title": "Sell car"})
        result = self.client.get("/api/transactions?search=milk").json()
        assert len(result) == 1
        assert result[0]["title"] == "Buy groceries"

    def test_list_filter_by_project(self) -> None:
        self.client.post("/api/transactions", json={"title": "P1", "project": "myloop"})
        self.client.post("/api/transactions", json={"title": "P2"})
        result = self.client.get("/api/transactions?project=myloop").json()
        assert len(result) == 1
        assert result[0]["project"] == "myloop"

    # ── Batch update tests ──

    def test_batch_update(self) -> None:
        a = self.client.post("/api/transactions", json={"title": "A"}).json()
        b = self.client.post("/api/transactions", json={"title": "B"}).json()
        result = self.client.patch(
            "/api/transactions/batch",
            json=[
                {"id": a["id"], "status": "done"},
                {"id": b["id"], "status": "waiting_feedback"},
            ],
        ).json()
        assert len(result) == 2
        assert result[0]["status"] == "done"
        assert result[1]["status"] == "waiting_feedback"

    def test_batch_update_missing_id(self) -> None:
        result = self.client.patch(
            "/api/transactions/batch", json=[{"id": "nonexistent", "status": "done"}]
        ).json()
        assert result[0]["error"] == "transaction_not_found"
