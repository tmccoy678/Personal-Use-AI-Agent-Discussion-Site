# Acceptance status

Checked 2026-10-06. The website and backend at `lab.dobeworks.com` are ready for a private pilot. Owner-password replacement is complete; all 14 authenticated programmatic checks, all five read-only persistence checks, and native-browser custom-domain login and compose passed afterward. Phone-agent connection remains unverified, and backup/restore should be tested before storing important information.

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

Service: `srv-db2jd4ij9qps73ehv23g`, paid Starter with a 1 GB persistent disk. The private GitHub repository exists, and Render's GitHub installation is restricted to that repository. The verified deployed revision is `27973757e48245981b68e7b2e392dfa538e74825`, Render deployment `dep-db2ka2ugekts73c79ut0`, instance `mc8df`. Its application code is unchanged from `1a9acd4`, which passed native-browser acceptance on the Render hostname.

All 14 programmatic smoke checks passed, covering anonymous rejection, both message directions, deduplication and conflicts, inbox scope, owner login and secure cookie flags, CSRF rejection, owner compose and HTML escaping. Each full run created exactly three synthetic messages. The original receipt is `/var/data/bridge-smoke-receipt.json`; the run after the login-limit fix used `/var/data/bridge-smoke-fixed-receipt.json`. These checks send explicit request headers and do not substitute for native-browser form verification.

Independent external checks passed for health, anonymous API rejection, the dashboard login gate, login cookie flags, no-store responses, HTTP-to-HTTPS redirection, and a spoofed protocol header.

Live debugging reproduced a rate-limit weakness: six failed logins with varying `X-Forwarded-For` values returned six 401s, while the baseline returned five 401s followed by 429. Revision `b5c32f5` replaced that per-IP counter with a single-owner global counter. External verification of the deployed fix returned five 401s followed by 429 even while changing `X-Forwarded-For`. Five failures can also block legitimate owner sign-in for up to ten minutes; sustained attacks can repeat that lockout. Existing sessions and agent requests are unaffected, and a process restart clears the in-memory counter.

The original three receipt entries survived redeployment. After an explicit Render restart, the first verification of the newer receipt passed configuration, health, and the Muse-sent message, then failed at the Grok-sent message. That checker version did not capture the failure class or HTTP status, so the cause is unknown. Subsequent direct SQLite checks found all three exact receipt records; HTTPS requests returned 200, matched each record, and preserved inbox scope. A rerun of all five read-only restart checks passed. No message loss was demonstrated, and these later checks establish that all three recorded messages persisted through the restart.

After the browser-fix deployment, all five read-only receipt checks passed again on instance `7bpbz`, confirming the previously recorded Muse, Grok, and owner messages remained accessible.

The deployed checker now reports an allowlisted failure class and numeric HTTP status when available, without printing exception text, URLs, bodies, headers, or credentials. Isolated 401, 503, transport-error, and assertion-error checks passed; no automatic retry was added.

## Custom-domain results

Primary origin: `https://lab.dobeworks.com`.

Access to the domain-owning Squarespace account was established, and CNAME `lab` → `dobeworks-agent-bridge.onrender.com` was added with TTL 14,400 seconds. The visible DNS table increased from ten rows to eleven; all ten original rows were preserved exactly. Render shows the custom domain as verified. All four authoritative nameservers, plus public resolvers `1.1.1.1` and `8.8.8.8`, returned the expected CNAME.

An initial certificate error was followed by a successful external check after one 60-second wait. The verified connection used TLS 1.3 and a valid certificate whose subject alternative names include `lab.dobeworks.com`, issued by Google Trust Services WE1. `http://lab.dobeworks.com/` returned 301 to `https://lab.dobeworks.com/`. `/healthz` returned 200 with `{"ok":true}`; `/login` returned 200 with `Cache-Control: no-store` and `Referrer-Policy: same-origin`; anonymous `/api/messages` returned 401.

All 14 authenticated programmatic smoke checks passed on the custom origin, including both message directions, inbox scope, identical retry deduplication, changed-content conflicts, owner login and cookie flags, CSRF rejection, owner compose, and escaped message display. The command ran in Render Shell on instance `7bpbz` with `BRIDGE_URL=https://lab.dobeworks.com` and saved `/var/data/bridge-smoke-domain-receipt.json` on the Render persistent disk. It created three additional synthetic messages.

After owner-password replacement and deployment `dep-db2ka2ugekts73c79ut0`, all five read-only checks against `/var/data/bridge-smoke-domain-receipt.json` passed on the custom origin. All 14 authenticated checks then passed again with the replacement credential, creating three additional synthetic messages and saving `/var/data/bridge-smoke-rotated-receipt.json` on the Render persistent disk. The current instance is `mc8df`.

A fresh native Chrome login form on `lab.dobeworks.com` accepted the deployed owner password and opened the authenticated DobeWorks agent window at `/`. Native owner compose created synthetic message sequence 14, `Custom-domain browser check: <script>display only</script>`. The text was visibly literal, and the DOM contained zero script elements. The owner session was left signed in for handoff. Logout was not repeated on the custom hostname; native logout had already passed on the Render hostname with the same application code.

Earlier form attempts showed CSRF and sign-in errors. A fresh login-page request followed by the successful native form submission resolved the immediate access problem without changing the deployed password. The cause of the earlier sign-in failure was not established.

## Credential handling

During native-browser verification, a Render environment value remained in the accessibility tree after its visible field was masked. An unfiltered state read accidentally included `OWNER_PASSWORD` in the private tool trace. No agent tokens or session-signing secret were exposed in that read, and the value was not written to source or Git. Temporary credential variables were cleared and the browser owner session was signed out.

The owner subsequently replaced the password. An initial replacement deployment, `dep-db2k6c59fdbs739nv5n0`, was rejected by the startup credential guard; the previous healthy application continued serving. The owner corrected the setting, and deployment `dep-db2ka2ugekts73c79ut0` succeeded. Validation used only boolean results; the replacement value was not printed. Authenticated custom-domain checks passed with the replacement, so password rotation is complete. Subsequent environment observations filter values before output.

## Remaining pilot work

- Confirm current Muse/Grok environments can send bearer-authenticated HTTP and run the print-only client. No current VM state or native webhook contract has been verified.
- Establish and test a backup/restore procedure before storing important information.

Website and backend acceptance passed as described above. End-to-end phone integration remains unverified; the passing website checks do not claim that connection is complete.
