"""Pure, original teaching model; no flight authority or core-engine execution.

State is server-owned JSON data. Returned states are copies, so prior candidates,
receipts and runs remain inspectable. Never restore this state from visitor input.
The adapter owns time, persistence and actual DobeWorks/DEGS calls. All physics
and the short countdown are original exercise rules, not a NASA vehicle model.
"""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from types import MappingProxyType


class InvalidCommand(ValueError):
    """A structurally invalid or stale command; the input state is untouched."""


@dataclass(frozen=True)
class Packet:
    correction: int
    choices: tuple
    config: str = "R1"
    sign: int = 1
    checks: tuple = ("WIND_BALANCE",)
    # id, signed world wind in cm/s, applicable configuration, validity in flight seconds
    observations: tuple = (("W2", 20, "R1", 0, 100),)
    cutoff: str = "FLIGHT"


PACKETS = MappingProxyType({
    "easy": Packet(0, (-20, 0, 20)),
    "medium": Packet(-2000, (-2000, -20, 20), checks=("UNIT_AND_WIND_BALANCE",)),
    "hard": Packet(-20, (-20, 20), config="R2", sign=-1,
                   checks=("STATE_BINDING", "WIND_BALANCE", "CUTOFF_EPOCH"),
                   observations=(("W1", -20, "R1", -100, -1), ("W2", 20, "R2", 0, 100)),
                   cutoff="ONBOARD"),
})

AGENT_NAMES = MappingProxyType({"easy": "ELIZA", "medium": "COLOSSUS", "hard": "GUARDIAN"})
PROMPTS = MappingProxyType({
    "easy": (
        {"id": "E-C1", "group": "correction", "label": "KEEP 0.00", "patch": {"correction_cm_s": 0}},
        {"id": "E-C2", "group": "correction", "label": "SET −0.20", "patch": {"correction_cm_s": -20}},
        {"id": "E-C3", "group": "correction", "label": "SET +0.20", "patch": {"correction_cm_s": 20}},
    ),
    "medium": (
        {"id": "M-C1", "group": "correction", "label": "KEEP −20.00", "patch": {"correction_cm_s": -2000}},
        {"id": "M-C2", "group": "correction", "label": "SET −0.20", "patch": {"correction_cm_s": -20}},
        {"id": "M-C3", "group": "correction", "label": "SET +0.20", "patch": {"correction_cm_s": 20}},
    ),
    "hard": (
        {"id": "H-C1", "group": "correction", "label": "SET −0.20", "patch": {"correction_cm_s": -20}},
        {"id": "H-C2", "group": "correction", "label": "SET +0.20", "patch": {"correction_cm_s": 20}},
        {"id": "H-O1", "group": "observation", "label": "USE WIND W1", "patch": {"condition_id": "W1"}},
        {"id": "H-O2", "group": "observation", "label": "USE WIND W2", "patch": {"condition_id": "W2"}},
        {"id": "H-T1", "group": "cutoff", "label": "USE FLIGHT CLOCK", "patch": {"cutoff_clock": "FLIGHT"}},
        {"id": "H-T2", "group": "cutoff", "label": "USE ONBOARD CLOCK", "patch": {"cutoff_clock": "ONBOARD"}},
    ),
})


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _candidate(difficulty, revision, correction, condition="W2", cutoff="FLIGHT", config=None, prompts=()):
    result = {"id": f"{difficulty}-A{revision}", "revision": revision,
              "config_id": config or PACKETS[difficulty].config, "condition_id": condition,
              "correction_cm_s": correction, "cutoff_clock": cutoff,
              "generated_by": AGENT_NAMES[difficulty], "prompt_history": list(prompts)}
    return {**result, "sha256": _digest(result)}


def new_run(difficulty, run_id, mode="governed"):
    if (not isinstance(difficulty, str) or difficulty not in PACKETS
            or mode not in {"governed", "direct"}
            or not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id)):
        raise InvalidCommand("Unknown mode, difficulty, or invalid server run identity")
    packet = PACKETS[difficulty]
    candidate = _candidate(difficulty, 1, packet.correction, cutoff=packet.cutoff,
                           prompts=("RECEIVED-AUTONOMOUS-DRAFT",))
    result = {"schema": "dobeworks.stage.launch.v1", "run_id": run_id, "version": 0,
            "difficulty": difficulty, "mode": mode, "phase": "PAD", "elapsed_s": 0,
            "vehicle": {"conditioned": False, "armed": False, "conditioning_until": None},
            "candidate_id": candidate["id"], "candidates": {candidate["id"]: candidate},
            "receipts": {}, "staged_ids": [], "records": {}, "record_id": None,
            "gates": {}, "authority": None, "countdown": None, "launch": None, "flight": None, "outcome": None,
            "history": [], "countdown_history": [], "prior_runs": []}
    if difficulty == "hard":
        old = _candidate(difficulty, 0, 20, "W1", "FLIGHT", "R1", prompts=("ARCHIVED-AUTONOMOUS-DRAFT",))
        result["candidates"][old["id"]] = old
        if mode == "governed":
            result["candidate_id"] = old["id"]
            receipt = _check(result, "WIND_BALANCE")
            receipt["provenance"] = "RECORDED_MISSION_CHECK"
            receipt.pop("sha256")
            receipt["sha256"] = _digest(receipt)
            result["receipts"][receipt["id"]] = receipt
            result["candidate_id"] = candidate["id"]
    return result


def _guard(state, run_id, version):
    if run_id != state["run_id"] or type(version) is not int or version != state["version"]:
        raise InvalidCommand("Stale run or command version")
    if len(state["history"]) >= 128:
        raise InvalidCommand("Run action record is full; retry this packet")


def _commit(state, action, choices):
    state["version"] += 1
    state["history"].append({"version": state["version"], "elapsed_s": state["elapsed_s"],
                             "action": action, "choices": deepcopy(choices),
                             "after": {key: deepcopy(state[key]) for key in
                                       ("phase", "candidate_id", "record_id", "authority", "outcome")}})
    return state


def _check(state, name):
    candidate = state["candidates"][state["candidate_id"]]
    packet = PACKETS[state["difficulty"]]
    if name not in packet.checks:
        raise InvalidCommand("Unknown mission check")
    observation = next(row for row in packet.observations if row[0] == candidate["condition_id"])
    sign = {"R1": 1, "R2": -1}[candidate["config_id"]]
    residual = observation[1] + sign * candidate["correction_cm_s"]
    details = {"residual_cm_s": residual}
    passed = residual == 0
    if name == "STATE_BINDING":
        passed = (candidate["config_id"] == packet.config and observation[2] == packet.config
                  and observation[3] <= 0 and observation[4] >= 100)
        details = {"required_config_id": packet.config, "observation_config_id": observation[2],
                   "valid_from_t": observation[3], "valid_through_t": observation[4]}
    elif name == "CUTOFF_EPOCH":
        passed = candidate["cutoff_clock"] == "FLIGHT"
        details = {"clock": candidate["cutoff_clock"], "seed_at_liftoff": 0 if passed else 20}
    receipt_id = f'check-{len(state["receipts"]) + 1}'
    inputs = {"candidate": deepcopy(candidate), "check": name,
              "observation": dict(zip(("id", "wind_cm_s", "config_id", "valid_from_t", "valid_through_t"), observation))}
    receipt = {"id": receipt_id, "candidate_id": candidate["id"], "candidate_sha256": candidate["sha256"],
            "config_id": candidate["config_id"], "condition_id": candidate["condition_id"],
            "name": name, "result": "PASS" if passed else "FAIL",
            "details": details, "provenance": "EXECUTED_MISSION_CHECK",
            "input": inputs, "input_sha256": _digest(inputs),
            "finding_ids": [] if passed else [receipt_id + "-finding"]}
    receipt["sha256"] = _digest(receipt)
    return receipt


def _references(values, known):
    if (not isinstance(values, list) or any(not isinstance(item, str) for item in values)
            or len(values) != len(set(values)) or any(item not in known for item in values)):
        raise InvalidCommand("Choose distinct existing references")
    return deepcopy(values)


def _binding(state):
    record = state["records"].get(state["record_id"])
    gate = state["gates"].get(state["record_id"])
    return _digest({"candidate": state["candidates"][state["candidate_id"]]["sha256"],
                    "record": record["sha256"] if record else None, "gate": gate})


def _support(state):
    if state["mode"] == "direct":
        return "DIRECT_UNCHECKED"
    record = state["records"].get(state["record_id"])
    if not record or not record["staged"] or record["candidate_id"] != state["candidate_id"]:
        return "UNSUPPORTED"
    candidate = state["candidates"][state["candidate_id"]]
    matching = [r for r in record["receipts"] if r["candidate_sha256"] == candidate["sha256"]
                and r["config_id"] == candidate["config_id"] and r["condition_id"] == candidate["condition_id"]]
    names = {receipt["name"] for receipt in matching}
    findings = {finding for receipt in matching for finding in receipt["finding_ids"]}
    known_findings = {finding for receipt in state["receipts"].values()
                      if receipt["candidate_sha256"] == candidate["sha256"] for finding in receipt["finding_ids"]}
    supported = (len(matching) == len(record["receipts"])
                 and set(PACKETS[state["difficulty"]].checks) <= names
                 and set(record["finding_ids"]) == findings == known_findings)
    return "SUPPORTED" if supported else "UNSUPPORTED"


def receive_gate(state, record_id, output, *, run_id, version):
    """TRUSTED adapter seam: retain the evaluated receipt for this exact projection.

    The caller must execute/validate DEGS and bind its input to this record. The
    top-level decision is the enforced result. If the adapter rejects binding,
    retain stock DEGS's unmodified output separately under ``degs`` in the receipt.
    The model cannot authenticate a caller; never expose this as a form action.
    """
    _guard(state, run_id, version)
    if (state["mode"] != "governed" or state["phase"] not in {"PAD", "COUNTDOWN"}
            or record_id != state["record_id"] or record_id not in state["records"]
            or not isinstance(output, dict) or not isinstance(output.get("decision"), str) or output["decision"] not in
            {"PASS", "PASS_WITH_WARNINGS", "BLOCKED", "FAIL", "INVALID"}):
        raise InvalidCommand("Gate output does not bind the current projection")
    try:
        _digest(output)
    except (ValueError, TypeError) as error:
        raise InvalidCommand("Gate output must be finite JSON") from error
    result = deepcopy(state)
    result["gates"][record_id] = {"record_sha256": state["records"][record_id]["sha256"],
                                 "output": deepcopy(output)}
    result["authority"] = None
    _cancel_countdown(result)
    return _commit(result, "receive_gate", {"record_id": record_id, "output": output})


def _denials(state):
    authority = state["authority"]
    gate = state["gates"].get(state["record_id"])
    decision = gate["output"]["decision"] if gate else None
    exact = authority is not None and authority["binding"] == _binding(state)
    overridden = exact and authority["action"] == "OVERRIDE"
    reasons = []
    if state["mode"] == "governed" and decision in {"BLOCKED", "FAIL", "INVALID"} and not overridden:
        reasons.append("GATE BLOCKED")
    allowed_authority = {"MANUAL_ACCEPT"} if state["mode"] == "direct" else {"ACCEPT", "OVERRIDE"}
    if not exact or authority["action"] not in allowed_authority:
        reasons.append("LAUNCH AUTHORITY ABSENT")
    if not state["vehicle"]["conditioned"]:
        reasons.append("NOT CONDITIONED")
    if not state["vehicle"]["armed"]:
        reasons.append("NOT ARMED")
    return reasons


def _cancel_countdown(state, reason="COUNTDOWN INPUT CHANGED"):
    countdown = state["countdown"]
    if countdown:
        state["countdown_history"].append({**deepcopy(countdown), "cancelled_s": state["elapsed_s"], "reason": reason})
        if countdown["engine_start"]:
            state["vehicle"].update(conditioned=False, armed=False, conditioning_until=None)
            state["outcome"] = {"flight": "PAD_ABORT", "record": _support(state),
                                "human": state["authority"]["action"] if state["authority"] else "NONE",
                                "reasons": [reason, "ENGINE OFF"]}
    if state["phase"] == "COUNTDOWN":
        state["phase"] = "PAD"
    state["countdown"] = None


def _ignite(state):
    reasons = _denials(state)
    authority = state["authority"]
    if reasons:
        first = reasons[0]
        state["phase"] = "PAD" if first in {"GATE BLOCKED", "LAUNCH AUTHORITY ABSENT"} else "NO_IGNITION"
        state["outcome"] = {"flight": "PAD_HOLD" if state["phase"] == "PAD" else "NO_IGNITION",
                            "record": _support(state), "human": authority["action"] if authority else "NONE",
                            "reasons": reasons}
        state["countdown"] = None
        return
    remaining = state["countdown"]["remaining_s"] if state["countdown"] else 10
    snapshot = {"candidate": deepcopy(state["candidates"][state["candidate_id"]]),
                       "record": deepcopy(state["records"].get(state["record_id"])),
                       "gate": deepcopy(state["gates"].get(state["record_id"])), "authority": deepcopy(authority),
                       "record_support": _support(state), "started_s": state["elapsed_s"] + remaining,
                       "world_wind_cm_s": 20, "actual_config_id": PACKETS[state["difficulty"]].config,
                       "body_to_world_sign": PACKETS[state["difficulty"]].sign}
    state["phase"] = "COUNTDOWN"
    state["outcome"] = None
    state["countdown"] = {"generation": state["version"] + 1, "remaining_s": remaining,
                          "holding": False, "engine_start": remaining <= 6,
                          "liftoff_s": snapshot["started_s"], "binding": _binding(state), "snapshot": snapshot}


def _liftoff(state):
    state["launch"] = deepcopy(state["countdown"]["snapshot"])
    state["countdown"] = None
    state["phase"] = "FLIGHT"
    state["outcome"] = None
    state["flight"] = {"t": 0, "x_cm": 0, "h": 0, "engine_on": True,
                       "events": [{"t": 0, "event": "LIFTOFF"}], "faults": []}
    launch = state["launch"]
    if launch["world_wind_cm_s"] + launch["body_to_world_sign"] * launch["candidate"]["correction_cm_s"]:
        state["flight"]["faults"].append({"code": "WIND_RESIDUAL", "at_t": 20, "status": "PRESENT_NOT_REACHED"})
    if launch["candidate"]["cutoff_clock"] == "ONBOARD":
        state["flight"]["faults"].append({"code": "EARLY_CUTOFF", "at_t": 80, "status": "PRESENT_NOT_REACHED"})


def advance(state, elapsed_s):
    """Advance absolute SERVER attempt time; no I/O or wall-clock access here."""
    if type(elapsed_s) is not int or elapsed_s < state["elapsed_s"]:
        raise InvalidCommand("Server time must be a monotonic integer")
    result = deepcopy(state)
    result["elapsed_s"] = elapsed_s
    until = result["vehicle"]["conditioning_until"]
    if until is not None and elapsed_s >= until:
        result["vehicle"].update(conditioned=True, conditioning_until=None)
    if result["phase"] == "COUNTDOWN" and not result["countdown"]["holding"]:
        countdown = result["countdown"]
        countdown["remaining_s"] = max(0, countdown["liftoff_s"] - elapsed_s)
        countdown["engine_start"] = countdown["remaining_s"] <= 6
        if countdown["remaining_s"] == 0:
            if (_denials(result) or countdown["binding"] != _binding(result)
                    or countdown["snapshot"]["authority"] != result["authority"]):
                _cancel_countdown(result)
                result["outcome"] = {"flight": "PAD_HOLD", "record": _support(result),
                                     "human": "NONE", "reasons": ["LAUNCH AUTHORITY ABSENT"]}
            else:
                _liftoff(result)
    if result["phase"] == "FLIGHT":
        launch = result["launch"]
        residual = launch["world_wind_cm_s"] + launch["body_to_world_sign"] * launch["candidate"]["correction_cm_s"]
        cutoff = 80 if launch["candidate"]["cutoff_clock"] == "ONBOARD" else 100
        stop = min(100, elapsed_s - launch["started_s"])
        for t in range(result["flight"]["t"] + 1, stop + 1):
            x = residual * min(40, max(0, t - 20))
            h = t * t if t <= cutoff else cutoff * cutoff + 2 * cutoff * (t - cutoff) - (t - cutoff) ** 2
            result["flight"].update(t=t, x_cm=x, h=h, engine_on=t < cutoff)
            for fault in result["flight"]["faults"]:
                if t >= fault["at_t"]:
                    fault["status"] = "REACHED"
            event = {20: "STEERING_WINDOW_OPEN", 60: "STEERING_WINDOW_CLOSED", 100: "PROFILE_COMPLETE"}.get(t)
            if t == cutoff:
                result["flight"]["events"].append({"t": t, "event": "ENGINE_CUTOFF"})
            if abs(x) > 500:
                result["phase"] = "RANGE_ABORT"
                result["flight"]["engine_on"] = False
                event = "RANGE_ABORT"
            elif t == 100:
                result["phase"] = "COMPLETE"
            if event:
                result["flight"]["events"].append({"t": t, "event": event})
            if result["phase"] != "FLIGHT":
                outcome = "RANGE_ABORT" if result["phase"] == "RANGE_ABORT" else "PROFILE_MISSED" if h < 10000 else "NOMINAL"
                result["outcome"] = {"flight": outcome,
                                     "record": launch["record_support"], "human": launch["authority"]["action"]}
                break
    return result


def retry(state, new_run_id, *, run_id, version):
    """Restart from cold with the same authored packet; retain up to eight prior runs."""
    if run_id != state["run_id"] or type(version) is not int or version != state["version"]:
        raise InvalidCommand("Stale retry")
    if new_run_id == run_id or any(item["run_id"] == new_run_id for item in state["prior_runs"]):
        raise InvalidCommand("Retry requires a new server run identity")
    result = new_run(state["difficulty"], new_run_id, state["mode"])
    retained = deepcopy(state)
    retained.pop("prior_runs")
    result["prior_runs"] = deepcopy(state["prior_runs"][-7:]) + [retained]
    return result


def act(state, action, *, run_id, version, **choices):
    """Apply an enum choice; this seam never accepts gate outputs or client time."""
    _guard(state, run_id, version)
    if not isinstance(action, str):
        raise InvalidCommand("Action must be a supplied name")
    if state["phase"] not in {"PAD", "COUNTDOWN"}:
        raise InvalidCommand("Preparation has ended")
    result = deepcopy(state)
    packet = PACKETS[state["difficulty"]]
    if state["mode"] == "direct" and action in {"check", "stage", "project", "override"}:
        raise InvalidCommand("That governed control is not present in direct mode")
    if action == "prompt" and set(choices) == {"prompt_id"}:
        prompt_id = choices["prompt_id"]
        prompt = next((item for item in PROMPTS[state["difficulty"]] if item["id"] == prompt_id), None)
        if prompt is None:
            raise InvalidCommand("Choose a supplied agent prompt")
        old = state["candidates"][state["candidate_id"]]
        patch = prompt["patch"]
        value = patch.get("correction_cm_s", old["correction_cm_s"])
        condition = patch.get("condition_id", old["condition_id"])
        cutoff = patch.get("cutoff_clock", old["cutoff_clock"])
        revision = max(item["revision"] for item in state["candidates"].values()) + 1
        candidate = _candidate(state["difficulty"], revision, value, condition, cutoff,
                               prompts=tuple(old["prompt_history"]) + (prompt_id,))
        result["candidates"][candidate["id"]] = candidate
        result["candidate_id"] = candidate["id"]
        result["authority"] = None
        result["record_id"] = None
        _cancel_countdown(result)
    elif action == "edit" and choices and set(choices) <= {"correction_cm_s", "condition_id", "cutoff_clock"}:
        old = state["candidates"][state["candidate_id"]]
        value = choices.get("correction_cm_s", old["correction_cm_s"])
        condition = choices.get("condition_id", old["condition_id"])
        cutoff = choices.get("cutoff_clock", old["cutoff_clock"])
        if (type(value) is not int or value not in packet.choices
                or condition not in [row[0] for row in packet.observations]
                or cutoff not in (("FLIGHT", "ONBOARD") if state["difficulty"] == "hard" else ("FLIGHT",))):
            raise InvalidCommand("Choose a supplied correction")
        revision = max(item["revision"] for item in state["candidates"].values()) + 1
        candidate = _candidate(state["difficulty"], revision, value, condition, cutoff,
                               prompts=tuple(old["prompt_history"]) + ("INTERNAL-DIRECT-EDIT",))
        result["candidates"][candidate["id"]] = candidate
        result["candidate_id"] = candidate["id"]
        result["authority"] = None
        result["record_id"] = None
        _cancel_countdown(result)
    elif action == "check" and set(choices) == {"name"}:
        receipt = _check(state, choices["name"])
        result["receipts"][receipt["id"]] = receipt
        result["authority"] = None
        result["record_id"] = None
        _cancel_countdown(result)
    elif action == "select" and set(choices) == {"candidate_id"}:
        key = choices["candidate_id"]
        if not isinstance(key, str) or key not in state["candidates"]:
            raise InvalidCommand("Choose an existing candidate")
        result["candidate_id"] = key
        result["authority"] = None
        result["record_id"] = None
        _cancel_countdown(result)
    elif action == "stage" and not choices:
        # Local exhibit staging intent only; the adapter separately retains Worker execution.
        if state["candidate_id"] not in result["staged_ids"]:
            result["staged_ids"].append(state["candidate_id"])
    elif action == "project" and set(choices) == {"receipt_ids", "finding_ids"}:
        receipt_ids = _references(choices["receipt_ids"], state["receipts"])
        findings = {finding for receipt in state["receipts"].values() for finding in receipt["finding_ids"]}
        finding_ids = _references(choices["finding_ids"], findings)
        record_id = f'record-{len(state["records"]) + 1}'
        record = {"id": record_id, "candidate_id": state["candidate_id"],
                  "candidate_sha256": state["candidates"][state["candidate_id"]]["sha256"],
                  "staged": state["candidate_id"] in state["staged_ids"],
                  "receipts": [deepcopy(state["receipts"][key]) for key in receipt_ids],
                  "finding_ids": finding_ids}
        record["sha256"] = _digest(record)
        result["records"][record_id] = record
        result["record_id"] = record_id
        result["authority"] = None
        _cancel_countdown(result)
    elif action == "accept" and not choices:
        gate = state["gates"].get(state["record_id"])
        accepted = (state["mode"] == "direct"
                    or (gate is not None and gate["output"]["decision"] == "PASS" and _support(state) == "SUPPORTED"))
        action_name = "MANUAL_ACCEPT" if state["mode"] == "direct" else "ACCEPT"
        result["authority"] = {"action": action_name if accepted else "HOLD", "binding": _binding(state)}
    elif action in {"hold", "override"} and not choices:
        result["authority"] = {"action": action.upper(), "binding": _binding(state)}
    elif action == "condition" and not choices:
        if not result["vehicle"]["conditioned"] and result["vehicle"]["conditioning_until"] is None:
            result["vehicle"]["conditioning_until"] = state["elapsed_s"] + 5
    elif action == "arm" and not choices:
        result["vehicle"]["armed"] = True
    elif action == "ignite" and not choices:
        if state["phase"] == "COUNTDOWN" and not state["countdown"]["holding"]:
            raise InvalidCommand("Countdown is already running")
        _ignite(result)
    else:
        raise InvalidCommand("Unknown action or invalid choice")
    if action in {"hold", "accept", "override"} and result["countdown"]:
        if result["countdown"]["engine_start"]:
            _cancel_countdown(result, "HOLD AFTER ENGINE START" if action == "hold" else "AUTHORITY CHANGED AFTER ENGINE START")
        else:
            result["countdown_history"].append({**deepcopy(result["countdown"]),
                                                "cancelled_s": state["elapsed_s"], "reason": "COUNTDOWN HELD"})
            result["countdown"].update(holding=True, liftoff_s=None, engine_start=False,
                                       generation=state["version"] + 1)
    return _commit(result, action, choices)
