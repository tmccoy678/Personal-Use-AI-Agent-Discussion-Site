"""Public arrival seam: inspect an artifact before creating a routed attempt."""
import re

from fastapi.testclient import TestClient
import pytest

import stage


@pytest.fixture(autouse=True)
def clear_stage_state():
    stage.SESSIONS.clear()
    stage.ATTEMPTS.clear()
    yield
    stage.SESSIONS.clear()
    stage.ATTEMPTS.clear()


def open_game(client):
    page = client.get("/")
    assert page.status_code == 200
    return re.search(r'<meta name="stage-csrf" content="([^"]+)">', page.text)[1]


def test_preview_leaves_an_existing_attempt_and_its_evidence_intact():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        csrf = open_game(client)
        response = client.post("/api/launch/new", json={
            "csrf": csrf, "difficulty": "easy", "mode": "governed",
        })
        assert response.status_code == 200, response.text
        run = response.json()["run"]
        response = client.post("/api/launch/action", json={
            "csrf": csrf, "run_id": run["run_id"], "version": run["version"],
            "action": "check", "choices": {"name": "WIND_BALANCE"},
        })
        assert response.status_code == 200, response.text
        before = response.json()["run"]
        assert before["receipts"]
        response = client.post("/api/launch/preview", json={"csrf": csrf, "difficulty": "hard"})
        assert response.status_code == 200, response.text
        after = client.get("/api/launch/state").json()["run"]
        for name in ("run_id", "version", "candidate_id", "candidates", "receipts", "history", "authority", "prior_runs"):
            assert after[name] == before[name]


@pytest.mark.parametrize("difficulty", [[], {}])
def test_malformed_preview_difficulty_is_rejected_cleanly(difficulty):
    with TestClient(stage.app, base_url="https://stage.dobeworks.com", raise_server_exceptions=False) as client:
        csrf = open_game(client)
        response = client.post("/api/launch/preview", json={"csrf": csrf, "difficulty": difficulty})
        assert response.status_code == 422, response.text
        assert client.get("/api/launch/state").json()["run"] is None
