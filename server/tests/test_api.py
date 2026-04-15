from pathlib import Path

from fastapi.testclient import TestClient

from server.app import config
from server.app.database import init_db
from server.app.main import app


def test_transaction_api_flow(tmp_path: Path) -> None:
    config.settings.database_path = tmp_path / "test.sqlite"
    init_db()

    client = TestClient(app)

    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    empty_list_response = client.get("/transactions")
    assert empty_list_response.status_code == 200
    assert empty_list_response.json() == []

    empty_summary_response = client.get("/transactions/summary")
    assert empty_summary_response.status_code == 200
    assert empty_summary_response.json() == {"total": 0, "by_status": {}}

    missing_title_response = client.post(
        "/transactions",
        json={"owner": "Owen"},
    )
    assert missing_title_response.status_code == 422

    create_response = client.post(
        "/transactions",
        json={
            "title": "Partnership follow-up",
            "owner": "Owen",
            "next_action": "Confirm next meeting time",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["title"] == "Partnership follow-up"
    assert created["status"] == "new"
    assert created["owner"] == "Owen"

    list_response = client.get("/transactions")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = client.get(f"/transactions/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]

    missing_get_response = client.get("/transactions/missing")
    assert missing_get_response.status_code == 404
    assert missing_get_response.json()["detail"]["code"] == "transaction_not_found"

    update_response = client.patch(
        f"/transactions/{created['id']}",
        json={
            "status": "waiting_feedback",
            "next_action": "Wait for partner feedback",
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "waiting_feedback"
    assert updated["next_action"] == "Wait for partner feedback"

    summary_response = client.get("/transactions/summary")
    assert summary_response.status_code == 200
    assert summary_response.json() == {
        "total": 1,
        "by_status": {"waiting_feedback": 1},
    }

    empty_update_response = client.patch(
        f"/transactions/{created['id']}",
        json={},
    )
    assert empty_update_response.status_code == 400
    assert empty_update_response.json()["detail"]["code"] == "no_fields_to_update"

    missing_response = client.patch(
        "/transactions/missing",
        json={"status": "done"},
    )
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"]["code"] == "transaction_not_found"
