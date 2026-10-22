# Shared DobeWorks and DEGS interface

This optional interface reuses Taylor's Desktop Command Center design: the blue-black display, Courier typography, bordered results, numbered menu, and quoted voices. One implementation lives here; the DEGS repository links to this same interface. Both cores remain separate and run through their existing Python CLIs.

## Start

Use Git and Python 3.9 or later. No Python packages or system installation are needed. Clone both public repositories into the same parent directory:

```sh
git clone https://github.com/tmccoy678/DobeWorks.git
git clone https://github.com/tmccoy678/DEGS.git
cd DobeWorks
python3 -B interface/command_center.py menu
```

On macOS, run `zsh DobeWorks.command` from Terminal in the DobeWorks checkout. To enable opening it by double-click in Finder, first run `chmod +x DobeWorks.command` once in your local checkout. The helper sets only the launching Terminal tab to 72 columns, 30 rows, and 13-point Courier. The menu uses a deep blue-black background and pale blue, white, and steel-blue text. Other terminals need Unicode and true-color support for the same display; their font and window settings are controlled by the terminal itself.

For an existing DEGS clone with another name or location, put the option before the command:

```sh
python3 -B interface/command_center.py --degs-root /path/to/DEGS menu
```

The interface requires Git checkouts with an `origin` remote and checks them before running a demonstration. Source archives are not supported by this launcher. Repository paths are resolved from the interface's location; no Taylor-specific home path or Desktop dependency is included.

## Menu and evidence

The eight programs match the Desktop interface: current-pair integration, fresh and stale Observer records, an unaccepted Worker result, complete and missing-rollback DEGS examples, core verification, and run evidence. `00` closes the interface. On macOS, the evidence program also opens its directory in Finder; elsewhere it displays the path.

Each program run writes a dated directory under ignored `interface/Runs/`, including source identity, inputs where generated, stdout, stderr, staged synthetic output, and applicable summaries. To keep evidence elsewhere, use `--runs-root /path/to/local-evidence` before the command. Git identities describe the local checkouts at run time; a dirty checkout is reported as dirty. Recorded remote URLs omit userinfo, query strings, and fragments. Treat generated records as local evidence before sharing them.

Noninteractive commands use the same program implementations:

```sh
python3 -B interface/command_center.py integration
python3 -B interface/command_center.py observer
python3 -B interface/command_center.py observer --stale
python3 -B interface/command_center.py worker
python3 -B interface/command_center.py degs tier2-complete-pass.json
python3 -B interface/command_center.py degs tier2-missing-rollback-blocked.json
python3 -B interface/command_center.py verify
```

Exit `0` means that demonstration matched its expected result, including the intentionally blocked DEGS example. Exit `1` reports a measured mismatch or failed test suite; exit `2` reports an interface/configuration/program error. The interactive menu keeps errors visible and returns to the menu; closing it exits the session. It does not aggregate earlier program results into its closing exit code. Child demonstrations and core suites have a 120-second timeout; Git identity and Finder commands have ten-second timeouts. There are no automatic retries.

## Current-pair contract

| DobeWorks synthetic result | Expected DEGS decision |
| --- | --- |
| Observer `VALIDATED` and `FRESH`, with the fixture's six expected signals | `PASS` for the read-only synthetic record |
| Observer `TELEMETRY_UNAVAILABLE` and `STALE`, with all six signals `UNKNOWN` | `BLOCKED` |
| Worker `COMPLETED_UNACCEPTED`, promotion `NOT_PERFORMED` | `BLOCKED` |

The interface supplies the DEGS task record because the cores do not define a shared wire format. Copied template controls are marked `PENDING` rather than inheriting fixture `PASS` assertions as measured test evidence. A mapping passes only when the actual source state and the gate's validation, exit, and decision match the stated expectations. Duplicate-key, nonfinite, malformed, or non-object child JSON and unexpected diagnostics are interface errors. This is a synthetic adapter check. It does not accept or promote output, operate a device, establish evidence truth, authorize work, or qualify the system for production.

### Warning readiness

The default gate is the sibling `DEGS` checkout. Keep that checkout current to receive the warning-readiness corrections. An explicit `--degs-root` selects that checkout's own gate behavior.

The adapter preserves the full DEGS evaluation response, including its derived `warning_state` and numbered, sanitized `warnings` entries. Any active record in `warnings` or `unresolved_items` makes the aggregate unresolved count nonzero, severity `CRITICAL`, status `UNRESOLVED`, and `resolved: false`, and blocks readiness at every tier. Counts come from the recorded items; callers cannot supply a zero count to suppress them.

A closed warning requires `severity: "NONE"`, `status: "RESOLVED"`, `resolved: true`, and a nonblank `evidence_path` for the recorded closure. Resolved records belong in `warnings` history; `unresolved_items` contains active records only. Conflicting fields and malformed values, including `"CRITICAL "`, fail validation. The gate checks the closure reference's presence; the referenced evidence's truth remains unverified. Zero unresolved items leaves the other gate requirements in effect.

Core verification runs the existing Worker/Observer and DEGS core/port suites. It preserves their full output and requires a successful unittest summary with at least one executed, non-skipped test per core. It does not run benchmarks, historical package validators, or the optional Rust comparison. Historical Phase 4 package checks still require the separate specification named by `DOBEWORKS_PHASE4_SPEC`.

The frontend's focused checks are separate:

```sh
python3 -B -m unittest discover -s interface -p 'test_*.py' -v
```

The warning contract tests run the actual sibling DEGS CLI through `run_degs_task`, checking a blocked active item, rejected conflicting resolution, and a passing recorded closure. They skip when no sibling `DEGS` checkout is available. To test another checkout explicitly, set `DOBEWORKS_DEGS_ROOT`; an invalid explicit path fails the tests:

```sh
DOBEWORKS_DEGS_ROOT=/path/to/DEGS python3 -B -m unittest discover -s interface -p test_degs_warning_contract.py -v
```

## Voices and design sources

One line from the [six-entry verified voice bank](workbench-voices.json) appears on each menu render, in quotation marks with its attribution. ELIZA, Colossus, and the joint post-fusion Colossus + Guardian voice have equal selection probability, with two entries each. Every entry records its primary source and exact locator, and the loader fails closed if that provenance or the balanced speaker set is missing.

The display is a visual homage to ELIZA-era printed terminals and the central-computer control room of *Colossus: The Forbin Project* (1970). Guardian has no independently spoken English output before the systems fuse, so the bank does not invent a solo Guardian quotation. The [verification record](../docs/research/verified-workbench-voices.md) documents the source review, integrity data, local-clip audit, and attribution decision. The interface imports no film graphics or third-party application code.

- Weizenbaum, J. (1966). [ELIZA—A computer program for the study of natural language communication between man and machine](https://doi.org/10.1145/365153.365168). *Communications of the ACM, 9*(1), 36–45.
- MIT CTSS history. [The IBM 7094 and CTSS at MIT](https://people.csail.mit.edu/saltzer/CTSS/CTSS-Documents/CTSS_50th_anniversary_web_03.pdf).
- IBM. [The IBM Selectric](https://www.ibm.com/history/selectric).
- American Film Institute. [Colossus: The Forbin Project](https://catalog.afi.com/Film/23505-THE-FORBIN-PROJECT).
