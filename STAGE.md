# stage.dobeworks.com

A fictional engineering desk carries one important component through several team handoffs. The packet is based on the actual NASA/JPL F´ `TableGenerator.c`, `Crc32.cpp` and license, plus an explicit requirement, source identities and fictional telemetry/evidence. The source component supports data integrity; this exhibit does not run flight guidance or vehicle control. The wider mission and all role decisions are fictional.

The existing Render Starter service and disk serve all three hostnames. No new paid service, model provider or per-visitor AI call is required. Existing hosting bandwidth/resource charges still apply. Dialogue is an original keyword/no-match script inspired by [Weizenbaum's 1966 ELIZA paper](https://doi.org/10.1145/365153.365168); it cannot change an engine result or a mission receipt.

## Mission workflow

1. Configuration engineer: establish the bounded CRC32 source package and requirement.
2. Telemetry engineer: inspect the real Observer's fresh/stale synthetic fixture result.
3. Package engineer: stage the real Worker's synthetic inventory of Markdown source summaries. Inspect its staged-only contract and unaccepted result. Independently check the source manifest and the candidate component's known-answer CRC behavior. In the default exercise, one mistyped digit compiles successfully but fails that check; show the exact rule and downstream consequence, then choose to keep, illustrate an error launch, or restore the published digit.
4. Verification engineer: inspect retained results from the frozen repositories' existing core tests, run once during release preparation through their shared interface adapter. Preserve counts, commands, stdout, stderr and Python version. Reparse the captured test output and check source identity before accepting the prepared record.
5. Independent reviewer: open the real DEGS read-only handoff decision, previous receipts and core verification. Opening the report does not accept the package; a separate action records the visitor's fictional acceptance after the checks pass.
6. Other mission teams: inspect separate fictional vehicle, weather and range reports, then explicitly record decisions against their conditions. Inspection alone never sets GO. Weather initially holds at wind 22 against limit 15; explicitly receiving the T+05 report supplies wind 9. The fictional director requires the accepted package and all three decisions.
7. Run the clean fictional flight after all handoffs and the complete poll. A separately labelled what-if branch illustrates a launch with the known checksum error while preserving the real BLOCKED decision and leaving package acceptance and successful-flight state unset.
8. View the recorded evidence inline. No checks rerun and no program downloads a file.

The focused teaching case is a quiet transcription error: the default received copy changes exactly one ASCII character in `TableGenerator.c`, line 44, from `0xEDB88320` to `0xEDB88321`. Its size stays the same and both C generators compile. Preparation runs the real C code for the altered copy, retains all 1,024 generated table values and build commands in ignored `stage_assets/transcription-check.json`, and runtime rechecks those values against the fixed candidate polynomial and exact source digest. The known input `123456789` produces `CFBDC920` instead of `CBF43926`. For the fictional telemetry sample, the changed component produces `9B0624A9` instead of the receiver's expected `B8BD3EAE`. The original telemetry's CRC can still be intact while its proposed generating component is wrong.

A visual chain links source, behavior, actual DEGS record decision, fictional receiver rejection and countdown hold. The alternative error-flight illustration does not predict a spacecraft trajectory or crash. Restoring the published digit submits a new copy, invalidates prior reviews, and retains the failed candidate beside the corrected run in evidence. Repeat the checks before accepting it. The clean-flight summary connects the corrected behavior to the received result.

Historical grounding: NASA's [Mariner 1 account](https://science.nasa.gov/mission/mariner-1/) records an omitted overbar in its guidance equation, alongside a guidance antenna fault. This CRC exercise is an original analogue of a small transcription change with a large downstream consequence; the planted CRC error is not a NASA incident. The pinned upstream sources and both governance engines remain unmodified.

Program 01 also opens a read-only packet tray with a collapsed list of the seven expected files, full escaped file contents, sizes and identities. Literal search matches filenames and text, shows matching line numbers, and never runs an engine or changes handoff receipts. The same packet construction function supplies both the viewer and execution checks. Missing and altered files remain visible as such. Code opens inside a bounded panel in the right half of the desk; the left half retains the programs, conversation and plain-language engine explanations.

Refreshing the game starts a new mission. Form actions redirect to a single-use view of their results, so reloads do not resubmit a program. The conversation remains a rule-based script above the programs.

A stale Observer, missing evidence, changed source copy or unresolved review item stops the relevant handoff. Selecting another packet invalidates all previous receipts and mission poll decisions. The altered-source case preserves the original telemetry CRC while changing one digit in a NASA source copy: the manifest and the candidate known-answer test detect the error. The original vendored NASA source is never altered.

The scenario is informed by NASA's [configuration management](https://www.nasa.gov/reference/6-5-configuration-management/) and [readiness review definitions](https://www.nasa.gov/reference/system-engineering-handbook-appendix/). It illustrates one package's contribution, not a complete NASA procedure or flight certification. One visitor plays several roles; the site does not authenticate separate human reviewers. Its role-labelled, hash-linked receipts bind the packet and recorded engine/test results. Hashes establish byte identity, not human identity or evidence authenticity.

## Engine and privacy boundaries

`StageHost` routes only `stage.dobeworks.com` to a separate ASGI app. Lab login, inboxes, jobs, messages, SQLite and credentials are absent from its routes. Other hosts continue into the existing bridge.

`stage_vendor/sources.json` freezes selected runtime files, tests, fixtures, support files and notices at these default-branch heads, checked on 2026-10-21:

- DobeWorks: `20ac2bc684cda9d0d4ce799e9379e44b2a1c51a9`
- DEGS: `29632112ea809e7a589bf04031ecb433ec169888`

These files are unmodified. The selected runtime files match the earlier `initial-release-final` snapshots. `check_sources()` verifies every selected file before a run. No runtime GitHub fetching or automatic upstream updates occur. The existing shared interface's task adapter, strict CLI result decoder, test commands and test summary parser are reused. DEGS evaluates the submitted read-only record; it does not independently inspect packet files. The exhibit performs the manifest comparison and maps a failed comparison to a blocked record. Worker output remains `COMPLETED_UNACCEPTED`, promotion `NOT_PERFORMED`; the separate simulated reviewer receipt does not promote that engine output or authorize real execution.

NASA/JPL F´ is pinned at `a37ffa40871e567481d0a7626c12b24d8acdbf15`. Preparation compiles its real C99 table generator and compares all 1,024 values to the pinned C++ reference. The exhibit's small checksum loop checks `123456789 → CBF43926` before using the generated table. Caltech's Apache-2.0 header and Stephan Brumme's embedded notice are retained. Full provenance is in `stage_vendor/nasa-fprime/`; no NASA endorsement is claimed.

Visitor progress is held in at most 256 temporary in-memory sessions, cleared on page refresh and expiring after two idle hours or server restart, with a random host-only HttpOnly SameSite cookie, Secure on HTTPS, and CSRF form tokens. There is no stage database, account, visitor upload, analytics, paid AI or stored conversation history. The five fixed scenario reports and one prepared core verification are shared read-only caches, while visitor receipts and polls remain separate.

Forms accept only a listed packet condition, a CSRF token and a command/question of at most 160 characters, within 2,048 bytes. Sixty POSTs per minute globally, one child process at a time, a 15-second scenario/60-second prepared-record limit, process-group termination and at most 64 recorded events per mission bound work. No visitor-provided code, path, URL, telemetry or shell text reaches a subprocess. Child environments omit bridge credentials. Runtime evidence directories are temporary and removed after fixed checks. Access logs remain disabled. Server-rendered HTML and local CSS use the existing Courier terminal palette, no JavaScript or remote fonts.

## Build and verify

```sh
python stage_mission.py --prepare
python -m pytest -q tests
```

Preparation runs both core suites with the shared interface's 120-second per-suite limit and rejects failures. A compiler is needed only for preparation. `tables.json` is generated and ignored by Git. Runtime checks compare it to the pinned reference; it can be prepared before transfer. The generated core-verification record is also ignored by Git. Core suites are standard-library `unittest`, invoked using the vendored shared interface's `core_test_commands()`.

The normal Git build is still recorded in `render.yaml`. If Git deployment is unavailable, `deploy_from_disk.py` supports a deliberately prepared release directory on the existing `/var/data` disk and a digest-pinned official Python 3.12.14 Linux image. Prepare this repository and pinned requirements in that directory's `packages/`, verify NASA tables and tests on the host, then retain the host-generated core verification and configure its Docker command to `python /var/data/stage-release/RELEASE/deploy_from_disk.py`. The launcher drops to the existing UID/GID 1000, preserves the bridge environment and SQLite path, and never installs or fetches code at startup. The image deployment sets `FORWARDED_ALLOW_IPS=*` so Uvicorn recognizes HTTPS from Render's terminating proxy. Blueprint Auto Sync is set to No to preserve this deliberate image configuration; the normal Git blueprint remains available for a future deliberate return to Git deployment. The source bundle digest and image digest identify this deployment, rather than Render's old Git commit display. No additional service, disk or registry account is needed. Source/image changes require a deliberate deployment.
