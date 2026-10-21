# Phase 4 Software Core

This directory contains two bounded, synthetic-only Modules. It is not a
deployed service, a device configuration, an integration result, a
qualification result, or release software.

## Worker Core Module

`worker_core.py` owns the complete synthetic Job Envelope-to-Staged Output
policy behind one operation:

```python
WorkerCore(...).execute(envelope_path, input_path, staging_root, now)
```

The Module validates closed-schema JSON, duplicate keys and excessive nesting, exact source and
configuration digests, dispatch authority, expiry, data class, job semantics,
input shape and scalar types, path confinement including symlink loops,
byte/record/time/retry bounds, duplicate job
identity, and a pre-execution cancellation signal. It invokes exactly one
runner attempt on detached envelope/input values under the envelope's
Worker-enforced deadline, including result
serialization, validation, and atomic handback; preserves
explicit failure or ambiguity, converts staging filesystem failures to bounded
results, and renames a complete staging directory atomically. It never retries
automatically or performs a Promotion Event. The default runner accepts only
the synthetic repository-inventory fixture. Authoritative input/output digests
and the timeout remain pinned inside Worker Core and cannot be changed by an
injected runner.

Worker and Observer share `bounded_input.py`. Reads open from the pinned
input-root identity, refuse symlink traversal below that root, validate the
opened regular-file descriptor, and enforce the byte limit while reading.
Directory replacement cannot redirect an already opened directory descriptor.
Concurrent content changes are not an immutable snapshot guarantee; Worker
still checks the exact input digest, and Observer records the bytes it read.

CLI example, using a disposable staging directory:

```sh
python3 -B worker_core.py \
  --envelope fixtures/job-envelope.json \
  --input fixtures/input-records.json \
  --staging-root <existing-disposable-directory> \
  --allowed-input-root fixtures \
  --configuration-sha256 ba0e803fc49b7a78989a44c9c9beb9789e37980b7ce92654a89d3f364460873d \
  --now 2026-09-06T00:01:00Z
```

Exit `0` means only `COMPLETED_UNACCEPTED`: an integrity-identified synthetic
result was staged. Exit `2` is a structured rejection, failure, cancellation,
or ambiguity. Neither exit accepts or promotes output.

## Observer Core Module

`observer_core.py` owns the complete synthetic snapshot-to-minimized-record
policy behind two operations:

```python
ObserverCore(...).collect(snapshot_path, policy_path, now)
ObserverCore(...).retention_decision(record_kind, age_days)
```

The Module reads but never writes its inputs. It validates a closed versioned
schema and scalar types, a pseudonymous role ID, provenance hashes, clock meaning, freshness,
dropped records, collector self-health, and an exact signal-to-decision map.
It rejects prohibited private or secret fields at any inspected level and
fails closed on excessive JSON nesting.
Missing, stale, dropped, failed, schema-incompatible, or time-uncertain evidence
yields `UNKNOWN` or `TELEMETRY_UNAVAILABLE`. Retention returns `RETAIN` or `EXPIRE`; it never
deletes. The policy fixes accepted `DEC-003` values: 30 days for raw permitted
events, 180 days for daily aggregates, immediate stop delivery, warnings
within 24 hours, and weekly trend review.

CLI example:

```sh
python3 -B observer_core.py \
  --snapshot fixtures/observer-snapshot.json \
  --policy fixtures/observer-policy.json \
  --allowed-input-root fixtures \
  --now 2026-09-06T00:01:00Z
```

## Bounds and non-authority

| Bound | Frozen value |
|---|---:|
| Envelope bytes | 65,536 |
| Default input bytes per Worker/Observer file | 131,072 |
| Maximum configurable input/output bytes | 4,194,304 |
| Worker input records | 1 through 100 |
| Worker bytes represented per record | 0 through 1,048,576 |
| Worker retries | 0 |
| Worker attempts per `execute` call | 1 |
| Worker remembered job identities per process | 64 |
| Worker candidate output nesting depth | 100 |
| Worker candidate output nodes | 1,024 |
| Input path components below the allowed root | 128 |
| Envelope timeout value | 1 through 30 seconds |
| Observer traversed privacy nodes | 256 |
| Observer signal identities | 6 |
| Observer dropped-record counter | 0 through 100,000 |
| Observer retention-request age | 0 through 36,500 days |

The synthetic runner has no network, subprocess, credential, device, service,
or private-content interface. On the tested host, Worker Core uses the main
thread's interval timer to enforce its in-process deadline and fails closed if
that timer is unavailable or already occupied. Injected test adapters exercise
interruption, ambiguity, cancellation-race, and unavailable-dependency states.
Candidate preservation after a cancellation race remains inside the envelope
deadline. If preservation reaches that deadline, the result is `FAILED_TIMEOUT`.
Separate-process termination, non-main-thread execution, and device behavior
remain future integration and qualification evidence. The Observer has no
remediation, dispatch, promotion, approval, deletion, network, or service
interface.

## Tests

```sh
python3 -B -m unittest discover -s contexts/operational-system/software/phase4 -p 'test_*_core.py' -v
```

The fixtures are deliberately synthetic and non-secret. Exact identities and
the limits of the claims are recorded in the
[Phase 4 source register](../../docs/program/v1/architecture/phase-4/source-register.md)
and [handoff](../../docs/program/v1/architecture/phase-4/handoff.md).
