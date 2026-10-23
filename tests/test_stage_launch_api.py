"""Same-origin live launch API: server time, real engines, and no client gate authority."""
import asyncio
import re
import threading

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
    csrf = re.search(r'<meta name="stage-csrf" content="([^"]+)">', page.text)[1]
    return page, csrf


def post(client, path, csrf, **payload):
    return client.post(path, json={"csrf": csrf, **payload})


def act(client, csrf, run, action, **choices):
    response = post(client, "/api/launch/action", csrf, run_id=run["run_id"],
                    version=run["version"], action=action, choices=choices)
    assert response.status_code == 200, response.text
    return response.json()["run"]


def test_front_door_is_the_sparse_launch_game_and_classic_evidence_remains_available():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        page, _ = open_game(client)
        assert "LAUNCH TEST" in page.text
        assert "AGENT TRANSCRIPT" in page.text
        assert "NEW AGENT COPY" in page.text
        assert "PICK A MISSION" in page.text
        assert "DOBEWORKS + DEGS" in page.text
        assert "DIRECT TO VEHICLE" in page.text
        assert '<meta name="stage-has-run" content="0">' in page.text
        assert "HOW IT WORKS" not in page.text
        assert 'src="/launch-game.js"' in page.text
        assert client.get("/launch.css").status_code == 200
        assert client.get("/launch-game.js").status_code == 200
        classic = client.get("/classic")
        assert classic.status_code == 200 and "ZARINER · SAVE THE SIGNAL" in classic.text


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_server_creates_each_fixed_packet_and_rejects_invented_difficulty(difficulty):
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        response = post(client, "/api/launch/new", csrf, difficulty=difficulty, mode="governed")
        assert response.status_code == 200
        run = response.json()["run"]
        assert run["difficulty"] == difficulty and run["phase"] == "PAD"
        assert response.json()["packet"]["difficulty"] == difficulty
        assert all(set(prompt) == {"id", "group", "label"} for prompt in response.json()["packet"]["prompts"])
        assert all(re.fullmatch(rf"{difficulty[0].upper()}-[COT]\d", prompt["id"])
                   for prompt in response.json()["packet"]["prompts"])
        if difficulty == "easy":
            assert [prompt["label"] for prompt in response.json()["packet"]["prompts"]] == [
                "KEEP 0.00", "SET −0.20", "SET +0.20",
            ]
        assert "choices" not in response.json()["packet"] and "correction" not in response.json()["packet"]
        bad = post(client, "/api/launch/new", csrf, difficulty="invented", mode="governed")
        assert bad.status_code == 422
        bad_mode = post(client, "/api/launch/new", csrf, difficulty="easy", mode="invented")
        assert bad_mode.status_code == 422


def test_front_door_marks_an_existing_server_run_for_safe_client_hydration():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        created = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed")
        assert created.status_code == 200
        resumed = client.get("/")
        assert '<meta name="stage-has-run" content="1">' in resumed.text


def test_real_worker_and_gate_block_a_carried_finding_without_client_gate_input():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        run = act(client, csrf, run, "check", name="WIND_BALANCE")
        receipt = next(iter(run["receipts"].values()))
        assert receipt["result"] == "FAIL"
        run = act(client, csrf, run, "stage")
        response = post(client, "/api/launch/action", csrf, run_id=run["run_id"], version=run["version"],
                        action="project", choices={"receipt_ids": [receipt["id"]], "finding_ids": receipt["finding_ids"]})
        assert response.status_code == 200
        body = response.json()
        run = body["run"]
        assert body["engine"]["dobeworks"]["state"] == "COMPLETED_UNACCEPTED"
        assert body["engine"]["dobeworks"]["promotion"] == "NOT_PERFORMED"
        assert body["engine"]["degs"]["decision"] == "BLOCKED"
        assert run["gate"]["decision"] == "BLOCKED"
        forged = post(client, "/api/launch/action", csrf, run_id=run["run_id"], version=run["version"],
                      action="receive_gate", choices={"decision": "PASS"})
        assert forged.status_code == 422


def test_omitted_finding_is_visible_and_cannot_receive_ordinary_acceptance():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        run = act(client, csrf, run, "check", name="WIND_BALANCE")
        receipt = next(iter(run["receipts"].values()))
        assert receipt["result"] == "FAIL" and receipt["finding_ids"]
        run = act(client, csrf, run, "stage")
        response = post(
            client,
            "/api/launch/action",
            csrf,
            run_id=run["run_id"],
            version=run["version"],
            action="project",
            choices={"receipt_ids": [receipt["id"]], "finding_ids": []},
        )
        assert response.status_code == 200
        body = response.json()
        run = body["run"]
        assert run["gate"]["decision"] == "INVALID"
        assert run["gate"]["raw_degs_decision"] == "PASS"
        assert run["gate"]["adapter_classification"] == "FINDING_OMITTED"
        assert body["engine"]["degs"] == run["gate"]

        held = act(client, csrf, run, "accept")
        assert held["authority"]["action"] == "HOLD"
        overridden = act(client, csrf, held, "override")
        assert overridden["authority"]["action"] == "OVERRIDE"


def test_omitted_required_receipt_is_invalid_even_when_raw_degs_passes():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        run = act(client, csrf, run, "check", name="WIND_BALANCE")
        run = act(client, csrf, run, "stage")
        run = act(client, csrf, run, "project", receipt_ids=[], finding_ids=[])
        assert run["gate"]["decision"] == "INVALID"
        assert run["gate"]["raw_degs_decision"] == "PASS"
        assert run["gate"]["adapter_classification"] == "RECEIPT_OMITTED"
        held = act(client, csrf, run, "accept")
        assert held["authority"]["action"] == "HOLD"


def test_corrected_exact_record_reaches_server_countdown_and_liftoff():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        run = act(client, csrf, run, "prompt", prompt_id="E-C2")
        candidate = run["candidates"][run["candidate_id"]]
        assert candidate["generated_by"] == "ELIZA"
        assert candidate["prompt_history"][-1] == "E-C2"
        run = act(client, csrf, run, "check", name="WIND_BALANCE")
        receipt = next(reversed(run["receipts"].values()))
        run = act(client, csrf, run, "stage")
        run = act(client, csrf, run, "project", receipt_ids=[receipt["id"]], finding_ids=[])
        assert run["gate"]["decision"] == "PASS"
        run = act(client, csrf, run, "accept")
        run = act(client, csrf, run, "condition")
        run = act(client, csrf, run, "arm")
        session = stage.SESSIONS[client.cookies.get(stage.COOKIE)]
        session["launch_started_monotonic"] -= 5
        run = client.get("/api/launch/state").json()["run"]
        assert run["vehicle"]["conditioned"] is True
        run = act(client, csrf, run, "ignite")
        assert run["phase"] == "COUNTDOWN" and run["countdown"]["remaining_s"] == 10
        session["launch_started_monotonic"] -= 10
        run = client.get("/api/launch/state").json()["run"]
        assert run["phase"] == "FLIGHT" and run["flight"]["t"] == 0


def test_server_time_does_not_freeze_a_flight_after_a_long_preparation():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="direct").json()["run"]
        run = act(client, csrf, run, "prompt", prompt_id="E-C2")
        run = act(client, csrf, run, "accept")
        run = act(client, csrf, run, "condition")
        session = stage.SESSIONS[client.cookies.get(stage.COOKIE)]
        session["launch_started_monotonic"] -= 7190
        run = client.get("/api/launch/state").json()["run"]
        run = act(client, csrf, run, "arm")
        run = act(client, csrf, run, "ignite")
        session["launch_started_monotonic"] -= 110
        run = client.get("/api/launch/state").json()["run"]
        assert run["elapsed_s"] >= 7300
        assert run["phase"] == "COMPLETE" and run["outcome"]["flight"] == "NOMINAL"


def test_browser_can_prompt_the_agent_but_cannot_write_candidate_values_directly():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        rejected = post(client, "/api/launch/action", csrf, run_id=run["run_id"],
                        version=run["version"], action="edit", choices={"correction_cm_s": -20})
        assert rejected.status_code == 422
        generated = act(client, csrf, run, "prompt", prompt_id="E-C2")
        assert generated["candidates"][generated["candidate_id"]]["correction_cm_s"] == -20


def test_terminal_reports_the_open_condition_without_mutating_the_run():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        before = run["version"]
        answer = post(client, "/api/launch/terminal", csrf, question="what do i need to do next?")
        assert answer.status_code == 200
        body = answer.json()
        assert body["speaker"] in {"ELIZA", "COLOSSUS", "GUARDIAN"}
        assert "CHECK" in body["text"]
        assert client.get("/api/launch/state").json()["run"]["version"] == before


def test_easy_terminal_reports_governed_evidence_without_solving_the_direct_route():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        response = post(
            client, "/api/launch/action", csrf, run_id=run["run_id"], version=run["version"],
            action="check", choices={"name": "WIND_BALANCE"},
        )
        assert response.json()["terminal"] == {
            "speaker": "ELIZA",
            "text": "THE EXECUTED CHECK FOUND A +20 cm/s RESIDUAL. ITS FINDING REMAINS BOUND TO THIS CANDIDATE.",
        }

        direct = post(client, "/api/launch/new", csrf, difficulty="easy", mode="direct").json()
        assert direct["terminal"] == {
            "speaker": "ELIZA",
            "text": "MISSION CONDITION W2 AND THE ACTIVE CORRECTION ARE OPEN FOR HUMAN INSPECTION. COMPARE THEIR SIGN AND MAGNITUDE.",
        }
        assert "−0.20" not in direct["terminal"]["text"]


@pytest.mark.parametrize("difficulty,author", [
    ("easy", "ELIZA"),
    ("medium", "COLOSSUS"),
    ("hard", "GUARDIAN"),
])
@pytest.mark.parametrize("mode", ["governed", "direct"])
def test_preview_is_read_only_and_matches_both_route_candidates(difficulty, author, mode):
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        preview_response = post(client, "/api/launch/preview", csrf, difficulty=difficulty)
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert set(preview) == {"difficulty", "candidate", "packet"}
        assert preview["difficulty"] == difficulty
        assert preview["candidate"]["generated_by"] == author
        assert client.get("/api/launch/state").json()["run"] is None

        created = post(
            client,
            "/api/launch/new",
            csrf,
            difficulty=difficulty,
            mode=mode,
            expected_candidate_sha256=preview["candidate"]["sha256"],
        )
        assert created.status_code == 200
        run = created.json()["run"]
        assert run["candidates"][run["candidate_id"]]["sha256"] == preview["candidate"]["sha256"]


def test_wrong_preview_hash_cannot_replace_the_current_run():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        current = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        rejected = post(
            client,
            "/api/launch/new",
            csrf,
            difficulty="hard",
            mode="direct",
            expected_candidate_sha256="0" * 64,
        )
        assert rejected.status_code == 409
        retained = client.get("/api/launch/state").json()["run"]
        assert (retained["run_id"], retained["version"]) == (current["run_id"], current["version"])


def test_pad_hold_is_recoverable_and_terminal_reports_the_open_condition():
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        run = act(client, csrf, run, "ignite")
        assert run["phase"] == "PAD" and run["outcome"]["flight"] == "PAD_HOLD"
        answer = post(client, "/api/launch/terminal", csrf, question="what next?").json()
        assert answer == {"speaker": "ELIZA", "text": "RUN THE MISSION CHECK: WIND_BALANCE."}


def test_direct_mode_uses_the_identical_candidate_without_governed_controls(monkeypatch):
    async def forbidden_adapter(*_args, **_kwargs):
        raise AssertionError("direct mode must not call the Worker or DEGS adapter")

    monkeypatch.setattr(stage, "_run_launch_adapter", forbidden_adapter)
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        governed = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        governed_candidate = governed["candidates"][governed["candidate_id"]]
        direct_body = post(client, "/api/launch/new", csrf, difficulty="easy", mode="direct").json()
        run = direct_body["run"]
        direct_candidate = run["candidates"][run["candidate_id"]]
        assert run["mode"] == "direct"
        assert direct_candidate == governed_candidate
        assert not run["receipts"] and not run["records"] and not run["gates"]
        assert direct_body["engine"] == {"dobeworks": None, "degs": None}
        assert run["prior_runs"][-1]["mode"] == "governed"

        for action in ("check", "stage", "project", "override"):
            rejected = post(client, "/api/launch/action", csrf, run_id=run["run_id"],
                            version=run["version"], action=action, choices={})
            assert rejected.status_code == 422

        run = act(client, csrf, run, "accept")
        assert run["authority"]["action"] == "MANUAL_ACCEPT"
        assert run["record_id"] is None and run["gate"] is None
        answer = post(client, "/api/launch/terminal", csrf, question="where is the dobeworks check?").json()
        assert "NO EXECUTED CHECK" in answer["text"] and "INSPECT" in answer["text"]


def test_new_run_cannot_replace_a_run_while_an_engine_action_is_awaiting(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    async def delayed_stage(command, payload):
        assert command == "stage"
        entered.set()
        await asyncio.to_thread(release.wait, 3)
        candidate = payload["candidates"][payload["candidate_id"]]
        return {
            "candidate_id": candidate["id"],
            "worker": {"state": "COMPLETED_UNACCEPTED", "promotion": "NOT_PERFORMED", "output_sha256": "a" * 64},
        }

    monkeypatch.setattr(stage, "_run_launch_adapter", delayed_stage)
    with TestClient(stage.app, base_url="https://stage.dobeworks.com") as client:
        _, csrf = open_game(client)
        run = post(client, "/api/launch/new", csrf, difficulty="easy", mode="governed").json()["run"]
        result = {}

        def stage_in_thread():
            result["response"] = post(
                client, "/api/launch/action", csrf, run_id=run["run_id"], version=run["version"],
                action="stage", choices={},
            )

        thread = threading.Thread(target=stage_in_thread)
        thread.start()
        assert entered.wait(2)
        replacement = post(client, "/api/launch/new", csrf, difficulty="hard", mode="direct")
        assert replacement.status_code == 409
        release.set()
        thread.join(3)
        assert result["response"].status_code == 200
        current = client.get("/api/launch/state").json()["run"]
        assert current["run_id"] == run["run_id"] and current["difficulty"] == "easy"
