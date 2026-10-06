# Local acceptance

Checked 2026-10-06 using Python 3.12.14 and the pinned development dependencies.

`python -m pytest -q`: **18 passed**. One upstream Starlette/httpx deprecation warning; no test failures.

`python -m compileall -q app.py bridge_client.py tests`: passed.

Tests cover missing/weak/duplicate secrets; anonymous rejection; separate agent identities and inboxes; owner login, cookie flags, logout and CSRF; HTML escaping; HTTPS and loopback constraints; trusted versus untrusted proxy headers; message/body/paging/retention limits; duplicate delivery conflicts; persistence after application restart; redirect refusal; terminal-safe display; and retry after a committed send whose response is lost.

`render.yaml` was checked against Render's official live JSON schema using its declared Draft 2020-12 dialect. The final deployment target is the same Python 3.12.14 tested locally. No remote validation or deployment has occurred.

An independent bounded code review found a lost-response retry issue in the CLI; that issue was fixed and received a regression test. No other concrete authentication bypass, cross-inbox leak, or terminal-control issue was found in that review. This is a focused review, not a comprehensive security audit.

## Still required on the deployed service

- Verify runtime/build, health, HTTP-to-HTTPS redirection, login/CSRF, and anonymous rejection on both service and custom hostnames.
- Verify Render proxy forwarding and resistance to spoofed forwarding headers, including login throttling.
- Send synthetic messages in both directions; retry the same IDs; restart and confirm retained messages remain.
- Verify approved `lab.dobeworks.com` DNS and certificate; preserve other domain records.
- Confirm current Muse/Grok environments can send bearer-authenticated HTTP and run the print-only client. No current VM state or native webhook contract has been verified.
- Establish and test a backup/restore procedure before storing important information.

Browser layout has not been visually checked. Live hosting and end-to-end phone integration remain unverified. The local passing tests do not claim those outcomes.
