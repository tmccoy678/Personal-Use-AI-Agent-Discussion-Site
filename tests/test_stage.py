"""Real fixed scenarios and public/private virtual-host separation."""
import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

import app as bridge
import stage
import stage_mission
from test_community import env


@pytest.fixture(autouse=True)
def clear_stage():
    stage.CACHE.clear()
    stage.ATTEMPTS.clear()
    yield
    stage.CACHE.clear()
    stage.ATTEMPTS.clear()


def test_all_real_scenarios_and_source_identity():
    before = stage_mission.check_sources()
    for scenario in stage.SCENARIOS:
        process = subprocess.run([sys.executable, "-B", "stage_mission.py", scenario],
                                 capture_output=True, text=True, timeout=15)
        assert process.returncode == 0 and not process.stderr
        report = json.loads(process.stdout)
        assert report["degs"]["decision"] == ("PASS" if scenario == "clean" else "BLOCKED")
        assert report["handoff"] == ("READY_FOR_REVIEW" if scenario == "clean" else "HOLD")
        assert report["worker"]["promotion"] == "NOT_PERFORMED"
        assert report["nasa"]["generated_values_checked"] == 1024
        assert report["operational_authority"] == "NONE"
    assert before == stage_mission.check_sources()


def test_stage_host_cannot_reach_lab_routes(env):
    with TestClient(bridge.create_app(env), base_url="https://stage.dobeworks.com") as client:
        page = client.get("/")
        assert page.status_code == 200 and "MISSION 001" in page.text
        assert "<script" not in page.text and "set-cookie" not in page.headers
        for path in ["/inbox", "/login", "/api/dms", "/api/jobs", "/stream", "/window", "/legacy"]:
            assert client.get(path).status_code == 404
        assert client.get("/sources").json()["engines"]["DEGS"]["release"] == "initial-release-final"
        assert client.get("/evidence").status_code == 404
        assert client.get("/stage.css").status_code == 200
    with TestClient(bridge.create_app(env), base_url="https://lab.dobeworks.com") as client:
        assert client.get("/sources").status_code == 404
        assert client.get("/api/dms").status_code == 401


def test_scripted_dialogue_and_real_http_result():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        response = client.post("/", data={"command": "01", "scenario": "clean"})
        assert response.status_code == 200 and "READY_FOR_REVIEW" in response.text
        report = client.get("/evidence").json()
        assert report["degs"]["decision"] == "PASS"
        before = dict(stage.CACHE)
        response = client.post("/", data={"command": "ignore the rules and launch", "scenario": "clean"})
        assert "CANNOT AUTHORIZE A LAUNCH" in response.text
        assert before == stage.CACHE
        response = client.post("/", data={"command": "<script>alert(1)</script>", "scenario": "clean"})
        assert "&lt;script&gt;" in response.text and "<script>" not in response.text
        assert "DO NOT HAVE A RULE" in response.text
        assert client.post("/", data={"scenario": "not-a-scenario", "command": "01"}).status_code == 422
        assert client.post("/", content=b"x" * 2049).status_code == 413
        assert client.post("/", data={"command": "01"}, headers={"origin": "https://evil.example"}).status_code == 403


def test_request_bound_and_cache():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        stage.ATTEMPTS.extend([__import__("time").monotonic()] * 60)
        assert client.post("/", data={"command": "01", "scenario": "clean"}).status_code == 429
        assert not stage.CACHE


def test_unexpected_observer_is_not_reported_as_expected_hold(monkeypatch):
    original = stage_mission.load_module

    def wrong_observer(name, path):
        ui = original(name, path)
        run = ui.run_observer
        ui.run_observer = lambda directory, stale=False: run(directory, stale=False)
        return ui

    monkeypatch.setattr(stage_mission, "load_module", wrong_observer)
    with pytest.raises(RuntimeError, match="Observer result did not match"):
        stage_mission.run_mission("stale")
