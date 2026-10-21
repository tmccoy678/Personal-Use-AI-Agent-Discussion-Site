#!/usr/bin/env python3
"""Bounded synthetic Worker Core with atomic, never-promoted handback."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import signal
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from bounded_input import BoundedInputError, read_regular


ENVELOPE_SCHEMA = "dobeworks.job-envelope.v1"
INPUT_SCHEMA = "dobeworks.synthetic.input.v1"
RESULT_SCHEMA = "dobeworks.synthetic.result.v1"
JOB_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_ENVELOPE_BYTES = 64 * 1024
MAX_RECORDS = 100
MAX_RECORD_BYTES = 1024 * 1024
MAX_SEEN_JOBS = 64
MAX_OUTPUT_DEPTH = 100
MAX_OUTPUT_NODES = 1024
ENVELOPE_KEYS = {
    "cancellation", "checkpoint", "configuration_sha256", "data_classes",
    "delivery_intent", "dispatch_authority", "expected_output_sha256",
    "expires_at", "handback", "idempotency", "input_sha256", "job_class",
    "job_id", "promotion_authority", "retry_limit", "schema_version",
    "side_effects", "timeout_seconds",
}


class WorkerTimeout(Exception):
    """The bounded runner reports that its deadline expired."""


class WorkerInterrupted(Exception):
    """The bounded runner reports interruption before acknowledgement."""


class WorkerAmbiguousCompletion(Exception):
    """Completion cannot be distinguished from communication loss."""


class WorkerNetworkUnavailable(Exception):
    """An explicitly permitted runner dependency is unavailable."""


class WorkerCancellationRace(Exception):
    """Cancellation and candidate output arrived without ordered authority."""

    def __init__(self, result: dict) -> None:
        super().__init__("synthetic cancellation race")
        self.result = result


class WorkerRejected(Exception):
    """A deterministic fail-closed Worker result."""

    def __init__(self, state: str, reason: str, job_id: str = "UNKNOWN") -> None:
        super().__init__(reason)
        self.state = state
        self.reason = reason
        self.job_id = job_id


class WorkerArgumentParser(argparse.ArgumentParser):
    """Route argument failures through the structured result seam."""

    def error(self, message: str) -> None:
        raise WorkerRejected("ERROR_INVALID_ARGUMENT", message)


@dataclass
class PreparedJob:
    envelope: dict
    input_value: dict
    job_id: str
    input_sha256: str
    expected_output_sha256: str
    timeout_seconds: int
    partial: Path
    destination: Path
    staging_identity: tuple
    partial_identity: Optional[tuple] = None


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _encoded(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _deadline_expired(_signum, _frame) -> None:
    raise WorkerTimeout("runner deadline expired")


def _utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise WorkerRejected("REJECTED_INVALID_ENVELOPE", "timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise WorkerRejected("REJECTED_INVALID_ENVELOPE", "timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise WorkerRejected("REJECTED_INVALID_ENVELOPE", "timestamp lacks timezone")
    return parsed


def _load_json(raw: bytes, state: str) -> dict:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise WorkerRejected(state, "duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (ValueError, RecursionError) as error:
        raise WorkerRejected(state, "invalid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise WorkerRejected(state, "JSON root is not an object")
    return value


def _read_regular(path: Path, root: Path, root_identity: tuple, limit: int, limit_state: str, root_alias=None) -> bytes:
    try:
        return read_regular(path, root, root_identity, limit, root_alias)
    except BoundedInputError as error:
        state = limit_state if error.limit_exceeded else "REJECTED_PATH"
        raise WorkerRejected(state, str(error)) from error


def _candidate_structure_bounded(value) -> bool:
    stack, nodes = [(iter((value,)), 1)], 0
    while stack:
        children, depth = stack[-1]
        try:
            node = next(children)
        except StopIteration:
            stack.pop()
            continue
        nodes += 1
        if depth > MAX_OUTPUT_DEPTH or nodes > MAX_OUTPUT_NODES:
            return False
        if isinstance(node, dict):
            stack.append((iter(node.values()), depth + 1))
        elif isinstance(node, (list, tuple)):
            stack.append((iter(node), depth + 1))
    return True


def _directory_matches(path: Path, identity: tuple) -> bool:
    try:
        observed = path.stat()
        return (
            not path.is_symlink()
            and path.is_dir()
            and (observed.st_dev, observed.st_ino) == identity
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _result(job_id: str, state: str, attempts: int, reason: str, digest=None) -> dict:
    return {
        "attempts": attempts,
        "job_id": job_id,
        "output_sha256": digest,
        "promotion": "NOT_PERFORMED",
        "reason": reason,
        "retry": "PROHIBITED_AUTOMATIC",
        "state": state,
    }


class SyntheticInventoryRunner:
    """Deterministically summarize a bounded synthetic inventory."""

    def __call__(self, envelope: dict, input_value: dict) -> dict:
        kinds: Dict[str, int] = {}
        total_bytes = 0
        for record in input_value["records"]:
            kinds[record["kind"]] = kinds.get(record["kind"], 0) + 1
            total_bytes += record["bytes"]
        return {
            "input_sha256": envelope["input_sha256"],
            "job_id": envelope["job_id"],
            "kinds": kinds,
            "record_count": len(input_value["records"]),
            "schema_version": RESULT_SCHEMA,
            "total_bytes": total_bytes,
        }


class WorkerCore:
    """Own Job Envelope enforcement and atomic Staged Output handback."""

    def __init__(
        self,
        configuration_sha256: str,
        allowed_input_root: Path,
        runner: Optional[Callable[[dict, dict], dict]] = None,
        max_input_bytes: int = 128 * 1024,
        max_output_bytes: int = 128 * 1024,
    ) -> None:
        if not isinstance(configuration_sha256, str) or not SHA256.fullmatch(configuration_sha256):
            raise ValueError("configuration_sha256 must be lowercase SHA-256")
        if not isinstance(max_input_bytes, int) or isinstance(max_input_bytes, bool) or not 1 <= max_input_bytes <= 4 * 1024 * 1024:
            raise ValueError("max_input_bytes is outside the fixed bound")
        if not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool) or not 1 <= max_output_bytes <= 4 * 1024 * 1024:
            raise ValueError("max_output_bytes is outside the fixed bound")
        if runner is not None and not callable(runner):
            raise ValueError("runner must be callable")
        self.configuration_sha256 = configuration_sha256
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
        self.runner = SyntheticInventoryRunner() if runner is None else runner
        self.max_input_bytes = max_input_bytes
        self.max_output_bytes = max_output_bytes
        self._seen_jobs: Dict[str, str] = {}

    def execute(
        self,
        envelope_path: Path,
        input_path: Path,
        staging_root: Path,
        now: str,
        cancellation_requested: bool = False,
    ) -> dict:
        """Validate, execute once, and atomically stage one synthetic job."""
        try:
            if not isinstance(cancellation_requested, bool):
                raise WorkerRejected("REJECTED_INVALID_ARGUMENT", "cancellation_requested must be Boolean")
            prepared = self._prepare(envelope_path, input_path, staging_root, now, cancellation_requested)
        except WorkerRejected as error:
            return _result(error.job_id, error.state, 0, error.reason)
        try:
            return self._run_once(prepared)
        except WorkerRejected as error:
            return _result(error.job_id, error.state, 0, error.reason)
        except OSError:
            return _result(prepared.job_id, "FAILED_STAGE_IO", 1, "staged-output file operation failed; partial state is unaccepted")

    def _prepare(self, envelope_path, input_path, staging_root, now, cancelled) -> PreparedJob:
        try:
            stage = Path(staging_root)
            stage_stat = stage.stat()
            if stage.is_symlink() or not stage.is_dir():
                raise WorkerRejected("REJECTED_PATH", "staging root must be an existing non-symlink directory")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise WorkerRejected("REJECTED_PATH", "staging root cannot be read") from error
        envelope_raw = _read_regular(envelope_path, self.allowed_input_root, self._allowed_input_identity, MAX_ENVELOPE_BYTES, "REJECTED_ENVELOPE_LIMIT", self._allowed_input_alias)
        envelope = _load_json(envelope_raw, "REJECTED_INVALID_ENVELOPE")
        self._validate_envelope(envelope, now)
        job_id = envelope["job_id"]
        fingerprint = _sha256(envelope_raw)
        if job_id in self._seen_jobs:
            state = "DUPLICATE_NO_EXECUTION" if self._seen_jobs[job_id] == fingerprint else "REJECTED_JOB_ID_REUSE"
            raise WorkerRejected(state, "job identity was already observed", job_id)
        if len(self._seen_jobs) >= MAX_SEEN_JOBS:
            raise WorkerRejected("REJECTED_JOB_REGISTRY_LIMIT", "in-memory job registry reached its fixed capacity", job_id)
        input_raw = _read_regular(input_path, self.allowed_input_root, self._allowed_input_identity, self.max_input_bytes, "REJECTED_INPUT_LIMIT", self._allowed_input_alias)
        if _sha256(input_raw) != envelope["input_sha256"]:
            raise WorkerRejected("REJECTED_INPUT_IDENTITY", "input digest differs", job_id)
        input_value = _load_json(input_raw, "REJECTED_INVALID_INPUT")
        self._validate_input(input_value, job_id)
        if cancelled:
            raise WorkerRejected("CANCELLED_BEFORE_EXECUTION", "cancellation preceded execution", job_id)
        partial, destination = stage / f".partial-{job_id}", stage / job_id
        if partial.exists() or partial.is_symlink() or destination.exists() or destination.is_symlink():
            raise WorkerRejected("REJECTED_DESTINATION_EXISTS", "staged destination already exists", job_id)
        self._seen_jobs[job_id] = fingerprint
        return PreparedJob(
            envelope, input_value, job_id, envelope["input_sha256"],
            envelope["expected_output_sha256"], envelope["timeout_seconds"],
            partial, destination, (stage_stat.st_dev, stage_stat.st_ino),
        )

    def _validate_envelope(self, value: dict, now: str) -> None:
        if set(value) != ENVELOPE_KEYS:
            raise WorkerRejected("REJECTED_INVALID_ENVELOPE", "envelope field set differs")
        exact = {
            "schema_version": ENVELOPE_SCHEMA, "job_class": "synthetic_repository_inventory",
            "data_classes": ["PUBLIC_METADATA"], "dispatch_authority": "TAYLOR_AI_WORKBENCH",
            "delivery_intent": "ANALYSIS_ONLY", "idempotency": "IDEMPOTENT",
            "side_effects": "STAGED_OUTPUT_ONLY", "retry_limit": 0, "checkpoint": "NONE",
            "cancellation": "STOP_AND_PRESERVE_PARTIAL", "handback": "ATOMIC_STAGED_OUTPUT",
            "promotion_authority": "PROHIBITED",
        }
        retry = value.get("retry_limit")
        if not isinstance(retry, int) or isinstance(retry, bool) or retry != 0:
            raise WorkerRejected("REJECTED_INVALID_ENVELOPE", "retry_limit must be the integer zero")
        if any(value.get(key) != expected for key, expected in exact.items()):
            raise WorkerRejected("REJECTED_INVALID_ENVELOPE", "envelope contract value differs")
        if not isinstance(value.get("job_id"), str) or not JOB_ID.fullmatch(value["job_id"]):
            raise WorkerRejected("REJECTED_INVALID_ENVELOPE", "job_id is invalid")
        for field in ("configuration_sha256", "input_sha256", "expected_output_sha256"):
            if not isinstance(value.get(field), str) or not SHA256.fullmatch(value[field]):
                raise WorkerRejected("REJECTED_INVALID_ENVELOPE", f"{field} is invalid", value["job_id"])
        if value["configuration_sha256"] != self.configuration_sha256:
            raise WorkerRejected("REJECTED_CONFIGURATION_MISMATCH", "configuration digest differs", value["job_id"])
        if not isinstance(value.get("timeout_seconds"), int) or isinstance(value["timeout_seconds"], bool) or not 1 <= value["timeout_seconds"] <= 30:
            raise WorkerRejected("REJECTED_INVALID_ENVELOPE", "timeout is outside 1..30 seconds", value["job_id"])
        if _utc(value.get("expires_at")) <= _utc(now):
            raise WorkerRejected("REJECTED_STALE", "envelope is expired", value["job_id"])

    def _validate_input(self, value: dict, job_id: str) -> None:
        if set(value) != {"schema_version", "records"} or value.get("schema_version") != INPUT_SCHEMA:
            raise WorkerRejected("REJECTED_INVALID_INPUT", "input schema differs", job_id)
        records = value.get("records")
        if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
            raise WorkerRejected("REJECTED_INVALID_INPUT", "record count is outside 1..100", job_id)
        paths = set()
        for record in records:
            if not isinstance(record, dict) or set(record) != {"path", "kind", "bytes"}:
                raise WorkerRejected("REJECTED_INVALID_INPUT", "record field set differs", job_id)
            path = record.get("path")
            kind = record.get("kind")
            size = record.get("bytes")
            if not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
                raise WorkerRejected("REJECTED_INVALID_INPUT", "record path is unsafe", job_id)
            if path in paths or not isinstance(kind, str) or kind not in {"markdown", "python"}:
                raise WorkerRejected("REJECTED_INVALID_INPUT", "record identity or kind differs", job_id)
            if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= MAX_RECORD_BYTES:
                raise WorkerRejected("REJECTED_INVALID_INPUT", "record byte count is invalid", job_id)
            paths.add(path)

    def _run_once(self, job: PreparedJob) -> dict:
        try:
            return self._with_deadline(job)
        except WorkerTimeout:
            return self._fail(job, "FAILED_TIMEOUT", "runner reported its bounded timeout")
        except WorkerInterrupted:
            return self._fail(job, "AMBIGUOUS_INTERRUPTED", "runner interruption left completion ambiguous")
        except WorkerAmbiguousCompletion:
            return self._fail(job, "AMBIGUOUS_COMPLETION", "completion acknowledgement is unavailable")
        except WorkerNetworkUnavailable:
            return self._fail(job, "FAILED_NETWORK_UNAVAILABLE", "approved dependency is unavailable")
        except WorkerRejected:
            raise
        except OSError:
            raise
        except Exception:
            return self._fail(job, "FAILED_RUNNER", "runner raised an unclassified exception")

    def _with_deadline(self, job: PreparedJob) -> dict:
        try:
            pending = signal.getitimer(signal.ITIMER_REAL)
        except (AttributeError, OSError, ValueError) as error:
            raise WorkerRejected("FAILED_TIMEOUT_CONTROL", "in-process deadline control is unavailable", job.job_id) from error
        if pending != (0.0, 0.0):
            raise WorkerRejected("FAILED_TIMEOUT_CONTROL", "an existing process deadline prevents bounded execution", job.job_id)
        previous = None
        try:
            previous = signal.signal(signal.SIGALRM, _deadline_expired)
            signal.setitimer(signal.ITIMER_REAL, job.timeout_seconds)
        except (AttributeError, OSError, ValueError) as error:
            if previous is not None:
                signal.signal(signal.SIGALRM, previous)
            raise WorkerRejected("FAILED_TIMEOUT_CONTROL", "in-process deadline could not be installed", job.job_id) from error
        try:
            return self._attempt(job)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

    def _attempt(self, job: PreparedJob) -> dict:
        if not _directory_matches(job.partial.parent, job.staging_identity):
            return _result(job.job_id, "FAILED_STAGE_INTEGRITY", 1, "staging root identity changed")
        try:
            job.partial.mkdir(mode=0o700)
            partial_stat = job.partial.stat()
            if job.partial.is_symlink() or not job.partial.is_dir():
                raise OSError("partial staging path is not a directory")
            job.partial_identity = (partial_stat.st_dev, partial_stat.st_ino)
        except OSError as error:
            raise WorkerRejected("FAILED_STAGE_PREPARATION", "partial staging directory could not be created", job.job_id) from error
        try:
            candidate = self.runner(copy.deepcopy(job.envelope), copy.deepcopy(job.input_value))
        except WorkerCancellationRace as error:
            if not self._staging_matches(job):
                return _result(job.job_id, "FAILED_STAGE_INTEGRITY", 1, "staging identity changed during execution")
            self._preserve_candidate(job, error.result)
            return self._fail(job, "AMBIGUOUS_CANCELLATION_RACE", "completion raced with cancellation")
        if not self._staging_matches(job):
            return _result(job.job_id, "FAILED_STAGE_INTEGRITY", 1, "staging identity changed during execution")
        raw = self._preserve_candidate(job, candidate)
        if raw is None:
            return self._fail(job, "FAILED_OUTPUT_VALIDATION", "candidate output cannot be encoded within structural bounds")
        if len(raw) > self.max_output_bytes:
            return self._fail(job, "FAILED_OUTPUT_LIMIT", "candidate output exceeds its byte limit")
        if not self._valid_result(candidate, job):
            return self._fail(job, "FAILED_OUTPUT_VALIDATION", "candidate output schema or semantics differ")
        digest = _sha256(raw)
        if digest != job.expected_output_sha256:
            return self._fail(job, "FAILED_OUTPUT_IDENTITY", "candidate output digest differs")
        return self._handback(job, digest)

    def _preserve_candidate(self, job: PreparedJob, candidate) -> Optional[bytes]:
        valid = False
        try:
            if not _candidate_structure_bounded(candidate):
                raise ValueError("candidate structure exceeds bounds")
            raw = _encoded(candidate)
            valid = True
        except (RecursionError, TypeError, ValueError):
            raw = b'{"unserializable_candidate":true}\n'
        if len(raw) <= self.max_output_bytes:
            (job.partial / "result.json").write_bytes(raw)
        return raw if valid else None

    def _valid_result(self, value, job: PreparedJob) -> bool:
        keys = {"input_sha256", "job_id", "kinds", "record_count", "schema_version", "total_bytes"}
        if not isinstance(value, dict) or set(value) != keys:
            return False
        if value.get("schema_version") != RESULT_SCHEMA or value.get("job_id") != job.job_id:
            return False
        if value.get("input_sha256") != job.input_sha256:
            return False
        kinds = value.get("kinds")
        if not isinstance(kinds, dict) or any(key not in {"markdown", "python"} for key in kinds):
            return False
        if any(not isinstance(count, int) or isinstance(count, bool) or count < 0 for count in kinds.values()):
            return False
        count, size = value.get("record_count"), value.get("total_bytes")
        return isinstance(count, int) and not isinstance(count, bool) and sum(kinds.values()) == count and isinstance(size, int) and not isinstance(size, bool) and size >= 0

    def _staging_matches(self, job: PreparedJob) -> bool:
        return (
            job.partial_identity is not None
            and _directory_matches(job.partial.parent, job.staging_identity)
            and _directory_matches(job.partial, job.partial_identity)
        )

    def _fail(self, job: PreparedJob, state: str, reason: str) -> dict:
        if not self._staging_matches(job):
            return _result(job.job_id, "FAILED_STAGE_INTEGRITY", 1, f"{reason}; staging identity changed")
        record = _result(job.job_id, state, 1, reason)
        try:
            (job.partial / "failure.json").write_bytes(_encoded(record))
        except OSError:
            record["reason"] = f"{reason}; failure evidence write failed"
        return record

    def _handback(self, job: PreparedJob, digest: str) -> dict:
        if not self._staging_matches(job):
            return _result(job.job_id, "FAILED_STAGE_INTEGRITY", 1, "staging identity changed before handback")
        if job.destination.exists() or job.destination.is_symlink():
            return self._fail(job, "FAILED_ATOMIC_HANDBACK", "staged destination appeared during execution")
        record = _result(job.job_id, "COMPLETED_UNACCEPTED", 1, "synthetic result staged", digest)
        manifest = f"{digest}  result.json\n".encode("utf-8")
        try:
            (job.partial / "result-sha256.txt").write_bytes(manifest)
            (job.partial / "handback.json").write_bytes(_encoded(record))
            if not self._staging_matches(job) or job.destination.exists() or job.destination.is_symlink():
                return self._fail(job, "FAILED_ATOMIC_HANDBACK", "staging identity changed before atomic handback")
            os.replace(str(job.partial), str(job.destination))
        except OSError:
            return self._fail(job, "FAILED_ATOMIC_HANDBACK", "atomic directory handback failed")
        return record


def _parser() -> WorkerArgumentParser:
    parser = WorkerArgumentParser(description=__doc__)
    parser.add_argument("--envelope", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--allowed-input-root", required=True)
    parser.add_argument("--configuration-sha256", required=True)
    parser.add_argument("--now", required=True)
    return parser


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
        core = WorkerCore(args.configuration_sha256, Path(args.allowed_input_root))
        result = core.execute(Path(args.envelope), Path(args.input), Path(args.staging_root), args.now)
    except (WorkerRejected, ValueError) as error:
        result = _result("UNKNOWN", getattr(error, "state", "ERROR_CONFIGURATION"), 0, str(error))
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0 if result["state"] == "COMPLETED_UNACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
