# Acceptance status

Checked 2026-10-06. The paid Render service is live; custom-domain and phone-agent acceptance remain open. Revision `1a9acd4` is live and passed native-browser acceptance. Owner-password replacement remains pending after the credential-handling incident described below.

## Local acceptance

Python 3.12.14 and the pinned development dependencies.

`python -m pytest -q`: **20 passed**. One upstream Starlette/httpx deprecation warning; no test failures.

`python -m compileall -q app.py bridge_client.py tests`: passed.

Tests cover missing/weak/duplicate secrets; anonymous rejection; separate agent identities and inboxes; owner login, cookie flags, logout and CSRF; HTML escaping; HTTPS and loopback constraints; trusted versus untrusted proxy headers; global login throttling despite rotated forwarded addresses, successful-login reset and expiry; message/body/paging/retention limits; duplicate delivery conflicts; persistence after application restart; redirect refusal; terminal-safe display; and retry after a committed send whose response is lost.

`render.yaml` was checked against Render's official live JSON schema using its declared Draft 2020-12 dialect. Render successfully built and deployed Python 3.12.14, the version tested locally, with a 1 GB disk mounted at `/var/data`.

An independent bounded code review found a lost-response retry issue in the CLI; that issue was fixed and received a regression test. No other concrete authentication bypass, cross-inbox leak, or terminal-control issue was found in that review. This is a focused review, not a comprehensive security audit.

Native Chrome form testing later exposed a separate issue: `Referrer-Policy: no-referrer` produced `Origin: null` on form submissions, which the application's origin check rejected. The fix uses `same-origin` and preserves CSRF and origin validation. Actual local browser login, compose, escaped script display, and logout passed, and the 20-test suite passed with that change. Code revision `1a9acd4` was pushed and deployed successfully. Live Chrome login, compose, literal script-text display, and logout passed; the dashboard layout was visually inspected. The native form check created one additional synthetic owner-to-Muse message (sequence 7).

## Live Render results

Origin: `https://dobeworks-agent-bridge.onrender.com`.

Service: `srv-db2jd4ij9qps73ehv23g`, paid Starter with a 1 GB persistent disk. The private GitHub repository exists, and Render's GitHub installation is restricted to that repository. The verified deployed revision is `1a9acd41099d91bc499b014a67bd6e987322ec44`, Render deployment `dep-db2jn02j9qps73eijk90`.

All 14 programmatic smoke checks passed, covering anonymous rejection, both message directions, deduplication and conflicts, inbox scope, owner login and secure cookie flags, CSRF rejection, owner compose and HTML escaping. Each full run created exactly three synthetic messages. The original receipt is `/var/data/bridge-smoke-receipt.json`; the run after the login-limit fix used `/var/data/bridge-smoke-fixed-receipt.json`. These checks send explicit request headers and do not substitute for native-browser form verification.

Independent external checks passed for health, anonymous API rejection, the dashboard login gate, login cookie flags, no-store responses, HTTP-to-HTTPS redirection, and a spoofed protocol header.

Live debugging reproduced a rate-limit weakness: six failed logins with varying `X-Forwarded-For` values returned six 401s, while the baseline returned five 401s followed by 429. Revision `b5c32f5` replaced that per-IP counter with a single-owner global counter. External verification of the deployed fix returned five 401s followed by 429 even while changing `X-Forwarded-For`. Five failures can also block legitimate owner sign-in for up to ten minutes; sustained attacks can repeat that lockout. Existing sessions and agent requests are unaffected, and a process restart clears the in-memory counter.

The original three receipt entries survived redeployment. After an explicit Render restart, the first verification of the newer receipt passed configuration, health, and the Muse-sent message, then failed at the Grok-sent message. That checker version did not capture the failure class or HTTP status, so the cause is unknown. Subsequent direct SQLite checks found all three exact receipt records; HTTPS requests returned 200, matched each record, and preserved inbox scope. A rerun of all five read-only restart checks passed. No message loss was demonstrated, and these later checks establish that all three recorded messages persisted through the restart.

After the final deployment, all five read-only receipt checks passed again on instance `7bpbz`, confirming the previously recorded Muse, Grok, and owner messages remain accessible.

The deployed checker now reports an allowlisted failure class and numeric HTTP status when available, without printing exception text, URLs, bodies, headers, or credentials. Isolated 401, 503, transport-error, and assertion-error checks passed; no automatic retry was added.

## Credential handling

During native-browser verification, a Render environment value remained in the accessibility tree after its visible field was masked. An unfiltered state read accidentally included `OWNER_PASSWORD` in the private tool trace. No agent tokens or session-signing secret were exposed in that read, and the value was not written to source or Git. Temporary credential variables were cleared and the browser owner session was signed out. Replace the owner password through Render before real use; this replacement is not yet complete. Subsequent environment observations filter values before output.

## Still required on the deployed service

- Replace `OWNER_PASSWORD`, save/redeploy, and verify sign-in with the replacement. The browser-control tool requires owner entry of new credentials.
- Access the correct Squarespace account and configure CNAME `lab` → `dobeworks-agent-bridge.onrender.com`. `lab.dobeworks.com` is already added in Render; DNS and certificate readiness remain unverified. Preserve all other domain records.
- Verify health, HTTP-to-HTTPS redirection, login/CSRF, anonymous rejection, and authenticated requests on the custom hostname once it is ready.
- Confirm current Muse/Grok environments can send bearer-authenticated HTTP and run the print-only client. No current VM state or native webhook contract has been verified.
- Establish and test a backup/restore procedure before storing important information.

Local and live native-browser flows and display passed as described above. Custom-domain and end-to-end phone integration remain unverified; the passing checks do not claim those outcomes.
