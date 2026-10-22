"""Fixed public mission harness. Released engines are imported without alteration."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "stage_vendor"
PHASE4 = VENDOR / "DobeWorks/contexts/operational-system/software/phase4"
NASA = VENDOR / "nasa-fprime"
CORE_RECORD = VENDOR / "core-verification.json"
TRANSCRIPTION_RECORD = ROOT / "stage_assets/transcription-check.json"
SCENARIOS = ("clean", "stale", "missing", "unresolved", "altered", "rbar", "rbar-fixed")
PACKET = b"DOBEWORKS-MISSION-001|TEMP_C=21.5|VOLTAGE_V=3.30|SEQ=7\n"
NOW = "2026-09-06T00:01:00Z"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def check_sources():
    sources = json.loads((VENDOR / "sources.json").read_text())
    for name, record in sources.items():
        for path, expected in record["files"].items():
            if digest((VENDOR / name / path).read_bytes()) != expected:
                raise RuntimeError("Pinned engine identity mismatch")
    nasa = json.loads((NASA / "provenance.json").read_text())
    for path, record in nasa["files"].items():
        if digest((NASA / path).read_bytes()) != record["sha256"]:
            raise RuntimeError("Pinned NASA source identity mismatch")
    return sources, nasa


def transcription_copy(source):
    before, after = b"polynomial = 0xEDB88320;", b"polynomial = 0xEDB88321;"
    if source.count(before) != 1:
        raise RuntimeError("The transcription exercise no longer matches the pinned source")
    return source.replace(before, after)


def compile_tables(source):
    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / "TableGenerator.c").write_bytes(source)
        commands = [["cc", "-std=c99", "-O2", "TableGenerator.c", "-o", "generator"], ["./generator"]]
        for command in commands:
            result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=15, check=True)
            if result.stderr:
                raise RuntimeError("NASA generator produced unexpected diagnostics")
        values = re.findall(r"0x([0-9A-Fa-f]{8})", result.stdout)
        if len(values) != 1024:
            raise RuntimeError("The compiled generator did not emit 1024 values")
        return [int(x, 16) for x in values], commands


def prepare_transcription():
    check_sources()
    source = (NASA / "TableGenerator.c").read_bytes()
    candidate = transcription_copy(source)
    table, commands = compile_tables(candidate)
    TRANSCRIPTION_RECORD.write_bytes(encode({"source_sha256": digest(source), "candidate_sha256": digest(candidate),
        "modified_demo_copy": True, "commands": commands, "exit": 0, "stderr": "", "tables": table}))
    source_behavior(candidate)


def prepare_nasa():
    check_sources()
    values, _ = compile_tables((NASA / "TableGenerator.c").read_bytes())
    reference = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{8})", (NASA / "Crc32.cpp").read_text())]
    if values != reference:
        raise RuntimeError("NASA-generated tables differ from pinned reference")
    (NASA / "tables.json").write_bytes(encode(values))
    if crc(b"123456789") != "CBF43926":
        raise RuntimeError("CRC known-vector check failed")
    prepare_transcription()


def crc(data):
    table = json.loads((NASA / "tables.json").read_text())
    reference = [int(value, 16) for value in re.findall(r"0x([0-9A-Fa-f]{8})", (NASA / "Crc32.cpp").read_text())]
    if len(table) != 1024 or table != reference:
        raise RuntimeError("Generated NASA tables changed after verification")
    return crc_with_table(data, table)


def crc_with_table(data, table):
    value = 0xFFFFFFFF
    for byte in data:
        value = (value >> 8) ^ table[(value ^ byte) & 255]
    return f"{value ^ 0xFFFFFFFF:08X}"


def source_behavior(candidate):
    source = (NASA / "TableGenerator.c").read_bytes()
    changed = candidate == transcription_copy(source)
    if candidate != source and not changed:
        raise RuntimeError("No compiled behavior evidence exists for this source")
    commands = [["cc", "-std=c99", "-O2", "TableGenerator.c", "-o", "generator"], ["./generator"]]
    actual = crc(b"123456789")
    packet_crc = crc(PACKET)
    if changed:
        record = json.loads(TRANSCRIPTION_RECORD.read_text())
        if (record["source_sha256"] != digest(source) or record["candidate_sha256"] != digest(candidate)
                or record["modified_demo_copy"] is not True or record["exit"] != 0 or record["stderr"]
                or record["commands"] != commands):
            raise RuntimeError("Compiled transcription evidence has a different identity")
        # Recheck all retained C output values against the fixed, altered polynomial.
        expected = []
        for i in range(256):
            value = i
            for _ in range(8):
                value = (value >> 1) ^ (0xEDB88321 if value & 1 else 0)
            expected.append(value)
        for row in range(3):
            expected.extend((value >> 8) ^ expected[value & 255] for value in expected[row * 256:(row + 1) * 256])
        if record["tables"] != expected:
            raise RuntimeError("Retained compiled tables differ from the candidate polynomial")
        actual = crc_with_table(b"123456789", record["tables"])
        packet_crc = crc_with_table(PACKET, record["tables"])
    line = next(i for i, text in enumerate(source.decode().splitlines(), 1) if "polynomial =" in text)
    return {"source_sha256": digest(candidate), "line": line, "changed_characters": int(changed),
            "polynomial": "0xEDB88321" if changed else "0xEDB88320", "compiled_at_preparation": True,
            "commands": commands, "compile_exit": 0, "stderr": "", "test_input": "123456789",
            "candidate_packet_crc32": packet_crc, "receiver_expected_crc32": crc(PACKET),
            "expected_crc32": "CBF43926", "actual_crc32": actual, "result": "PASS" if actual == "CBF43926" else "FAIL"}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def stage_inventory(directory, artifacts):
    sys.path.insert(0, str(PHASE4))
    import worker_core
    inputs = {"schema_version": worker_core.INPUT_SCHEMA, "records": [
        {"path": "inventory/" + name + ".md", "kind": "markdown",
         "bytes": len(f"Source: {name}\nBytes: {len(data)}\nSHA256: {digest(data)}\n".encode())}
        for name, data in artifacts.items()]}
    raw = encode(inputs)
    envelope = json.loads((PHASE4 / "fixtures/job-envelope.json").read_text())
    envelope.update(job_id="job-mission-001", input_sha256=digest(raw))
    expected = worker_core.SyntheticInventoryRunner()(envelope, inputs)
    envelope["expected_output_sha256"] = digest(encode(expected))
    (directory / "input.json").write_bytes(raw)
    (directory / "envelope.json").write_bytes(encode(envelope))
    stage = directory / "staged"
    stage.mkdir()
    worker = worker_core.WorkerCore(envelope["configuration_sha256"], directory)
    result = worker.execute(directory / "envelope.json", directory / "input.json", stage, NOW)
    if result.get("state") != "COMPLETED_UNACCEPTED" or result.get("promotion") != "NOT_PERFORMED":
        raise RuntimeError("Worker did not preserve the unaccepted result")
    return result, inputs, envelope


def verify_cores():
    sources, _ = check_sources()
    ui = load_module("stage_public_interface", VENDOR / "DobeWorks/interface/command_center.py")
    ui.DEGS = VENDOR / "DEGS"
    results = {}
    for name, (command, directory) in ui.core_test_commands().items():
        completed = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=ui.PROCESS_TIMEOUT_SECONDS)
        results[name] = {**ui.test_execution_summary(completed.stdout + completed.stderr, completed.returncode),
                         "command": command, "stdout": completed.stdout, "stderr": completed.stderr}
    return {"schema_version": "dobeworks.stage.core-tests.v1", "source_identity": sources,
            "python": sys.version, "results": results,
            "result": "PASS" if all(item["passed"] for item in results.values()) else "FAIL",
            "operational_authority": "NONE"}


def read_core_verification():
    sources, _ = check_sources()
    report = json.loads(CORE_RECORD.read_text())
    ui = load_module("stage_public_interface", VENDOR / "DobeWorks/interface/command_center.py")
    if (report.get("schema_version") != "dobeworks.stage.core-tests.v1"
            or report.get("source_identity") != sources or report.get("operational_authority") != "NONE"
            or set(report.get("results", {})) != {"dobeworks", "degs"}):
        raise RuntimeError("Prepared core verification has a different identity")
    for item in report["results"].values():
        summary = ui.test_execution_summary(item["stdout"] + item["stderr"], item["exit"])
        if any(item.get(key) != value for key, value in summary.items()):
            raise RuntimeError("Prepared core verification does not match the test output")
    expected = "PASS" if all(item["passed"] for item in report["results"].values()) else "FAIL"
    if report.get("result") != expected:
        raise RuntimeError("Prepared core verification has an inconsistent result")
    return report


def mission_package(scenario, sources, nasa):
    """Exact packet bytes shared by execution and the read-only package viewer."""
    if scenario not in SCENARIOS:
        raise ValueError("Unknown mission scenario")
    if scenario.startswith("rbar"):
        artifacts = {
            "handoff/guidance-note.md": "Required guidance notation: R\u0305.\n".encode(),
            "handoff/context.md": b"Teaching reconstruction of the notation loss described by NASA for Mariner 1. Not historical flight code. Preserve the required overbar through this handoff.\n",
            "handoff/acceptance.md": b"Completed work remains staged. An open notation finding blocks readiness. Closing the finding requires check evidence; acceptance is separate.\n",
            "evidence/reference.md": b"NASA: https://science.nasa.gov/mission/mariner-1/\nNASA records an omitted overbar and a guidance antenna fault. This exercise models notation preservation, not flight dynamics.\n"}
        expected = {name: digest(data) for name, data in artifacts.items()}
        if scenario == "rbar":
            artifacts["handoff/guidance-note.md"] = artifacts["handoff/guidance-note.md"].replace("\u0305".encode(), b"")
        return artifacts, expected
    artifacts = {"mission/telemetry.md": PACKET,
                 "source/TableGenerator.c": (NASA / "TableGenerator.c").read_bytes(),
                 "source/Crc32.cpp": (NASA / "Crc32.cpp").read_bytes(),
                 "source/LICENSE.txt": (NASA / "LICENSE.txt").read_bytes(),
                 "mission/plan.md": encode({"mission": "DEMO-001", "required_crc32": "B8BD3EAE", "next_stage": "INDEPENDENT_REVIEW"}),
                 "mission/context.md": encode({"component": "TM-CRC-001: NASA/JPL F prime CRC32 source handoff",
                     "requirement": "Retain the exact sequence-7 telemetry bytes and reject missing or changed package evidence.",
                     "impact": "Ground telemetry integrity review; one component of a larger fictional mission.",
                     "limits": "No flight guidance, vehicle control or launch authority.",
                     "source_commits": {name: item["commit"] for name, item in sources.items()}}),
                 "evidence/nasa-source.md": nasa["files"]["TableGenerator.c"]["sha256"].encode()}
    expected_manifest = {name: digest(data) for name, data in artifacts.items()}
    if scenario == "missing":
        del artifacts["evidence/nasa-source.md"]
    if scenario == "altered":
        artifacts["source/TableGenerator.c"] = transcription_copy(artifacts["source/TableGenerator.c"])
    return artifacts, expected_manifest


def run_mission(scenario):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown mission scenario")
    sources, nasa = check_sources()
    if crc(b"123456789") != "CBF43926":
        raise RuntimeError("NASA table control failed")
    ui = load_module("stage_public_interface", VENDOR / "DobeWorks/interface/command_center.py")
    ui.DEGS = VENDOR / "DEGS"
    with tempfile.TemporaryDirectory(prefix="mission-") as temporary:
        directory = Path(temporary)
        telemetry = PACKET
        artifacts, expected_manifest = mission_package(scenario, sources, nasa)
        expected_crc = "B8BD3EAE"
        if scenario.startswith("rbar"):
            telemetry = artifacts["handoff/guidance-note.md"]
            expected_crc = crc("Required guidance notation: R\u0305.\n".encode())
        worker, inventory, envelope = stage_inventory(directory, artifacts)
        ui.RUNS = directory
        observer = ui.run_observer(directory, stale=scenario == "stale")
        if not ui.observer_matches(observer, scenario == "stale"):
            raise RuntimeError("Observer result did not match the fixed scenario")
        task = ui.observer_task(observer, Path("evidence/observer.json"), scenario == "stale")
        actual_crc = crc(telemetry)
        actual_manifest = {name: digest(data) for name, data in artifacts.items()}
        behavior = source_behavior(artifacts.get("source/TableGenerator.c", (NASA / "TableGenerator.c").read_bytes()))
        intact = actual_manifest == expected_manifest and actual_crc == expected_crc and behavior["result"] == "PASS"
        task.update(task_id="DEGS-STAGE-MISSION-001", title="Fictional mission packet handoff",
                    objective="Inspect a fictional packet; no launch or operational authority.")
        task["scope"]["description"] = "Read the Observer, source-identity comparison and CRC known-answer result for this handoff."
        task["requirements"] = ["Fresh validated observations are required.",
            "Retain exact source identities and required evidence.", "The candidate CRC32 component must reproduce 123456789 -> CBF43926."]
        task["acceptance_criteria"] = ["Preserve a stop while any required check or unresolved finding is open."]
        task["selected_design"] = "Translate the recorded Observer and exhibit test outcomes into a read-only readiness record."
        (directory / "source-check.json").write_bytes(encode(behavior))
        task["verification"] = {"status": behavior["result"], "evidence_path": str(directory / "source-check.json")}
        if not intact:
            task["status"] = "BLOCKED"
            task["unresolved_items"] = ["The candidate source or its known-answer test differs from the published baseline."]
        if scenario == "unresolved":
            task["unresolved_items"] = ["MISSION-001: the independent checksum review remains open."]
        notation = None
        if scenario.startswith("rbar"):
            note = artifacts["handoff/guidance-note.md"]
            intact = digest(note) == expected_manifest["handoff/guidance-note.md"]
            notation = {"required": "R\u0305", "received": "R\u0305" if intact else "R", "result": "PASS" if intact else "FAIL",
                        "evidence_sha256": digest(note), "detector": "Exact match to the supplied reference note; not a guidance-equation verifier."}
            (directory / "notation-check.json").write_bytes(encode(notation))
            task.update(title="Preserve the R-bar finding at a handoff", status="READY_FOR_EXECUTION",
                        requirements=["Preserve the required R-bar notation.", "An unresolved finding must remain a stop across translation."],
                        unresolved_items=[], warnings=[{"severity": "NONE" if intact else "CRITICAL", "resolved": intact,
                            "status": "RESOLVED" if intact else "UNRESOLVED", "evidence_path": str(directory / "notation-check.json")}])
            task["scope"]["description"] = "Read a teaching notation check and preserve its warning state. No flight operation or promotion."
            task["verification"] = {"status": notation["result"], "evidence_path": str(directory / "notation-check.json")}
        (directory / "task.json").write_bytes(encode(task))
        gate = ui.run_degs_task(task, directory, "mission")
        if gate["validate_exit"] != 0 or gate["validate_decision"] != "PASS":
            raise RuntimeError("Scenario task failed the real DEGS schema")
        expected_decision = "PASS" if scenario in {"clean", "rbar-fixed"} else "BLOCKED"
        expected_exit = 0 if expected_decision == "PASS" else 2
        if (gate["evaluate_exit"], gate["evaluate_decision"]) != (expected_exit, expected_decision):
            raise RuntimeError("Scenario produced an unexpected real gate decision")
        report = {"schema_version": "dobeworks.stage.mission.v1", "scenario": scenario,
                  "mission": "DEMO-001", "simulation": True, "operational_authority": "NONE",
                  "source_identity": sources, "nasa": {"repository": "https://github.com/nasa/fprime", "commit": nasa["upstream_commit"], "known_vector": "CBF43926", "generated_values_checked": 1024},
                  "packet": {"text": telemetry.decode(), "expected_crc32": expected_crc, "actual_crc32": actual_crc,
                             "integrity": "PASS" if intact else "BLOCKED", "expected_manifest": expected_manifest,
                             "actual_manifest": actual_manifest},
                  "worker": worker, "worker_input": inventory, "worker_envelope": envelope,
                  "source_behavior": behavior,
                  "package_sha256": digest(encode(actual_manifest)),
                  "observer": observer, "degs_task": task, "degs": gate["evaluate"],
                  "degs_exit": gate["evaluate_exit"], "handoff": "READY_FOR_REVIEW" if expected_decision == "PASS" else "HOLD"}
        if notation:
            report["notation_check"] = notation
            # This separate evaluation illustrates a broken adapter; it never drives the actual handoff.
            lost = dict(task, warnings=[])
            trial = ui.run_degs_task(lost, directory, "completion-only")
            if (trial["validate_exit"], trial["evaluate_exit"], trial["evaluate_decision"]) != (0, 0, "PASS"):
                raise RuntimeError("Completion-only teaching comparison did not match the fixed record")
            report["translation_comparison"] = {"changed_field": "warnings", "completion_only_task": lost,
                "completion_only_decision": trial["evaluate"], "actual_execution": "NONE",
                "same_candidate_sha256": digest(encode(actual_manifest))}
        # Temporary execution paths are not part of the portable public evidence.
        return json.loads(json.dumps(report).replace(str(directory), "evidence"))


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare-transcription"]:
        prepare_transcription()
        print("Modified demo source compiled; one-character behavior evidence retained")
    elif sys.argv[1:] == ["--prepare"]:
        prepare_nasa()
        CORE_RECORD.write_bytes(encode(verify_cores()))
        report = read_core_verification()
        if report["result"] != "PASS":
            raise RuntimeError("Core verification failed; inspect the retained test output")
        print("Pinned sources, NASA table generator and both core suites verified")
    elif sys.argv[1:] == ["--verify-cores"]:
        print(json.dumps(verify_cores(), sort_keys=True, separators=(",", ":")))
    elif sys.argv[1:] == ["--read-core-verification"]:
        print(json.dumps(read_core_verification(), sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(run_mission(sys.argv[1]), sort_keys=True, separators=(",", ":")))
