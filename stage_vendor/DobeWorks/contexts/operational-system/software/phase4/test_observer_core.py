#!/usr/bin/env python3
"""Public-seam tests for the bounded synthetic Observer Core."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from observer_core import ObserverCore, ObserverRejected


BASE = Path(__file__).resolve().parent
FIXTURES = BASE / "fixtures"
NOW = "2026-09-06T00:01:00Z"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ObserverCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.snapshot = self.inputs / "observer-snapshot.json"
        self.policy = self.inputs / "observer-policy.json"
        shutil.copy2(FIXTURES / "observer-snapshot.json", self.snapshot)
        shutil.copy2(FIXTURES / "observer-policy.json", self.policy)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def core(self, **kwargs) -> ObserverCore:
        return ObserverCore(allowed_input_root=self.inputs, **kwargs)

    def collect(self, core=None) -> dict:
        return (core or self.core()).collect(self.snapshot, self.policy, NOW)

    def mutate_snapshot(self, **updates) -> None:
        value = load(self.snapshot)
        value.update(updates)
        write_json(self.snapshot, value)

    @contextmanager
    def racing_snapshot_open(self, change):
        original_io, original_os, changed = io.open, os.open, []

        def before_open(path):
            if not isinstance(path, int) and Path(path).name == self.snapshot.name and not changed:
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

    def test_growth_between_check_and_open_is_bounded(self) -> None:
        original = self.snapshot.read_bytes()
        enlarged = original + b" " * (131073 - len(original))
        with self.racing_snapshot_open(lambda: self.snapshot.write_bytes(enlarged)) as changed:
            with self.assertRaisesRegex(ObserverRejected, "INPUT_LIMIT"):
                self.collect()
        self.assertTrue(changed)

    def test_swap_to_external_symlink_at_open_is_rejected(self) -> None:
        outside = self.root / "outside-snapshot.json"
        shutil.copyfile(self.snapshot, outside)

        def replace_snapshot():
            self.snapshot.unlink()
            self.snapshot.symlink_to(outside)

        with self.racing_snapshot_open(replace_snapshot) as changed:
            with self.assertRaisesRegex(ObserverRejected, "PATH_REJECTED"):
                self.collect()
        self.assertTrue(changed)

    def test_parent_swap_cannot_redirect_an_open_directory(self) -> None:
        nested, outside = self.inputs / "nested", self.root / "outside"
        nested.mkdir()
        outside.mkdir()
        source = self.snapshot
        self.snapshot = nested / source.name
        shutil.copyfile(source, self.snapshot)
        value = load(source)
        value["role_id"] = "WK-CANDIDATE-02"
        write_json(outside / source.name, value)

        def replace_parent():
            nested.rename(self.inputs / "saved")
            nested.symlink_to(outside, target_is_directory=True)

        with self.racing_snapshot_open(replace_parent) as changed:
            record = self.collect()
        self.assertTrue(changed)
        self.assertEqual(record["role_id"], "WK-CANDIDATE-01")

    def test_symlinked_input_ancestor_is_rejected(self) -> None:
        linked = self.inputs / "linked-directory"
        linked.symlink_to(self.inputs, target_is_directory=True)
        with self.assertRaisesRegex(ObserverRejected, "PATH_REJECTED"):
            self.core().collect(linked / self.snapshot.name, self.policy, NOW)

    def test_input_descriptors_close_on_success_and_rejection(self) -> None:
        original_open, original_close, active, observed = os.open, os.close, set(), []

        def track_open(*args, **kwargs):
            descriptor = original_open(*args, **kwargs)
            active.add(descriptor)
            observed.append(descriptor)
            return descriptor

        def track_close(descriptor):
            original_close(descriptor)
            active.remove(descriptor)

        with mock.patch("os.open", side_effect=track_open), mock.patch("os.close", side_effect=track_close):
            self.collect()
            self.assertEqual(active, set())
            with self.assertRaisesRegex(ObserverRejected, "INPUT_LIMIT"):
                self.core(max_input_bytes=1).collect(self.snapshot, self.policy, NOW)
            self.assertEqual(active, set())
            with mock.patch("bounded_input.os.fdopen", side_effect=OSError("synthetic read failure")):
                with self.assertRaisesRegex(ObserverRejected, "PATH_REJECTED"):
                    self.collect()
            self.assertEqual(active, set())
        self.assertTrue(observed)

    def test_short_reads_do_not_hide_trailing_malformed_input(self) -> None:
        valid = self.snapshot.read_bytes()
        self.snapshot.write_bytes(valid + b" invalid trailing data")
        original = os.fdopen

        class ShortReader:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def read(self, size):
                return self.stream.read(min(size, len(valid)))

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

        with mock.patch("bounded_input.os.fdopen", side_effect=lambda *a, **k: ShortReader(original(*a, **k))):
            with self.assertRaisesRegex(ObserverRejected, "INVALID_JSON"):
                self.collect()

    def test_growth_during_open_descriptor_read_is_bounded(self) -> None:
        valid = self.snapshot.read_bytes()
        enlarged = valid + b" " * (131073 - len(valid))
        original, changed = os.fdopen, []

        class GrowingReader:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def read(inner, size):
                if not changed:
                    changed.append(True)
                    self.snapshot.write_bytes(enlarged)
                return inner.stream.read(size)

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

        with mock.patch("bounded_input.os.fdopen", side_effect=lambda *a, **k: GrowingReader(original(*a, **k))):
            with self.assertRaisesRegex(ObserverRejected, "INPUT_LIMIT"):
                self.collect()
        self.assertTrue(changed)

    def test_valid_fixture_matches_exact_expected_record(self) -> None:
        actual = json.dumps(self.collect(), indent=2, sort_keys=True) + "\n"
        self.assertEqual(actual.encode(), (FIXTURES / "expected-observer-record.json").read_bytes())

    def test_result_is_deterministic(self) -> None:
        self.assertEqual(self.collect(), self.collect())

    def test_nested_prohibited_field_is_rejected(self) -> None:
        value = load(self.snapshot)
        value["signals"][0]["token"] = "synthetic-secret"
        write_json(self.snapshot, value)
        with self.assertRaisesRegex(ObserverRejected, "PROHIBITED_DATA"):
            self.collect()

    def test_credential_and_secret_aliases_are_rejected(self) -> None:
        for field in ("credentials", "password", "private-key", "secret_value"):
            with self.subTest(field=field):
                value = load(FIXTURES / "observer-snapshot.json")
                value["signals"][0][field] = "synthetic-placeholder"
                write_json(self.snapshot, value)
                with self.assertRaisesRegex(ObserverRejected, "PROHIBITED_DATA"):
                    self.collect()

    def test_private_vault_text_is_rejected(self) -> None:
        value = load(self.snapshot)
        value["signals"][0]["value"] = "PRIVATE VAULT"
        write_json(self.snapshot, value)
        with self.assertRaisesRegex(ObserverRejected, "PROHIBITED_DATA"):
            self.collect()

    def test_unknown_top_level_field_is_rejected(self) -> None:
        self.mutate_snapshot(remediation="restart")
        with self.assertRaisesRegex(ObserverRejected, "INVALID_SCHEMA"):
            self.collect()

    def test_schema_mismatch_surfaces_unknown(self) -> None:
        self.mutate_snapshot(schema_version="dobeworks.observer-snapshot.v2")
        record = self.collect()
        self.assertEqual((record["status"], record["freshness"]), ("UNKNOWN", "UNKNOWN"))
        self.assertEqual(record["self_health"]["failure_status"], "SCHEMA_INCOMPATIBLE")
        self.assertTrue(all(value == "UNKNOWN" for value in record["signals"].values()))
        command = [sys.executable, "-B", str(BASE / "observer_core.py"), "--snapshot", str(self.snapshot), "--policy", str(self.policy), "--allowed-input-root", str(self.inputs), "--now", NOW]
        completed = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
        parsed = json.loads(completed.stdout)
        self.assertEqual((completed.returncode, completed.stderr, parsed["status"]), (0, "", "UNKNOWN"))

    def test_duplicate_json_key_is_rejected(self) -> None:
        raw = self.policy.read_text(encoding="utf-8")
        self.policy.write_text(raw.replace('{\n', '{\n  "raw_event_retention_days": 99,\n', 1), encoding="utf-8")
        with self.assertRaisesRegex(ObserverRejected, "DUPLICATE_KEY"):
            self.collect()

    def test_decoder_errors_are_rejected_without_traceback(self) -> None:
        cases = ["[" * 1500 + "]" * 1500 + "\n"]
        limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
        if 0 < limit and limit + 1 + len('{"x":}') <= self.core().max_input_bytes:
            cases.append('{"x":' + "9" * (limit + 1) + "}")
        for raw in cases:
            with self.subTest(input_bytes=len(raw)):
                self.snapshot.write_text(raw, encoding="utf-8")
                with self.assertRaisesRegex(ObserverRejected, "INVALID_JSON"):
                    self.collect()

    def test_stale_snapshot_never_implies_health(self) -> None:
        self.mutate_snapshot(sampled_at="2026-09-05T23:00:00Z")
        record = self.collect()
        self.assertEqual((record["status"], record["freshness"]), ("TELEMETRY_UNAVAILABLE", "STALE"))
        self.assertTrue(all(value == "UNKNOWN" for value in record["signals"].values()))

    def test_collector_failure_is_unavailable(self) -> None:
        self.mutate_snapshot(collector_status="FAILED")
        record = self.collect()
        self.assertEqual(record["status"], "TELEMETRY_UNAVAILABLE")
        self.assertEqual(record["self_health"]["failure_status"], "COLLECTOR_FAILED")

    def test_clock_uncertainty_marks_meanings_unknown(self) -> None:
        self.mutate_snapshot(clock_quality="UNKNOWN")
        record = self.collect()
        self.assertEqual((record["status"], record["freshness"]), ("UNKNOWN", "UNKNOWN"))
        self.assertTrue(all(value == "UNKNOWN" for value in record["signals"].values()))

    def test_dropped_records_mark_interval_unknown(self) -> None:
        self.mutate_snapshot(dropped_records=1)
        record = self.collect()
        self.assertEqual(record["status"], "UNKNOWN")
        self.assertEqual(record["self_health"]["failure_status"], "DROPPED_RECORDS")

    def test_missing_signal_is_explicit_unknown(self) -> None:
        value = load(self.snapshot)
        value["signals"] = value["signals"][:-1]
        write_json(self.snapshot, value)
        record = self.collect()
        self.assertEqual(record["status"], "UNKNOWN")
        self.assertEqual(record["signals"]["storage_presence"], "UNKNOWN")

    def test_duplicate_and_unknown_signals_are_rejected(self) -> None:
        value = load(self.snapshot)
        value["signals"].append(value["signals"][0])
        write_json(self.snapshot, value)
        with self.assertRaisesRegex(ObserverRejected, "INVALID_SIGNALS"):
            self.collect()
        value = load(FIXTURES / "observer-snapshot.json")
        value["signals"][0]["name"] = "private_filename"
        write_json(self.snapshot, value)
        with self.assertRaises(ObserverRejected):
            self.collect()

    def test_unhashable_signal_and_api_values_are_rejected(self) -> None:
        value = load(self.snapshot)
        value["signals"][3]["value"] = {}
        write_json(self.snapshot, value)
        with self.assertRaisesRegex(ObserverRejected, "INVALID_SIGNALS"):
            self.collect()
        with self.assertRaisesRegex(ObserverRejected, "INVALID_RETENTION_REQUEST"):
            self.core().retention_decision({}, 30)

    def test_policy_must_equal_accepted_decision(self) -> None:
        value = load(self.policy)
        value["raw_event_retention_days"] = 31
        write_json(self.policy, value)
        with self.assertRaisesRegex(ObserverRejected, "POLICY_MISMATCH"):
            self.collect()

    def test_retention_boundaries_decide_without_deleting(self) -> None:
        core = self.core()
        self.assertEqual(core.retention_decision("RAW_EVENT", 29), "RETAIN")
        self.assertEqual(core.retention_decision("RAW_EVENT", 30), "EXPIRE")
        self.assertEqual(core.retention_decision("DAILY_AGGREGATE", 179), "RETAIN")
        self.assertEqual(core.retention_decision("DAILY_AGGREGATE", 180), "EXPIRE")
        self.assertFalse(hasattr(core, "delete"))

    def test_invalid_retention_request_is_rejected(self) -> None:
        with self.assertRaisesRegex(ObserverRejected, "INVALID_RETENTION_REQUEST"):
            self.core().retention_decision("UNKNOWN", -1)

    def test_retention_age_has_a_fixed_upper_bound(self) -> None:
        core = self.core()
        self.assertEqual(core.retention_decision("RAW_EVENT", 36500), "EXPIRE")
        for age in (36501, True):
            with self.subTest(age=age):
                with self.assertRaisesRegex(ObserverRejected, "INVALID_RETENTION_REQUEST"):
                    core.retention_decision("RAW_EVENT", age)

    def test_oversized_input_is_rejected(self) -> None:
        with self.assertRaisesRegex(ObserverRejected, "INPUT_LIMIT"):
            self.collect(self.core(max_input_bytes=1))

    def test_out_of_root_and_symlink_inputs_are_rejected(self) -> None:
        outside = self.root / "outside.json"
        shutil.copy2(self.snapshot, outside)
        with self.assertRaisesRegex(ObserverRejected, "PATH_REJECTED"):
            self.core().collect(outside, self.policy, NOW)
        linked = self.inputs / "linked.json"
        linked.symlink_to(self.snapshot)
        with self.assertRaisesRegex(ObserverRejected, "PATH_REJECTED"):
            self.core().collect(linked, self.policy, NOW)

    def test_symlink_loop_input_is_rejected(self) -> None:
        loop = self.inputs / "loop.json"
        loop.symlink_to(loop)
        with self.assertRaisesRegex(ObserverRejected, "PATH_REJECTED"):
            self.core().collect(loop, self.policy, NOW)

    def test_symlink_loop_allowed_root_fails_closed_through_core_and_cli(self) -> None:
        loop = self.root / "root-loop"
        loop.symlink_to(loop)
        with self.assertRaisesRegex(ValueError, "allowed input root"):
            ObserverCore(allowed_input_root=loop)
        missing = self.root / "missing-root"
        dangling = self.root / "dangling-root"
        dangling.symlink_to(missing)
        for invalid in ({}, missing, dangling):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "allowed input root"):
                    ObserverCore(allowed_input_root=invalid)
        command = [sys.executable, "-B", str(BASE / "observer_core.py"), "--snapshot", str(self.snapshot), "--policy", str(self.policy), "--allowed-input-root", str(loop), "--now", NOW]
        completed = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
        parsed = json.loads(completed.stdout)
        self.assertEqual((completed.returncode, completed.stderr, parsed["status"]), (2, "", "ERROR"))

    def test_allowed_root_identity_drift_is_rejected(self) -> None:
        for replacement in ("loop", "symlink", "directory"):
            with self.subTest(replacement=replacement):
                base = self.root / f"drift-{replacement}"
                allowed, saved = base / "allowed", base / "saved"
                allowed.mkdir(parents=True)
                shutil.copy2(FIXTURES / "observer-snapshot.json", allowed / "observer-snapshot.json")
                shutil.copy2(FIXTURES / "observer-policy.json", allowed / "observer-policy.json")
                core = ObserverCore(allowed_input_root=allowed)
                allowed.rename(saved)
                if replacement == "loop":
                    allowed.symlink_to(allowed)
                elif replacement == "symlink":
                    allowed.symlink_to(saved, target_is_directory=True)
                else:
                    allowed.mkdir()
                    shutil.copy2(FIXTURES / "observer-snapshot.json", allowed / "observer-snapshot.json")
                    shutil.copy2(FIXTURES / "observer-policy.json", allowed / "observer-policy.json")
                with self.assertRaisesRegex(ObserverRejected, "PATH_REJECTED"):
                    core.collect(allowed / "observer-snapshot.json", allowed / "observer-policy.json", NOW)

    def test_public_api_types_fail_closed(self) -> None:
        with self.assertRaisesRegex(ObserverRejected, "PATH_REJECTED"):
            self.core().collect({}, self.policy, NOW)
        with self.assertRaisesRegex(ObserverRejected, "PATH_REJECTED"):
            self.core().collect(self.snapshot, {}, NOW)
        with self.assertRaisesRegex(ObserverRejected, "INVALID_TIME"):
            self.core().collect(self.snapshot, self.policy, bytearray(NOW.encode()))

    def test_core_exposes_no_action_authority(self) -> None:
        core = self.core()
        self.assertFalse(any(hasattr(core, name) for name in ("remediate", "dispatch", "promote", "approve", "delete")))
        self.assertEqual(self.collect()["limitations"][-1], "NO_ACTION_AUTHORITY")

    def test_cli_emits_one_complete_json_result(self) -> None:
        command = [sys.executable, "-B", str(BASE / "observer_core.py"), "--snapshot", str(self.snapshot), "--policy", str(self.policy), "--allowed-input-root", str(self.inputs), "--now", NOW]
        completed = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
        parsed = json.loads(completed.stdout)
        self.assertEqual((completed.returncode, completed.stderr, parsed["status"]), (0, "", "VALIDATED"))


if __name__ == "__main__":
    unittest.main()
