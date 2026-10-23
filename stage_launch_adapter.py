"""Truthful live adapter between the launch exercise and frozen DobeWorks/DEGS.

The packet model owns the fictional mission math. This module executes a real
DobeWorks inventory and a real DEGS CLI validation/evaluation over the exact
record the player projects. DEGS is never credited with wind math, freshness,
hash recomputation, or arbitrary receipt-misbinding detection.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

from stage_launch_model import PACKETS
from stage_mission import VENDOR, check_sources, digest, encode, load_module, stage_inventory


class AdapterError(RuntimeError):
    """The trusted stage adapter could not bind or execute an engine result."""


def _candidate(state):
    try:
        return state["candidates"][state["candidate_id"]]
    except (KeyError, TypeError) as error:
        raise AdapterError("No exact current candidate is available") from error


def _record(state):
    try:
        return state["records"][state["record_id"]]
    except (KeyError, TypeError) as error:
        raise AdapterError("No exact outgoing record is available") from error


def _payload_digest(value):
    return digest(encode(value))


def _source_identity():
    engines, _ = check_sources()
    return {name: item["commit"] for name, item in engines.items()}


def _stage_material(state, candidate):
    candidate_payload_sha256 = _payload_digest(candidate)
    context = {
        "schema": "dobeworks.stage.launch-candidate.v1",
        "run_id": state["run_id"],
        "difficulty": state["difficulty"],
        "candidate_id": candidate["id"],
        "candidate_payload_sha256": candidate_payload_sha256,
        "scope": "Fictional teaching-model candidate inventory; no vehicle execution or promotion.",
    }
    context_payload_sha256 = _payload_digest(context)
    artifacts = {
        f"candidate/{candidate_payload_sha256}.json": encode(candidate),
        f"context/{context_payload_sha256}.json": encode(context),
    }
    package_manifest_sha256 = _payload_digest({name: digest(data) for name, data in artifacts.items()})
    return candidate_payload_sha256, context_payload_sha256, artifacts, package_manifest_sha256


def stage_candidate(state):
    """Run the frozen Worker on a package-distinct inventory for this candidate."""
    candidate = deepcopy(_candidate(state))
    candidate_payload_sha256, context_payload_sha256, artifacts, package_manifest_sha256 = _stage_material(
        state, candidate
    )
    job_id = f"stage-launch-{package_manifest_sha256[:20]}"
    with tempfile.TemporaryDirectory(prefix="stage-launch-worker-") as temporary:
        worker, worker_input, envelope = stage_inventory(
            Path(temporary), artifacts, job_id=job_id
        )
    if worker.get("state") != "COMPLETED_UNACCEPTED" or worker.get("promotion") != "NOT_PERFORMED":
        raise AdapterError("DobeWorks did not return a completed unaccepted inventory")
    return {
        "schema": "dobeworks.stage.launch-worker-receipt.v1",
        "run_id": state["run_id"],
        "difficulty": state["difficulty"],
        "candidate_id": candidate["id"],
        "candidate_sha256": candidate.get("sha256"),
        "candidate_payload_sha256": candidate_payload_sha256,
        "context_payload_sha256": context_payload_sha256,
        "package_manifest_sha256": package_manifest_sha256,
        "worker": worker,
        "worker_input": worker_input,
        "worker_envelope": envelope,
        "source_identity": _source_identity(),
    }


def _classification(state, candidate, record):
    receipts = record.get("receipts", [])
    mismatched = any(
        receipt.get("candidate_sha256") != candidate.get("sha256")
        or receipt.get("config_id") != candidate.get("config_id")
        or receipt.get("condition_id") != candidate.get("condition_id")
        for receipt in receipts
    )
    current_receipts = [
        receipt for receipt in state.get("receipts", {}).values()
        if receipt.get("candidate_sha256") == candidate.get("sha256")
        and receipt.get("config_id") == candidate.get("config_id")
        and receipt.get("condition_id") == candidate.get("condition_id")
    ]
    required_checks = set(PACKETS[state["difficulty"]].checks)
    projected_checks = {receipt.get("name") for receipt in receipts}
    known_findings = {
        finding for receipt in current_receipts if receipt.get("result") == "FAIL"
        for finding in receipt.get("finding_ids", [])
    }
    carried = set(record.get("finding_ids", []))
    if mismatched:
        return "RECEIPT_MISBOUND"
    if required_checks - projected_checks:
        return "RECEIPT_OMITTED"
    if known_findings - carried:
        return "FINDING_OMITTED"
    if carried:
        return "OPEN_FINDING_PRESERVED"
    return "EXACT_CLEAN_RECORD"


def _task(record, classification):
    open_findings = list(record.get("finding_ids", []))
    warnings = [
        {"severity": "CRITICAL", "resolved": False, "status": "UNRESOLVED",
         "evidence_path": f"evidence/findings/{finding}.json"}
        for finding in open_findings
    ]
    verification = "FAIL" if any(receipt.get("result") == "FAIL" for receipt in record.get("receipts", [])) else "PASS"
    return {
        "schema_version": 1,
        "task_id": "DEGS-STAGE-LAUNCH-RECORD-001",
        "title": "Inspect a fictional launch-record projection",
        "objective": "Evaluate the exact warning state supplied by the launch-record adapter.",
        "status": "READY_FOR_EXECUTION",
        "risk_tier": "TIER_0",
        "authority_lane": "COMMAND_CENTER",
        "scope": {"description": "Read one fictional teaching record; no launch, remediation or promotion authority.", "read_only": True},
        "requirements": ["Preserve every supplied unresolved finding as a stop condition."],
        "acceptance_criteria": ["The gate decision corresponds to the warning fields in this exact projected record."],
        "selected_design": "Validate and evaluate the supplied read-only record with the frozen DEGS CLI.",
        "alternatives": [], "assumptions": [], "affected_files": [],
        "blast_radius": "One temporary record and one local DEGS evaluation.",
        "stakeholders": ["Stage visitor"],
        "non_goals": ["Compute wind balance", "Authenticate evidence contents", "Operate a vehicle", "Promote staged work"],
        "invariants": ["DEGS-SEC-001", "DEGS-SEC-002"],
        "stop_conditions": [], "unresolved_items": [],
        "warnings": warnings,
        "baseline": {"status": "RECORDED", "evidence_path": "evidence/record.json"},
        "verification": {"status": verification, "evidence_path": "evidence/mission-checks.json"},
        "validation": {"status": "PENDING", "evidence_path": "evidence/record.json"},
        "documentation": {"status": "PENDING", "evidence_path": "evidence/record.json"},
        "handoff": {"status": "PENDING", "evidence_path": "evidence/record.json"},
        "telemetry": {"status": "SANITIZED", "evidence_path": "evidence/record.json"},
        "tests": {"static": [], "positive": [], "negative": [], "integration": [], "end_to_end": [], "failure_path": [], "security": []},
        "backup": {"required": False, "reason": "Read-only temporary evaluation."},
        "rollback": {"required": False, "reason": "No mutation is authorized."},
        "recovery_validation": {"required": False, "status": "NOT_REQUIRED"},
        "post_action_validation": {"status": "NOT_REQUIRED"},
        "human_approval": {"required": False, "status": "NOT_REQUIRED"},
        "independent_review": {"required": False, "status": "NOT_REQUIRED"},
        "secret_handling": {"controlled": True, "exposure_possible": False},
        "target_identity": None,
    }


def evaluate_projection(state, staged):
    """Run DEGS on the exact current projection and retain an explicit binding."""
    candidate = deepcopy(_candidate(state))
    record = deepcopy(_record(state))
    candidate_payload_sha256, context_payload_sha256, _, package_manifest_sha256 = _stage_material(
        state, candidate
    )
    job_id = f"stage-launch-{package_manifest_sha256[:20]}"
    if (
        staged.get("run_id") != state.get("run_id")
        or staged.get("difficulty") != state.get("difficulty")
        or staged.get("candidate_id") != candidate.get("id")
        or staged.get("candidate_sha256") != candidate.get("sha256")
        or staged.get("candidate_payload_sha256") != candidate_payload_sha256
        or staged.get("context_payload_sha256") != context_payload_sha256
        or staged.get("package_manifest_sha256") != package_manifest_sha256
        or staged.get("worker", {}).get("job_id") != job_id
        or staged.get("worker_envelope", {}).get("job_id") != job_id
        or staged.get("worker", {}).get("state") != "COMPLETED_UNACCEPTED"
        or staged.get("worker", {}).get("promotion") != "NOT_PERFORMED"
    ):
        raise AdapterError("The DobeWorks receipt does not bind the projected candidate")

    classification = _classification(state, candidate, record)
    task = _task(record, classification)
    binding = {
        "run_id": state["run_id"],
        "candidate_id": candidate["id"],
        "candidate_sha256": candidate.get("sha256"),
        "candidate_payload_sha256": candidate_payload_sha256,
        "config_id": candidate.get("config_id"),
        "condition_id": candidate.get("condition_id"),
        "receipt_sha256": _payload_digest(record.get("receipts", [])),
        "record_id": record["id"],
        "record_sha256": record.get("sha256"),
        "record_payload_sha256": _payload_digest(record),
        "worker_output_sha256": staged["worker"]["output_sha256"],
        "worker_package_manifest_sha256": staged["package_manifest_sha256"],
        "task_sha256": _payload_digest(task),
    }
    with tempfile.TemporaryDirectory(prefix="stage-launch-gate-") as temporary:
        directory = Path(temporary)
        evidence = directory / "evidence"
        (evidence / "findings").mkdir(parents=True)
        (evidence / "record.json").write_bytes(encode(record))
        (evidence / "mission-checks.json").write_bytes(encode(record.get("receipts", [])))
        for finding in record.get("finding_ids", []):
            (evidence / "findings" / f"{finding}.json").write_bytes(encode({"finding_id": finding, "status": "UNRESOLVED"}))
        ui = load_module("stage_launch_public_interface", VENDOR / "DobeWorks/interface/command_center.py")
        ui.DEGS = VENDOR / "DEGS"
        gate = ui.run_degs_task(task, directory, "launch-record")
    if gate["validate_exit"] != 0 or gate["validate_decision"] != "PASS":
        raise AdapterError("The exact projected task did not pass the DEGS schema")
    raw_decision = gate["evaluate_decision"]
    if raw_decision not in {"PASS", "BLOCKED", "FAIL", "INVALID"}:
        raise AdapterError("DEGS returned an unsupported decision")
    decision = "INVALID" if classification in {
        "FINDING_OMITTED", "RECEIPT_MISBOUND", "RECEIPT_OMITTED",
    } else raw_decision
    return {
        "schema": "dobeworks.stage.launch-gate-receipt.v1",
        "decision": decision,
        "validate_decision": gate["validate_decision"],
        "adapter_classification": classification,
        "raw_degs_decision": raw_decision,
        "binding": binding,
        "degs": gate["evaluate"],
        "degs_exit": gate["evaluate_exit"],
        "source_identity": staged["source_identity"],
    }


def _main():
    """Small process boundary for web use; WorkerCore owns process signals."""
    if len(sys.argv) != 2 or sys.argv[1] not in {"stage", "evaluate"}:
        raise SystemExit(2)
    raw = sys.stdin.buffer.read(512_001)
    if len(raw) > 512_000:
        raise SystemExit(2)
    try:
        request = json.loads(raw)
        if sys.argv[1] == "stage" and isinstance(request, dict):
            result = stage_candidate(request)
        elif (sys.argv[1] == "evaluate" and isinstance(request, dict)
              and set(request) == {"state", "staged"}):
            result = evaluate_projection(request["state"], request["staged"])
        else:
            raise ValueError("Invalid adapter request")
    except (AdapterError, KeyError, TypeError, ValueError):
        raise SystemExit(1) from None
    sys.stdout.buffer.write(encode(result))


if __name__ == "__main__":
    _main()
