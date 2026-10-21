"""Real fixed scenarios, mission handoffs, and public/private host separation."""
import json
from html import escape
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
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/evidence").text)[1]
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
        assert "FROZEN SOURCES" in client.get("/sources").text
        assert client.get("/evidence").headers["content-type"].startswith("text/html")
        assert client.get("/stage.css").status_code == 200
    with TestClient(bridge.create_app(env), base_url="https://lab.dobeworks.com") as client:
        assert client.get("/sources").status_code == 404
        assert client.get("/api/dms").status_code == 401
    with TestClient(bridge.create_app(env), base_url="http://stage.dobeworks.com:10000") as client:
        health = client.get("/healthz")
        assert health.status_code == 200 and health.json() == {"ok": True}
        assert "set-cookie" not in health.headers


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
        assert client.get("/api/evidence").json()["completed_handoffs"] == ["01", "02", "03", "04"]
        command(client, "accept")
        assert client.get("/api/evidence").json()["completed_handoffs"] == ["01", "02", "03", "04", "05"]
        command(client, "director")
        assert not client.get("/api/evidence").json()["fictional_role_poll"]
        for role in ("vehicle", "weather", "range"):
            command(client, role)
        assert not client.get("/api/evidence").json()["fictional_role_poll"]
        assert "HOLD" in command(client, "go-weather").text
        command(client, "clear-weather")
        for role in ("vehicle", "weather", "range"):
            command(client, "go-" + role)
        command(client, "07")
        assert not client.get("/api/evidence").json()["simulated_flight_completed"]
        command(client, "go-director")
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


def test_package_view_matches_packet_and_search_does_not_advance(monkeypatch):
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        response = command(client, "01")
        assert "<h2>ESTABLISH PACKAGE BASELINE</h2>" in response.text
        assert response.text.count('class="package-file"') == 7
        assert "&lt;stdint.h&gt;" in response.text
        before = client.get("/api/evidence").json()
        assert before["fixed_engine_run"]["package_sha256"] == "100bf914d582bf2d7f7b9136af2e8bf22993f3ca3979f4ec4daf9e93b9ac4295"
        sources, nasa = stage_mission.check_sources()
        artifacts, _ = stage_mission.mission_package("clean", sources, nasa)
        for data in artifacts.values():
            assert escape(data.decode()) in response.text
        async def unexpected_run(_):
            raise AssertionError("Package search must not run an engine")
        with monkeypatch.context() as patch:
            patch.setattr(stage, "mission", unexpected_run)
            response = client.get("/package", params={"q": "crc32"})
            assert "MATCHING LINES" in response.text and "COMPLETE FILE" in response.text
            assert client.get("/api/evidence").json() == before
            csrf = re.search(r'name="csrf" value="([^"]+)"', response.text)[1]
            response = client.post("/", data={"command": "inspect", "scenario": "clean", "csrf": csrf, "q": "crc32"})
            assert "MATCHING LINES" in response.text
            assert client.get("/api/evidence").json() == before
            assert "NO MATCHES IN THIS PACKET" in client.get("/package", params={"q": "no-such-phrase-123"}).text
            response = client.get("/package", params={"q": '<script>alert("x")</script>'})
            assert "<script>" not in response.text and "&lt;script&gt;" in response.text
            assert client.get("/package", params={"q": "x" * 121}).status_code == 422
            assert client.get("/package?path=/etc/passwd").status_code == 422
            assert client.get("/package?q=crc&q=source").status_code == 422
        command(client, "01", "missing")
        assert "evidence/nasa-source.md · MISSING" in client.get("/package").text
        command(client, "01", "altered")
        response = client.get("/package", params={"q": "0xEDB88321"})
        assert "IDENTITY DIFFERS" in response.text and "MATCHING LINES" in response.text


def test_one_character_failure_counterfactual_and_corrected_flight(real_cores, monkeypatch, tmp_path):
    stage.CACHE["cores"] = real_cores
    source = (stage_mission.NASA / "TableGenerator.c").read_bytes()
    changed = stage_mission.transcription_copy(source)
    assert len(source) == len(changed) and sum(a != b for a, b in zip(source, changed)) == 1
    behavior = stage_mission.source_behavior(changed)
    assert behavior["compile_exit"] == 0 and behavior["stderr"] == ""
    assert behavior["actual_crc32"] == "CFBDC920" and behavior["result"] == "FAIL"
    assert behavior["candidate_packet_crc32"] != behavior["receiver_expected_crc32"]
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        for number in ("01", "02", "03"):
            response = command(client, number, "altered")
        assert "COUNTDOWN" in response.text and "CFBDC920" in response.text
        before = client.get("/api/evidence").json()
        assert before["completed_handoffs"] == ["01", "02"]
        assert "BLOCKED" in command(client, "keep", "altered").text
        assert "WHAT-IF" in command(client, "what-if", "altered").text
        error_flight = client.get("/api/evidence").json()
        assert error_flight["counterfactual_flight_with_errors"] is True
        assert error_flight["simulated_flight_completed"] is False
        assert error_flight["fixed_engine_run"] == before["fixed_engine_run"]
        assert error_flight["completed_handoffs"] == ["01", "02"]
        assert "COUNTDOWN HOLD" in command(client, "07", "altered").text
        command(client, "restore", "altered")
        corrected = client.get("/api/evidence").json()
        assert corrected["completed_handoffs"] == ["01"]
        assert corrected["prior_candidate_runs"] == [before["fixed_engine_run"]]
        assert corrected["fixed_engine_run"]["source_behavior"]["result"] == "PASS"
        assert not corrected["counterfactual_flight_with_errors"]
        for number in ("02", "03", "04", "05"):
            command(client, number)
        assert client.get("/api/evidence").json()["completed_handoffs"] == ["01", "02", "03", "04"]
        command(client, "accept")
        command(client, "clear-weather")
        for role in ("vehicle", "weather", "range", "director"):
            command(client, "go-" + role)
        assert "ALL EXERCISE CHECKS PASS" in command(client, "07").text
        client.get("/")
        fresh = client.get("/api/evidence").json()
        assert not fresh["prior_candidate_runs"] and not fresh["counterfactual_flight_with_errors"]
    record = json.loads(stage_mission.TRANSCRIPTION_RECORD.read_text())
    record["tables"][-1] ^= 1
    altered_record = tmp_path / "transcription.json"
    altered_record.write_text(json.dumps(record))
    monkeypatch.setattr(stage_mission, "TRANSCRIPTION_RECORD", altered_record)
    with pytest.raises(RuntimeError, match="Retained compiled tables differ"):
        stage_mission.source_behavior(changed)


def test_refresh_starts_a_clean_game_after_redirected_interactions():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        command(client, "01")
        csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/evidence").text)[1]
        response = client.post("/", data={"command": "hello", "scenario": "clean", "csrf": csrf}, follow_redirects=False)
        assert response.status_code == 303
        response = client.get(response.headers["location"])
        assert "BEGIN WITH 01" in response.text
        assert client.get("/api/evidence").json()["completed_handoffs"] == ["01"]
        client.get("/")
        evidence = client.get("/api/evidence").json()
        assert evidence["completed_handoffs"] == [] and evidence["handoff_record"] == []
        assert evidence["fictional_role_poll"] == {} and evidence["fixed_engine_run"] is None
        assert not evidence["simulated_flight_completed"]
