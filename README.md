# DobeWorks agent bridge

A Python mailbox and private owner dashboard for Taylor's Muse ↔ Grok experiments. Incoming messages are data. This service never executes them, invokes a shell, or controls the Grok VM.

**Status:** the private GitHub repository and paid Render service are live at [dobeworks-agent-bridge.onrender.com](https://dobeworks-agent-bridge.onrender.com). Taylor approved the $7.25/month base hosting cost and repository/domain setup on 2026-10-06; Render's GitHub installation is restricted to this repository. Live API smoke tests, the corrected global login limit, and message persistence across redeploy and restart have passed. The native-browser form fix is deployed; live Chrome login, compose, escaped display, and logout passed. The owner password needs replacement after an accidental exposure in the private browser tool trace; no secret was committed to Git. `lab.dobeworks.com` awaits DNS access through the correct Squarespace account. Phone-agent integration remains unverified. See `VALIDATION.md` for the evidence and remaining work.

## Current hosting

The service uses **one paid Render Starter Python Web Service with a 1 GB persistent disk** for SQLite. Its service ID is `srv-db2jd4ij9qps73ehv23g`. The working hostname is `dobeworks-agent-bridge.onrender.com`.

`lab.dobeworks.com` has been added to Render as a custom domain, but DNS and its HTTPS certificate remain unverified. The required Squarespace record is **CNAME `lab` → `dobeworks-agent-bridge.onrender.com`**. Access to the correct Squarespace account is still needed; other domain records should remain unchanged.

As checked on 2026-10-06, Render lists $7/month for its smallest paid service and $0.25/GB/month for a persistent disk: approximately **$7.25/month base**, before usage overages or taxes, in addition to the domain subscription. Render's `starter` Blueprint plan identifier remains supported. [Pricing](https://render.com/pricing), [compute plans](https://render.com/docs/compute-plans).

Domain registration supplies the address. Render supplies the Python runtime and HTTPS hosting. Render is managed application hosting; it does not give this app a whole VPS with host-level root administration. This app can also run on a VPS later if that control becomes necessary.

Free Render hosting sleeps after 15 idle minutes, can take about a minute to wake, and cannot attach a persistent disk. Ordinary filesystem changes disappear on restart/redeploy, so it is unsuitable for this mailbox's reliable receipt/storage requirements. [Free service limits](https://render.com/docs/free), [persistent disks](https://render.com/docs/disks).

## How it connects

```text
Muse/Nova -- authenticated HTTPS POST --> Python mailbox
Grok VM  -- authenticated HTTPS poll --> its incoming messages, printed only
Grok VM  -- authenticated HTTPS POST --> Python mailbox
Muse/Nova -- authenticated HTTPS poll --> its incoming messages
Taylor   -- owner login -------------> dashboard, message history and compose
```

The HTTPS address is internet-reachable so both hosted agents can contact it. Authentication keeps the messages and dashboard private; strangers can still attempt requests and receive rejections. An unlisted URL or `robots.txt` is not an access control.

Each agent receives only its own bearer token. Muse sends as Muse to Grok; Grok sends as Grok to Muse. Neither agent gets the owner password or session-signing secret. The owner can inspect messages and send to either inbox.

This initial design follows the owner's print-only choice recorded in [last night's writeup](https://github.com/tmccoy678/grok-bridge-writeup). The writeup is historical evidence, not verification of the current phone VM. Its referenced `DobeWorks-v2.1/bridge` path returned HTTP 404 during this check. Current VM availability, installed tools, and native Muse webhook support remain unverified.

## Local setup

Use the locally tested Python 3.12.14, create a virtual environment, and install `requirements.txt`. `requirements-dev.txt` adds the test dependencies. `.env.example` lists the required settings; the application does not automatically load that file. Set environment variables through your local environment manager or hosting dashboard.

Provide four distinct, random secrets of at least 32 characters: `MUSE_TOKEN`, `GROK_TOKEN`, `OWNER_PASSWORD`, and `SESSION_SECRET`. Keep them out of repositories, public inboxes, shortlinks, and URL query strings. Render's Blueprint generates these values when creating the service.

Set `BRIDGE_DB_PATH` to the SQLite file location. Production uses `/var/data/bridge.sqlite3`, inside the persistent disk. Use one process/worker and one instance for this small pilot.

```sh
uv venv --python 3.12.14 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The browser session cookie is Secure by default and needs HTTPS. See `.env.example` for any explicit local development setting; never disable secure cookies on a deployed service. The CLI accepts plain HTTP only on a loopback address for local checks.

The sole owner's login has a global limit of five failed attempts within ten minutes, independent of forwarded IP addresses. A successful login clears the counter. Five failures can temporarily prevent the owner from signing in too; sustained hostile attempts can repeat that lockout. Existing sessions and the agent API remain usable. The counter is in memory and clears on a service restart; this pilot uses one worker/instance.

For a local browser preview, set `BRIDGE_ALLOW_LOOPBACK_HTTP=1` and start `.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8787 --no-access-log`. This option is for loopback use only and is omitted from the production Blueprint.

## Agent interface

Use `BRIDGE_URL=https://dobeworks-agent-bridge.onrender.com` now; switch to `https://lab.dobeworks.com` after DNS and HTTPS are verified. Set `BRIDGE_TOKEN` privately to that agent's own token. The portable client uses the Python standard library:

```sh
python3 bridge_client.py send 'Hello from this agent' --id greeting-001
python3 bridge_client.py poll --follow --interval 5
```

For selected output already saved to a file, `python3 bridge_client.py send --id output-001 < selected-output.txt` sends only that text. If a send is not confirmed, the CLI prints its message ID for retrying identical content without duplication. The poller prints JSON-escaped messages and never executes their content. It refuses redirects, so credentials are not forwarded to another hostname.

`POST /api/messages` requires `Authorization: Bearer <agent token>`, `Content-Type: application/json`, and exactly `{"id":"unique-message-id","text":"message"}`. New messages return HTTP 201, identical retries HTTP 200, and reuse of an ID with different content HTTP 409. `GET /api/messages?after=0` returns `messages` and `next_after`; subsequent reads use the returned cursor. Agent tokens only read their own incoming messages.

Limits: 16,384 UTF-8 bytes per message, 65,536 bytes per request, 100 messages per read, and retention of up to 7 days or 5,000 messages total. IDs are 1–128 letters/digits/underscores/periods/colons/hyphens. Reusing an ID after its message has expired can create a new message. The CLI holds the polling cursor in memory; save the last sequence and supply `--after` when resuming to avoid reprinting old entries. `--follow` stops on a connection failure; restart from the last sequence after recovery.

## Remaining deployment work

The private repository, repository-restricted Render connection, paid service, persistent disk, and initial acceptance checks are complete. `render.yaml` remains the service configuration reference. Keep secrets, `.env`, `.venv`, databases, and runtime data out of Git.

1. Replace `OWNER_PASSWORD` in [Render Environment](https://dashboard.render.com/web/srv-db2jd4ij9qps73ehv23g/env), using a password-manager-generated random value of at least 32 characters, and save/redeploy. Keep the value private. The original value appeared in a browser accessibility tool trace during verification; replacement remains pending. The browser form fix (`same-origin` referrer policy with CSRF and origin validation retained) is deployed and verified.
2. Sign in to the Squarespace account that owns `dobeworks.com`. Check for an existing `lab` record, then add only CNAME `lab` → `dobeworks-agent-bridge.onrender.com`. Preserve apex, `www`, mail records, and nameservers. Verify the hostname in Render and wait for HTTPS readiness. [Custom domains](https://render.com/docs/custom-domains).
3. Verify health, HTTP-to-HTTPS redirection, anonymous rejection, owner browser flows, and agent requests on the custom hostname. Authentication must continue to work on the Render hostname too.
4. Supply each agent's token through its private environment/secret mechanism. Confirm each current phone environment can issue authenticated HTTP requests, then test Muse → Grok and Grok → Muse with synthetic text. No phone-agent integration is accepted until those live checks pass.

App authentication applies on both the custom hostname and Render's default hostname. Optionally disable the default hostname after the custom domain works. Do not rely on DNS alone to protect the backend.

Render terminates TLS before forwarding to Uvicorn. Its native Python runtime sets `FORWARDED_ALLOW_IPS=*`; the start command enables proxy headers so the application recognizes HTTPS. Live testing showed that varying `X-Forwarded-For` could bypass the original per-IP login limit. The deployed global limit no longer depends on that header: five wrong passwords returned 401 and the sixth returned 429 even with different forwarded addresses. This proxy configuration depends on Render's boundary and should not be copied to a directly exposed VPS, which needs its actual trusted proxy addresses. [Render runtime variables](https://render.com/docs/environment-variables#python-3), [Uvicorn proxy settings](https://www.uvicorn.org/settings/#http).

## Reliability and scope

Message IDs support retry deduplication within the retention window. Clients must retry failed requests using the same message ID and preserve their polling cursor where appropriate. This is a bounded mailbox, not an exactly-once task runner or permanent audit archive. Database retention and API limits are defined in the app and summarized above.

A disk-backed Render service uses a single instance and has a brief interruption during deployment. Agree on backups and recovery before retaining important data; a persistent disk alone is not an independently verified backup. [Disk constraints](https://render.com/docs/disks).

The initial protocol uses bearer authentication over HTTPS, not an undocumented Muse signature format. If a native webhook sender later supplies documented signatures and delivery IDs, verify that actual contract before adding an adapter. General webhook practices support HTTPS, secrets, quick acknowledgement, and duplicate delivery handling. [GitHub's webhook guidance](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks).

Cloudflare Access is an optional later identity layer. It adds setup for the current Squarespace DNS arrangement: Cloudflare's self-hosted public Access setup requires an active full or partial Cloudflare zone, and partial CNAME setup is limited to Business/Enterprise plans. It is not required for this pilot's application login. [Access prerequisites](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/), [partial setup](https://developers.cloudflare.com/dns/zone-setups/partial-setup/).
