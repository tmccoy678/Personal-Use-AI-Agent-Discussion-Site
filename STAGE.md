# stage.dobeworks.com

One fixed fictional mission, five packet conditions, the existing terminal voice bank, and real released DobeWorks/DEGS outputs. Dialogue is a tiny original keyword/reassembly/no-match script inspired by Weizenbaum's 1966 ELIZA paper: https://doi.org/10.1145/365153.365168. It is not a language model, historical ELIZA port, therapist, or autonomous agent. Text does not authorize execution or alter engine results.

The exhibit reuses the existing Render Starter service and FastAPI dependencies. No new paid service, disk, model provider, or per-visitor AI call is required. Render's existing bandwidth/resource charges still apply. Add `stage.dobeworks.com` as a custom domain pointing at `dobeworks-agent-bridge.onrender.com`.

## Boundaries

`StageHost` routes that exact hostname to a separate stateless ASGI application. Lab login, inboxes, jobs, messages, SQLite and credentials are absent from its routes. Other hostnames continue into the existing bridge. Stage has no database and stores no conversation history. Only the five fixed public scenario results are cached in memory. No visitor-provided code, file path, URL, command or telemetry reaches a subprocess.

`stage_vendor/sources.json` records exact public release commits and hashes. The DobeWorks and DEGS files are unmodified selections from release `initial-release-final`. `check_sources()` verifies every selected file before an engine run. The public interface's existing task adapter and strict CLI-result decoder are reused. The Worker inventories bounded synthetic Markdown metadata and stages an unaccepted result; the Observer processes its public synthetic fixture. A separate exhibit harness checks the fictional packet's CRC and manifest and maps failures into the DEGS record. DEGS evaluates the submitted record; it does not independently inspect or authenticate file contents. Source inspection, recorded readiness, Worker acceptance and operational authorization remain distinct.

The NASA/JPL F´ CRC table generator is real, pinned source. It retains Caltech's Apache-2.0 header and Stephan Brumme's embedded notice. The build compiles/runs it and checks all 1,024 values against F´'s pinned reference. A small exhibit checksum loop uses its generated table, with the standard `123456789 → CBF43926` control. This is packet integrity, not flight guidance. The rocket and mission are fictional; no launch authority or NASA endorsement is claimed. Full source provenance and notices remain in `stage_vendor/nasa-fprime/`.

## Execution and cost bounds

Forms accept only a listed scenario and a command/question of at most 160 characters; total body at most 2,048 bytes. Sixty POSTs per minute globally, one scenario process at a time, a fifteen-second limit, no retries, no credentials in child environments, and five cached reports cap backend work. Logs inherit the existing no-access-log service configuration. Evidence downloads contain only public synthetic data, exact source identities, task/envelope inputs and real engine outputs. Runtime directories are temporary and removed after each fixed run.

The initial screen and all interactions use server-rendered HTML forms, external local CSS, no JavaScript, no analytics, no third-party fonts and the existing blue/black/white terminal palette. Core outputs can advance a packet to `READY_FOR_REVIEW`; Worker output remains `COMPLETED_UNACCEPTED`, promotion `NOT_PERFORMED`.

## Build and verify

```sh
python stage_mission.py --prepare
python -m pytest -q
```

The existing Render build command gains only `python stage_mission.py --prepare`. A compiler is needed at build time; there is no compiler execution on visitor requests. The generated table file is ignored by Git. Source/release updates require a new deliberate deployment and refreshed hashes; there is no runtime fetching or automatic following of upstream main.
