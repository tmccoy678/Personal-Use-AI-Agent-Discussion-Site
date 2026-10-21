#!/usr/bin/env python3
"""Public-seam tests for the bounded synthetic Worker Core."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from worker_core import (
    MAX_ENVELOPE_BYTES,
    WorkerAmbiguousCompletion,
    WorkerCancellationRace,
    WorkerCore,
    WorkerInterrupted,
    WorkerNetworkUnavailable,
    WorkerTimeout,
)


BASE = Path(__file__).resolve().parent
FIXTURES = BASE / "fixtures"
CONFIG_SHA256 = "ba0e803fc49b7a78989a44c9c9beb9789e37980b7ce92654a89d3f364460873d"
NOW = "2026-09-06T00:01:00Z"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class CountingRunner:
    """Inject one deterministic result or failure and count invocations."""

    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def __call__(self, envelope: dict, input_value: dict) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class BlockingRunner:
    """Block long enough for Worker Core's own deadline to interrupt it."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, envelope: dict, input_value: dict) -> dict:
        self.calls += 1
        time.sleep(5)
        return {}


class MutatingPath:
    """Perform one deterministic path-side effect when converted."""

    def __init__(self, path: Path, mutation) -> None:
        self.path = path
        self.mutation = mutation
        self.called = False

    def __fspath__(self) -> str:
        if not self.called:
            self.called = True
            self.mutation()
        return os.fspath(self.path)


class WorkerCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "inputs"
        self.staging = self.root / "staging"
        self.inputs.mkdir()
        self.staging.mkdir()
        self.envelope = self.inputs / "job-envelope.json"
        self.input_file = self.inputs / "input-records.json"
        shutil.copy2(FIXTURES / "job-envelope.json", self.envelope)
        shutil.copy2(FIXTURES / "input-records.json", self.input_file)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def core(self, **kwargs) -> WorkerCore:
        return WorkerCore(CONFIG_SHA256, allowed_input_root=self.inputs, **kwargs)

    def execute(self, core=None, **kwargs) -> dict:
        selected = core or self.core()
        return selected.execute(self.envelope, self.input_file, self.staging, NOW, **kwargs)

    def mutate_envelope(self, **updates) -> None:
        value = load(self.envelope)
        value.update(updates)
        write_json(self.envelope, value)

    @contextmanager
    def racing_input_open(self, change):
        original_io, original_os, changed = io.open, os.open, []

        def before_open(path):
            if not isinstance(path, int) and Path(path).name == self.input_file.name and not changed:
                changed.append(True)
                change()

        def open_io(path, *args, **kwargs):
            before_open(path)
            return original_io(path, *args, **kwargs)

        def open_os(path, *args, **kwargs):
            before_open(path)
            return original_os(path, *args, **kwargs)

        with mock.patch("io.open", side_effect=open_io), mock.patch("os.open", side_effect=open_os):
            yield changed

    def expect_input_bytes(self, raw: bytes) -> None:
        digest = hashlib.sha256(raw).hexdigest()
        expected = load(FIXTURES / "expected-result.json")
        expected["input_sha256"] = digest
        records = json.loads(raw)["records"]
        expected["total_bytes"] = sum(record["bytes"] for record in records)
        encoded = (json.dumps(expected, indent=2, sort_keys=True) + "\n").encode()
        self.mutate_envelope(input_sha256=digest, expected_output_sha256=hashlib.sha256(encoded).hexdigest())

    def test_growth_between_check_and_open_is_bounded(self) -> None:
        original = self.input_file.read_bytes()
        enlarged = original + b" " * (131073 - len(original))
        self.expect_input_bytes(enlarged)
        with self.racing_input_open(lambda: self.input_file.write_bytes(enlarged)) as changed:
            result = self.execute()
        self.assertTrue(changed)
        self.assertEqual(result["state"], "REJECTED_INPUT_LIMIT")

    def test_swap_to_external_symlink_at_open_is_rejected(self) -> None:
        outside = self.root / "outside-input.json"
        shutil.copyfile(self.input_file, outside)

        def replace_input():
            self.input_file.unlink()
            self.input_file.symlink_to(outside)

        with self.racing_input_open(replace_input) as changed:
            result = self.execute()
        self.assertTrue(changed)
        self.assertEqual(result["state"], "REJECTED_PATH")

    def test_parent_swap_cannot_redirect_an_open_directory(self) -> None:
        nested, outside = self.inputs / "nested", self.root / "outside"
        nested.mkdir()
        outside.mkdir()
        source = self.input_file
        self.input_file = nested / source.name
        shutil.copyfile(source, self.input_file)
        value = load(source)
        value["records"][0]["bytes"] += 1
        write_json(outside / source.name, value)
        self.expect_input_bytes((outside / source.name).read_bytes())

        def replace_parent():
            nested.rename(self.inputs / "saved")
            nested.symlink_to(outside, target_is_directory=True)

        with self.racing_input_open(replace_parent) as changed:
            result = self.execute()
        self.assertTrue(changed)
        self.assertEqual(result["state"], "REJECTED_INPUT_IDENTITY")

    def test_symlinked_input_ancestor_is_rejected(self) -> None:
        linked = self.inputs / "linked-directory"
        linked.symlink_to(self.inputs, target_is_directory=True)
        result = self.core().execute(self.envelope, linked / self.input_file.name, self.staging, NOW)
        self.assertEqual(result["state"], "REJECTED_PATH")

    def test_valid_fixture_is_atomic_completed_unaccepted(self) -> None:
        result = self.execute()
        destination = self.staging / "job-phase4-fixture-001"
        self.assertEqual(result["state"], "COMPLETED_UNACCEPTED")
        self.assertEqual(result["promotion"], "NOT_PERFORMED")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual((destination / "result.json").read_bytes(), (FIXTURES / "expected-result.json").read_bytes())
        self.assertTrue((destination / "handback.json").is_file())
        self.assertFalse((self.staging / ".partial-job-phase4-fixture-001").exists())

    def test_result_is_deterministic_across_fresh_cores(self) -> None:
        first = self.execute()
        other_staging = self.root / "other-staging"
        other_staging.mkdir()
        second = self.core().execute(self.envelope, self.input_file, other_staging, NOW)
        self.assertEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual((self.staging / first["job_id"] / "result.json").read_bytes(), (other_staging / second["job_id"] / "result.json").read_bytes())

    def test_same_envelope_is_deduplicated_without_execution(self) -> None:
        runner = CountingRunner(result=load(FIXTURES / "expected-result.json"))
        core = self.core(runner=runner)
        self.execute(core)
        other = self.root / "other"
        other.mkdir()
        second = core.execute(self.envelope, self.input_file, other, NOW)
        self.assertEqual(second["state"], "DUPLICATE_NO_EXECUTION")
        self.assertEqual(second["attempts"], 0)
        self.assertEqual(runner.calls, 1)

    def test_changed_envelope_reusing_job_id_is_rejected(self) -> None:
        core = self.core()
        self.execute(core)
        self.mutate_envelope(expires_at="2031-01-01T00:00:00Z")
        other = self.root / "other"
        other.mkdir()
        second = core.execute(self.envelope, self.input_file, other, NOW)
        self.assertEqual(second["state"], "REJECTED_JOB_ID_REUSE")

    def test_existing_destination_is_rejected(self) -> None:
        destination = self.staging / "job-phase4-fixture-001"
        destination.mkdir()
        self.assertEqual(self.execute()["state"], "REJECTED_DESTINATION_EXISTS")
        destination.rmdir()
        destination.symlink_to(self.staging / "missing-destination", target_is_directory=True)
        self.assertEqual(self.execute()["state"], "REJECTED_DESTINATION_EXISTS")

    def test_staging_root_identity_drift_is_rejected(self) -> None:
        for timing in ("path", "runner"):
            with self.subTest(timing=timing):
                base = self.root / f"stage-drift-{timing}"
                inputs, stage, saved, outside = base / "inputs", base / "stage", base / "saved", base / "outside"
                inputs.mkdir(parents=True)
                stage.mkdir()
                outside.mkdir()
                envelope, input_file = inputs / "job-envelope.json", inputs / "input-records.json"
                shutil.copy2(FIXTURES / "job-envelope.json", envelope)
                shutil.copy2(FIXTURES / "input-records.json", input_file)

                def replace_stage() -> None:
                    stage.rename(saved)
                    stage.symlink_to(outside, target_is_directory=True)

                runner = None
                envelope_arg = MutatingPath(envelope, replace_stage) if timing == "path" else envelope
                if timing == "runner":
                    def runner(_envelope, _input):
                        replace_stage()
                        return load(FIXTURES / "expected-result.json")
                result = WorkerCore(CONFIG_SHA256, inputs, runner=runner).execute(envelope_arg, input_file, stage, NOW)
                self.assertEqual(result["state"], "FAILED_STAGE_INTEGRITY")
                self.assertEqual(list(outside.iterdir()), [])

    def test_destination_created_by_runner_is_not_replaced(self) -> None:
        destination = self.staging / "job-phase4-fixture-001"

        def runner(_envelope, _input):
            destination.mkdir()
            return load(FIXTURES / "expected-result.json")

        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "FAILED_ATOMIC_HANDBACK")
        self.assertTrue(destination.is_dir())
        self.assertEqual(list(destination.iterdir()), [])

    def test_expired_envelope_is_rejected_without_runner(self) -> None:
        self.mutate_envelope(expires_at="2020-01-01T00:00:00Z")
        runner = CountingRunner(result={})
        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "REJECTED_STALE")
        self.assertEqual(runner.calls, 0)

    def test_duplicate_json_key_is_rejected(self) -> None:
        raw = self.envelope.read_text(encoding="utf-8")
        self.envelope.write_text(raw.replace('{\n', '{\n  "job_id": "duplicate",\n', 1), encoding="utf-8")
        self.assertEqual(self.execute()["state"], "REJECTED_INVALID_ENVELOPE")

    def test_unknown_envelope_field_is_rejected(self) -> None:
        self.mutate_envelope(unapproved=True)
        self.assertEqual(self.execute()["state"], "REJECTED_INVALID_ENVELOPE")

    def test_configuration_mismatch_is_rejected(self) -> None:
        self.mutate_envelope(configuration_sha256="0" * 64)
        self.assertEqual(self.execute()["state"], "REJECTED_CONFIGURATION_MISMATCH")

    def test_input_digest_mismatch_is_rejected(self) -> None:
        value = load(self.input_file)
        value["records"][0]["bytes"] = 121
        write_json(self.input_file, value)
        self.assertEqual(self.execute()["state"], "REJECTED_INPUT_IDENTITY")

    def test_unhashable_record_kind_is_rejected(self) -> None:
        value = load(self.input_file)
        value["records"][0]["kind"] = {}
        write_json(self.input_file, value)
        digest = hashlib.sha256(self.input_file.read_bytes()).hexdigest()
        self.mutate_envelope(input_sha256=digest)
        self.assertEqual(self.execute()["state"], "REJECTED_INVALID_INPUT")

    def test_cancellation_before_execution_is_bounded(self) -> None:
        runner = CountingRunner(result={})
        result = self.execute(self.core(runner=runner), cancellation_requested=True)
        self.assertEqual(result["state"], "CANCELLED_BEFORE_EXECUTION")
        self.assertEqual(runner.calls, 0)

    def test_timeout_has_one_attempt_and_no_automatic_retry(self) -> None:
        runner = CountingRunner(error=WorkerTimeout("synthetic timeout"))
        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "FAILED_TIMEOUT")
        self.assertEqual(result["retry"], "PROHIBITED_AUTOMATIC")
        self.assertEqual(runner.calls, 1)

    def test_core_enforces_the_envelope_deadline(self) -> None:
        self.mutate_envelope(timeout_seconds=1)
        runner = BlockingRunner()
        started = time.monotonic()
        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "FAILED_TIMEOUT")
        self.assertEqual(runner.calls, 1)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_unavailable_or_occupied_deadline_control_fails_closed(self) -> None:
        for response, error in ((None, OSError("synthetic unavailable")), ((1.0, 0.0), None)):
            with self.subTest(response=response, error=error):
                staging = self.root / f"deadline-{response is None}"
                staging.mkdir()
                runner = CountingRunner(result=load(FIXTURES / "expected-result.json"))
                effect = error if error is not None else None
                with mock.patch("worker_core.signal.getitimer", return_value=response, side_effect=effect):
                    result = self.core(runner=runner).execute(self.envelope, self.input_file, staging, NOW)
                self.assertEqual(result["state"], "FAILED_TIMEOUT_CONTROL")
                self.assertEqual(result["promotion"], "NOT_PERFORMED")
                self.assertEqual(runner.calls, 0)

    def test_deep_runner_result_is_a_structured_failure(self) -> None:
        payload = []
        for _ in range(1500):
            payload = [payload]
        result = self.execute(self.core(runner=CountingRunner(result=payload)))
        self.assertEqual(result["state"], "FAILED_OUTPUT_VALIDATION")
        self.assertEqual(result["promotion"], "NOT_PERFORMED")

    def test_output_depth_is_explicit_even_when_encoder_accepts_it(self) -> None:
        payload = []
        for _ in range(101):
            payload = [payload]
        result = self.execute(self.core(runner=CountingRunner(result=payload)))
        self.assertEqual(result["state"], "FAILED_OUTPUT_VALIDATION")
        partial = self.staging / ".partial-job-phase4-fixture-001" / "result.json"
        self.assertEqual(partial.read_bytes(), b'{"unserializable_candidate":true}\n')

    def test_failed_serialization_placeholder_cannot_be_handed_back(self) -> None:
        import worker_core

        candidate = load(FIXTURES / "expected-result.json")
        placeholder = b'{"unserializable_candidate":true}\n'
        self.mutate_envelope(expected_output_sha256=hashlib.sha256(placeholder).hexdigest())
        original = worker_core._encoded

        def fail_candidate(value):
            if value is candidate:
                raise ValueError("synthetic encoding failure")
            return original(value)

        with mock.patch("worker_core._encoded", side_effect=fail_candidate):
            result = self.execute(self.core(runner=CountingRunner(result=candidate)))
        self.assertEqual(result["state"], "FAILED_OUTPUT_VALIDATION")
        self.assertFalse((self.staging / result["job_id"]).exists())

    def test_decoder_errors_are_rejected_without_traceback(self) -> None:
        cases = ["[" * 1500 + "]" * 1500 + "\n"]
        limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
        if 0 < limit and limit + 1 + len('{"x":}') <= MAX_ENVELOPE_BYTES:
            cases.append('{"x":' + "9" * (limit + 1) + "}")
        for raw in cases:
            with self.subTest(input_bytes=len(raw)):
                self.envelope.write_text(raw, encoding="utf-8")
                result = self.execute()
                self.assertEqual(result["state"], "REJECTED_INVALID_ENVELOPE")
                self.assertEqual(result["attempts"], 0)

    def test_boolean_numeric_controls_are_rejected(self) -> None:
        for field in ("timeout_seconds", "retry_limit"):
            with self.subTest(field=field):
                shutil.copy2(FIXTURES / "job-envelope.json", self.envelope)
                self.mutate_envelope(**{field: True})
                self.assertEqual(self.execute()["state"], "REJECTED_INVALID_ENVELOPE")
        for field in ("max_input_bytes", "max_output_bytes"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.core(**{field: True})

    def test_job_registry_has_a_fixed_capacity(self) -> None:
        runner = CountingRunner(result={})
        core = self.core(runner=runner)
        for number in range(64):
            self.mutate_envelope(job_id=f"bounded-job-{number:02d}")
            result = self.execute(core)
            self.assertEqual(result["state"], "FAILED_OUTPUT_VALIDATION")
        self.mutate_envelope(job_id="bounded-job-64")
        result = self.execute(core)
        self.assertEqual(result["state"], "REJECTED_JOB_REGISTRY_LIMIT")
        self.assertEqual((result["attempts"], runner.calls), (0, 64))

    def test_expected_output_digest_mismatch_is_not_handed_back(self) -> None:
        self.mutate_envelope(expected_output_sha256="0" * 64)
        result = self.execute()
        self.assertEqual(result["state"], "FAILED_OUTPUT_IDENTITY")
        self.assertFalse((self.staging / result["job_id"]).exists())

    def test_runner_cannot_mutate_authoritative_contract(self) -> None:
        forged = load(FIXTURES / "expected-result.json")
        forged["total_bytes"] = 999999
        forged_raw = (json.dumps(forged, indent=2, sort_keys=True) + "\n").encode("utf-8")

        def runner(envelope, input_value):
            envelope["expected_output_sha256"] = hashlib.sha256(forged_raw).hexdigest()
            input_value["records"][0]["bytes"] = forged["total_bytes"]
            return forged

        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "FAILED_OUTPUT_IDENTITY")
        self.assertEqual(result["promotion"], "NOT_PERFORMED")
        self.assertFalse((self.staging / result["job_id"]).exists())

    def test_missing_required_envelope_field_is_rejected(self) -> None:
        value = load(self.envelope)
        del value["delivery_intent"]
        write_json(self.envelope, value)
        result = self.execute()
        self.assertEqual((result["state"], result["attempts"]), ("REJECTED_INVALID_ENVELOPE", 0))

    def test_interruption_is_explicitly_ambiguous(self) -> None:
        runner = CountingRunner(error=WorkerInterrupted("synthetic interruption"))
        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "AMBIGUOUS_INTERRUPTED")
        self.assertEqual(result["promotion"], "NOT_PERFORMED")

    def test_communication_loss_is_explicitly_ambiguous(self) -> None:
        runner = CountingRunner(error=WorkerAmbiguousCompletion("synthetic loss"))
        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "AMBIGUOUS_COMPLETION")
        self.assertEqual(result["retry"], "PROHIBITED_AUTOMATIC")

    def test_cancellation_race_preserves_partial_output(self) -> None:
        payload = load(FIXTURES / "expected-result.json")
        runner = CountingRunner(error=WorkerCancellationRace(payload))
        result = self.execute(self.core(runner=runner))
        partial = self.staging / ".partial-job-phase4-fixture-001"
        self.assertEqual(result["state"], "AMBIGUOUS_CANCELLATION_RACE")
        self.assertTrue((partial / "result.json").is_file())
        self.assertFalse((self.staging / result["job_id"]).exists())

    def test_cancellation_candidate_preservation_has_the_envelope_deadline(self) -> None:
        class SlowCandidate(dict):
            def items(self):
                time.sleep(2)
                return super().items()

        self.mutate_envelope(timeout_seconds=1)
        runner = CountingRunner(error=WorkerCancellationRace(SlowCandidate({"candidate": "partial"})))
        started = time.monotonic()
        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "FAILED_TIMEOUT")
        self.assertLess(time.monotonic() - started, 1.8)
        failure = self.staging / ".partial-job-phase4-fixture-001" / "failure.json"
        self.assertEqual(load(failure)["state"], "FAILED_TIMEOUT")

    def test_network_unavailable_does_not_substitute_a_source(self) -> None:
        runner = CountingRunner(error=WorkerNetworkUnavailable("synthetic offline"))
        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "FAILED_NETWORK_UNAVAILABLE")
        self.assertEqual(runner.calls, 1)

    def test_invalid_output_remains_partial_and_unpromoted(self) -> None:
        runner = CountingRunner(result={"unexpected": True})
        result = self.execute(self.core(runner=runner))
        self.assertEqual(result["state"], "FAILED_OUTPUT_VALIDATION")
        self.assertEqual(result["promotion"], "NOT_PERFORMED")
        self.assertTrue((self.staging / ".partial-job-phase4-fixture-001").is_dir())

    def test_partial_directory_creation_failure_is_structured(self) -> None:
        with mock.patch.object(Path, "mkdir", side_effect=OSError("synthetic mkdir failure")):
            result = self.execute()
        self.assertEqual(result["state"], "FAILED_STAGE_PREPARATION")
        self.assertEqual(result["promotion"], "NOT_PERFORMED")

    def test_result_write_failure_is_structured(self) -> None:
        original = Path.write_bytes

        def fail_result(path, payload):
            if path.name == "result.json":
                raise OSError("synthetic result write failure")
            return original(path, payload)

        with mock.patch.object(Path, "write_bytes", autospec=True, side_effect=fail_result):
            result = self.execute()
        self.assertEqual(result["state"], "FAILED_STAGE_IO")
        self.assertEqual(result["attempts"], 1)

    def test_handback_write_and_rename_failures_are_structured(self) -> None:
        original = Path.write_bytes
        for target in ("result-sha256.txt", "handback.json"):
            with self.subTest(target=target):
                staging = self.root / target.replace(".", "-")
                staging.mkdir()

                def fail_target(path, payload):
                    if path.name == target:
                        raise OSError("synthetic handback write failure")
                    return original(path, payload)

                with mock.patch.object(Path, "write_bytes", autospec=True, side_effect=fail_target):
                    result = self.core().execute(self.envelope, self.input_file, staging, NOW)
                self.assertEqual(result["state"], "FAILED_ATOMIC_HANDBACK")
        rename_stage = self.root / "rename-failure"
        rename_stage.mkdir()
        with mock.patch("worker_core.os.replace", side_effect=OSError("synthetic rename failure")):
            result = self.core().execute(self.envelope, self.input_file, rename_stage, NOW)
        self.assertEqual(result["state"], "FAILED_ATOMIC_HANDBACK")

    def test_oversized_input_is_rejected(self) -> None:
        self.assertEqual(self.execute(self.core(max_input_bytes=1))["state"], "REJECTED_INPUT_LIMIT")

    def test_oversized_output_is_not_handed_back(self) -> None:
        payload = load(FIXTURES / "expected-result.json")
        runner = CountingRunner(result={**payload, "padding": "x" * 1024})
        result = self.execute(self.core(runner=runner, max_output_bytes=100))
        self.assertEqual(result["state"], "FAILED_OUTPUT_LIMIT")

    def test_input_outside_allowed_root_is_rejected(self) -> None:
        outside = self.root / "outside.json"
        shutil.copy2(self.input_file, outside)
        result = self.core().execute(self.envelope, outside, self.staging, NOW)
        self.assertEqual(result["state"], "REJECTED_PATH")

    def test_symlink_input_and_staging_root_are_rejected(self) -> None:
        linked_input = self.inputs / "linked.json"
        linked_input.symlink_to(self.input_file)
        first = self.core().execute(self.envelope, linked_input, self.staging, NOW)
        linked_stage = self.root / "linked-stage"
        linked_stage.symlink_to(self.staging, target_is_directory=True)
        second = self.core().execute(self.envelope, self.input_file, linked_stage, NOW)
        self.assertEqual((first["state"], second["state"]), ("REJECTED_PATH", "REJECTED_PATH"))

    def test_symlink_loop_input_is_rejected(self) -> None:
        loop = self.inputs / "loop.json"
        loop.symlink_to(loop)
        result = self.core().execute(self.envelope, loop, self.staging, NOW)
        self.assertEqual(result["state"], "REJECTED_PATH")

    def test_symlink_loop_allowed_root_fails_closed_through_core_and_cli(self) -> None:
        loop = self.root / "root-loop"
        loop.symlink_to(loop)
        with self.assertRaisesRegex(ValueError, "allowed input root"):
            WorkerCore(CONFIG_SHA256, allowed_input_root=loop)
        missing = self.root / "missing-root"
        dangling = self.root / "dangling-root"
        dangling.symlink_to(missing)
        for invalid in ({}, missing, dangling):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "allowed input root"):
                    WorkerCore(CONFIG_SHA256, allowed_input_root=invalid)
        command = [sys.executable, "-B", str(BASE / "worker_core.py"), "--envelope", str(self.envelope), "--input", str(self.input_file), "--staging-root", str(self.staging), "--allowed-input-root", str(loop), "--configuration-sha256", CONFIG_SHA256, "--now", NOW]
        completed = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
        parsed = json.loads(completed.stdout)
        self.assertEqual((completed.returncode, completed.stderr, parsed["state"]), (2, "", "ERROR_CONFIGURATION"))

    def test_allowed_root_identity_drift_is_rejected(self) -> None:
        for replacement in ("loop", "symlink", "directory"):
            with self.subTest(replacement=replacement):
                base = self.root / f"drift-{replacement}"
                allowed, saved, staging = base / "allowed", base / "saved", base / "staging"
                allowed.mkdir(parents=True)
                staging.mkdir()
                shutil.copy2(FIXTURES / "job-envelope.json", allowed / "job-envelope.json")
                shutil.copy2(FIXTURES / "input-records.json", allowed / "input-records.json")
                core = WorkerCore(CONFIG_SHA256, allowed_input_root=allowed)
                allowed.rename(saved)
                if replacement == "loop":
                    allowed.symlink_to(allowed)
                elif replacement == "symlink":
                    allowed.symlink_to(saved, target_is_directory=True)
                else:
                    allowed.mkdir()
                    shutil.copy2(FIXTURES / "job-envelope.json", allowed / "job-envelope.json")
                    shutil.copy2(FIXTURES / "input-records.json", allowed / "input-records.json")
                result = core.execute(allowed / "job-envelope.json", allowed / "input-records.json", staging, NOW)
                self.assertEqual(result["state"], "REJECTED_PATH")

    def test_public_api_types_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "configuration_sha256"):
            WorkerCore({}, allowed_input_root=self.inputs)
        with self.assertRaisesRegex(ValueError, "runner must be callable"):
            self.core(runner={})
        cases = (
            self.core().execute({}, self.input_file, self.staging, NOW),
            self.core().execute(self.envelope, {}, self.staging, NOW),
            self.core().execute(self.envelope, self.input_file, {}, NOW),
        )
        self.assertTrue(all(result["state"] == "REJECTED_PATH" for result in cases))
        invalid_time = self.core().execute(self.envelope, self.input_file, self.staging, bytearray(NOW.encode()))
        invalid_cancel = self.execute(cancellation_requested={})
        self.assertEqual(invalid_time["state"], "REJECTED_INVALID_ENVELOPE")
        self.assertEqual(invalid_cancel["state"], "REJECTED_INVALID_ARGUMENT")

    def test_core_exposes_no_promotion_operation(self) -> None:
        core = self.core()
        self.assertFalse(any(hasattr(core, name) for name in ("promote", "dispatch", "approve")))

    def test_cli_emits_one_complete_json_result(self) -> None:
        command = [sys.executable, "-B", str(BASE / "worker_core.py"), "--envelope", str(self.envelope), "--input", str(self.input_file), "--staging-root", str(self.staging), "--allowed-input-root", str(self.inputs), "--configuration-sha256", CONFIG_SHA256, "--now", NOW]
        completed = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
        parsed = json.loads(completed.stdout)
        self.assertEqual((completed.returncode, completed.stderr, parsed["state"]), (0, "", "COMPLETED_UNACCEPTED"))


if __name__ == "__main__":
    unittest.main()
