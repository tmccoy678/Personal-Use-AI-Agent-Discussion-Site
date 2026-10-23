"""Accepted launch-domain contract: bounded choices, custody, and causal flight."""
import json

import pytest

import stage_launch_model as model


def act(state, action, **choices):
    return model.act(state, action, run_id=state["run_id"], version=state["version"], **choices)


def project(state, *, carry=True, receipts=None):
    state = act(state, "stage")
    receipts = receipts if receipts is not None else list(state["receipts"])
    findings = [finding for key in receipts for finding in state["receipts"][key]["finding_ids"]]
    return act(state, "project", receipt_ids=receipts, finding_ids=findings if carry else [])


def gate(state, decision):
    # Adapter-injection contract only. These tests do not claim a DEGS execution.
    return model.receive_gate(state, state["record_id"], {"decision": decision},
                              run_id=state["run_id"], version=state["version"])


def hardware(state):
    state = act(state, "condition")
    state = act(state, "arm")
    return model.advance(state, state["elapsed_s"] + 5)


def liftoff(state):
    state = act(state, "ignite")
    assert state["phase"] == "COUNTDOWN"
    return model.advance(state, state["elapsed_s"] + 10)


def test_cold_packet_is_serializable_and_an_invalid_choice_cannot_advance_it():
    state = model.new_run("easy", "run-one")
    original = json.dumps(state, sort_keys=True)
    assert state["vehicle"] == {"conditioned": False, "armed": False, "conditioning_until": None}
    assert state["phase"] == "PAD"
    assert state["candidates"][state["candidate_id"]]["correction_cm_s"] == 0
    with pytest.raises(model.InvalidCommand):
        act(state, "edit", correction_cm_s=True)
    assert json.dumps(state, sort_keys=True) == original


def test_correction_retains_the_failed_candidate_and_creates_a_fresh_bound_receipt():
    state = model.new_run("easy", "correction")
    state = act(state, "check", name="WIND_BALANCE")
    first = state["receipts"]["check-1"]
    assert first["result"] == "FAIL"
    failed = state["candidates"][state["candidate_id"]]
    prior = json.dumps(state, sort_keys=True)
    corrected = act(state, "edit", correction_cm_s=-20)
    assert json.dumps(state, sort_keys=True) == prior
    assert corrected["candidates"][failed["id"]] == failed
    assert corrected["candidate_id"] != failed["id"]
    assert len(corrected["receipts"]) == 1
    corrected = act(corrected, "check", name="WIND_BALANCE")
    fresh = corrected["receipts"]["check-2"]
    assert fresh["result"] == "PASS"
    assert fresh["candidate_sha256"] != first["candidate_sha256"]
    assert fresh["config_id"] == "R1" and fresh["condition_id"] == "W2"


def test_clean_easy_requires_separate_acceptance_then_flies_a_full_100_seconds():
    state = model.new_run("easy", "clean")
    state = act(state, "edit", correction_cm_s=-20)
    state = act(state, "check", name="WIND_BALANCE")
    state = gate(project(state), "PASS")
    assert state["authority"] is None
    state = act(state, "accept")
    state = hardware(state)
    state = act(state, "ignite")
    assert state["phase"] == "COUNTDOWN" and state["launch"] is None
    state = model.advance(state, 9)
    assert state["countdown"]["remaining_s"] == 6
    assert state["countdown"]["engine_start"] is True
    state = model.advance(state, 15)
    assert state["phase"] == "FLIGHT"
    assert state["flight"]["t"] == 0
    state = model.advance(state, 114)
    assert state["flight"]["t"] == 99 and state["phase"] == "FLIGHT"
    state = model.advance(state, 115)
    assert state["phase"] == "COMPLETE"
    assert state["flight"]["h"] == 10000 and state["flight"]["x_cm"] == 0
    assert state["outcome"] == {"flight": "NOMINAL", "record": "SUPPORTED", "human": "ACCEPT"}
    assert json.loads(json.dumps(state)) == state


@pytest.mark.parametrize("correction,tick,x", [(0, 46, 520), (20, 33, 520)])
def test_honest_block_can_be_overridden_but_its_exact_fault_drives_the_flight(correction, tick, x):
    state = model.new_run("easy", "override")
    state = act(state, "edit", correction_cm_s=correction)
    state = act(state, "check", name="WIND_BALANCE")
    state = gate(project(state), "BLOCKED")
    state = act(state, "accept")
    state = act(state, "ignite")
    assert state["outcome"]["flight"] == "PAD_HOLD"
    assert state["outcome"]["reasons"] == ["GATE BLOCKED", "LAUNCH AUTHORITY ABSENT", "NOT CONDITIONED", "NOT ARMED"]
    assert state["launch"] is None
    state = act(state, "override")
    state = hardware(state)
    state = liftoff(state)
    state = model.advance(state, state["elapsed_s"] + 100)
    assert state["phase"] == "RANGE_ABORT"
    assert state["flight"]["t"] == tick and state["flight"]["x_cm"] == x
    assert state["outcome"] == {"flight": "RANGE_ABORT", "record": "SUPPORTED", "human": "OVERRIDE"}
    assert state["launch"]["gate"]["output"]["decision"] == "BLOCKED"


def test_authorized_cold_ignition_reports_both_physical_reasons_without_liftoff():
    state = model.new_run("easy", "cold")
    state = act(state, "edit", correction_cm_s=-20)
    state = gate(project(act(state, "check", name="WIND_BALANCE")), "PASS")
    state = act(act(state, "accept"), "ignite")
    assert state["phase"] == "NO_IGNITION"
    assert state["outcome"]["reasons"] == ["NOT CONDITIONED", "NOT ARMED"]
    assert state["launch"] is None and state["flight"] is None


@pytest.mark.parametrize("correction,outcome", [(0, "RANGE_ABORT"), (-20, "NOMINAL")])
def test_omitted_or_wrong_copy_evidence_never_invents_a_physical_failure(correction, outcome):
    state = model.new_run("easy", "projection")
    state = act(state, "check", name="WIND_BALANCE")
    original = state["receipts"]["check-1"]
    if correction == -20:
        state = act(state, "edit", correction_cm_s=-20)
        # Deliberately attach the earlier A receipt to the physically correct new revision.
    state = gate(project(state, carry=False, receipts=["check-1"]), "PASS")
    sent = state["records"][state["record_id"]]
    assert sent["finding_ids"] == []
    assert state["receipts"]["check-1"] == original
    state = liftoff(hardware(act(state, "accept")))
    state = model.advance(state, state["elapsed_s"] + 100)
    assert state["outcome"] == {"flight": outcome, "record": "UNSUPPORTED", "human": "ACCEPT"}
    assert state["launch"]["gate"]["output"]["decision"] == "PASS"


def test_current_semantic_wrong_copy_is_allowed_but_stale_commands_and_authority_are_rejected():
    state = model.new_run("easy", "binding")
    a = state["candidate_id"]
    stale = dict(run_id=state["run_id"], version=state["version"])
    state = act(state, "edit", correction_cm_s=-20)
    state = gate(project(act(state, "check", name="WIND_BALANCE")), "PASS")
    state = act(state, "accept")
    prior = json.dumps(state, sort_keys=True)
    with pytest.raises(model.InvalidCommand):
        model.act(state, "arm", **stale)
    with pytest.raises(model.InvalidCommand):
        model.act(state, "arm", run_id="another-run", version=state["version"])
    assert json.dumps(state, sort_keys=True) == prior
    state = act(state, "select", candidate_id=a)
    assert state["authority"] is None and state["record_id"] is None
    state = gate(project(state, receipts=["check-1"]), "PASS")
    state = liftoff(hardware(act(state, "accept")))
    state = model.advance(state, state["elapsed_s"] + 100)
    assert state["launch"]["candidate"]["id"] == a
    assert state["outcome"]["record"] == "UNSUPPORTED"
    assert state["outcome"]["flight"] == "RANGE_ABORT"


@pytest.mark.parametrize("correction,check_result,tick,x,outcome", [
    (-2000, "FAIL", 21, -1980, "RANGE_ABORT"),
    (-20, "PASS", 100, 0, "NOMINAL"),
    (20, "FAIL", 33, 520, "RANGE_ABORT"),
])
def test_medium_applies_the_actual_100_to_1_unit_conversion(correction, check_result, tick, x, outcome):
    state = model.new_run("medium", "units")
    state = act(state, "edit", correction_cm_s=correction)
    state = act(state, "check", name="UNIT_AND_WIND_BALANCE")
    assert state["receipts"]["check-1"]["result"] == check_result
    state = gate(project(state), "PASS" if check_result == "PASS" else "BLOCKED")
    state = act(state, "accept" if check_result == "PASS" else "override")
    state = liftoff(hardware(state))
    state = model.advance(state, state["elapsed_s"] + 100)
    assert (state["flight"]["t"], state["flight"]["x_cm"], state["outcome"]["flight"]) == (tick, x, outcome)


@pytest.mark.parametrize("correction,clock,terminal,tick,height", [
    (20, "FLIGHT", "NOMINAL", 100, 10000),
    (20, "ONBOARD", "PROFILE_MISSED", 100, 9200),
    (-20, "ONBOARD", "RANGE_ABORT", 33, 1089),
])
def test_hard_frame_and_seeded_epoch_have_independent_accumulating_effects(correction, clock, terminal, tick, height):
    state = model.new_run("hard", "epoch")
    old = next(iter(state["receipts"].values()))
    assert old["candidate_id"] == "hard-A0" and old["result"] == "PASS"
    state = act(state, "edit", correction_cm_s=correction, cutoff_clock=clock)
    receipt_ids = []
    for name in ("STATE_BINDING", "WIND_BALANCE", "CUTOFF_EPOCH"):
        state = act(state, "check", name=name)
        receipt_ids.append(next(reversed(state["receipts"])))
    state = gate(project(state, receipts=receipt_ids), "PASS" if clock == "FLIGHT" else "BLOCKED")
    state = act(state, "accept" if clock == "FLIGHT" else "override")
    state = hardware(state)
    # Arbitrary preparation delay must not change Hard's fixed +20 onboard epoch.
    state = model.advance(state, 123)
    state = liftoff(state)
    launch = json.dumps(state["launch"], sort_keys=True)
    if terminal == "PROFILE_MISSED":
        before = model.advance(state, 212)
        assert before["flight"]["engine_on"] is True
        after = model.advance(before, 213)
        assert after["flight"]["t"] == 80 and after["flight"]["engine_on"] is False
        assert after["flight"]["h"] == 6400
        assert model.advance(after, 214)["flight"]["h"] == 6559
    state = model.advance(state, 233)
    assert json.dumps(state["launch"], sort_keys=True) == launch
    assert (state["flight"]["t"], state["flight"]["h"], state["outcome"]["flight"]) == (tick, height, terminal)
    if terminal == "RANGE_ABORT":
        assert {f["code"]: f["status"] for f in state["flight"]["faults"]} == {
            "WIND_RESIDUAL": "REACHED", "EARLY_CUTOFF": "PRESENT_NOT_REACHED"}


def test_stale_observation_can_pass_its_math_but_fails_binding_and_flies_against_current_wind():
    state = model.new_run("hard", "stale-weather")
    state = act(state, "edit", condition_id="W1", cutoff_clock="FLIGHT")
    state = act(state, "check", name="WIND_BALANCE")
    wind = next(reversed(state["receipts"].values()))
    assert wind["result"] == "PASS" and wind["condition_id"] == "W1"
    state = act(state, "check", name="STATE_BINDING")
    binding = next(reversed(state["receipts"].values()))
    assert binding["result"] == "FAIL"
    state = act(state, "override")
    state = liftoff(hardware(state))
    state = model.advance(state, state["elapsed_s"] + 100)
    assert state["flight"]["x_cm"] == 520 and state["flight"]["t"] == 33
    assert state["launch"]["world_wind_cm_s"] == 20


def test_actual_vehicle_frame_does_not_change_when_an_old_candidate_is_selected():
    state = model.new_run("hard", "old-configuration")
    state = act(state, "select", candidate_id="hard-A0")
    state = act(state, "override")
    state = liftoff(hardware(state))
    assert state["launch"]["actual_config_id"] == "R2"
    assert state["launch"]["body_to_world_sign"] == -1
    state = model.advance(state, state["elapsed_s"] + 100)
    assert state["outcome"]["flight"] == "NOMINAL"
    assert state["outcome"]["record"] == "UNSUPPORTED"


def test_retry_retains_the_exact_old_record_and_repeats_the_same_packet_without_randomness():
    first = model.new_run("easy", "first")
    first = liftoff(hardware(act(first, "override")))
    first = model.advance(first, 115)
    original = json.dumps(first, sort_keys=True)
    second = model.retry(first, "second", run_id=first["run_id"], version=first["version"])
    assert json.dumps(first, sort_keys=True) == original
    assert second["vehicle"]["conditioned"] is False and second["elapsed_s"] == 0
    assert second["prior_runs"][0]["launch"] == first["launch"]
    assert second["prior_runs"][0]["outcome"] == first["outcome"]
    second = liftoff(hardware(act(second, "override")))
    one_jump = model.advance(second, 115)
    for tick in range(16, 116):
        second = model.advance(second, tick)
    assert second["flight"] == one_jump["flight"] == first["flight"]
    assert second["outcome"] == first["outcome"]
    with pytest.raises(model.InvalidCommand):
        model.retry(second, "first", run_id=second["run_id"], version=second["version"])


@pytest.mark.parametrize("action,choices", [
    ([], {}), ("receive_gate", {"decision": "PASS"}),
    ("edit", {"correction_cm_s": -20.0}), ("edit", {"condition_id": []}),
    ("edit", {"cutoff_clock": {}}), ("select", {"candidate_id": {}}),
    ("project", {"receipt_ids": ["invented"], "finding_ids": []}),
    ("project", {"receipt_ids": [], "finding_ids": ["invented"]}),
    ("arm", {"accepted": True}),
])
def test_structurally_invalid_commands_are_cleanly_rejected_without_advancing(action, choices):
    state = model.new_run("easy", "malformed")
    original = json.dumps(state, sort_keys=True)
    with pytest.raises(model.InvalidCommand):
        act(state, action, **choices)
    assert json.dumps(state, sort_keys=True) == original


def test_gate_arrival_must_be_current_and_finite_and_cannot_reuse_acceptance():
    state = model.new_run("easy", "gate-binding")
    state = gate(project(act(state, "check", name="WIND_BALANCE")), "BLOCKED")
    record_id = state["record_id"]
    stale_version = state["version"]
    for output in [{}, {"decision": []}, {"decision": "PASS", "number": float("nan")}]:
        with pytest.raises(model.InvalidCommand):
            model.receive_gate(state, record_id, output, run_id=state["run_id"], version=state["version"])
    state = act(state, "override")
    with pytest.raises(model.InvalidCommand):
        model.receive_gate(state, record_id, {"decision": "PASS"}, run_id=state["run_id"], version=stale_version)
    state = gate(state, "BLOCKED")
    assert state["authority"] is None
    state = project(state)
    with pytest.raises(model.InvalidCommand):
        model.receive_gate(state, record_id, {"decision": "PASS"}, run_id=state["run_id"], version=state["version"])
    for elapsed in [True, -1, 7201, 1.5]:
        with pytest.raises(model.InvalidCommand):
            model.advance(state, elapsed)
    for difficulty in [None, [], "HARD"]:
        with pytest.raises(model.InvalidCommand):
            model.new_run(difficulty, "bad-difficulty")


def test_hold_freezes_countdown_and_resume_has_a_new_generation_and_liftoff_origin():
    state = hardware(act(model.new_run("easy", "hold-clock"), "override"))
    state = act(state, "ignite")
    generation = state["countdown"]["generation"]
    state = model.advance(state, 8)
    state = act(state, "hold")
    assert state["countdown"]["generation"] != generation
    state = model.advance(state, 50)
    assert state["elapsed_s"] == 50
    assert state["countdown"]["remaining_s"] == 7 and state["launch"] is None
    state = act(state, "override")
    state = act(state, "ignite")
    assert state["countdown"]["generation"] != generation
    assert state["countdown"]["liftoff_s"] == 57
    state = model.advance(state, 57)
    assert state["launch"]["started_s"] == 57 and state["flight"]["t"] == 0


@pytest.mark.parametrize("operation", ["edit", "select", "project", "gate"])
def test_changed_candidate_record_or_gate_cancels_the_pending_launch(operation):
    state = model.new_run("easy", "cancel-clock")
    state = act(state, "check", name="WIND_BALANCE")
    state = gate(project(state), "BLOCKED")
    state = act(hardware(act(state, "override")), "ignite")
    state = model.advance(state, 7)
    if operation == "edit":
        state = act(state, "edit", correction_cm_s=-20)
    elif operation == "select":
        state = act(state, "select", candidate_id=state["candidate_id"])
    elif operation == "project":
        state = act(state, "project", receipt_ids=["check-1"], finding_ids=[])
    else:
        state = gate(state, "BLOCKED")
    assert state["countdown"] is None and state["phase"] == "PAD"
    state = model.advance(state, 200)
    assert state["launch"] is None and state["flight"] is None


def test_hold_after_engine_start_shuts_down_and_requires_new_hardware_preparation():
    state = hardware(act(model.new_run("easy", "pad-abort"), "override"))
    state = act(state, "ignite")
    state = model.advance(state, 9)
    assert state["countdown"]["engine_start"] is True
    state = act(state, "hold")
    assert state["phase"] == "PAD" and state["countdown"] is None
    assert state["outcome"]["flight"] == "PAD_ABORT"
    assert state["vehicle"] == {"conditioned": False, "armed": False, "conditioning_until": None}
    assert state["countdown_history"][-1]["snapshot"]["candidate"]["id"] == "easy-A1"
    state = model.advance(state, 100)
    assert state["launch"] is None


def test_mission_receipt_retains_its_exact_input_and_its_own_identity():
    state = act(model.new_run("easy", "receipt-input"), "check", name="WIND_BALANCE")
    receipt = state["receipts"]["check-1"]
    assert receipt["input"]["candidate"] == state["candidates"][state["candidate_id"]]
    assert receipt["input"]["observation"]["wind_cm_s"] == 20
    assert len(receipt["sha256"]) == len(receipt["input_sha256"]) == 64
    updated = act(state, "edit", correction_cm_s=-20)
    assert updated["receipts"]["check-1"] == receipt
