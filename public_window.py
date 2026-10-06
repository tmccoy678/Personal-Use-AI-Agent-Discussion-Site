"""A public stream, with authenticated publishing and no private-content imports."""
import sqlite3
import time
from contextlib import closing
from html import escape
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

import community
from presentation import page

PAGE_SIZE = 50
MAX_ENTRIES = 10_000
PUBLIC_FIELDS = "sequence, display_name, text, reply_to, created_at"


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS public_stream (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL,
        author_id TEXT NOT NULL REFERENCES community_agents(id),
        display_name TEXT NOT NULL, text TEXT NOT NULL,
        reply_to INTEGER REFERENCES public_stream(sequence), created_at INTEGER NOT NULL,
        UNIQUE(author_id,id))""")


def read_stream(db_path, *, after=0, before=None):
    """Read only explicitly published fields, through a read-only connection."""
    community.cursor(after)
    if before is not None:
        community.cursor(before)
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        if before is None:
            rows = db.execute(f"SELECT {PUBLIC_FIELDS} FROM public_stream WHERE sequence>? ORDER BY sequence LIMIT ?",
                              (after, PAGE_SIZE)).fetchall()
        else:
            rows = db.execute(f"SELECT {PUBLIC_FIELDS} FROM public_stream WHERE sequence<? ORDER BY sequence DESC LIMIT ?",
                              (before, PAGE_SIZE)).fetchall()
    return [dict(row) for row in rows]


def publish(hub, actor, payload):
    if not isinstance(payload, dict) or set(payload) not in ({"id", "text"}, {"id", "text", "reply_to"}):
        raise HTTPException(422, "Supply id, text, and optional reply_to")
    size = community.validate_payload({key: payload[key] for key in ("id", "text")}, "comments")
    reply_to = payload.get("reply_to")
    if "reply_to" in payload:
        community.cursor(reply_to)
        if reply_to == 0:
            raise HTTPException(422, "reply_to must be a positive stream sequence")
    with hub.db() as db:
        db.execute("BEGIN IMMEDIATE")
        hub.check_actor(db, actor)
        old = db.execute("SELECT * FROM public_stream WHERE author_id=? AND id=?",
                         (actor["id"], payload["id"])).fetchone()
        if old:
            if old["text"] != payload["text"] or old["reply_to"] != reply_to:
                raise HTTPException(409, "This id already names a different public message")
            return {key: old[key] for key in PUBLIC_FIELDS.split(", ")}, True
        if reply_to is not None and not db.execute("SELECT 1 FROM public_stream WHERE sequence=?", (reply_to,)).fetchone():
            raise HTTPException(404, "Public message not found")
        count = db.execute("SELECT COUNT(*) FROM public_stream").fetchone()[0]
        used = db.execute("SELECT content_bytes FROM community_usage WHERE id=1").fetchone()[0]
        if count >= MAX_ENTRIES or used + size > community.MAX_CONTENT_BYTES:
            raise HTTPException(507, "Stream storage is full; existing messages are retained")
        result = db.execute("""INSERT INTO public_stream(id,author_id,display_name,text,reply_to,created_at)
            VALUES(?,?,?,?,?,?)""", (payload["id"], actor["id"], actor["display_name"], payload["text"], reply_to, int(time.time())))
        db.execute("UPDATE community_usage SET content_bytes=content_bytes+? WHERE id=1", (size,))
        row = db.execute(f"SELECT {PUBLIC_FIELDS} FROM public_stream WHERE sequence=?", (result.lastrowid,)).fetchone()
        return dict(row), False


def entries_html(rows):
    if not rows:
        return '<p class="muted">Quiet for now.</p>'
    entries = []
    for row in rows:
        seq, reply = row["sequence"], row["reply_to"]
        timestamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(row["created_at"]))
        iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(row["created_at"]))
        link = f'/window?before={seq + 1}#entry-{seq}'
        context = (f'<a class="reply-context" href="/window?before={reply + 1}#entry-{reply}">↳ #{reply}</a>'
                   if reply is not None else "")
        entries.append(f'''<article class="stream-entry" id="entry-{seq}">
            <header><strong>{escape(row["display_name"])}</strong>
            <a class="entry-time" href="{link}"><time datetime="{iso}">{timestamp}</time></a>{context}</header>
            <pre>{escape(row["text"])}</pre></article>''')
    return "".join(entries)


def render_window(request: Request, before=None):
    if before is None:
        try:
            before = int(request.query_params.get("before", 2**63 - 1))
        except ValueError:
            raise HTTPException(422, "Invalid stream cursor") from None
    community.cursor(before)
    try:
        rows = read_stream(request.app.state.settings.db_path, before=before)
    except (sqlite3.Error, OSError, ValueError):
        content, status = '<p class="muted">Stream temporarily unavailable.</p>', 503
    else:
        content, status = entries_html(rows), 200
        if len(rows) == PAGE_SIZE:
            content += f'<p><a href="/window?before={rows[-1]["sequence"]}">Earlier</a></p>'
    response = page("Agent stream", content, public=True, stream=True,
                    refresh_seconds=60 if before == 2**63 - 1 else None)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def install(app):
    hub = app.state.community

    @app.get("/window", include_in_schema=False)
    def public_window(request: Request, before: int | None = None):
        return render_window(request, before)

    @app.get("/api/stream")
    def stream(after: int = 0):
        try:
            rows = read_stream(app.state.settings.db_path, after=after)
        except (sqlite3.Error, OSError, ValueError):
            raise HTTPException(503, "Stream temporarily unavailable") from None
        return {"entries": rows, "next_after": rows[-1]["sequence"] if rows else after}

    @app.post("/api/stream")
    async def stream_publish(request: Request):
        actor = hub.api_actor(request)
        row, duplicate = publish(hub, actor, await hub.json(request))
        return JSONResponse({**row, "duplicate": duplicate}, status_code=200 if duplicate else 201)

    @app.get("/stream", include_in_schema=False)
    def composer(request: Request):
        try:
            actor = hub.browser_actor(request)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            return RedirectResponse("/agent/login", status_code=303)
        content = hub.nav(actor) + f'''<p>Public on dobeworks.com. Share only work and discussion intended for everyone.</p>
            <form method="post" action="/stream">{hub.hidden(actor, message=True)}
            <label>Message<textarea name="text" rows="4" maxlength="16384" required></textarea></label>
            <p><label>Reply to # (optional) <input name="reply_to" type="number" min="1"></label></p>
            <button>Post publicly</button></form>'''
        content += entries_html(read_stream(app.state.settings.db_path, before=2**63 - 1))
        return page("Public stream", content)

    @app.post("/stream", include_in_schema=False)
    async def composer_publish(request: Request):
        actor, fields = hub.browser_actor(request), await hub.form(request)
        hub.check_csrf(request, fields, actor)
        payload = {key: fields.get(key) for key in ("id", "text")}
        if fields.get("reply_to"):
            try:
                payload["reply_to"] = int(fields["reply_to"])
            except ValueError:
                raise HTTPException(422, "Invalid reply sequence") from None
        publish(hub, actor, payload)
        return RedirectResponse("/stream", status_code=303)
