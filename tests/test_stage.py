"""Real fixed scenarios, mission handoffs, and public/private host separation."""
import hashlib
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
    page = client.get("/evidence")
    session_key = client.cookies.get(stage.COOKIE)
    stage.SESSIONS[session_key]["lesson_mode"] = False
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
    return client.post("/", data={"command": number, "scenario": scenario, "csrf": csrf}, **kwargs)


def lesson_command(client, page, action):
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
    scenario = re.search(r'name="scenario" value="([^"]+)"', page.text)[1]
    return client.post("/", data={"command": action, "scenario": scenario, "csrf": csrf})


def test_stage_voice_bank_contains_only_primary_source_verified_outputs():
    speakers = {"ELIZA", "COLOSSUS", "COLOSSUS + GUARDIAN"}
    assert len(stage.VOICES) == 6
    assert {entry["speaker"] for entry in stage.VOICES} == speakers
    assert {
        speaker: sum(entry["speaker"] == speaker for entry in stage.VOICES)
        for speaker in speakers
    } == {"ELIZA": 2, "COLOSSUS": 2, "COLOSSUS + GUARDIAN": 2}
    for entry in stage.VOICES:
        assert entry["verification"] == "primary-source-verified"
        assert entry["source"] and entry["locator"]
        assert re.fullmatch(r"[0-9a-f]{64}", entry["source_sha256"])
        assert entry.get("origin") != "Original workbench line"


def test_stage_voice_bank_rejects_incomplete_provenance(tmp_path):
    entries = json.loads(json.dumps(stage.VOICES))
    del entries[0]["locator"]
    bank = tmp_path / "voices.json"
    bank.write_text(json.dumps(entries))
    with pytest.raises(RuntimeError, match="verified primary-source provenance"):
        stage.load_workbench_voices(bank)


def test_mission_position_is_persistent_and_programmatic():
    state = stage.new_state()
    completed, current, held, count = stage.workflow_progress(state)
    assert completed == set() and current == "01" and held is False and count == 0
    menu = stage.program_menu(state)
    assert 'value="01" aria-current="step"' in menu
    assert '<span class="program-status">NEXT</span>' in menu
    progress = stage.mission_progress(state)
    assert 'role="progressbar"' in progress and 'aria-valuenow="0"' in progress


def test_out_of_order_program_keeps_the_required_step_visible():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        response = command(client, "04", "rbar")
        assert "HANDOFF HOLD" in response.text
        assert 'value="01" aria-current="step"' in response.text
        assert 'aria-valuenow="0"' in response.text


def test_mission_position_advances_and_holds_at_the_failed_boundary():
    state = stage.new_state()
    state["completed"] = ["01", "02"]
    state["report"] = {"package_sha256": "packet", "notation_check": {"result": "FAIL"}}
    state["tested_package"] = "packet"
    completed, current, held, count = stage.workflow_progress(state)
    assert completed == {"01", "02"} and current == "03" and held is True and count == 2
    menu = stage.program_menu(state)
    assert 'class="program is-held" name="command" value="03" aria-current="step"' in menu
    assert '<span class="program-status">HOLD</span>' in menu


def test_mission_position_moves_from_poll_to_flight_and_evidence():
    state = stage.new_state()
    state["completed"] = ["01", "02", "03", "04", "05"]
    assert stage.workflow_progress(state)[1:] == ("06", False, 5)
    state["poll"] = {role: "GO" for role in stage.POLL}
    assert stage.workflow_progress(state)[1:] == ("07", False, 6)
    state["launched"] = True
    assert stage.workflow_progress(state)[1:] == ("08", False, 7)
    assert 'aria-valuenow="7"' in stage.mission_progress(state)


def test_all_real_scenarios_and_source_identity():
    before = stage_mission.check_sources()
    for scenario in stage.SCENARIOS:
        process = subprocess.run([sys.executable, "-B", "stage_mission.py", scenario],
                                 capture_output=True, text=True, timeout=15)
        assert process.returncode == 0 and not process.stderr
        report = json.loads(process.stdout)
        ready = scenario in {"clean", "rbar-fixed"}
        assert report["degs"]["decision"] == ("PASS" if ready else "BLOCKED")
        assert report["handoff"] == ("READY_FOR_REVIEW" if ready else "HOLD")
        assert report["worker"]["promotion"] == "NOT_PERFORMED"
        assert report["nasa"]["generated_values_checked"] == 1024
        assert report["operational_authority"] == "NONE"
        if not scenario.startswith("rbar"):
            assert report["packet"]["expected_manifest"]["source/TableGenerator.c"] == before[1]["files"]["TableGenerator.c"]["sha256"]
        if scenario == "altered":
            assert report["packet"]["actual_crc32"] == report["packet"]["expected_crc32"]
            assert report["packet"]["actual_manifest"]["source/TableGenerator.c"] != report["packet"]["expected_manifest"]["source/TableGenerator.c"]
    assert before == stage_mission.check_sources()


def test_stage_host_cannot_reach_lab_routes(env):
    with TestClient(bridge.create_app(env), base_url="https://stage.dobeworks.com") as client:
        page = client.get("/")
        assert page.status_code == 200 and "ZARINER · SAVE THE SIGNAL" in page.text
        assert 'src="/stage-game.js"' in page.text
        assert page.headers["referrer-policy"] == "same-origin"
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert "HttpOnly" in page.headers["set-cookie"] and "Secure" in page.headers["set-cookie"]
        for path in ["/inbox", "/login", "/api/dms", "/api/jobs", "/stream", "/window", "/legacy"]:
            assert client.get(path).status_code == 404
        assert "FROZEN SOURCES" in client.get("/sources").text
        assert client.get("/evidence").headers["content-type"].startswith("text/html")
        assert client.get("/stage.css").status_code == 200
        assert client.get("/stage-game.js").headers["content-type"].startswith("application/javascript")
    with TestClient(bridge.create_app(env), base_url="https://lab.dobeworks.com") as client:
        assert client.get("/sources").status_code == 404
        assert client.get("/api/dms").status_code == 401
    with TestClient(bridge.create_app(env), base_url="http://stage.dobeworks.com:10000") as client:
        health = client.get("/healthz")
        assert health.status_code == 200 and health.json() == {"ok": True}
        assert "set-cookie" not in health.headers


def test_stage_preserves_content_addressed_logo_assets_without_forcing_them_into_the_game():
    logo_url = "/dobeworks-logo-a56f5aab2111.svg"
    favicon_16_url = "/dobeworks-favicon-015c1a2f70b6-16.png"
    favicon_32_url = "/dobeworks-favicon-45fd62c64976-32.png"
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        logo = client.get(logo_url)
        assert logo.status_code == 200
        assert logo.headers["content-type"] == "image/svg+xml"
        assert hashlib.sha256(logo.content).hexdigest() == "a56f5aab211143a64a5360f4b2fd99232ec41c6807a41c57746e23f762f8ed15"
        assert b"<script" not in logo.content.lower()
        assert not re.search(rb'(?:href|src)=["\'](?:https?:|//)', logo.content, re.I)
        assert "immutable" in logo.headers["cache-control"]
        assert "set-cookie" not in logo.headers

        favicon_16 = client.get(favicon_16_url)
        favicon_32 = client.get(favicon_32_url)
        assert favicon_16.headers["content-type"] == "image/png"
        assert favicon_32.headers["content-type"] == "image/png"
        assert hashlib.sha256(favicon_16.content).hexdigest() == "015c1a2f70b68d6ae2a2d23b5e92120cba5d3c3654e27756b6a900af455d99a9"
        assert hashlib.sha256(favicon_32.content).hexdigest() == "45fd62c64976486cd7a741b6a4d936a1a791d2290ad673d4e5af70e2d711fa6d"
        assert "immutable" in favicon_16.headers["cache-control"]
        assert "immutable" in favicon_32.headers["cache-control"]
        page = client.get("/")
        assert page.text.count(logo_url) == 0
        assert page.text.count(favicon_16_url) == 1
        assert page.text.count(favicon_32_url) == 1
        assert "img-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-store"


def test_public_front_door_starts_with_a_plain_language_play_loop():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "ZARINER · SAVE THE SIGNAL" in page.text
        assert "FIND R WITHOUT BAR" in page.text
        assert page.text.count('data-signal-wrong') == 12
        assert 'class="signal-token signal-target"' in page.text
        assert 'value="lesson-start"' in page.text
        assert "NO TIMER" in page.text
        assert "HOW IT WORKED" not in page.text
        assert 'src="/stage-game.js"' in page.text


def test_public_mission_shows_a_failed_check_without_advancing(monkeypatch):
    async def failed_mission(_scenario):
        raise RuntimeError("fixture busy")

    monkeypatch.setattr(stage, "mission", failed_mission)
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        opening = client.get("/")
        failed = lesson_command(client, opening, "lesson-start")
        assert "MISSION PAUSED" in failed.text
        assert "THE CHECK COULD NOT COMPLETE. PLEASE TRY THE PROGRAM AGAIN." in failed.text
        assert "NO HANDOFF WAS ACCEPTED." in failed.text
        evidence = client.get("/api/evidence").json()
        assert evidence["completed_handoffs"] == []
        assert evidence["simulated_flight_completed"] is False


def test_public_mission_cannot_unlock_the_engineering_station_early():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        opening = client.get("/")
        direct_program = lesson_command(client, opening, "01")
        assert "FIND R WITHOUT BAR" in direct_program.text
        assert "SOFTWARE / TELEMETRY DESK" not in direct_program.text
        assert client.get("/api/evidence").json()["fixed_engine_run"] is None

        direct_unlock = lesson_command(client, direct_program, "lesson-mission")
        assert "FIND R WITHOUT BAR" in direct_unlock.text
        assert "SOFTWARE / TELEMETRY DESK" not in direct_unlock.text

        csrf = re.search(r'name="csrf" value="([^"]+)"', direct_unlock.text)[1]
        forged = client.post("/", data={"command": "01", "scenario": "clean", "csrf": csrf})
        assert "FIND R WITHOUT BAR" in forged.text
        assert "SOFTWARE / TELEMETRY DESK" not in forged.text
        assert client.get("/api/evidence").json()["fixed_engine_run"] is None


def test_public_mission_bypass_reveals_history_without_overriding_the_gate():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        opening = client.get("/")
        carry = lesson_command(client, opening, "lesson-start")
        assert "EVERYONE SAYS DONE" in carry.text
        assert "KEEP WARNING ATTACHED" in carry.text
        assert "CARRY WARNING" in carry.text
        assert "TRUST DONE" in carry.text
        too_early = lesson_command(client, carry, "lesson-fix")
        assert "KEEP WARNING ATTACHED" in too_early.text
        before = client.get("/api/evidence").json()
        assert before["fixed_engine_run"]["degs"]["decision"] == "BLOCKED"
        assert before["completed_handoffs"] == ["01"]

        bypass = lesson_command(client, too_early, "lesson-bypass")
        assert "MISSION LOST" in bypass.text
        assert "WARNING DROPPED" in bypass.text
        assert "FAILURE LEFT THE RECORD" in bypass.text
        assert "HANDOFF · WARNING ABSENT" in bypass.text
        assert "GATE · FALSE PASS" in bypass.text
        assert "Range Safety Officer" in bypass.text
        assert "T+294.5 seconds" in bypass.text
        assert "guidance-antenna fault" in bypass.text
        assert "omitted overbar" in bypass.text
        after = client.get("/api/evidence").json()
        assert after["fixed_engine_run"] == before["fixed_engine_run"]
        assert after["completed_handoffs"] == ["01"]
        assert after["counterfactual_flight_with_errors"] is True
        assert after["simulated_flight_completed"] is False
        recovered = lesson_command(client, bypass, "lesson-recover")
        assert "KEEP WARNING ATTACHED" in recovered.text
        restored = client.get("/api/evidence").json()
        assert restored["fixed_engine_run"] == before["fixed_engine_run"]
        assert restored["counterfactual_flight_with_errors"] is False
        held = lesson_command(client, recovered, "lesson-carry")
        assert "GATE BLOCKED" in held.text
        assert "WARNING FOUND" in held.text
        assert "WORK STAGED" in held.text
        assert "FAILED PACKET · RETAINED" in held.text
        assert "APPLY BAR" in held.text
        assert "WHAT IF: APPROVE FAILED" in held.text
        assert client.get("/api/evidence").json()["completed_handoffs"] == ["01", "02"]
        before_override = client.get("/api/evidence").json()
        override = lesson_command(client, held, "lesson-bypass")
        assert "HUMAN OVERRIDE" in override.text
        assert "FAILED PACKAGE APPROVED" in override.text
        assert "DEGS · BLOCKED" in override.text
        assert "HUMAN · OVERRIDE" in override.text
        after_override = client.get("/api/evidence").json()
        assert after_override["fixed_engine_run"] == before_override["fixed_engine_run"]
        assert after_override["completed_handoffs"] == before_override["completed_handoffs"]
        assert after_override["counterfactual_flight_with_errors"] is True


def test_public_mission_requires_fix_then_acceptance_before_successful_flight():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        opening = client.get("/")
        carry = lesson_command(client, opening, "lesson-start")
        held = lesson_command(client, carry, "lesson-carry")
        fixed = lesson_command(client, held, "lesson-fix")
        assert "FAULT REPAIRED" in fixed.text
        assert "REVIEW THE FIX" in fixed.text
        assert "FAILED · RETAINED" in fixed.text
        assert "CORRECTED · PASS" in fixed.text
        evidence = client.get("/api/evidence").json()
        assert evidence["fixed_engine_run"]["degs"]["decision"] == "PASS"
        assert evidence["prior_candidate_runs"][0]["degs"]["decision"] == "BLOCKED"
        assert evidence["completed_handoffs"] == ["01", "02", "03", "04"]

        too_early = lesson_command(client, fixed, "lesson-flight")
        assert "REVIEW THE FIX" in too_early.text
        assert client.get("/api/evidence").json()["simulated_flight_completed"] is False

        accepted = lesson_command(client, too_early, "accept")
        assert "HUMAN ACCEPTED" in accepted.text
        assert "YOU HOLD THE KEY" in accepted.text
        flight = lesson_command(client, accepted, "lesson-flight")
        assert "ZARINER 2 · VENUS RUN" in flight.text
        assert "HOLD TO CLIMB" in flight.text
        assert 'style="--gap:' not in flight.text
        stage_css = client.get("/stage.css").text
        for gate in ("1", "2", "3"):
            assert f'.telemetry-gate[data-gate="{gate}"]' in stage_css
        assert client.get("/api/evidence").json()["simulated_flight_completed"] is False
        launched = lesson_command(client, flight, "lesson-win")
        assert "VENUS REACHED" in launched.text
        assert "STOP FIXED. SIGNAL SAVED." in launched.text
        assert "HOW IT WORKED" in launched.text
        assert "OPEN TERMINAL" in launched.text
        assert "&gt; FIND R-BAR" in launched.text
        assert "SOFTWARE / TELEMETRY DESK" not in launched.text
        final = client.get("/api/evidence").json()
        assert final["completed_handoffs"] == ["01", "02", "03", "04", "05"]
        assert final["simulated_flight_completed"] is True


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
        command(client, "lesson-launch")
        assert client.get("/api/evidence").json()["simulated_flight_completed"] is False
        command(client, "director")
        assert not client.get("/api/evidence").json()["fictional_role_poll"]
        weather = command(client, "weather")
        assert "SURFACE WIND          22 KT" in weather.text
        assert "HOLD · WIND EXCEEDS LIMIT" in weather.text
        assert not client.get("/api/evidence").json()["fictional_role_poll"]
        assert "HOLD" in command(client, "go-weather").text
        updated = command(client, "clear-weather")
        assert "SURFACE WIND          9 KT" in updated.text
        assert "RECORD WEATHER GO FOR T+05" in updated.text
        command(client, "go-weather")
        command(client, "07")
        assert not client.get("/api/evidence").json()["simulated_flight_completed"]
        director = command(client, "director")
        assert "READY FOR DIRECTOR DECISION" in director.text
        assert "AUTHORIZE SIMULATED COUNTDOWN" in director.text
        authorized = command(client, "go-director")
        assert "SIMULATED COUNTDOWN AUTHORIZED" in authorized.text
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
        assert before["fixed_engine_run"]["package_sha256"] == "722f7daac9b895aa22d2ead39332ce0bcf8c40db769fe6b6bd05664a8685e8fc"
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
        command(client, "go-weather")
        command(client, "go-director")
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


def test_rbar_rocket_mission_stops_before_launch_then_rechecks_correction(real_cores):
    stage.CACHE["cores"] = real_cores
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        opening = client.get("/")
        assert "ZARINER · SAVE THE SIGNAL" in opening.text
        assert "FIND R WITHOUT BAR" in opening.text
        assert "HOW IT WORKED" not in opening.text
        for number in ("01", "02", "03"):
            response = command(client, number, "rbar")
        original = client.get("/api/evidence").json()
        task = original["fixed_engine_run"]["degs_task"]
        assert task["warnings"][0]["resolved"] is False
        assert original["fixed_engine_run"]["worker"]["state"] == "COMPLETED_UNACCEPTED"
        assert original["fixed_engine_run"]["degs"]["decision"] == "BLOCKED"
        assert "EXACT NOTATION CHECK  FAIL" in response.text
        assert "PACKAGE HANDOFF · HOLD BEFORE LAUNCH" in response.text
        assert "THE MISSING MARK" in response.text
        assert "DEGS" in response.text and "COUNTDOWN" in response.text
        assert "05" not in original["completed_handoffs"]
        trial = original["fixed_engine_run"]["translation_comparison"]
        assert trial["completion_only_decision"]["decision"] == "PASS"
        assert trial["same_candidate_sha256"] == original["fixed_engine_run"]["package_sha256"]
        assert "WHAT-IF · LAUNCH WITH BLOCKED NOTATION" in command(client, "what-if", "rbar").text
        bypass = client.get("/api/evidence").json()
        assert bypass["counterfactual_flight_with_errors"] is True
        assert bypass["simulated_flight_completed"] is False
        command(client, "hold", "rbar")
        command(client, "accept", "rbar")
        assert "05" not in client.get("/api/evidence").json()["completed_handoffs"]
        response = command(client, "restore", "rbar")
        corrected = client.get("/api/evidence").json()
        warning = corrected["fixed_engine_run"]["degs_task"]["warnings"][0]
        assert warning["resolved"] is True and warning["status"] == "RESOLVED" and warning["evidence_path"]
        assert corrected["fixed_engine_run"]["degs"]["decision"] == "PASS"
        assert corrected["prior_candidate_runs"] == [original["fixed_engine_run"]]
        assert "THE REQUIRED OVERBAR IS RESTORED" in response.text
        assert corrected["completed_handoffs"] == ["01"]
        for number in ("02", "03", "04", "05"):
            response = command(client, number, "rbar-fixed")
        assert "READY FOR YOUR DECISION" in response.text
        response = command(client, "accept", "rbar-fixed")
        accepted = client.get("/api/evidence").json()
        assert "05" in accepted["completed_handoffs"]
        assert "CONTINUE TO THE OTHER MISSION TEAMS" in response.text
        assert accepted["fixed_engine_run"]["worker"]["promotion"] == "NOT_PERFORMED"
        assert "R-BAR-NOTE" in client.get("/package").text
        command(client, "clear-weather", "rbar-fixed")
        command(client, "go-weather", "rbar-fixed")
        command(client, "go-director", "rbar-fixed")
        flight = command(client, "07", "rbar-fixed")
        assert "EXACT NOTATION CHECK PASSED" in flight.text
        assert "receiving team obtains the required notation" in flight.text
        assert client.get("/api/evidence").json()["simulated_flight_completed"] is True
        client.get("/")
        assert not client.get("/api/evidence").json()["completed_handoffs"]


def test_ready_poll_has_a_next_step_and_recorded_teams_are_clear():
    import asyncio
    state = stage.new_state()
    state["completed"] = ["01", "02", "03", "04", "05"]
    state["poll"] = {role: "GO" for role in stage.POLL}
    state["weather_clear"] = True
    result = asyncio.run(stage.program(state, "06"))
    assert result["actions"] == [("07", "RUN THE SUCCESSFUL SIMULATED FLIGHT")]
    inspected = asyncio.run(stage.program(state, "weather"))
    assert "WEATHER DECISION · GO · T+05 WINDOW" in inspected["lines"]
    assert all(command != "go-weather" for command, _ in inspected["actions"])
    assert stage.POLL == {"weather": "WEATHER OFFICER", "director": "LAUNCH DIRECTOR"}
