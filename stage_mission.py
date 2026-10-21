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
SCENARIOS = ("clean", "stale", "missing", "unresolved", "altered")
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


def prepare_nasa():
    check_sources()
    with tempfile.TemporaryDirectory() as directory:
        binary = Path(directory) / "generator"
        for command in (["cc", "-std=c99", "-O2", str(NASA / "TableGenerator.c"), "-o", str(binary)], [str(binary)]):
            result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=True)
            if result.stderr:
                raise RuntimeError("NASA generator produced unexpected diagnostics")
        values = re.findall(r"0x([0-9A-Fa-f]{8})", result.stdout)
        reference = re.findall(r"0x([0-9A-Fa-f]{8})", (NASA / "Crc32.cpp").read_text())
        if len(values) != 1024 or [int(x, 16) for x in values] != [int(x, 16) for x in reference]:
            raise RuntimeError("NASA-generated tables differ from pinned reference")
        (NASA / "tables.json").write_bytes(encode([int(x, 16) for x in values]))
    if crc(b"123456789") != "CBF43926":
        raise RuntimeError("CRC known-vector check failed")


def crc(data):
    table = json.loads((NASA / "tables.json").read_text())
    reference = [int(value, 16) for value in re.findall(r"0x([0-9A-Fa-f]{8})", (NASA / "Crc32.cpp").read_text())]
    if len(table) != 1024 or table != reference:
        raise RuntimeError("Generated NASA tables changed after verification")
    value = 0xFFFFFFFF
    for byte in data:
        value = (value >> 8) ^ table[(value ^ byte) & 255]
    return f"{value ^ 0xFFFFFFFF:08X}"


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
        artifacts["source/TableGenerator.c"] += b"\n/* changed during fictional handoff */\n"
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
        worker, inventory, envelope = stage_inventory(directory, artifacts)
        ui.RUNS = directory
        observer = ui.run_observer(directory, stale=scenario == "stale")
        if not ui.observer_matches(observer, scenario == "stale"):
            raise RuntimeError("Observer result did not match the fixed scenario")
        task = ui.observer_task(observer, Path("evidence/observer.json"), scenario == "stale")
        actual_crc = crc(telemetry)
        actual_manifest = {name: digest(data) for name, data in artifacts.items()}
        intact = actual_manifest == expected_manifest and actual_crc == "B8BD3EAE"
        task.update(task_id="DEGS-STAGE-MISSION-001", title="Fictional mission packet handoff",
                    objective="Inspect a fictional packet; no launch or operational authority.")
        if not intact:
            task["status"] = "BLOCKED"
        if scenario == "unresolved":
            task["unresolved_items"] = ["MISSION-001: the independent checksum review remains open."]
        (directory / "task.json").write_bytes(encode(task))
        gate = ui.run_degs_task(task, directory, "mission")
        if gate["validate_exit"] != 0 or gate["validate_decision"] != "PASS":
            raise RuntimeError("Scenario task failed the real DEGS schema")
        expected_decision = "PASS" if scenario == "clean" else "BLOCKED"
        expected_exit = 0 if scenario == "clean" else 2
        if (gate["evaluate_exit"], gate["evaluate_decision"]) != (expected_exit, expected_decision):
            raise RuntimeError("Scenario produced an unexpected real gate decision")
        report = {"schema_version": "dobeworks.stage.mission.v1", "scenario": scenario,
                  "mission": "DEMO-001", "simulation": True, "operational_authority": "NONE",
                  "source_identity": sources, "nasa": {"repository": "https://github.com/nasa/fprime", "commit": nasa["upstream_commit"], "known_vector": "CBF43926", "generated_values_checked": 1024},
                  "packet": {"text": telemetry.decode(), "expected_crc32": "B8BD3EAE", "actual_crc32": actual_crc,
                             "integrity": "PASS" if intact else "BLOCKED", "expected_manifest": expected_manifest,
                             "actual_manifest": actual_manifest},
                  "worker": worker, "worker_input": inventory, "worker_envelope": envelope,
                  "package_sha256": digest(encode(actual_manifest)),
                  "observer": observer, "degs_task": task, "degs": gate["evaluate"],
                  "degs_exit": gate["evaluate_exit"], "handoff": "READY_FOR_REVIEW" if expected_decision == "PASS" else "HOLD"}
        # Temporary execution paths are not part of the portable public evidence.
        return json.loads(json.dumps(report).replace(str(directory), "evidence"))


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare"]:
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
