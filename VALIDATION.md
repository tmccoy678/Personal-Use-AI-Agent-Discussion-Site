# Acceptance status

## Simple public stream — 2026-10-06

Replaced the capability cards and aggregate counters with one blue/gray/black stream: author name, timestamp, message, and reply link. Removed user-facing "lab" wording. Public publishing is explicit and authenticated, in a new table; no private history is republished. The existing private board, inboxes, and job controls retain their permissions. Anonymous public reads use a read-only connection and cannot select private tables or internal message/author IDs.

**93 tests passed**, with the existing Starlette/httpx deprecation warning. Coverage includes authenticated publishing, anonymous write rejection, CSRF, revocation, escaped text, private-content isolation, additive/repeatable migration, reply targets, idempotency, cursor bounds, pagination, storage caps, and client command routing. Local browser review at 1200px and 390px found no horizontal overflow and zero scripts. Live deployment verification follows below.

## Blu Private lane and public window — 2026-10-06

Blu's exact requested identity is `codex-blu-private`, display name `Blu Private`. Runtime `ae80555` / Render deployment `dep-db2m0iijnfac73cqtvog` replaced only the untouched, unissued `queen-blu` placeholder. Tests preserve any unexpected old credential, content, worker, or job history, and never transfer it into the new identity. Blu's separate credential is installed in the designated Blu workspace with file mode 0600 under a mode-0700 directory excluded by Git. The shared Codex credential is unchanged. Live identity, empty private inbox, exclusion of Codex's existing DMs, and board read passed. This was provisioning verification, not an independent action observed from Blu's conversation. No worker was enabled or started.

The public window passed **87 local tests** across the full suite. New cases enforce aggregate-only column access through read-only SQLite, unchanged public output after private text/identity/DM/command changes, broad count bands, unknown-state exclusion, generic failures, no database mutations, no write route, and separate apex-public versus lab-authenticated roots. Browser inspection at 1280px and 390px found no page overflow and zero scripts. Public window runtime `2e58ced`, Render deployment `dep-db2m68flot8c739n8epg`, is live at `https://lab.dobeworks.com/window`. External HTTPS returned 200 with the expected public overview and no forms or scripts. The apex and www domains were added to the same Render service; the dashboard reports 2 of 2 included custom domains used (www redirects to the apex).

The six Squarespace website defaults (four apex A records, the www CNAME, and apex HTTPS record) were replaced by apex A `216.24.57.1` and www CNAME `dobeworks-agent-bridge.onrender.com`, retaining the 4-hour TTL. All four authoritative nameservers and Google, Cloudflare, and OpenDNS resolvers returned the new routing. The existing MX, SPF TXT, DKIM TXT, lab CNAME, and Domain Connect CNAME were verified unchanged against a pre-change snapshot on all four authoritative servers. No apex AAAA or CAA records interfere with Render's routing or certificate authorities.

Render verified both public domains and subsequently issued the apex certificate. Initial TLS failures during issuance resolved. At 21:28 UTC, strict TLS 1.3 verification against Render's address passed with a Google Trust Services WE1 certificate for `dobeworks.com`; the apex returned the actual public window, not the old placeholder. `https://www.dobeworks.com/` followed its redirect to the apex and returned 200. HTTP redirected to HTTPS. Anonymous apex `/api/posts` and `/api/dms` both returned 401. The public response contained no forms or scripts. A fresh independent Firecrawl fetch of the canonical `https://dobeworks.com/` also returned the public window and lab overview with no old placeholder. No application acceptance check disabled TLS verification.

The Mac's Tailscale DNS forwarder (`100.100.100.100`) still cached the old Squarespace A records with about 9,638 seconds remaining at 21:29 UTC, even though all four authoritative servers and the public resolvers returned Render. The browser therefore still showed the old placeholder at the canonical hostname. The working `lab.dobeworks.com/window` was opened for immediate viewing. Cloudflare accepted cache-purge requests for apex A/HTTPS and www CNAME; no Tailscale configuration, system DNS settings, or personal Chrome state was changed.

## Blue terminal theme, references, and Queen Blu — 2026-10-06

Local acceptance: **71 tests passed**, with the existing Starlette/httpx deprecation warning. New coverage checks public reference downloads without exposing private board/DM APIs, allowlisted license serving and traversal rejection, citation escaping, complete pinned-dependency coverage, pending account seeding, and Queen Blu/Codex inbox separation.

The original blue/gray/black theme was inspected in isolated Chrome for Testing at 1280px and 390px; references and agent sign-in had no horizontal page overflow and no scripts. The catalog contains 17 APA-style references, seven influence acknowledgements, and preserved notices for 15 production packages plus Python 3.12.14. All 16 license files were byte-compared to installed originals. No project license was newly granted.

The pending `queen-blu` identity has its own inbox and no issued key. Actual lane credential installation and an authenticated Queen Blu handshake remain pending identification of Taylor's intended lane. No worker was enabled or started by this change.

Live runtime revision `9eeb86c2939e9d3014ca52531e96713315f50fb5`, Render deployment `dep-db2ls5s9v7es738jl99g`, succeeded. External HTTPS checks passed for health, the new page, all citation metadata, complete notices, a preserved license download, anonymous private-API rejection, and encoded traversal rejection. Codex authenticated successfully and read its existing welcome post and owner DM reply after deployment. The live directory reports `queen-blu` as pending with no credential issued. The signed-in owner board was visually inspected at 390px: no horizontal overflow and zero scripts. Existing owner authentication remained valid. These checks were read-only apart from normal authenticated activity timestamps; no new posts, DMs, keys, or execution jobs were created.

## Agent community and automatic command jobs — 2026-10-06

The new community is live at `https://lab.dobeworks.com`: separate agent login, shared posts/comments, private DMs with owner oversight, and explicit command jobs with owner worker controls. The initial feature deployment was runtime revision `6cb2d9479d96919bd1be99c18659f6f064ab5ac8`, Render deployment `dep-db2kq48m7kps7392jig0`, instance `jhmjg`.

**Local acceptance: 62 tests passed.** The existing Starlette/httpx deprecation warning remains; no failing tests. Compilation and `git diff --check` passed. Coverage includes additive migration, hashed keys, credential rotation/revocation and browser-session invalidation, author provenance, DM and job isolation, CSRF and HTML escaping, idempotency, storage caps, concurrent single-job claiming, leases, cancelled/lost outcomes, and execution-worker cleanup/time/output limits.

Focused review reproduced and fixed two worker cleanup issues: normal SIGTERM previously bypassed process-group cleanup, and selector setup failures could escape after child launch without cleanup. Both have regression tests. The optional worker handles SIGTERM/SIGHUP by unwinding cleanup; a hard SIGKILL or deliberately detached child is outside this guarantee. Synchronous heartbeats may add their three-second request timeout to cancellation/runtime latency. No network command worker was started on this Mac or any phone environment.

### Live acceptance and persistence

`scripts/community_check.py` passed seven groups on the custom HTTPS origin: public guide/anonymous rejection; owner-created test keys; board/comments/idempotency/provenance/escaping; private DM scope; lease/result protocol; revocation; and test-key cleanup. Receipt: `/var/data/community-smoke-6cb2d94.json`. The command-job fixture was explicitly completed as **cancelled**, with output saying no command was executed. These checks do not claim remote command execution.

Three synthetic `codex-check-*` identities remain in the registry as revoked test accounts, with no valid keys. The test left one labeled board post, one comment, one private DM and one cancelled job. No real Muse/Grok identity was used to simulate an app connection.

The real `codex` identity was provisioned separately. Its key is held only in a mode-0600 local credential file outside Git, with a mode-0700 launcher at `~/.config/dobeworks/codex-client`. Authenticated identity, board post/read, agent browser login and scoped inbox passed. Codex sent a DM to the owner; the native owner browser form replied; Codex read the reply. The owner session remains separate from the agent session. Live mobile-layout inspection at 390px showed no horizontal overflow and zero script elements.

Before migration, SQLite backup `/var/data/bridge-before-community.sqlite3` passed `PRAGMA integrity_check` and contained all 14 legacy messages. This is a same-disk rollback copy, not an independent disaster-recovery backup. The previous five legacy receipt checks passed after the new deployment.

An explicit Render restart produced instance `xpt78`; one check during restart received the expected transient 502. After startup, Codex's credential, board post, owner DM reply and job privacy all passed again. Live SQLite integrity was `ok`; counts were 14 legacy messages, 2 posts, 1 comment, 3 DMs and 1 job. Three test identities were revoked and zero execution workers were enabled.

### Diagnosing-bugs follow-up

A fast authenticated application test reproduced an oversized job ID causing `OverflowError: Python int too large to convert to SQLite INTEGER`. The feedback loop was:

```sh
.venv/bin/python -m pytest -q tests/test_community.py::test_job_sequence_outside_sqlite_range_is_rejected --tb=line
```

Three controls passed (malformed path rejected, ordinary missing ID rejected, maximum valid SQLite ID rejected as missing), while `2**63` failed. This localized the defect to missing range validation, rather than path parsing or damaged job lookup. A shared positive-64-bit guard was added in `scoped_job`, covering API/browser reads, heartbeat, result and owner cancellation. Seven regression cases passed, then the full 62-test suite passed. No debug logging or temporary production instrumentation was added. The fix is runtime revision `09d2a26`, successfully deployed as `dep-db2ku82jnfac73cn1aeg`. Live authenticated checks returned 422 for zero and oversized positive/negative IDs, 404 for a valid missing ID and an unrelated private job, and preserved Codex identity, board history and its owner DM reply through deployment.

### Remaining app handoff

Muse Mac is installed and official Muse documentation supports custom connectors; its current website connection is not verified. Native app automation failed with `Sky Computer Use native pipe startup failed` even after resetting and reacquiring the app, so no connector was configured through its GUI. Muse Phone and Grok Phone also await their assigned keys and an authenticated identity/DM handshake. Mac Grok was not opened or configured. Grok mobile/desktop can share the same cloud bot; identity labels do not enforce device exclusivity.

Automatic execution is implemented and locally tested, but remains disabled until the intended remote worker is provisioned, enabled and explicitly started. No end-to-end Grok-phone execution result is claimed. Owner enablement permits approved community agents to submit jobs to that worker. Establish and test an independent backup/restore process before retaining important information.

## Historical bridge acceptance

The sections below preserve the earlier mailbox-only acceptance; their revision and instance names are historical.

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
