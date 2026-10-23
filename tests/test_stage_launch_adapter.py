"""The live adapter executes frozen DobeWorks/DEGS paths without inventing their scope."""
import json

import stage_launch_adapter as adapter


def sample_state(*, result="PASS", carry=True, misbind=False):
    candidate = {
        "id": "easy-A2", "revision": 2, "config_id": "R1", "condition_id": "W2",
        "correction_cm_s": -20, "cutoff_clock": "FLIGHT", "sha256": "c" * 64,
    }
    receipt = {
        "id": "check-1", "candidate_id": "easy-A1" if misbind else candidate["id"],
        "candidate_sha256": "a" * 64 if misbind else candidate["sha256"],
        "config_id": "R1", "condition_id": "W2", "name": "WIND_BALANCE",
        "result": result, "details": {"residual_cm_s": 0 if result == "PASS" else 20},
        "provenance": "EXECUTED_MISSION_CHECK",
        "finding_ids": [] if result == "PASS" else ["check-1-finding"],
    }
    record = {
        "id": "record-1", "candidate_id": candidate["id"],
        "candidate_sha256": candidate["sha256"], "staged": True,
        "receipts": [receipt],
        "finding_ids": receipt["finding_ids"] if carry else [], "sha256": "r" * 64,
    }
    return {
        "run_id": "run-one", "difficulty": "easy", "candidate_id": candidate["id"],
        "candidates": {candidate["id"]: candidate}, "receipts": {receipt["id"]: receipt},
        "record_id": record["id"], "records": {record["id"]: record},
    }


def test_worker_receipt_is_completed_unaccepted_and_package_distinct():
    first = adapter.stage_candidate(sample_state())
    changed = sample_state()
    changed["candidates"]["easy-A2"] = {**changed["candidates"]["easy-A2"], "sha256": "d" * 64}
    changed["candidate_id"] = "easy-A2"
    second = adapter.stage_candidate(changed)
    assert first["worker"]["state"] == "COMPLETED_UNACCEPTED"
    assert first["worker"]["promotion"] == "NOT_PERFORMED"
    assert first["worker"]["job_id"].startswith("stage-launch-")
    assert first["worker"]["job_id"] != second["worker"]["job_id"]
    assert first["package_manifest_sha256"] != second["package_manifest_sha256"]


def test_actual_degs_passes_a_fresh_clean_projection():
    state = sample_state()
    staged = adapter.stage_candidate(state)
    result = adapter.evaluate_projection(state, staged)
    assert result["decision"] == "PASS"
    assert result["raw_degs_decision"] == "PASS"
    assert result["degs"]["decision"] == "PASS"
    assert result["validate_decision"] == "PASS"
    assert result["adapter_classification"] == "EXACT_CLEAN_RECORD"
    assert result["binding"]["candidate_sha256"] == "c" * 64
    assert json.loads(json.dumps(result)) == result


def test_actual_degs_blocks_a_carried_open_finding():
    state = sample_state(result="FAIL", carry=True)
    result = adapter.evaluate_projection(state, adapter.stage_candidate(state))
    assert result["decision"] == "BLOCKED"
    assert result["degs"]["warning_state"]["unresolved_count"] == 1
    assert result["adapter_classification"] == "OPEN_FINDING_PRESERVED"


def test_omission_and_misbinding_are_adapter_defects_not_claimed_degs_detection():
    omitted = sample_state(result="FAIL", carry=False)
    omitted_result = adapter.evaluate_projection(omitted, adapter.stage_candidate(omitted))
    assert omitted_result["decision"] == "INVALID"
    assert omitted_result["raw_degs_decision"] == "PASS"
    assert omitted_result["adapter_classification"] == "FINDING_OMITTED"
    assert omitted_result["degs"]["warnings"] == []

    misbound = sample_state(misbind=True)
    misbound_result = adapter.evaluate_projection(misbound, adapter.stage_candidate(misbound))
    assert misbound_result["decision"] == "INVALID"
    assert misbound_result["raw_degs_decision"] == "PASS"
    assert misbound_result["adapter_classification"] == "RECEIPT_MISBOUND"
    assert misbound_result["degs"]["decision"] == "PASS"
