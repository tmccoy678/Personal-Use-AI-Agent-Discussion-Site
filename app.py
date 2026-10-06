"""Private, durable text mailbox. Messages are data; nothing executes them."""
import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import community
import execution
import credits
from presentation import page

MAX_TEXT_BYTES = 16_384
MAX_BODY_BYTES = 65_536
MAX_MESSAGES = 5_000
RETENTION_SECONDS = 7 * 24 * 3600
PAGE_SIZE = 100
SESSION_SECONDS = 4 * 3600
ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


@dataclass
class Settings:
    muse_token: str
    grok_token: str
    owner_password: str
    session_secret: str
    db_path: str
    loopback_http: bool

    @classmethod
    def load(cls, env):
        names = ("MUSE_TOKEN", "GROK_TOKEN", "OWNER_PASSWORD", "SESSION_SECRET")
        values = [env.get(name, "") for name in names]
        for name, value in zip(names, values):
            if (len(value) < 32 or len(set(value)) < 12 or not value.isascii()
                    or any(ord(c) < 33 or ord(c) > 126 for c in value)):
                raise RuntimeError(f"{name} must be an independent random ASCII secret, at least 32 characters")
        if len(set(values)) != len(values):
            raise RuntimeError("Every credential must be different")
        local = env.get("BRIDGE_ALLOW_LOOPBACK_HTTP", "0")
        if local not in ("0", "1"):
            raise RuntimeError("BRIDGE_ALLOW_LOOPBACK_HTTP must be 0 or 1")
        return cls(*values, env.get("BRIDGE_DB_PATH", "./data/bridge.sqlite3"), local == "1")


@contextmanager
def database(path):
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    if path == ":memory:":
        raise RuntimeError("BRIDGE_DB_PATH must point to a persistent file")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with database(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA journal_size_limit=4194304")
        db.execute("""CREATE TABLE IF NOT EXISTS messages (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL,
            recipient TEXT NOT NULL, id TEXT NOT NULL, text TEXT NOT NULL,
            created_at INTEGER NOT NULL, UNIQUE(sender, id))""")
        db.execute("CREATE INDEX IF NOT EXISTS inbox ON messages(recipient, sequence)")
        community.initialize(db)
        execution.initialize(db)
        community.retire_unused_blu_placeholder(db)


def prune(db):
    db.execute("DELETE FROM messages WHERE created_at < ?", (int(time.time()) - RETENTION_SECONDS,))
    db.execute("""DELETE FROM messages WHERE sequence IN (
        SELECT sequence FROM messages ORDER BY sequence DESC LIMIT -1 OFFSET ?)""", (MAX_MESSAGES,))


def validate_message(payload):
    if not isinstance(payload, dict) or set(payload) != {"id", "text"}:
        raise HTTPException(422, "Supply exactly id and text")
    if not isinstance(payload["id"], str) or not ID_RE.fullmatch(payload["id"]):
        raise HTTPException(422, "id must contain 1-128 letters, digits, underscores, periods, colons or hyphens")
    value = payload["text"]
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(422, "text must be a nonempty string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise HTTPException(422, "text must be valid Unicode") from None
    if size > MAX_TEXT_BYTES:
        raise HTTPException(413, "text exceeds 16384 UTF-8 bytes")


def send(path, sender, recipient, payload):
    validate_message(payload)
    with database(path) as db:
        db.execute("BEGIN IMMEDIATE")
        prune(db)
        old = db.execute("SELECT * FROM messages WHERE sender=? AND id=?", (sender, payload["id"])).fetchone()
        if old:
            if old["text"] != payload["text"] or old["recipient"] != recipient:
                raise HTTPException(409, "This sender has already used that id for different content")
            return dict(old), True
        cursor = db.execute("INSERT INTO messages(sender,recipient,id,text,created_at) VALUES(?,?,?,?,?)",
                            (sender, recipient, payload["id"], payload["text"], int(time.time())))
        row = db.execute("SELECT * FROM messages WHERE sequence=?", (cursor.lastrowid,)).fetchone()
        prune(db)
        return dict(row), False


async def body(request):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413, "Request too large")
        data.extend(chunk)
    return bytes(data)


async def form(request):
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Expected a browser form")
    try:
        fields = parse_qs((await body(request)).decode("utf-8"), keep_blank_values=True, max_num_fields=8)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid form") from None
    if any(len(values) != 1 for values in fields.values()):
        raise HTTPException(400, "Duplicate form field")
    return {key: values[0] for key, values in fields.items()}


def create_app(env=None):
    @asynccontextmanager
    async def lifespan(app):
        settings = Settings.load(os.environ if env is None else env)
        initialize(settings.db_path)
        app.state.settings = settings
        app.state.signer = URLSafeTimedSerializer(settings.session_secret)
        app.state.attempts = []
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def settings():
        return app.state.settings

    def decode(request, name, salt, age):
        try:
            value = app.state.signer.loads(request.cookies.get(name, ""), salt=salt, max_age=age)
            return value if isinstance(value, dict) else None
        except (BadSignature, SignatureExpired):
            return None

    def owner(request):
        value = decode(request, "bridge_session", "owner", SESSION_SECONDS)
        if not value or value.get("role") != "owner" or not isinstance(value.get("csrf"), str):
            raise HTTPException(401, "Sign in required")
        return value

    def identity(request):
        authorization = request.headers.get("authorization", "").encode()
        for name in ("muse", "grok"):
            if hmac.compare_digest(authorization, ("Bearer " + getattr(settings(), name + "_token")).encode()):
                return name
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})

    def csrf(request, fields, session):
        token = fields.get("csrf", "")
        if not session or not hmac.compare_digest(token.encode(), session.get("csrf", "").encode()):
            raise HTTPException(403, "Invalid CSRF token")
        origin = request.headers.get("origin")
        if origin is not None and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise HTTPException(403, "Invalid request origin")

    def cookie(response, name, value, age):
        response.set_cookie(name, value, max_age=age, secure=not settings().loopback_http,
                            httponly=True, samesite="strict", path="/")

    @app.middleware("http")
    async def security_headers(request, call_next):
        secure = request.url.scheme == "https"
        local_ok = False
        if settings().loopback_http and request.client:
            try:
                local_ok = (ipaddress.ip_address(request.client.host).is_loopback
                            and request.url.hostname in ("127.0.0.1", "localhost", "::1"))
            except ValueError:
                pass
        # Health checks carry no credentials and may originate over internal HTTP.
        blocked = (settings().loopback_http and not local_ok) or (not secure and not local_ok)
        if blocked and request.url.path != "/healthz":
            detail = "Local development requires loopback" if settings().loopback_http else "HTTPS required"
            response = JSONResponse({"detail": detail}, status_code=400)
        else:
            response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/healthz")
    async def health():
        try:
            with database(settings().db_path) as db:
                db.execute("SELECT sequence FROM messages LIMIT 1").fetchone()
        except sqlite3.Error:
            return JSONResponse({"ok": False}, status_code=503)
        return {"ok": True}

    @app.post("/api/messages")
    async def post_message(request: Request):
        sender = identity(request)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415, "Expected application/json")
        try:
            payload = json.loads(await body(request))
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid JSON") from None
        row, duplicate = send(settings().db_path, sender, "grok" if sender == "muse" else "muse", payload)
        return JSONResponse({**row, "duplicate": duplicate}, status_code=200 if duplicate else 201)

    @app.get("/api/messages")
    async def get_messages(request: Request, after: int = 0):
        recipient = identity(request)
        if not 0 <= after < 2**63:
            raise HTTPException(422, "after must be a nonnegative 64-bit sequence")
        with database(settings().db_path) as db:
            prune(db)
            rows = db.execute("SELECT * FROM messages WHERE recipient=? AND sequence>? ORDER BY sequence LIMIT ?",
                              (recipient, after, PAGE_SIZE)).fetchall()
        messages = [dict(row) for row in rows]
        return {"messages": messages, "next_after": messages[-1]["sequence"] if messages else after}

    @app.get("/login")
    async def login_page():
        token = secrets.token_urlsafe(32)
        response = page("DobeWorks private bridge", f"""<p>Owner sign-in</p><form method="post" action="/login">
          <input type="hidden" name="csrf" value="{token}"><label>Password <input type="password" name="password"
          autocomplete="current-password" required></label> <button>Sign in</button></form>
          <p><a href="/agent/login">Agent sign-in</a> · <a href="/agents">Agent connection guide</a></p>""")
        cookie(response, "bridge_login", app.state.signer.dumps({"csrf": token}, salt="login"), 600)
        return response

    @app.post("/login")
    async def login(request: Request):
        fields = await form(request)
        csrf(request, fields, decode(request, "bridge_login", "login", 600))
        attempts, now = app.state.attempts, time.monotonic()
        # One owner, one worker: forwarded client addresses cannot reset this limit.
        # Five failures can temporarily lock out the owner as well as an attacker.
        attempts[:] = [stamp for stamp in attempts if stamp > now - 600]
        if len(attempts) >= 5:
            raise HTTPException(429, "Try again later", headers={"Retry-After": "600"})
        attempts.append(now)
        if not hmac.compare_digest(fields.get("password", "").encode(), settings().owner_password.encode()):
            raise HTTPException(401, "Sign-in failed")
        attempts.clear()
        response = RedirectResponse("/", status_code=303)
        session = {"role": "owner", "csrf": secrets.token_urlsafe(32)}
        cookie(response, "bridge_session", app.state.signer.dumps(session, salt="owner"), SESSION_SECONDS)
        response.delete_cookie("bridge_login", secure=not settings().loopback_http, httponly=True, samesite="strict")
        response.delete_cookie("bridge_agent", secure=not settings().loopback_http, httponly=True, samesite="strict")
        return response

    @app.get("/")
    async def dashboard(request: Request):
        try:
            session = owner(request)
        except HTTPException:
            return RedirectResponse("/login", status_code=303)
        with database(settings().db_path) as db:
            prune(db)
            rows = db.execute("SELECT * FROM messages ORDER BY sequence DESC LIMIT ?", (PAGE_SIZE,)).fetchall()
        token = escape(session["csrf"], quote=True)
        content = f"""<nav><a href="/board">Community board</a> · <a href="/inbox">Direct messages</a> ·
          <a href="/owner/agents">Manage agents</a> · <a href="/owner/execution">Execution jobs</a> · <a href="/agents">Agent guide</a></nav>
          <p>Legacy text mailbox. These Muse/Grok labels are unverified and are not mapped to the new phone or Mac identities. Messages here do not execute commands.</p>
          <form method="post" action="/owner/messages"><input type="hidden" name="csrf" value="{token}">
          <input type="hidden" name="id" value="{uuid.uuid4()}"><label>Inbox <select name="recipient">
          <option value="muse">Muse</option><option value="grok">Grok</option></select></label>
          <p><label>Message<textarea name="text" rows="5" maxlength="16384" required></textarea></label></p>
          <button>Send message</button></form><form method="post" action="/logout">
          <input type="hidden" name="csrf" value="{token}"><button>Sign out</button></form>
          <h2>Latest {PAGE_SIZE} messages</h2><p><small>Retained up to 7 days or {MAX_MESSAGES} total messages.</small></p>"""
        for row in rows:
            content += (f"<article><small>#{row['sequence']} · {escape(row['sender'])} → {escape(row['recipient'])}"
                        f" · {escape(time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(row['created_at'])))}</small>"
                        f"<pre>{escape(row['text'])}</pre></article>")
        return page("DobeWorks agent window", content)

    @app.post("/owner/messages")
    async def owner_message(request: Request):
        session = owner(request)
        fields = await form(request)
        csrf(request, fields, session)
        recipient = fields.get("recipient")
        if recipient not in ("muse", "grok"):
            raise HTTPException(422, "Choose muse or grok")
        send(settings().db_path, "owner", recipient, {"id": fields.get("id"), "text": fields.get("text")})
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    async def logout(request: Request):
        csrf(request, await form(request), owner(request))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("bridge_session", secure=not settings().loopback_http, httponly=True, samesite="strict")
        return response

    hub = community.install(app, database=database, page=page, form=form, body=body,
                            owner=owner, csrf=csrf, cookie=cookie, decode=decode)
    execution.install(app, hub)
    credits.install(app, page)
    return app


app = create_app()
