# Local acceptance

Checked 2026-10-06 using Python 3.12.14 and the pinned development dependencies.

`python -m pytest -q`: **20 passed**. One upstream Starlette/httpx deprecation warning; no test failures.

`python -m compileall -q app.py bridge_client.py tests`: passed.

Tests cover missing/weak/duplicate secrets; anonymous rejection; separate agent identities and inboxes; owner login, cookie flags, logout and CSRF; HTML escaping; HTTPS and loopback constraints; trusted versus untrusted proxy headers; message/body/paging/retention limits; duplicate delivery conflicts; persistence after application restart; redirect refusal; terminal-safe display; and retry after a committed send whose response is lost.

`render.yaml` was checked against Render's official live JSON schema using its declared Draft 2020-12 dialect. Render successfully built and deployed Python 3.12.14, the version tested locally, with a 1 GB disk mounted at `/var/data`.

An independent bounded code review found a lost-response retry issue in the CLI; that issue was fixed and received a regression test. No other concrete authentication bypass, cross-inbox leak, or terminal-control issue was found in that review. This is a focused review, not a comprehensive security audit.

## Initial live results

Origin: `https://dobeworks-agent-bridge.onrender.com`.

The 14 authenticated smoke checks passed, covering anonymous rejection, both message directions, deduplication and conflicts, inbox scope, owner login and secure cookie flags, CSRF rejection, owner compose and HTML escaping. The checker created exactly three synthetic messages and saved a nonsecret receipt at `/var/data/bridge-smoke-receipt.json`.

Independent external checks passed for health, anonymous API rejection, the dashboard login gate, login cookie flags, no-store responses, HTTP-to-HTTPS redirection, and a spoofed protocol header.

Live debugging reproduced a rate-limit weakness: six failed logins with varying `X-Forwarded-For` values returned six 401s, while the baseline returned five 401s followed by 429. This revision replaces that per-IP counter with a single-owner global counter. Local regressions pass; live verification of the fix and restart persistence follows deployment.

## Still required on the deployed service

- Verify runtime/build, health, HTTP-to-HTTPS redirection, login/CSRF, and anonymous rejection on both service and custom hostnames.
- Verify Render proxy forwarding and resistance to spoofed forwarding headers, including login throttling.
- Send synthetic messages in both directions; retry the same IDs; restart and confirm retained messages remain.
- Verify approved `lab.dobeworks.com` DNS and certificate; preserve other domain records.
- Confirm current Muse/Grok environments can send bearer-authenticated HTTP and run the print-only client. No current VM state or native webhook contract has been verified.
- Establish and test a backup/restore procedure before storing important information.

Browser layout has not been visually checked. Full custom-domain and end-to-end phone integration remain unverified. The local passing tests do not claim those outcomes.
