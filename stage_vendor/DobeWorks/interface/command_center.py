#!/usr/bin/env python3
"""Shared terminal interface for the public DobeWorks and DEGS checkouts."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
import math
from pathlib import Path
import re
import secrets
import subprocess
import sys
import textwrap
from urllib.parse import urlsplit, urlunsplit


SUPPORT = Path(__file__).resolve().parent
ROOT = SUPPORT.parent
DOBEWORKS = ROOT
DEGS = ROOT.parent / "DEGS"
PHASE4 = DOBEWORKS / "contexts" / "operational-system" / "software" / "phase4"
RUNS = SUPPORT / "Runs"
VOICE_BANK = SUPPORT / "workbench-voices.json"
WORKER_CONFIGURATION_SHA256 = (
    "ba0e803fc49b7a78989a44c9c9beb9789e37980b7ce92654a89d3f364460873d"
)
FRAME_WIDTH = 70
FIELD_LABEL_WIDTH = 22
FIELD_VALUE_WIDTH = FRAME_WIDTH - FIELD_LABEL_WIDTH - 4
PROCESS_TIMEOUT_SECONDS = 120


class Color:
    # ELIZA paper white and machine gray, carried into the cool blue-black,
    # pale monitor blue, and white display lines of the Colossus control room.
    BASE = "\033[0m\033[48;2;9;20;38m\033[38;2;196;217;232m"  # #091426 / #C4D9E8
    ICE = "\033[38;2;240;244;247m"                       # #F0F4F7
    PALE = "\033[38;2;212;224;233m"                      # #D4E0E9
    CYAN = "\033[38;2;154;209;237m"                      # #9AD1ED
    BLUE = "\033[38;2;132;180;208m"                      # #84B4D0
    DEEP = "\033[38;2;86;140;179m"                       # #568CB3
    MUTED = "\033[38;2;168;187;203m"                     # #A8BBCB
    RESET = "\033[0m"


def paint(value: str, color: str) -> str:
    if not sys.stdout.isatty():
        return value
    return f"{color}{value}{Color.BASE}"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def choose_workbench_voice() -> tuple[str, str, str]:
    """Choose one of the three historical voices with equal probability."""
    entries = json.loads(VOICE_BANK.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or len(entries) != 100:
        raise RuntimeError("The workbench voice bank must contain exactly 100 lines")
    by_speaker: dict[str, list[tuple[str, str]]] = {
        "ELIZA": [],
        "COLOSSUS": [],
        "GUARDIAN": [],
    }
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("Every workbench voice entry must be an object")
        speaker = entry.get("speaker")
        line = entry.get("text")
        attribution = entry.get("attribution")
        if (
            speaker not in by_speaker
            or not isinstance(line, str)
            or not line
            or not isinstance(attribution, str)
            or not attribution
        ):
            raise RuntimeError("Every workbench voice needs a known speaker, text, and attribution")
        if len(f"“{line}”") > 68 or len(attribution) > 68:
            raise RuntimeError(f"Workbench quote or attribution is too wide: {line}")
        by_speaker[speaker].append((line, attribution))
    speaker = secrets.choice(tuple(by_speaker))
    line, attribution = secrets.choice(by_speaker[speaker])
    return speaker, line, attribution


def spaced(value: str) -> str:
    return " ".join(value.upper())


def clear_screen() -> None:
    if sys.stdout.isatty():
        print(Color.BASE + "\033[2J\033[H", end="")


def print_program_header(program: str) -> None:
    """Render one program with the same visual grammar as the main Workbench."""
    print(paint("╔" + "═" * FRAME_WIDTH + "╗", Color.DEEP))
    print(paint("║" + " D O B E W O R K S ".center(FRAME_WIDTH) + "║", Color.CYAN))
    print(paint("║" + f" {spaced(program)} ".center(FRAME_WIDTH) + "║", Color.ICE))
    print(paint("╚" + "═" * FRAME_WIDTH + "╝", Color.DEEP))
    print()


def print_field(label: str, value: object, color: str = Color.PALE) -> None:
    text = "UNKNOWN" if value is None else str(value)
    lines = textwrap.wrap(
        text,
        width=FIELD_VALUE_WIDTH,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]
    for index, line in enumerate(lines):
        visible_label = label.upper() if index == 0 else ""
        print(
            "  "
            + paint(f"{visible_label:<{FIELD_LABEL_WIDTH}}", Color.MUTED)
            + paint(line, color)
        )


def print_mapping_table(rows: list[tuple[str, str, str]]) -> None:
    widths = (18, 34, 16)
    content_widths = tuple(width - 2 for width in widths)

    def border(left: str, middle: str, right: str) -> None:
        line = left + middle.join("─" * width for width in widths) + right
        print(paint(line, Color.DEEP))

    def cell_lines(value: str, width: int) -> list[str]:
        lines: list[str] = []
        for source_line in value.splitlines() or [""]:
            lines.extend(
                textwrap.wrap(
                    source_line,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                or [""]
            )
        return lines

    def row(values: tuple[str, str, str], colors: tuple[str, str, str]) -> None:
        wrapped = [
            cell_lines(value, width)
            for value, width in zip(values, content_widths)
        ]
        height = max(len(lines) for lines in wrapped)
        for line_index in range(height):
            pieces = [paint("│", Color.DEEP)]
            for lines, width, color in zip(wrapped, content_widths, colors):
                value = lines[line_index] if line_index < len(lines) else ""
                pieces.append(paint(f" {value:<{width}} ", color))
                pieces.append(paint("│", Color.DEEP))
            print("".join(pieces))

    border("┌", "┬", "┐")
    row(
        ("MAPPING", "DOBEWORKS RESULT", "DEGS DECISION"),
        (Color.CYAN, Color.CYAN, Color.CYAN),
    )
    border("├", "┼", "┤")
    for index, values in enumerate(rows):
        row(values, (Color.PALE, Color.PALE, Color.ICE))
        if index < len(rows) - 1:
            border("├", "┼", "┤")
    border("└", "┴", "┘")


def print_result(label: str, result: object) -> None:
    message = f"{label.upper()} · {result}"
    if len(message) + 2 > FRAME_WIDTH:
        raise ValueError(f"Result message is too wide for the Workbench: {message}")
    print()
    print(paint("┌" + "─" * FRAME_WIDTH + "┐", Color.DEEP))
    print(paint("│" + f" {message} ".center(FRAME_WIDTH) + "│", Color.CYAN))
    print(paint("└" + "─" * FRAME_WIDTH + "┘", Color.DEEP))


def print_path(label: str, path: Path) -> None:
    try:
        display = str(path.relative_to(ROOT))
    except ValueError:
        display = str(path)
    parts = display.split("/")
    lines: list[str] = []
    current = parts[0]
    for part in parts[1:]:
        candidate = f"{current}/{part}"
        if len(candidate) <= FRAME_WIDTH - 2:
            current = candidate
        else:
            lines.append(current)
            current = part
    lines.append(current)
    print()
    print(paint(label.upper(), Color.MUTED))
    for line in lines:
        print("  " + paint(line, Color.BLUE))


def print_evidence(path: Path) -> None:
    print_path("Evidence", path)


def unittest_failure_sections(output: str) -> list[str]:
    """Return complete unittest FAIL/ERROR sections without rewriting them."""
    pattern = re.compile(
        r"(?ms)^={70}\n(?:FAIL|ERROR): .*?"
        r"(?=^={70}\n|^-{70}\nRan \d+ tests?)"
    )
    return [match.group(0).rstrip("\n") for match in pattern.finditer(output)]


def print_verbatim_failures(name: str, output: str) -> None:
    sections = unittest_failure_sections(output)
    print()
    print(paint(f"{name.upper()} TEST FAILURE", Color.CYAN))
    print()
    if sections:
        for index, section in enumerate(sections):
            if index:
                print()
            print(paint(section, Color.PALE))
        return
    print(paint(output.rstrip() or "NO TEST OUTPUT WAS CAPTURED.", Color.PALE))


def new_run(label: str) -> Path:
    RUNS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    path = RUNS / f"{timestamp}-{label}"
    path.mkdir()
    write_json(path / "source-identity.json", source_identity())
    return path


def safe_remote(remote: str) -> str:
    parsed = urlsplit(remote)
    if parsed.scheme in {"http", "https", "ssh", "git"} and parsed.netloc:
        return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
    if "://" in remote or "::" in remote:
        return "LOCAL_OR_UNRECOGNIZED_REMOTE"
    scp = re.fullmatch(r"(?:[^@/]+@)?([^:/\s]+):(.+)", remote)
    if scp:
        return f"{scp[1]}:{scp[2].split('?', 1)[0].split('#', 1)[0]}"
    return "LOCAL_OR_UNRECOGNIZED_REMOTE"


def git_identity(repository: Path) -> dict[str, object]:
    commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    remote = subprocess.run(
        ["git", "-C", str(repository), "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    return {"commit": commit, "clean": not bool(status), "remote": safe_remote(remote)}


def source_identity() -> dict[str, object]:
    return {
        "dobeworks": git_identity(DOBEWORKS),
        "degs": git_identity(DEGS),
    }


def check_checkouts() -> None:
    for repository, entrypoint in (
        (DOBEWORKS, PHASE4 / "worker_core.py"),
        (DEGS, DEGS / "bin" / "engineering-gate.py"),
    ):
        if not (repository / ".git").exists() or not entrypoint.is_file():
            raise RuntimeError(
                f"A Git checkout is required at {repository}. "
                "See interface/README.md; --degs-root selects another DEGS clone."
            )
    source_identity()  # Check Git and origin before any demonstration writes.


def unique_object(pairs: list[tuple]) -> dict:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("Duplicate JSON keys in child output")
    return value


def finite_number(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("Nonfinite number in child output")
    return value


def run_json(
    command: list[str],
    run_dir: Path,
    label: str,
    expected_exits: tuple[int, ...],
    cwd: Path | None = None,
) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        command,
        cwd=cwd or ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=PROCESS_TIMEOUT_SECONDS,
    )
    (run_dir / f"{label}.stdout.json").write_text(completed.stdout, encoding="utf-8")
    (run_dir / f"{label}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.stderr:
        raise RuntimeError(f"{label} produced diagnostics; see {run_dir / f'{label}.stderr.txt'}")
    if completed.returncode not in expected_exits:
        raise RuntimeError(
            f"{label} exited {completed.returncode}; expected {expected_exits}. "
            f"See {run_dir / f'{label}.stderr.txt'}"
        )
    try:
        payload = json.loads(completed.stdout, object_pairs_hook=unique_object,
                             parse_float=finite_number, parse_constant=finite_number)
    except (ValueError, RecursionError) as error:
        raise RuntimeError(f"{label} did not return JSON: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned a non-object JSON value")
    return completed.returncode, payload


def observer_matches(record: dict[str, object], stale: bool) -> bool:
    snapshot = json.loads((PHASE4 / "fixtures" / "observer-snapshot.json").read_text(encoding="utf-8"))
    signals = {item["name"]: "UNKNOWN" if stale else item["value"] for item in snapshot["signals"]}
    return (
        record.get("schema_version") == "dobeworks.observer-record.v1"
        and record.get("role_id") == snapshot["role_id"]
        and record.get("status") == ("TELEMETRY_UNAVAILABLE" if stale else "VALIDATED")
        and record.get("freshness") == ("STALE" if stale else "FRESH")
        and record.get("signals") == signals
    )


def worker_matches(record: dict[str, object]) -> bool:
    return record.get("state") == "COMPLETED_UNACCEPTED" and record.get("promotion") == "NOT_PERFORMED"


def run_observer(run_dir: Path, stale: bool = False) -> dict[str, object]:
    label = "dobeworks-observer-stale" if stale else "dobeworks-observer-fresh"
    now = "2026-09-07T00:01:00Z" if stale else "2026-09-06T00:01:00Z"
    _, payload = run_json(
        [
            sys.executable,
            "-B",
            str(PHASE4 / "observer_core.py"),
            "--snapshot",
            str(PHASE4 / "fixtures" / "observer-snapshot.json"),
            "--policy",
            str(PHASE4 / "fixtures" / "observer-policy.json"),
            "--allowed-input-root",
            str(PHASE4 / "fixtures"),
            "--now",
            now,
        ],
        run_dir,
        label,
        (0,),
    )
    write_json(run_dir / f"{label}.json", payload)
    return payload


def run_worker(run_dir: Path) -> tuple[dict[str, object], Path]:
    staging_root = run_dir / "worker-stage"
    staging_root.mkdir()
    _, payload = run_json(
        [
            sys.executable,
            "-B",
            str(PHASE4 / "worker_core.py"),
            "--envelope",
            str(PHASE4 / "fixtures" / "job-envelope.json"),
            "--input",
            str(PHASE4 / "fixtures" / "input-records.json"),
            "--staging-root",
            str(staging_root),
            "--allowed-input-root",
            str(PHASE4 / "fixtures"),
            "--configuration-sha256",
            WORKER_CONFIGURATION_SHA256,
            "--now",
            "2026-09-06T00:01:00Z",
        ],
        run_dir,
        "dobeworks-worker",
        (0,),
    )
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError("DobeWorks Worker returned no job identity")
    handback = staging_root / job_id / "handback.json"
    if not handback.is_file():
        raise RuntimeError(f"DobeWorks Worker did not stage {handback}")
    return payload, handback


def replace_evidence_paths(value: object, evidence_path: str) -> object:
    if isinstance(value, dict):
        adapted = {}
        for key, child in value.items():
            if key == "evidence_path":
                adapted[key] = evidence_path
            elif key == "status" and child == "PASS":
                adapted[key] = "PENDING"
            else:
                adapted[key] = replace_evidence_paths(child, evidence_path)
        return adapted
    if isinstance(value, list):
        return [replace_evidence_paths(child, evidence_path) for child in value]
    return value


def observer_task(record: dict[str, object], evidence: Path, stale: bool) -> dict[str, object]:
    source = json.loads((DEGS / "fixtures" / "tier0-readonly-pass.json").read_text(encoding="utf-8"))
    task = replace_evidence_paths(copy.deepcopy(source), str(evidence))
    task.update(
        {
            "task_id": "DEGS-LOCAL-DOBEWORKS-OBSERVER-STALE" if stale else "DEGS-LOCAL-DOBEWORKS-OBSERVER-FRESH",
            "title": "Evaluate a current DobeWorks synthetic Observer record",
            "objective": "Record the DobeWorks Observer state through the current DEGS gate without authorizing action.",
            "scope": {
                "description": "Read one locally generated synthetic Observer record and preserve its availability state.",
                "read_only": True,
            },
            "non_goals": ["Operate a device", "Authorize remediation", "Treat synthetic evidence as production evidence"],
            "requirements": ["Fresh validated evidence may proceed; stale or unavailable evidence must stop."],
            "acceptance_criteria": ["The DEGS decision preserves the DobeWorks freshness boundary."],
            "selected_design": "Translate only the recorded Observer status, freshness, and evidence path.",
            "blast_radius": "One synthetic Observer record and one local DEGS evaluation.",
            "status": "BLOCKED" if stale else "READY_FOR_EXECUTION",
        }
    )
    if not observer_matches(record, stale):
        task["status"] = "FAILED"
    return task


def worker_task(record: dict[str, object], handback: Path) -> dict[str, object]:
    source = json.loads((DEGS / "fixtures" / "tier1-reversible-pass.json").read_text(encoding="utf-8"))
    task = replace_evidence_paths(copy.deepcopy(source), str(handback))
    task.update(
        {
            "task_id": "DEGS-LOCAL-DOBEWORKS-WORKER-HANDBACK",
            "title": "Evaluate a current DobeWorks synthetic Worker handback",
            "objective": "Preserve the unaccepted state of a staged DobeWorks Worker result through the current DEGS gate.",
            "scope": {
                "description": "Stage one bounded synthetic Worker result and evaluate its recorded handback state.",
                "read_only": False,
            },
            "non_goals": ["Accept output", "Promote output", "Authorize subsequent work"],
            "requirements": ["A COMPLETED_UNACCEPTED result must remain stopped pending a separate authorized acceptance step."],
            "acceptance_criteria": ["DEGS returns BLOCKED for the staged unaccepted result."],
            "assumptions": ["The included DobeWorks fixture remains synthetic and bounded."],
            "selected_design": "Pass the staged handback state and evidence path to a Tier 1 DEGS record.",
            "affected_files": [str(handback), str(handback.with_name("result.json"))],
            "target_identity": str(handback),
            "blast_radius": "One disposable local staging directory.",
            "stop_conditions": ["DobeWorks does not return COMPLETED_UNACCEPTED.", "Any promotion is attempted."],
            "status": "BLOCKED" if worker_matches(record) else "FAILED",
        }
    )
    return task


def run_degs_task(task: dict[str, object], run_dir: Path, label: str) -> dict[str, object]:
    task_path = run_dir / f"{label}.task.json"
    write_json(task_path, task)
    validate_exit, validate = run_json(
        [sys.executable, "-B", str(DEGS / "bin" / "engineering-gate.py"), "validate", str(task_path), "--json"],
        run_dir,
        f"{label}.validate",
        (0, 4),
    )
    evaluate_exit, evaluate = run_json(
        [sys.executable, "-B", str(DEGS / "bin" / "engineering-gate.py"), "evaluate", str(task_path), "--json"],
        run_dir,
        f"{label}.evaluate",
        (0, 1, 2, 3, 4),
    )
    return {
        "task": str(task_path),
        "validate_exit": validate_exit,
        "validate_decision": validate.get("decision"),
        "evaluate_exit": evaluate_exit,
        "evaluate_decision": evaluate.get("decision"),
        "evaluate": evaluate,
    }


def integration_checks(fresh, stale, worker, fresh_degs, stale_degs, worker_degs) -> list[dict]:
    return [
        {
            "name": "fresh-observer-record",
            "source_status": fresh.get("status"),
            "source_freshness": fresh.get("freshness"),
            "degs_decision": fresh_degs["evaluate_decision"],
            "passed": observer_matches(fresh, False)
            and fresh_degs["validate_exit"] == 0
            and fresh_degs["validate_decision"] == "PASS"
            and fresh_degs["evaluate_exit"] == 0
            and fresh_degs["evaluate_decision"] == "PASS",
        },
        {
            "name": "stale-observer-record",
            "source_status": stale.get("status"),
            "source_freshness": stale.get("freshness"),
            "degs_decision": stale_degs["evaluate_decision"],
            "passed": observer_matches(stale, True)
            and stale_degs["validate_exit"] == 0
            and stale_degs["validate_decision"] == "PASS"
            and stale_degs["evaluate_exit"] == 2
            and stale_degs["evaluate_decision"] == "BLOCKED",
        },
        {
            "name": "unaccepted-worker-handback",
            "source_state": worker.get("state"),
            "source_promotion": worker.get("promotion"),
            "degs_decision": worker_degs["evaluate_decision"],
            "passed": worker_matches(worker)
            and worker_degs["validate_exit"] == 0
            and worker_degs["validate_decision"] == "PASS"
            and worker_degs["evaluate_exit"] == 2
            and worker_degs["evaluate_decision"] == "BLOCKED",
        },
    ]


def run_integration() -> int:
    print_program_header("Current-Pair Integration")
    run_dir = new_run("current-pair-integration")
    fresh = run_observer(run_dir)
    stale = run_observer(run_dir, stale=True)
    worker, handback = run_worker(run_dir)
    fresh_evidence = run_dir / "dobeworks-observer-fresh.json"
    stale_evidence = run_dir / "dobeworks-observer-stale.json"
    fresh_degs = run_degs_task(observer_task(fresh, fresh_evidence, False), run_dir, "observer-fresh")
    stale_degs = run_degs_task(observer_task(stale, stale_evidence, True), run_dir, "observer-stale")
    worker_degs = run_degs_task(worker_task(worker, handback), run_dir, "worker-unaccepted")
    checks = integration_checks(fresh, stale, worker, fresh_degs, stale_degs, worker_degs)
    summary = {
        "schema_version": "local-command-center.integration.v1",
        "source_identity": source_identity(),
        "contract": {
            "fresh_validated_observer": "PASS",
            "stale_unavailable_observer": "BLOCKED",
            "completed_unaccepted_worker": "BLOCKED",
        },
        "checks": checks,
        "result": "PASS" if all(check["passed"] for check in checks) else "FAIL",
    }
    write_json(run_dir / "integration-summary.json", summary)
    print_mapping_table(
        [
            (
                "FRESH OBSERVER",
                f"{fresh.get('status')} · {fresh.get('freshness')}",
                str(fresh_degs["evaluate_decision"]),
            ),
            (
                "STALE OBSERVER",
                f"{stale.get('status')} · {stale.get('freshness')}",
                str(stale_degs["evaluate_decision"]),
            ),
            (
                "WORKER HANDBACK",
                f"{worker.get('state')}\nPROMOTION · {worker.get('promotion')}",
                str(worker_degs["evaluate_decision"]),
            ),
        ]
    )
    print_result("Current-Pair Integration", summary["result"])
    print_evidence(run_dir)
    return 0 if summary["result"] == "PASS" else 1


def show_observer(stale: bool = False) -> int:
    print_program_header("Observer — Stale" if stale else "Observer — Fresh")
    run_dir = new_run("observer-stale" if stale else "observer-fresh")
    payload = run_observer(run_dir, stale=stale)
    self_health = payload.get("self_health")
    signals = payload.get("signals")
    collector = self_health.get("collector_status") if isinstance(self_health, dict) else None
    failure = self_health.get("failure_status") if isinstance(self_health, dict) else None
    known_signals = (
        sum(value != "UNKNOWN" for value in signals.values())
        if isinstance(signals, dict)
        else 0
    )
    signal_count = len(signals) if isinstance(signals, dict) else 0
    print_field("Role", payload.get("role_id"))
    print_field("Status", payload.get("status"), Color.ICE)
    print_field("Freshness", payload.get("freshness"), Color.ICE)
    print_field("Observed At", payload.get("observed_at"))
    print_field("Collector", collector)
    print_field("Failure State", failure)
    print_field("Signals Available", f"{known_signals} OF {signal_count}")
    passed = observer_matches(payload, stale)
    print_result("Observer Record", payload.get("status") if passed else "FAIL")
    print_evidence(run_dir)
    return 0 if passed else 1


def show_worker() -> int:
    print_program_header("Worker — Stage Unaccepted Result")
    run_dir = new_run("worker")
    payload, handback = run_worker(run_dir)
    print_field("Job", payload.get("job_id"))
    print_field("State", payload.get("state"), Color.ICE)
    print_field("Promotion", payload.get("promotion"), Color.ICE)
    print_field("Attempts", payload.get("attempts"))
    print_field("Retry", payload.get("retry"))
    print_field("Reason", payload.get("reason"))
    print_path("Staged Handback", handback)
    passed = worker_matches(payload)
    print_result("Worker Result", payload.get("state") if passed else "FAIL")
    print_evidence(run_dir)
    return 0 if passed else 1


def show_degs_fixture(name: str) -> int:
    expectations = {
        "tier2-complete-pass.json": (0, "PASS"),
        "tier2-missing-rollback-blocked.json": (2, "BLOCKED"),
    }
    if name not in expectations:
        raise ValueError("Choose one of the two bundled DEGS demonstration fixtures.")
    program = {
        "tier2-complete-pass.json": "Complete Tier 2 record",
        "tier2-missing-rollback-blocked.json": "Missing rollback record",
    }.get(name, Path(name).stem.replace("-", " "))
    print_program_header(program)
    run_dir = new_run(f"degs-{Path(name).stem}")
    fixture = DEGS / "fixtures" / name
    exit_code, payload = run_json(
        [sys.executable, "-B", str(DEGS / "bin" / "engineering-gate.py"), "evaluate", str(fixture), "--json"],
        run_dir,
        "degs-evaluate",
        (0, 1, 2, 3, 4),
    )
    task = json.loads(fixture.read_text(encoding="utf-8"))
    rules = payload.get("applicable_rule_ids")
    unmet = payload.get("unmet_requirements")
    print_field("Task", task.get("task_id"))
    print_field("Decision", payload.get("decision"), Color.ICE)
    print_field("Risk Tier", payload.get("risk_tier"))
    print_field("Authority Lane", payload.get("authority_lane"))
    print_field("Rules Evaluated", len(rules) if isinstance(rules, list) else 0)
    print_field("Unmet Requirements", len(unmet) if isinstance(unmet, list) else 0)
    if isinstance(unmet, list) and unmet and isinstance(unmet[0], dict):
        print_field("Gate Message", unmet[0].get("message"), Color.ICE)
    print_field("Gate Exit", exit_code)
    print_result("Gate Decision", payload.get("decision"))
    passed = (exit_code, payload.get("decision")) == expectations[name]
    if not passed:
        print_result("Demonstration", "FAIL")
    print_evidence(run_dir)
    return 0 if passed else 1


def core_test_commands() -> dict:
    return {
        "dobeworks": ([
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            str(PHASE4),
            "-p",
            "test_*_core.py",
            "-v",
        ], DOBEWORKS),
        "degs": ([
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            str(DEGS / "tests"),
            "-v",
        ], DEGS),
    }


def test_execution_summary(output: str, exit_code: int) -> dict:
    count = re.search(r"(?m)^Ran (\d+) tests? in ", output)
    success = re.search(r"(?m)^OK(?: \(([^\n]*)\))?$", output)
    skipped = re.search(r"(?:^|, )skipped=(\d+)(?:,|$)", success[1] or "") if success else None
    total = int(count[1]) if count else None
    executed = total - (int(skipped[1]) if skipped else 0) if total is not None else 0
    return {"exit": exit_code, "tests": total, "executed": executed,
            "passed": exit_code == 0 and success is not None and executed > 0}


def verify_cores() -> int:
    print_program_header("Core Verification")
    run_dir = new_run("core-verification")
    results = {}
    test_counts: dict[str, int | None] = {}
    test_outputs: dict[str, str] = {}
    for name, (command, working_directory) in core_test_commands().items():
        print(paint(f"RUNNING {name.upper()} CORE TESTS.", Color.CYAN), flush=True)
        completed = subprocess.run(
            command,
            cwd=working_directory,
            check=False,
            capture_output=True,
            text=True,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
        (run_dir / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (run_dir / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
        output = completed.stdout + completed.stderr
        test_outputs[name] = output
        results[name] = test_execution_summary(output, completed.returncode)
        test_counts[name] = results[name]["tests"]
    summary = {
        "source_identity": source_identity(),
        "results": results,
        "result": "PASS" if all(item["passed"] for item in results.values()) else "FAIL",
    }
    write_json(run_dir / "verification-summary.json", summary)
    print()
    for name in ("dobeworks", "degs"):
        result = "PASS" if results[name]["passed"] else "FAIL"
        count = test_counts[name]
        detail = f"{result} · {count} TESTS" if count is not None else result
        print_field(f"{name} Core", detail, Color.ICE)
    for name in ("dobeworks", "degs"):
        if not results[name]["passed"]:
            print_verbatim_failures(name, test_outputs[name])
    print_result("Core Verification", summary["result"])
    print_evidence(run_dir)
    return 0 if summary["result"] == "PASS" else 1


def open_runs() -> int:
    print_program_header("Run Evidence")
    RUNS.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["open", str(RUNS)], check=True, timeout=10)
    print_path("Location", RUNS)
    print_result("Evidence Archive", "OPEN")
    return 0


def print_header() -> None:
    speaker, voice, attribution = choose_workbench_voice()
    voice_color = {
        "ELIZA": Color.CYAN,
        "COLOSSUS": Color.ICE,
        "GUARDIAN": Color.BLUE,
    }[speaker]
    if sys.stdout.isatty():
        print("\033]0;DobeWorks\007", end="")
    print(paint("╔" + "═" * FRAME_WIDTH + "╗", Color.DEEP))
    print(paint("║" + " D O B E W O R K S ".center(FRAME_WIDTH) + "║", Color.CYAN))
    print(paint("╠" + "═" * FRAME_WIDTH + "╣", Color.DEEP))
    print(paint("║" + f" “{voice}” ".center(FRAME_WIDTH) + "║", voice_color))
    print(paint("║" + f" {attribution} ".center(FRAME_WIDTH) + "║", Color.MUTED))
    print(paint("╚" + "═" * FRAME_WIDTH + "╝", Color.DEEP))
    print(paint("PLEASE GO ON.", Color.CYAN))
    print()


def pause() -> None:
    try:
        input(paint("\nWHEN YOU ARE READY, PRESS RETURN.", Color.BLUE) + " ")
    except EOFError:
        pass


def menu() -> int:
    actions = [
        ("Run current-pair integration", run_integration),
        ("DobeWorks Observer — fresh", lambda: show_observer(False)),
        ("DobeWorks Observer — stale", lambda: show_observer(True)),
        ("DobeWorks Worker — stage unaccepted result", show_worker),
        ("DEGS — complete Tier 2 record", lambda: show_degs_fixture("tier2-complete-pass.json")),
        ("DEGS — missing rollback record", lambda: show_degs_fixture("tier2-missing-rollback-blocked.json")),
        ("Verify both current cores", verify_cores),
        ("Open run evidence", open_runs),
    ]
    choices = {key: action for index, (_, action) in enumerate(actions, 1)
               for key in (str(index), f"{index:02d}")}
    while True:
        clear_screen()
        print_header()
        for index, (label, _) in enumerate(actions, start=1):
            print(f"  {paint(f'{index:02d}', Color.ICE)}  {paint(label.upper(), Color.PALE)}")
        print(f"\n  {paint('00', Color.ICE)}  {paint('CLOSE INTERFACE', Color.PALE)}")
        try:
            choice = input(paint("\nWHICH PROGRAM SHALL WE RUN? >", Color.CYAN) + " ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in {"0", "00", "q", "quit", "exit"}:
            return 0
        action = choices.get(choice)
        if action is None:
            print(paint("THAT PROGRAM IS NOT AVAILABLE. CHOOSE A LISTED NUMBER.", Color.BLUE))
            pause()
            continue
        clear_screen()
        try:
            action()
        except Exception as error:  # The menu must retain a visible failure report.
            print_program_header("Program Error")
            print_field("Error", error, Color.ICE)
            print_result("Program", "ERROR")
        pause()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--degs-root", type=Path, default=DEGS, help="DEGS Git checkout (default: sibling DEGS)")
    parser.add_argument("--runs-root", type=Path, default=RUNS, help="local output directory (default: interface/Runs)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("menu")
    subparsers.add_parser("integration")
    observer_parser = subparsers.add_parser("observer")
    observer_parser.add_argument("--stale", action="store_true")
    subparsers.add_parser("worker")
    fixture_parser = subparsers.add_parser("degs")
    fixture_parser.add_argument("fixture")
    subparsers.add_parser("verify")
    return parser.parse_args(argv)


def run_command(argv: list[str] | None = None) -> int:
    global DEGS, RUNS
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    DEGS = args.degs_root.expanduser().resolve()
    RUNS = args.runs_root.expanduser().resolve()
    check_checkouts()
    if args.command == "menu":
        try:
            return menu()
        finally:
            if sys.stdout.isatty():
                print(Color.RESET, end="")
    if args.command == "integration":
        return run_integration()
    if args.command == "observer":
        return show_observer(args.stale)
    if args.command == "worker":
        return show_worker()
    if args.command == "degs":
        return show_degs_fixture(args.fixture)
    if args.command == "verify":
        return verify_cores()
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    try:
        return run_command(argv)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print_program_header("Program Error")
        print_field("Error", error, Color.ICE)
        print_result("Program", "ERROR")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
