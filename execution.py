"""Explicit, opt-in remote command jobs; board posts and DMs are never commands."""
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from html import escape

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

MAX_COMMAND_BYTES = 8192
MAX_OUTPUT_BYTES = 65536
MAX_RESULT_BODY_BYTES = 448 * 1024
MAX_JOBS = 1000
LEASE_SECONDS = 30
MAX_TIMEOUT_SECONDS = 300
PAGE_SIZE = 25
ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
FINAL_STATES = {"succeeded", "failed", "timed_out", "cancelled"}


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS execution_workers (
        agent_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS execution_jobs (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT NOT NULL, submitter_id TEXT NOT NULL, worker_id TEXT NOT NULL,
        command TEXT NOT NULL, timeout_seconds INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL,
        claimed_at INTEGER, finished_at INTEGER, lease_expires_at INTEGER,
        execution_deadline INTEGER, lease_hash TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        exit_code INTEGER, output TEXT NOT NULL DEFAULT '',
        truncated INTEGER NOT NULL DEFAULT 0,
        UNIQUE(submitter_id,id))""")
    db.execute("CREATE INDEX IF NOT EXISTS execution_claim ON execution_jobs(worker_id,status,sequence)")
    db.execute("CREATE INDEX IF NOT EXISTS execution_submitter ON execution_jobs(submitter_id,sequence)")


def revoke_agent(db, agent_id):
    """Call in the same transaction that revokes an agent credential."""
    db.execute("UPDATE execution_workers SET enabled=0,updated_at=? WHERE agent_id=?", (now(), agent_id))
    db.execute("""UPDATE execution_jobs SET status='cancelled',cancel_requested=1,finished_at=?
        WHERE status='pending' AND (worker_id=? OR submitter_id=?)""", (now(), agent_id, agent_id))
    db.execute("""UPDATE execution_jobs SET cancel_requested=1
        WHERE status='running' AND (worker_id=? OR submitter_id=?)""", (agent_id, agent_id))


def now():
    return int(time.time())


def hash_lease(value):
    return hashlib.sha256(value.encode()).hexdigest()


def expire(db):
    # A command may have run even if the worker disappeared. Never requeue it.
    db.execute("""UPDATE execution_jobs SET status='lost',finished_at=?
        WHERE status='running' AND lease_expires_at<=?""", (now(), now()))


def public_job(row, *, detail=True):
    result = dict(row)
    result.pop("lease_hash", None)
    result["cancel_requested"] = bool(result["cancel_requested"])
    result["truncated"] = bool(result["truncated"])
    if not detail:
        result.pop("output", None)
    return result


def text_bytes(value, name, limit, *, nonempty=False):
    if not isinstance(value, str) or (nonempty and (not value.strip() or "\0" in value)):
        raise HTTPException(422, f"{name} must be a {'nonempty ' if nonempty else ''}string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise HTTPException(422, f"{name} must be valid Unicode") from None
    if size > limit:
        raise HTTPException(413, f"{name} exceeds {limit} UTF-8 bytes")


def validate_job(payload):
    if not isinstance(payload, dict) or set(payload) != {"id", "worker_id", "command", "timeout_seconds"}:
        raise HTTPException(422, "Supply exactly id, worker_id, command and timeout_seconds")
    for field in ("id", "worker_id"):
        if not isinstance(payload[field], str) or not ID_RE.fullmatch(payload[field]):
            raise HTTPException(422, f"Invalid {field}")
    text_bytes(payload["command"], "command", MAX_COMMAND_BYTES, nonempty=True)
    timeout = payload["timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise HTTPException(422, "timeout_seconds must be an integer from 1 to 300")


def ensure_target(hub, db, worker_id):
    target = hub.find_agent(db, worker_id)
    if (not target or target["role"] != "agent" or target["status"] not in ("active", "pending")
            or not target["credential_issued"]):
        raise HTTPException(422, "Worker must be a non-revoked agent with an issued credential")
    return target


def submit(hub, actor, payload):
    validate_job(payload)
    with hub.db() as db:
        db.execute("BEGIN IMMEDIATE")
        hub.check_actor(db, actor)
        if actor["role"] != "owner":
            submitter = hub.find_agent(db, actor["id"])
            if not submitter or not submitter.get("can_submit_jobs", False):
                raise HTTPException(403, "This identity cannot submit command jobs")
        expire(db)
        old = db.execute("SELECT * FROM execution_jobs WHERE submitter_id=? AND id=?",
                         (actor["id"], payload["id"])).fetchone()
        if old:
            if any(old[key] != payload[key] for key in ("worker_id", "command", "timeout_seconds")):
                raise HTTPException(409, "This id already describes a different command")
            return public_job(old), True
        ensure_target(hub, db, payload["worker_id"])
        worker = db.execute("SELECT enabled FROM execution_workers WHERE agent_id=?", (payload["worker_id"],)).fetchone()
        if not worker or not worker["enabled"]:
            raise HTTPException(409, "Worker is disabled")
        if db.execute("SELECT COUNT(*) FROM execution_jobs").fetchone()[0] >= MAX_JOBS:
            raise HTTPException(507, "Command job capacity reached; owner maintenance required")
        cursor = db.execute("""INSERT INTO execution_jobs
            (id,submitter_id,worker_id,command,timeout_seconds,created_at) VALUES(?,?,?,?,?,?)""",
            (payload["id"], actor["id"], payload["worker_id"], payload["command"], payload["timeout_seconds"], now()))
        return public_job(db.execute("SELECT * FROM execution_jobs WHERE sequence=?", (cursor.lastrowid,)).fetchone()), False


def scoped_job(db, actor, sequence):
    if type(sequence) is not int or not 1 <= sequence < 2**63:
        raise HTTPException(422, "Job sequence must be a positive 64-bit integer")
    row = db.execute("SELECT * FROM execution_jobs WHERE sequence=?", (sequence,)).fetchone()
    if not row or (actor["role"] != "owner" and actor["id"] not in (row["submitter_id"], row["worker_id"])):
        raise HTTPException(404, "Command job not found")
    return row


def check_lease(row, actor, lease):
    if actor["role"] == "owner" or row["worker_id"] != actor["id"]:
        raise HTTPException(404, "Command job not found")
    if (not isinstance(lease, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", lease)
            or not row["lease_hash"] or not hmac.compare_digest(hash_lease(lease), row["lease_hash"])):
        raise HTTPException(403, "Invalid job lease")


def list_jobs(hub, actor, after=0, *, latest=False):
    with hub.db() as db:
        db.execute("BEGIN IMMEDIATE")
        hub.check_actor(db, actor)
        expire(db)
        where, args = "sequence>?", [after]
        if actor["role"] != "owner":
            where += " AND (submitter_id=? OR worker_id=?)"
            args.extend((actor["id"], actor["id"]))
        rows = db.execute(f"SELECT * FROM execution_jobs WHERE {where} ORDER BY sequence {'DESC' if latest else 'ASC'} LIMIT ?",
                          (*args, PAGE_SIZE)).fetchall()
        return [public_job(row, detail=False) for row in rows]


def csrf_field(actor):
    return '<input type="hidden" name="csrf" value="' + escape(actor["_session"]["csrf"], quote=True) + '">'


async def result_json(request):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "Expected JSON")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_RESULT_BODY_BYTES:
            raise HTTPException(413, "Request too large")
        data.extend(chunk)
    try:
        return json.loads(data)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid JSON") from None


def install(app, hub):
    hub.on_revoke = revoke_agent

    @app.post("/api/jobs")
    async def create_job(request: Request):
        actor = hub.api_actor(request)
        job, duplicate = submit(hub, actor, await hub.json(request))
        return JSONResponse({**job, "duplicate": duplicate}, status_code=200 if duplicate else 201)

    @app.get("/api/jobs")
    async def get_jobs(request: Request, after: int = 0):
        actor = hub.api_actor(request)
        if not 0 <= after < 2**63:
            raise HTTPException(422, "Invalid cursor")
        jobs = list_jobs(hub, actor, after)
        return {"jobs": jobs, "next_after": jobs[-1]["sequence"] if jobs else after}

    @app.get("/api/jobs/{sequence}")
    async def get_job(sequence: int, request: Request):
        actor = hub.api_actor(request)
        with hub.db() as db:
            db.execute("BEGIN IMMEDIATE")
            hub.check_actor(db, actor)
            expire(db)
            return public_job(scoped_job(db, actor, sequence))

    @app.post("/api/worker/claim")
    async def claim(request: Request):
        actor = hub.api_actor(request)
        if await hub.json(request) != {}:
            raise HTTPException(422, "Supply an empty JSON object")
        with hub.db() as db:
            db.execute("BEGIN IMMEDIATE")
            hub.check_actor(db, actor)
            expire(db)
            enabled = db.execute("SELECT enabled FROM execution_workers WHERE agent_id=?", (actor["id"],)).fetchone()
            if not enabled or not enabled["enabled"]:
                raise HTTPException(409, "Worker is disabled")
            if db.execute("SELECT 1 FROM execution_jobs WHERE worker_id=? AND status='running'", (actor["id"],)).fetchone():
                return {"job": None}
            row = db.execute("SELECT * FROM execution_jobs WHERE worker_id=? AND status='pending' ORDER BY sequence LIMIT 1", (actor["id"],)).fetchone()
            if not row:
                return {"job": None}
            lease, claimed = secrets.token_urlsafe(32), now()
            deadline = claimed + row["timeout_seconds"] + LEASE_SECONDS
            db.execute("""UPDATE execution_jobs SET status='running',claimed_at=?,lease_expires_at=?,
                execution_deadline=?,lease_hash=? WHERE sequence=?""",
                (claimed, min(claimed + LEASE_SECONDS, deadline), deadline, hash_lease(lease), row["sequence"]))
            job = public_job(db.execute("SELECT * FROM execution_jobs WHERE sequence=?", (row["sequence"],)).fetchone())
            return {"job": {**job, "lease_token": lease}}

    @app.post("/api/jobs/{sequence}/heartbeat")
    async def heartbeat(sequence: int, request: Request):
        actor = hub.api_actor(request)
        payload = await hub.json(request)
        if not isinstance(payload, dict) or set(payload) != {"lease_token"}:
            raise HTTPException(422, "Supply exactly lease_token")
        with hub.db() as db:
            db.execute("BEGIN IMMEDIATE")
            hub.check_actor(db, actor)
            expire(db)
            row = scoped_job(db, actor, sequence)
            check_lease(row, actor, payload["lease_token"])
            if row["status"] != "running":
                return JSONResponse({"detail": "Job is not running; expired jobs are never automatically retried"}, status_code=409)
            expires = min(now() + LEASE_SECONDS, row["execution_deadline"])
            db.execute("UPDATE execution_jobs SET lease_expires_at=? WHERE sequence=?", (expires, sequence))
            return {"cancel_requested": bool(row["cancel_requested"]), "lease_expires_at": expires}

    @app.post("/api/jobs/{sequence}/result")
    async def result(sequence: int, request: Request):
        actor = hub.api_actor(request)
        payload = await result_json(request)
        fields = {"lease_token", "status", "exit_code", "output", "truncated"}
        if not isinstance(payload, dict) or set(payload) != fields:
            raise HTTPException(422, "Supply exactly lease_token, status, exit_code, output and truncated")
        if not isinstance(payload["status"], str) or payload["status"] not in FINAL_STATES:
            raise HTTPException(422, "Invalid completion status")
        code = payload["exit_code"]
        if code is not None and (type(code) is not int or not -(2**31) <= code < 2**31):
            raise HTTPException(422, "Invalid exit_code")
        if payload["status"] == "succeeded" and code != 0:
            raise HTTPException(422, "Successful jobs require exit_code 0")
        if type(payload["truncated"]) is not bool:
            raise HTTPException(422, "truncated must be a boolean")
        text_bytes(payload["output"], "output", MAX_OUTPUT_BYTES)
        with hub.db() as db:
            db.execute("BEGIN IMMEDIATE")
            hub.check_actor(db, actor)
            expire(db)
            row = scoped_job(db, actor, sequence)
            check_lease(row, actor, payload["lease_token"])
            if row["status"] in FINAL_STATES:
                if all(row[key] == payload[key] for key in ("status", "exit_code", "output", "truncated")):
                    return public_job(row)
                raise HTTPException(409, "Job already completed with a different result")
            if row["status"] != "running":
                return JSONResponse({"detail": "Lease expired; execution outcome is unknown and will not be retried"}, status_code=409)
            db.execute("""UPDATE execution_jobs SET status=?,exit_code=?,output=?,truncated=?,finished_at=?
                WHERE sequence=?""", (payload["status"], code, payload["output"], int(payload["truncated"]), now(), sequence))
            return public_job(db.execute("SELECT * FROM execution_jobs WHERE sequence=?", (sequence,)).fetchone())

    @app.get("/owner/execution")
    async def owner_execution(request: Request):
        actor = hub.owner_actor(request)
        with hub.db() as db:
            agents = hub.agents(db)
            states = {row["agent_id"]: row["enabled"] for row in db.execute("SELECT * FROM execution_workers")}
        controls = []
        options = []
        for agent in agents:
            enabled = bool(states.get(agent["id"], 0))
            if agent["role"] != "agent" or (not enabled and (agent["status"] == "revoked" or not agent["credential_issued"])):
                continue
            key = escape(agent["id"], quote=True)
            label = escape(agent["display_name"])
            controls.append(f'<form method="post" action="/owner/execution/workers">{csrf_field(actor)}'
                f'<input type="hidden" name="worker_id" value="{key}">'
                f'<input type="hidden" name="enabled" value="{0 if enabled else 1}">'
                f'<strong>{label}</strong> — {"Enabled" if enabled else "Disabled"} '
                f'<button>{"Stop worker" if enabled else "Enable worker"}</button></form>')
            if enabled:
                options.append(f'<option value="{key}">{label}</option>')
        submit_form = (f'<form method="post" action="/owner/execution/jobs">{csrf_field(actor)}'
            f'<input type="hidden" name="id" value="{uuid.uuid4()}"><label>Remote worker '
            f'<select name="worker_id">{"".join(options)}</select></label>'
            '<p><label>Command <textarea name="command" required></textarea></label></p>'
            '<label>Timeout (seconds) <input type="number" name="timeout_seconds" min="1" max="300" value="60"></label> '
            '<button>Queue command</button></form>') if options else '<p>Enable a provisioned remote worker to queue commands.</p>'
        return hub.page("Command workers", hub.nav(actor) +
            '<p>Automatic execution is opt-in for each worker and requires a running worker client on its intended computer. '
            'Enabling a worker lets agents with job-submission permission submit commands to it. '
            'Commands run with that client’s operating-system privileges. Shared posts and private messages remain text.</p>'
            '<p>Stop worker cancels pending jobs and asks a connected runner to stop its running job at the next heartbeat. '
            'A disconnected runner cannot be stopped by this website. A lost lease means the outcome is unknown; '
            'inspect that computer before submitting a new job.</p>' + ''.join(controls) + submit_form +
            '<h2>Recent jobs</h2>' + render_jobs(hub, actor, list_jobs(hub, actor, latest=True)))

    @app.post("/owner/execution/workers")
    async def configure_worker(request: Request):
        actor = hub.owner_actor(request)
        fields = await hub.form(request)
        hub.check_csrf(request, fields, actor)
        if set(fields) != {"csrf", "worker_id", "enabled"} or fields["enabled"] not in ("0", "1"):
            raise HTTPException(422, "Invalid worker settings")
        with hub.db() as db:
            db.execute("BEGIN IMMEDIATE")
            enabled = int(fields["enabled"])
            if enabled:
                ensure_target(hub, db, fields["worker_id"])
            elif not hub.find_agent(db, fields["worker_id"]):
                raise HTTPException(404, "Worker not found")
            db.execute("""INSERT INTO execution_workers(agent_id,enabled,updated_at) VALUES(?,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET enabled=excluded.enabled,updated_at=excluded.updated_at""",
                (fields["worker_id"], enabled, now()))
            if not enabled:
                db.execute("UPDATE execution_jobs SET status='cancelled',cancel_requested=1,finished_at=? WHERE worker_id=? AND status='pending'", (now(), fields["worker_id"]))
                db.execute("UPDATE execution_jobs SET cancel_requested=1 WHERE worker_id=? AND status='running'", (fields["worker_id"],))
        return RedirectResponse("/owner/execution", 303)

    @app.post("/owner/execution/jobs")
    async def owner_submit(request: Request):
        actor = hub.owner_actor(request)
        fields = await hub.form(request)
        hub.check_csrf(request, fields, actor)
        if set(fields) != {"csrf", "id", "worker_id", "command", "timeout_seconds"}:
            raise HTTPException(422, "Invalid command form")
        try:
            timeout = int(fields["timeout_seconds"])
        except ValueError:
            raise HTTPException(422, "Invalid timeout") from None
        submit(hub, actor, {"id": fields["id"], "worker_id": fields["worker_id"], "command": fields["command"], "timeout_seconds": timeout})
        return RedirectResponse("/owner/execution", 303)

    @app.post("/owner/execution/jobs/{sequence}/cancel")
    async def cancel(sequence: int, request: Request):
        actor = hub.owner_actor(request)
        fields = await hub.form(request)
        hub.check_csrf(request, fields, actor)
        with hub.db() as db:
            db.execute("BEGIN IMMEDIATE")
            expire(db)
            row = scoped_job(db, actor, sequence)
            if row["status"] == "pending":
                db.execute("UPDATE execution_jobs SET status='cancelled',cancel_requested=1,finished_at=? WHERE sequence=?", (now(), sequence))
            elif row["status"] == "running":
                db.execute("UPDATE execution_jobs SET cancel_requested=1 WHERE sequence=?", (sequence,))
        return RedirectResponse("/owner/execution", 303)

    @app.get("/jobs")
    async def browser_jobs(request: Request):
        actor = hub.browser_actor(request)
        return hub.page("Command jobs", hub.nav(actor) + render_jobs(hub, actor, list_jobs(hub, actor, latest=True)))

    @app.get("/jobs/{sequence}")
    async def browser_job(sequence: int, request: Request):
        actor = hub.browser_actor(request)
        with hub.db() as db:
            db.execute("BEGIN IMMEDIATE")
            hub.check_actor(db, actor)
            expire(db)
            row = public_job(scoped_job(db, actor, sequence))
        return hub.page(f'Command job {sequence}', hub.nav(actor) + render_jobs(hub, actor, [row]) +
            '<h2>Output</h2><pre>' + escape(row["output"]) + '</pre>' +
            ('<p>Output was truncated by the worker.</p>' if row["truncated"] else ''))


def render_jobs(hub, actor, jobs):
    items = []
    for job in jobs:
        sequence = job["sequence"]
        cancel = (f'<form method="post" action="/owner/execution/jobs/{sequence}/cancel">{csrf_field(actor)}'
                  '<button>Cancel job</button></form>') if actor["role"] == "owner" and job["status"] in ("pending", "running") else ''
        items.append(f'<article><a href="/jobs/{sequence}">Job {sequence}</a> — {escape(job["status"])}'
            f'<p>{escape(job["submitter_id"])} → {escape(job["worker_id"])}</p>'
            f'<pre>{escape(job["command"])}</pre>{cancel}</article>')
    return ''.join(items) or '<p>No command jobs yet.</p>'
