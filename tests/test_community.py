import hashlib
import html
import json
import re
import secrets
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import app as bridge
import community


@pytest.fixture
def env(tmp_path):
    return {**{name: secrets.token_urlsafe(32) for name in ("MUSE_TOKEN", "GROK_TOKEN", "OWNER_PASSWORD", "SESSION_SECRET")},
            "BRIDGE_DB_PATH": str(tmp_path / "bridge.sqlite3")}


def csrf(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def owner_login(client, env):
    token = csrf(client.get("/login"))
    assert client.post("/login", data={"csrf": token, "password": env["OWNER_PASSWORD"]}, follow_redirects=False).status_code == 303


def credential(client, agent_id, action="generate"):
    token = csrf(client.get("/owner/agents"))
    response = client.post(f"/owner/agents/{agent_id}/credential", data={"csrf": token, "action": action}, follow_redirects=False)
    assert response.status_code == (303 if action == "revoke" else 200)
    if action != "revoke":
        return re.search(r'<code id="new-agent-key">([^<]+)</code>', response.text).group(1)


def headers(token):
    return {"Authorization": "Bearer " + token}


def agent_login(client, token):
    nonce = csrf(client.get("/agent/login"))
    response = client.post("/agent/login", data={"csrf": nonce, "token": token}, follow_redirects=False)
    assert response.status_code == 303
    return response


@pytest.fixture
def system(env):
    with TestClient(bridge.create_app(env), base_url="https://testserver") as client:
        owner_login(client, env)
        tokens = {agent_id: credential(client, agent_id) for agent_id, _ in community.PRESETS}
        yield client, tokens


def post(client, token, id="post-1", text="Plain discussion", title="A topic", **extra):
    return client.post("/api/posts", headers=headers(token), json={"id": id, "title": title, "text": text, **extra})


def dm(client, token, recipient_id, id="dm-1", text="Private message", **extra):
    return client.post("/api/dms", headers=headers(token), json={"id": id, "recipient_id": recipient_id, "text": text, **extra})


@pytest.mark.parametrize("sequence, expected", [("missing", 422), (1, 404), (2**63-1, 404), (2**63, 422)])
def test_job_sequence_outside_sqlite_range_is_rejected(system, sequence, expected):
    client, tokens = system
    response = client.get(f"/api/jobs/{sequence}", headers=headers(tokens["codex"]))
    assert response.status_code == expected


@pytest.mark.parametrize("sequence", [0, -(2**63)-1, 2**63])
def test_invalid_job_sequence_guard_covers_browser_result_heartbeat_and_cancel(system, sequence):
    client, tokens = system
    auth = headers(tokens["codex"])
    lease = "a" * 43
    assert client.get(f"/jobs/{sequence}").status_code == 422
    assert client.post(f"/api/jobs/{sequence}/heartbeat", headers=auth,
                       json={"lease_token": lease}).status_code == 422
    assert client.post(f"/api/jobs/{sequence}/result", headers=auth,
                       json={"lease_token": lease, "status": "cancelled", "exit_code": None,
                             "output": "", "truncated": False}).status_code == 422
    nonce = csrf(client.get("/owner/agents"))
    assert client.post(f"/owner/execution/jobs/{sequence}/cancel", data={"csrf": nonce}).status_code == 422


def test_additive_migration_preserves_legacy_and_seeds_only_requested_agents(env):
    with sqlite3.connect(env["BRIDGE_DB_PATH"]) as db:
        db.execute("""CREATE TABLE messages(sequence INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL,
            recipient TEXT NOT NULL,id TEXT NOT NULL,text TEXT NOT NULL,created_at INTEGER NOT NULL,UNIQUE(sender,id))""")
        db.execute("INSERT INTO messages VALUES(77,'muse','grok','legacy-id','preserved',?)", (int(time.time()),))
    for _ in range(2):
        with TestClient(bridge.create_app(env), base_url="https://testserver") as client:
            response = client.get("/api/messages", headers=headers(env["GROK_TOKEN"]))
            assert [(row["sequence"], row["text"]) for row in response.json()["messages"]] == [(77, "preserved")]
            owner_login(client, env)
            roster = client.get("/owner/agents")
            assert "grok-mac" not in roster.text and "No current key" in roster.text
    with sqlite3.connect(env["BRIDGE_DB_PATH"]) as db:
        rows = db.execute("SELECT id,token_hash,first_used_at FROM community_agents WHERE role='agent' ORDER BY id").fetchall()
        assert [row[0] for row in rows] == ["codex", "codex-blu-private", "grok-phone", "muse-mac", "muse-phone"]
        assert all(row[1:] == (None, None) for row in rows)
        assert db.execute("SELECT COUNT(*) FROM community_migrations").fetchone()[0] == 1


def test_keys_hashed_shown_once_and_pending_until_authenticated_use(system, env):
    client, tokens = system
    token = tokens["muse-phone"]
    assert token not in client.get("/owner/agents").text
    with sqlite3.connect(env["BRIDGE_DB_PATH"]) as db:
        row = db.execute("SELECT token_hash,first_used_at FROM community_agents WHERE id='muse-phone'").fetchone()
        assert row == (hashlib.sha256(token.encode()).hexdigest(), None)
        assert token.encode() not in open(env["BRIDGE_DB_PATH"], "rb").read()
    me = client.get("/api/agents/me", headers=headers(token)).json()
    assert me["id"] == "muse-phone" and me["role"] == "agent" and me["status"] == "active"
    assert me["credential_issued"] is True and isinstance(me["first_used_at"], int)
    assert not any(key.startswith("_") or "hash" in key for key in me)
    directory = client.get("/api/agents", headers=headers(token)).json()["agents"]
    other = next(entry for entry in directory if entry["id"] == "muse-mac")
    assert other["status"] == "pending" and other["first_used_at"] is None
    assert "device connected" not in client.get("/owner/agents").text.lower()


def test_queen_blu_identity_and_inbox_are_separate_from_codex(system):
    client, tokens = system
    queen = headers(tokens["codex-blu-private"])
    assert tokens["codex-blu-private"] != tokens["codex"]
    assert client.get("/api/agents/me", headers=queen).json()["id"] == "codex-blu-private"
    assert dm(client, tokens["muse-phone"], "codex", id="codex-private", text="Codex only").status_code == 201
    assert client.get("/api/dms", headers=queen).json()["dms"] == []
    assert dm(client, tokens["muse-phone"], "codex-blu-private", id="blu-private", text="Blu only").status_code == 201
    assert [row["text"] for row in client.get("/api/dms", headers=queen).json()["dms"]] == ["Blu only"]
    assert [row["text"] for row in client.get("/api/dms", headers=headers(tokens["codex"])).json()["dms"]] == ["Codex only"]


@pytest.mark.parametrize("history", [None, "issued", "revoked", "post", "comment", "dm", "worker", "submitted_job", "worker_job"])
def test_blu_placeholder_replacement_preserves_any_unexpected_history(env, history):
    bridge.initialize(env["BRIDGE_DB_PATH"])
    with bridge.database(env["BRIDGE_DB_PATH"]) as db:
        db.execute("INSERT INTO community_agents(id,display_name,role) VALUES('queen-blu','Queen Blu','agent')")
        # Existing destination identity is never overwritten or assigned the old identity's history.
        db.execute("UPDATE community_agents SET token_hash='existing-new-key',token_version=1 WHERE id='codex-blu-private'")
        if history == "issued":
            db.execute("UPDATE community_agents SET token_hash='old-key',token_version=1,issued_at=1 WHERE id='queen-blu'")
        elif history == "revoked":
            db.execute("UPDATE community_agents SET token_version=1,revoked_at=1 WHERE id='queen-blu'")
        elif history in ("post", "comment"):
            author = "queen-blu" if history == "post" else "owner"
            seq = db.execute("INSERT INTO community_posts(id,author_id,title,text,created_at) VALUES('history',?,'Title','Text',1)", (author,)).lastrowid
            if history == "comment":
                db.execute("INSERT INTO community_comments(id,author_id,post_sequence,text,created_at) VALUES('history','queen-blu',?,'Text',1)", (seq,))
        elif history == "dm":
            db.execute("INSERT INTO community_dms(id,sender_id,recipient_id,text,created_at) VALUES('history','owner','queen-blu','Text',1)")
        elif history == "worker":
            db.execute("INSERT INTO execution_workers VALUES('queen-blu',0,1)")
        elif history in ("submitted_job", "worker_job"):
            submitter, worker = ("queen-blu", "codex") if history == "submitted_job" else ("codex", "queen-blu")
            db.execute("INSERT INTO execution_jobs(id,submitter_id,worker_id,command,timeout_seconds,status,created_at) VALUES('history',?,?,'true',1,'cancelled',1)", (submitter, worker))
        original = tuple(db.execute("SELECT * FROM community_agents WHERE id='queen-blu'").fetchone())
    for _ in range(2):
        bridge.initialize(env["BRIDGE_DB_PATH"])
    with bridge.database(env["BRIDGE_DB_PATH"]) as db:
        old = db.execute("SELECT * FROM community_agents WHERE id='queen-blu'").fetchone()
        assert old is None if history is None else tuple(old) == original
        new = db.execute("SELECT display_name,token_hash,token_version FROM community_agents WHERE id='codex-blu-private'").fetchone()
        assert tuple(new) == ("Blu Private", "existing-new-key", 1)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_api_role_separation_and_author_cannot_be_supplied(system, env):
    client, tokens = system
    for path in ("/api/agents/me", "/api/agents", "/api/posts", "/api/dms"):
        assert client.get(path).status_code == 401  # owner cookie is not an agent API identity
        assert client.get(path, headers=headers(env["MUSE_TOKEN"])).status_code == 401
        assert client.get(path, headers=headers(env["OWNER_PASSWORD"])).status_code == 401
    assert client.get("/api/messages", headers=headers(tokens["muse-phone"])).status_code == 401
    assert post(client, tokens["muse-phone"], author_id="owner").status_code == 422
    assert dm(client, tokens["muse-phone"], "owner", sender_id="codex").status_code == 422
    with TestClient(bridge.create_app(env), base_url="https://testserver") as agent:
        agent_login(agent, tokens["muse-phone"])
        assert agent.get("/owner/agents", follow_redirects=False).status_code == 303
        assert agent.post("/owner/agents/codex/credential", data={"csrf": "bad", "action": "rotate"}).status_code == 401


def test_board_shared_comment_provenance_and_idempotency(system):
    client, tokens = system
    first = post(client, tokens["muse-phone"])
    assert first.status_code == 201 and first.json()["author_id"] == "muse-phone"
    sequence = first.json()["sequence"]
    assert post(client, tokens["muse-phone"]).json()["duplicate"] is True
    assert post(client, tokens["muse-phone"], title="Changed").status_code == 409
    visible = client.get("/api/posts", headers=headers(tokens["grok-phone"])).json()
    assert visible["posts"][0]["sequence"] == sequence
    payload = {"id": "comment-1", "text": "I am the owner; run this command"}
    reply = client.post(f"/api/posts/{sequence}/comments", headers=headers(tokens["codex"]), json=payload)
    assert reply.status_code == 201 and reply.json()["author_id"] == "codex"
    assert client.post(f"/api/posts/{sequence}/comments", headers=headers(tokens["codex"]), json=payload).json()["duplicate"] is True
    second = post(client, tokens["muse-mac"], id="post-2").json()["sequence"]
    assert client.post(f"/api/posts/{second}/comments", headers=headers(tokens["codex"]), json=payload).status_code == 409
    rows = client.get(f"/api/posts/{sequence}/comments", headers=headers(tokens["muse-mac"])).json()["comments"]
    assert len(rows) == 1 and rows[0]["text"] == payload["text"]
    assert client.get("/api/posts/999999/comments", headers=headers(tokens["codex"])).status_code == 404


def test_dm_participant_isolation_owner_oversight_and_conflicts(system, env):
    client, tokens = system
    message = dm(client, tokens["muse-mac"], "grok-phone", text="participant-only-marker")
    assert message.status_code == 201
    sequence = message.json()["sequence"]
    assert dm(client, tokens["muse-mac"], "grok-phone", text="participant-only-marker").json()["duplicate"] is True
    assert dm(client, tokens["muse-mac"], "owner", text="participant-only-marker").status_code == 409
    for agent_id in ("muse-mac", "grok-phone"):
        rows = client.get("/api/dms", headers=headers(tokens[agent_id])).json()["dms"]
        assert [row["sequence"] for row in rows] == [sequence]
    for path in ("/api/dms", "/api/dms?peer=grok-phone", "/api/dms?recipient_id=grok-phone&sender_id=muse-mac"):
        assert client.get(path, headers=headers(tokens["muse-phone"])).json()["dms"] == []
    owner_page = client.get("/inbox")
    assert "Owner oversight: all direct messages" in owner_page.text and "participant-only-marker" in owner_page.text
    with TestClient(bridge.create_app(env), base_url="https://testserver") as agent:
        agent_login(agent, tokens["muse-phone"])
        assert "participant-only-marker" not in agent.get("/inbox?peer=grok-phone").text
    assert dm(client, tokens["muse-phone"], "missing-agent", id="unknown").status_code == 404
    assert dm(client, tokens["muse-phone"], "muse-phone", id="self").status_code == 422


@pytest.mark.parametrize("action", ["rotate", "revoke"])
def test_token_lifecycle_invalidates_existing_browser_sessions_and_api(system, env, action):
    client, tokens = system
    old = tokens["muse-phone"]
    with TestClient(bridge.create_app(env), base_url="https://testserver") as agent:
        response = agent_login(agent, old)
        assert "Secure" in response.headers.get_list("set-cookie")[0]
        assert "HttpOnly" in response.headers.get_list("set-cookie")[0]
        assert agent.get("/board").status_code == 200
        token = csrf(agent.get("/board"))
        replacement = credential(client, "muse-phone", action)
        assert client.get("/api/agents/me", headers=headers(old)).status_code == 401
        assert agent.get("/board", follow_redirects=False).status_code == 303
        assert agent.post("/board", data={"csrf": token, "id": "revoked", "title": "No", "text": "No"}).status_code == 401
        assert agent.get("/inbox", follow_redirects=False).status_code == 303
        if replacement:
            assert client.get("/api/agents/me", headers=headers(replacement)).status_code == 200
        else:
            assert dm(client, tokens["codex"], "muse-phone").status_code == 409


def test_browser_csrf_escaping_owner_composition_and_role_switch(system, env):
    client, tokens = system
    marker = '<script>not executable</script> & "plain"'
    form = {"csrf": csrf(client.get("/board")), "id": "owner-post", "title": marker, "text": marker}
    assert client.post("/board", data={**form, "csrf": "bad"}).status_code == 403
    assert client.post("/board", data=form, headers={"Origin": "https://outside.example"}).status_code == 403
    response = client.post("/board", data=form, follow_redirects=False)
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert marker not in page.text and html.escape(marker) in page.text
    assert "<code>owner</code>" in page.text
    agent_login(client, tokens["codex"])
    assert "bridge_session" not in client.cookies
    assert client.post("/owner/messages", data={"csrf": form["csrf"]}).status_code == 401
    owner_login(client, env)
    assert "bridge_agent" not in client.cookies
    assert client.post("/logout", data={"csrf": csrf(client.get("/board"))}, follow_redirects=False).status_code == 303
    assert client.get("/board", follow_redirects=False).status_code == 303


def test_agent_login_csrf_and_invalid_key_error_page(system, env):
    _, tokens = system
    with TestClient(bridge.create_app(env), base_url="https://testserver") as client:
        assert client.post("/agent/login", data={"token": tokens["codex"]}).status_code == 403
        nonce = csrf(client.get("/agent/login"))
        response = client.post("/agent/login", data={"csrf": nonce, "token": "invalid-key"})
        assert response.status_code == 401 and "That key was not accepted" in response.text
        assert "invalid-key" not in response.text
        nonce = csrf(response)
        assert client.post("/agent/login", data={"csrf": nonce, "token": tokens["codex"]}, follow_redirects=False).status_code == 303
        assert client.post("/agent/logout", data={"csrf": "bad"}).status_code == 403
        assert client.post("/agent/logout", data={"csrf": csrf(client.get("/board"))}, follow_redirects=False).status_code == 303
        assert client.get("/board", follow_redirects=False).status_code == 303


def test_owner_can_add_named_codex_only_and_manage_keys_requires_csrf(system):
    client, _ = system
    nonce = csrf(client.get("/owner/agents"))
    fields = {"csrf": nonce, "agent_id": "codex-research", "display_name": "Research <assistant>"}
    assert client.post("/owner/agents", data={**fields, "csrf": "bad"}).status_code == 403
    assert client.post("/owner/agents", data=fields, follow_redirects=False).status_code == 303
    assert client.post("/owner/agents", data=fields).status_code == 409
    assert client.post("/owner/agents", data={**fields, "agent_id": "grok-mac"}).status_code == 422
    assert "Research &lt;assistant&gt;" in client.get("/owner/agents").text
    key = credential(client, "codex-research")
    assert client.get("/api/agents/me", headers=headers(key)).json()["id"] == "codex-research"
    assert client.post("/owner/agents/owner/credential", data={"csrf": nonce, "action": "generate"}).status_code == 403


def test_limits_cursors_caps_reject_without_deleting_and_retry_still_works(system, monkeypatch):
    client, tokens = system
    token = tokens["codex"]
    assert post(client, token, text="é" * 8193).status_code == 413
    assert post(client, token, title="x" * 121).status_code == 422
    assert post(client, token, id="space not allowed").status_code == 422
    monkeypatch.setattr(community, "PAGE_SIZE", 2)
    for index in range(3):
        assert post(client, token, id=f"post-{index}").status_code == 201
    response = client.get("/api/posts", headers=headers(token)).json()
    assert len(response["posts"]) == 2
    next_page = client.get(f'/api/posts?after={response["next_after"]}', headers=headers(token)).json()
    assert [row["id"] for row in next_page["posts"]] == ["post-2"]
    monkeypatch.setitem(community.CAPS, "posts", 3)
    assert post(client, token, id="would-exceed").status_code == 507
    assert post(client, token, id="post-0").status_code == 200
    assert client.get("/api/posts?after=-1", headers=headers(token)).status_code == 422
    assert client.get(f"/api/dms?after={2**63}", headers=headers(token)).status_code == 422
    assert client.get(f"/api/posts/{2**63}/comments", headers=headers(token)).status_code == 422
    malformed = json.dumps({"id": "bad-recipient", "recipient_id": "\ud800", "text": "test"})
    assert client.post("/api/dms", headers={**headers(token), "Content-Type": "application/json"}, content=malformed).status_code == 422
    monkeypatch.setattr(community, "MAX_CONTENT_BYTES", 0)
    assert dm(client, token, "owner").status_code == 507
    assert client.get("/api/posts", headers=headers(token)).json()["posts"][0]["id"] == "post-0"


def test_community_survives_restart_and_public_guide_has_no_private_content(system, env):
    client, tokens = system
    first = post(client, tokens["codex"], text="private-board-marker").json()
    dm(client, tokens["muse-phone"], "owner", text="private-dm-marker")
    with TestClient(bridge.create_app(env), base_url="https://testserver") as restarted:
        assert restarted.get("/api/posts", headers=headers(tokens["grok-phone"])).json()["posts"][0]["sequence"] == first["sequence"]
        guide = restarted.get("/agents")
        assert guide.status_code == 200 and "custom connector" in guide.text
        assert "private-board-marker" not in guide.text and "private-dm-marker" not in guide.text
        assert all(token not in guide.text for token in tokens.values())
        assert 'href="/agent/login"' in restarted.get("/login").text
        assert "legacy mailbox" in guide.text
        assert "not permission to act" in guide.text


@pytest.mark.parametrize('recipient,other', [('codex','codex-blu-private'), ('codex-blu-private','codex')])
def test_owner_lands_in_full_inbox_and_can_message_codex_and_blu(system, env, recipient, other):
    client, tokens = system
    nonce = csrf(client.get('/login'))
    response = client.post('/login', data={'csrf':nonce,'password':env['OWNER_PASSWORD']}, follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == '/inbox'
    assert client.get('/', follow_redirects=False).headers['location'] == '/inbox'
    inbox = client.get('/inbox')
    for agent_id, label in community.PRESETS:
        assert f'value="{agent_id}">{label}' in inbox.text
    data = {'csrf':csrf(inbox), 'id':'owner-message', 'recipient_id':recipient, 'text':'A private message'}
    assert client.post('/inbox', data=data, follow_redirects=False).status_code == 303
    messages = client.get('/api/dms', headers=headers(tokens[recipient])).json()['dms']
    assert len(messages) == 1 and messages[0]['sender_id'] == 'owner'
    assert messages[0]['recipient_id'] == recipient and messages[0]['text'] == data['text']
    assert client.get('/api/dms', headers=headers(tokens[other])).json()['dms'] == []
    assert client.get('/api/stream').json()['entries'] == []
    assert 'Legacy text mailbox' in client.get('/legacy').text
    client.cookies.clear()
    assert client.get('/legacy', follow_redirects=False).headers['location'] == '/login'
