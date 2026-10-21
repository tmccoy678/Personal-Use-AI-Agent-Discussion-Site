#!/usr/bin/env python3
"""Read-only synthetic Observer Core with privacy-safe unknown semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from bounded_input import BoundedInputError, read_regular


SNAPSHOT_SCHEMA = "dobeworks.observer-snapshot.v1"
POLICY_SCHEMA = "dobeworks.observer-policy.v1"
RECORD_SCHEMA = "dobeworks.observer-record.v1"
MAX_NODES = 256
MAX_JSON_DEPTH = 100
MAX_RETENTION_AGE_DAYS = 36500
ROLE_ID = re.compile(r"^[A-Z]{2}-CANDIDATE-[0-9]{2}$")
GENERATION = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
SNAPSHOT_KEYS = {
    "clock_quality", "collector_status", "dropped_records", "heartbeat_at",
    "last_success_at", "role_id", "sampled_at", "schema_version", "signals",
}
POLICY = {
    "daily_aggregate_retention_days": 180,
    "raw_event_retention_days": 30,
    "schema_version": POLICY_SCHEMA,
    "stale_after_seconds": 300,
    "stop_condition_delivery": "IMMEDIATE",
    "trend_review_days": 7,
    "warning_delivery_max_hours": 24,
}
DECISION_MAP = {
    "backup_restore_age_days": "DECIDE_RECOVERY_RECENCY",
    "bounded_resource_percent": "DECIDE_RESOURCE_GUARD",
    "configuration_generation": "DECIDE_CONFIGURATION_MATCH",
    "job_state": "DECIDE_JOB_DISPATCH_ELIGIBILITY",
    "role_freshness": "DECIDE_ROLE_FRESHNESS",
    "storage_presence": "DECIDE_STORAGE_AVAILABILITY",
}
PROHIBITED_KEYS = {
    "api_key", "auth", "authorization", "content", "credential", "credentials",
    "file_content", "filename", "full_serial", "password", "private_filename",
    "private_key", "private_vault", "prompt", "recovery_key", "secret",
    "secret_value", "serial", "token", "tokens",
}


class ObserverRejected(Exception):
    """A deterministic fail-closed Observer result."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class ObserverArgumentParser(argparse.ArgumentParser):
    """Route argument failures through the structured result seam."""

    def error(self, message: str) -> None:
        raise ObserverRejected("INVALID_ARGUMENT", message)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ObserverRejected("INVALID_TIME", "timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ObserverRejected("INVALID_TIME", "timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ObserverRejected("INVALID_TIME", "timestamp lacks timezone")
    return parsed


def _check_depth(value) -> None:
    """Reject excessively nested JSON without recursion.

    Whether json.loads raises RecursionError for deep input depends on
    interpreter version and build, so enforce the bound explicitly and
    iteratively. The rejection code is then deterministic: over-deep input
    is INVALID_JSON on every interpreter, not an accident of C-stack depth.
    """
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise ObserverRejected("INVALID_JSON", "JSON nesting exceeds limit")
        if isinstance(node, dict):
            stack.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in node)


def _load(raw: bytes) -> dict:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ObserverRejected("DUPLICATE_KEY", f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (ValueError, RecursionError) as error:
        raise ObserverRejected("INVALID_JSON", "input is not one UTF-8 JSON value") from error
    _check_depth(value)
    if not isinstance(value, dict):
        raise ObserverRejected("INVALID_SCHEMA", "JSON root is not an object")
    return value


def _read(path: Path, root: Path, root_identity: tuple, limit: int, root_alias=None) -> bytes:
    try:
        return read_regular(path, root, root_identity, limit, root_alias)
    except BoundedInputError as error:
        code = "INPUT_LIMIT" if error.limit_exceeded else "PATH_REJECTED"
        raise ObserverRejected(code, str(error)) from error


def _scan_privacy(value) -> None:
    pending = [value]
    seen = 0
    while pending:
        item = pending.pop()
        seen += 1
        if seen > MAX_NODES:
            raise ObserverRejected("INPUT_LIMIT", "input exceeds the node bound")
        if isinstance(item, dict):
            for key, child in item.items():
                if key.lower().replace("-", "_") in PROHIBITED_KEYS:
                    raise ObserverRejected("PROHIBITED_DATA", f"prohibited field: {key}")
                pending.append(child)
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and "PRIVATE VAULT" in item.upper():
            raise ObserverRejected("PROHIBITED_DATA", "prohibited classified-data marker")


def _valid_signal(name: str, value) -> bool:
    if name == "backup_restore_age_days":
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 36500
    if name == "bounded_resource_percent":
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100
    if name == "configuration_generation":
        return isinstance(value, str) and GENERATION.fullmatch(value) is not None
    allowed = {
        "job_state": {"IDLE", "RUNNING", "COMPLETED_UNACCEPTED", "FAILED", "AMBIGUOUS"},
        "role_freshness": {"CURRENT", "STALE", "UNKNOWN"},
        "storage_presence": {"PRESENT", "ABSENT", "UNKNOWN"},
    }
    return name in allowed and isinstance(value, str) and value in allowed[name]


class ObserverCore:
    """Own schema, privacy, meaning, self-health, and retention decisions."""

    def __init__(self, allowed_input_root: Path, max_input_bytes: int = 128 * 1024) -> None:
        if not isinstance(max_input_bytes, int) or isinstance(max_input_bytes, bool) or not 1 <= max_input_bytes <= 4 * 1024 * 1024:
            raise ValueError("max_input_bytes is outside the fixed bound")
        try:
            input_root_alias = Path(allowed_input_root).absolute()
            resolved_root = input_root_alias.resolve(strict=True)
            root_stat = resolved_root.stat()
            if not resolved_root.is_dir():
                raise ValueError("allowed input root is not a directory")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise ValueError("allowed input root must identify an existing directory") from error
        self.allowed_input_root = resolved_root
        self._allowed_input_alias = input_root_alias
        self._allowed_input_identity = (root_stat.st_dev, root_stat.st_ino)
        self.max_input_bytes = max_input_bytes

    def collect(self, snapshot_path: Path, policy_path: Path, now: str) -> dict:
        """Validate two read-only inputs and return one minimized record."""
        _utc(now)
        snapshot_raw = _read(snapshot_path, self.allowed_input_root, self._allowed_input_identity, self.max_input_bytes, self._allowed_input_alias)
        policy_raw = _read(policy_path, self.allowed_input_root, self._allowed_input_identity, self.max_input_bytes, self._allowed_input_alias)
        snapshot, policy = _load(snapshot_raw), _load(policy_raw)
        _scan_privacy(snapshot)
        _scan_privacy(policy)
        self._validate_policy(policy)
        if snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
            return self._schema_unknown(snapshot_raw, policy_raw, now)
        signals = self._validate_snapshot(snapshot, now)
        status, freshness, failure = self._meaning_state(snapshot, signals, now)
        if status != "VALIDATED":
            signals = {name: "UNKNOWN" for name in DECISION_MAP}
        return self._record(snapshot, snapshot_raw, policy_raw, signals, status, freshness, failure, now)

    def retention_decision(self, record_kind: str, age_days: int) -> str:
        """Return a decision only; this interface never deletes a record."""
        limits = {"RAW_EVENT": 30, "DAILY_AGGREGATE": 180}
        if not isinstance(record_kind, str) or record_kind not in limits or not isinstance(age_days, int) or isinstance(age_days, bool) or not 0 <= age_days <= MAX_RETENTION_AGE_DAYS:
            raise ObserverRejected("INVALID_RETENTION_REQUEST", "kind or age is invalid")
        return "EXPIRE" if age_days >= limits[record_kind] else "RETAIN"

    def _validate_policy(self, policy: dict) -> None:
        if policy != POLICY:
            raise ObserverRejected("POLICY_MISMATCH", "policy differs from accepted DEC-003 values")

    def _validate_snapshot(self, snapshot: dict, now: str) -> dict:
        if set(snapshot) != SNAPSHOT_KEYS:
            raise ObserverRejected("INVALID_SCHEMA", "snapshot field set differs")
        if snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
            raise ObserverRejected("SCHEMA_INCOMPATIBLE", "snapshot schema version differs")
        if not isinstance(snapshot.get("role_id"), str) or not ROLE_ID.fullmatch(snapshot["role_id"]):
            raise ObserverRejected("INVALID_SCHEMA", "role_id is not pseudonymous")
        if not isinstance(snapshot.get("collector_status"), str) or snapshot["collector_status"] not in {"OK", "FAILED"}:
            raise ObserverRejected("INVALID_SCHEMA", "collector status differs")
        if not isinstance(snapshot.get("clock_quality"), str) or snapshot["clock_quality"] not in {"SYNTHETIC_EXACT", "UNKNOWN"}:
            raise ObserverRejected("INVALID_SCHEMA", "clock quality differs")
        dropped = snapshot.get("dropped_records")
        if not isinstance(dropped, int) or isinstance(dropped, bool) or not 0 <= dropped <= 100000:
            raise ObserverRejected("INVALID_SCHEMA", "dropped-record count differs")
        for field in ("sampled_at", "heartbeat_at", "last_success_at"):
            if _utc(snapshot.get(field)) > _utc(now):
                raise ObserverRejected("INVALID_TIME", f"{field} is in the future")
        return self._signals(snapshot.get("signals"))

    def _signals(self, values) -> dict:
        if not isinstance(values, list) or len(values) > len(DECISION_MAP):
            raise ObserverRejected("INVALID_SIGNALS", "signal count exceeds its bound")
        result = {}
        for item in values:
            if not isinstance(item, dict) or set(item) != {"name", "value"}:
                raise ObserverRejected("INVALID_SIGNALS", "signal field set differs")
            name = item.get("name")
            if not isinstance(name, str) or name not in DECISION_MAP or name in result or not _valid_signal(name, item.get("value")):
                raise ObserverRejected("INVALID_SIGNALS", "signal identity or value differs")
            result[name] = item["value"]
        return {name: result.get(name, "UNKNOWN") for name in DECISION_MAP}

    def _meaning_state(self, snapshot: dict, signals: dict, now: str):
        age = (_utc(now) - _utc(snapshot["sampled_at"])).total_seconds()
        if snapshot["collector_status"] != "OK":
            return "TELEMETRY_UNAVAILABLE", "UNKNOWN", "COLLECTOR_FAILED"
        if age > POLICY["stale_after_seconds"]:
            return "TELEMETRY_UNAVAILABLE", "STALE", "STALE_DATA"
        if snapshot["clock_quality"] != "SYNTHETIC_EXACT":
            return "UNKNOWN", "UNKNOWN", "CLOCK_UNCERTAIN"
        if snapshot["dropped_records"] > 0:
            return "UNKNOWN", "INCOMPLETE", "DROPPED_RECORDS"
        if any(value == "UNKNOWN" for value in signals.values()):
            return "UNKNOWN", "INCOMPLETE", "MISSING_SIGNAL"
        return "VALIDATED", "FRESH", "NONE"

    def _record(self, snapshot, snapshot_raw, policy_raw, signals, status, freshness, failure, now):
        return {
            "decision_map": dict(DECISION_MAP),
            "freshness": freshness,
            "limitations": ["SYNTHETIC_FIXTURE_ONLY", "NO_DEVICE_OBSERVATION", "NO_ACTION_AUTHORITY"],
            "observed_at": now,
            "provenance": {"policy_sha256": _sha256(policy_raw), "snapshot_sha256": _sha256(snapshot_raw)},
            "role_id": snapshot["role_id"],
            "schema_version": RECORD_SCHEMA,
            "self_health": {
                "clock_quality": snapshot["clock_quality"],
                "collector_status": snapshot["collector_status"],
                "dropped_records": snapshot["dropped_records"],
                "failure_status": failure,
                "heartbeat_at": snapshot["heartbeat_at"],
                "last_success_at": snapshot["last_success_at"],
                "schema_version": snapshot["schema_version"],
            },
            "signals": signals,
            "status": status,
        }

    def _schema_unknown(self, snapshot_raw: bytes, policy_raw: bytes, now: str) -> dict:
        snapshot = {
            "clock_quality": "UNKNOWN",
            "collector_status": "UNKNOWN",
            "dropped_records": 0,
            "heartbeat_at": "UNKNOWN",
            "last_success_at": "UNKNOWN",
            "role_id": "UNKNOWN",
            "schema_version": "UNKNOWN",
        }
        signals = {name: "UNKNOWN" for name in DECISION_MAP}
        return self._record(
            snapshot, snapshot_raw, policy_raw, signals,
            "UNKNOWN", "UNKNOWN", "SCHEMA_INCOMPATIBLE", now,
        )


def _parser() -> ObserverArgumentParser:
    parser = ObserverArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--allowed-input-root", required=True)
    parser.add_argument("--now", required=True)
    return parser


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
        core = ObserverCore(Path(args.allowed_input_root))
        result = core.collect(Path(args.snapshot), Path(args.policy), args.now)
        exit_code = 0
    except (ObserverRejected, ValueError) as error:
        result = {"code": getattr(error, "code", "CONFIGURATION_ERROR"), "message": str(error), "status": "ERROR"}
        exit_code = 2
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
