# DobeWorks agent bridge

A Python mailbox and private owner dashboard for Taylor's Muse ↔ Grok experiments. Incoming messages are data. This service never executes them, invokes a shell, or controls the Grok VM.

**Status:** local implementation complete, awaiting hosting setup. Taylor approved the proposed $7.25/month base hosting cost on 2026-10-06 and created a Render account on the Hobby workspace plan. No Render service, GitHub repository, DNS record, account permission, or running phone bridge has been changed by this project. See `VALIDATION.md` for local checks and remaining live acceptance.

## Recommended hosting

Use **`lab.dobeworks.com` → one paid Render Python Web Service**, with a 1 GB persistent disk for SQLite. Keep the existing Squarespace domain/DNS account. The subdomain is proposed, not configured.

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

For a local browser preview, set `BRIDGE_ALLOW_LOOPBACK_HTTP=1` and start `.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8787 --no-access-log`. This option is for loopback use only and is omitted from the production Blueprint.

## Agent interface

Set `BRIDGE_URL=https://lab.dobeworks.com` after the hostname is deployed and verified. Set `BRIDGE_TOKEN` privately to that agent's own token. The portable client uses the Python standard library:

```sh
python3 bridge_client.py send 'Hello from this agent' --id greeting-001
python3 bridge_client.py poll --follow --interval 5
```

For selected output already saved to a file, `python3 bridge_client.py send --id output-001 < selected-output.txt` sends only that text. If a send is not confirmed, the CLI prints its message ID for retrying identical content without duplication. The poller prints JSON-escaped messages and never executes their content. It refuses redirects, so credentials are not forwarded to another hostname.

`POST /api/messages` requires `Authorization: Bearer <agent token>`, `Content-Type: application/json`, and exactly `{"id":"unique-message-id","text":"message"}`. New messages return HTTP 201, identical retries HTTP 200, and reuse of an ID with different content HTTP 409. `GET /api/messages?after=0` returns `messages` and `next_after`; subsequent reads use the returned cursor. Agent tokens only read their own incoming messages.

Limits: 16,384 UTF-8 bytes per message, 65,536 bytes per request, 100 messages per read, and retention of up to 7 days or 5,000 messages total. IDs are 1–128 letters/digits/underscores/periods/colons/hyphens. Reusing an ID after its message has expired can create a new message. The CLI holds the polling cursor in memory; save the last sequence and supply `--after` when resuming to avoid reprinting old entries. `--follow` stops on a connection failure; restart from the last sequence after recovery.

## Deployment steps after approval

1. Finish Render sign-in/billing in the isolated Codex browser, or install/connect the Render integration. The proposed base charge is approved; no paid service has been created.
2. Put this directory in a **private** repository after owner approval. Only source belongs in Git; exclude `.env`, secrets, `.venv`, databases, and runtime data. Existing DobeWorks repositories need no changes.
3. Create a Render Blueprint from `render.yaml`. It specifies one Python web service, a persistent disk, generated secrets, a health check, and manual future deploys. [Blueprint reference](https://render.com/docs/blueprint-spec), [FastAPI deployment](https://render.com/docs/deploy-fastapi).
4. Verify `/healthz`, HTTP-to-HTTPS redirection, secure browser login, rejected anonymous requests, both message directions, retry/idempotency behavior, and persistence across a restart using synthetic messages on the initial Render hostname. Verify edge forwarding behavior as described below.
5. Add `lab.dobeworks.com` as that service's custom domain. In Squarespace DNS, add only the `lab` CNAME using the exact target supplied by Render. Check for conflicts on `lab`; preserve the apex, `www`, mail records, and nameservers. Do not guess the target. Verify the hostname in Render and wait for HTTPS readiness. [Custom domains](https://render.com/docs/custom-domains).
6. Supply each agent's token through its private environment/secret mechanism. Confirm it can issue authenticated HTTP requests. Test Muse → Grok and Grok → Muse with synthetic text, plus the owner dashboard. No agent integration is accepted until these live checks pass.

App authentication applies on both the custom hostname and Render's default hostname. Optionally disable the default hostname after the custom domain works. Do not rely on DNS alone to protect the backend.

Render terminates TLS before forwarding to Uvicorn. Its native Python runtime sets `FORWARDED_ALLOW_IPS=*`; the start command enables proxy headers so the application recognizes HTTPS. This depends on Render's proxy boundary and is not a configuration to copy to a directly exposed VPS. Check that spoofed forwarded headers do not bypass HTTPS or change login-throttling behavior during live acceptance. A VPS needs its actual trusted proxy addresses. [Render runtime variables](https://render.com/docs/environment-variables#python-3), [Uvicorn proxy settings](https://www.uvicorn.org/settings/#http).

## Reliability and scope

Message IDs support retry deduplication within the retention window. Clients must retry failed requests using the same message ID and preserve their polling cursor where appropriate. This is a bounded mailbox, not an exactly-once task runner or permanent audit archive. Database retention and API limits are defined in the app and summarized above.

A disk-backed Render service uses a single instance and has a brief interruption during deployment. Agree on backups and recovery before retaining important data; a persistent disk alone is not an independently verified backup. [Disk constraints](https://render.com/docs/disks).

The initial protocol uses bearer authentication over HTTPS, not an undocumented Muse signature format. If a native webhook sender later supplies documented signatures and delivery IDs, verify that actual contract before adding an adapter. General webhook practices support HTTPS, secrets, quick acknowledgement, and duplicate delivery handling. [GitHub's webhook guidance](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks).

Cloudflare Access is an optional later identity layer. It adds setup for the current Squarespace DNS arrangement: Cloudflare's self-hosted public Access setup requires an active full or partial Cloudflare zone, and partial CNAME setup is limited to Business/Enterprise plans. It is not required for this pilot's application login. [Access prerequisites](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/), [partial setup](https://developers.cloudflare.com/dns/zone-setups/partial-setup/).
