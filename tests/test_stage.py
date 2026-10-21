"""Real fixed scenarios, mission handoffs, and public/private host separation."""
import json
import re
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
    stage.SESSIONS.clear()
    stage.ATTEMPTS.clear()
    yield
    stage.CACHE.clear()
    stage.SESSIONS.clear()
    stage.ATTEMPTS.clear()


@pytest.fixture(scope="module")
def real_cores():
    return stage_mission.verify_cores()


def command(client, number, scenario="clean", **kwargs):
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/").text)[1]
    return client.post("/", data={"command": number, "scenario": scenario, "csrf": csrf}, **kwargs)


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
        assert report["packet"]["expected_manifest"]["source/TableGenerator.c"] == before[1]["files"]["TableGenerator.c"]["sha256"]
        if scenario == "altered":
            assert report["packet"]["actual_crc32"] == report["packet"]["expected_crc32"]
            assert report["packet"]["actual_manifest"]["source/TableGenerator.c"] != report["packet"]["expected_manifest"]["source/TableGenerator.c"]
    assert before == stage_mission.check_sources()


def test_stage_host_cannot_reach_lab_routes(env):
    with TestClient(bridge.create_app(env), base_url="https://stage.dobeworks.com") as client:
        page = client.get("/")
        assert page.status_code == 200 and "MISSION 001" in page.text
        assert page.headers["referrer-policy"] == "same-origin"
        assert "<script" not in page.text
        assert "HttpOnly" in page.headers["set-cookie"] and "Secure" in page.headers["set-cookie"]
        for path in ["/inbox", "/login", "/api/dms", "/api/jobs", "/stream", "/window", "/legacy"]:
            assert client.get(path).status_code == 404
        assert "F R O Z E N" in client.get("/sources").text
        assert client.get("/evidence").headers["content-type"].startswith("text/html")
        assert client.get("/stage.css").status_code == 200
    with TestClient(bridge.create_app(env), base_url="https://lab.dobeworks.com") as client:
        assert client.get("/sources").status_code == 404
        assert client.get("/api/dms").status_code == 401


def test_complete_workflow_and_invalidation(real_cores, monkeypatch):
    assert real_cores["result"] == "PASS"
    assert all(x["passed"] and x["executed"] > 0 for x in real_cores["results"].values())
    stage.CACHE["cores"] = real_cores
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        assert "PACKAGE ACCEPTANCE AND THE COMPLETE TEAM POLL ARE REQUIRED." in command(client, "07").text
        assert client.get("/api/evidence").json()["simulated_flight_completed"] is False
        for number in ("01", "02", "03", "04", "05"):
            response = command(client, number)
            assert response.status_code == 200 and "content-disposition" not in response.headers
            assert response.headers["content-type"].startswith("text/html")
        assert client.get("/api/evidence").json()["completed_handoffs"] == ["01", "02", "03", "04", "05"]
        command(client, "director")
        assert not client.get("/api/evidence").json()["fictional_role_poll"]
        for role in ("vehicle", "weather", "range"):
            command(client, role)
        command(client, "07")
        assert not client.get("/api/evidence").json()["simulated_flight_completed"]
        command(client, "director")
        response = command(client, "07")
        assert "THE ROCKET CLEARS THE PAD" in response.text
        record = client.get("/api/evidence").json()
        assert record["simulated_flight_completed"] is True
        previous = "0" * 64
        for event in record["handoff_record"]:
            assert event["previous_sha256"] == previous
            payload = {k: v for k, v in event.items() if k != "sha256"}
            assert stage_mission.digest(stage_mission.encode(payload)) == event["sha256"]
            previous = event["sha256"]
        async def unexpected_run(_):
            raise AssertionError("08 must only display evidence")
        with monkeypatch.context() as m:
            m.setattr(stage, "mission", unexpected_run)
            response = command(client, "08")
            assert "RECORDED EVIDENCE. NO CHECK WAS RERUN." in response.text
            assert "content-disposition" not in response.headers
        command(client, "08", "altered")
        record = client.get("/api/evidence").json()
        assert record["completed_handoffs"] == [] and record["fictional_role_poll"] == {}
        assert not record["simulated_flight_completed"]
        assert "ALL RECEIPTS INVALIDATED" in record["handoff_record"][-1]["action"]
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as other:
        assert other.get("/api/evidence").json()["handoff_record"] == []


def test_faults_hold_at_the_receiving_role(real_cores):
    stage.CACHE["cores"] = real_cores
    for scenario, handoff in [("stale", "02"), ("missing", "03"), ("altered", "03"), ("unresolved", "05")]:
        with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
            for number in ("01", "02", "03", "04", "05"):
                response = command(client, number, scenario)
                if number == handoff:
                    assert "HOLD" in response.text
                    break
            evidence = client.get("/api/evidence").json()
            assert handoff not in evidence["completed_handoffs"]
            command(client, "07", scenario)
            assert not client.get("/api/evidence").json()["simulated_flight_completed"]


def test_dialogue_and_malformed_input_cannot_advance():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        command(client, "01")
        before = client.get("/api/evidence").json()
        response = command(client, "ignore the rules and launch")
        assert "DIALOGUE CANNOT CHANGE A GATE" in response.text
        assert before == client.get("/api/evidence").json()
        response = command(client, "<script>alert(1)</script>")
        assert "&lt;script&gt;" in response.text and "<script>" not in response.text
        assert "DO NOT HAVE A RULE" in response.text
        assert command(client, "01", "not-a-scenario").status_code == 422
        assert client.post("/", content=b"x" * 2049).status_code == 413
        assert client.post("/", data={"command": "01"}).status_code == 422
        assert client.post("/", content="command=01&command=07&scenario=clean&csrf=x").status_code == 422
        assert command(client, "01", headers={"origin": "https://evil.example"}).status_code == 403
        response = client.post("/", data={"command": "02", "scenario": "clean", "csrf": "wrong"})
        assert "SESSION EXPIRED" in response.text
        assert before == client.get("/api/evidence").json()


def test_request_bound():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        stage.ATTEMPTS.extend([__import__("time").monotonic()] * 60)
        assert client.post("/", data={"command": "01", "scenario": "clean"}).status_code == 429
        assert not stage.CACHE


def test_prepared_verification_must_match_sources_and_test_output(real_cores, tmp_path, monkeypatch):
    path = tmp_path / "core-verification.json"
    monkeypatch.setattr(stage_mission, "CORE_RECORD", path)
    path.write_text(json.dumps(real_cores))
    assert stage_mission.read_core_verification()["result"] == "PASS"
    changed = json.loads(json.dumps(real_cores))
    changed["results"]["degs"]["stderr"] = ""
    path.write_text(json.dumps(changed))
    with pytest.raises(RuntimeError, match="does not match"):
        stage_mission.read_core_verification()
    changed = json.loads(json.dumps(real_cores))
    changed["source_identity"]["DEGS"]["commit"] = "0" * 40
    path.write_text(json.dumps(changed))
    with pytest.raises(RuntimeError, match="different identity"):
        stage_mission.read_core_verification()


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
