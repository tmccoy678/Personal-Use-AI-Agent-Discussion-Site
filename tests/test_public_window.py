import secrets
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import app as bridge
import public_window


@pytest.fixture
def window(tmp_path):
    env = {name: secrets.token_urlsafe(32) for name in
           ("MUSE_TOKEN", "GROK_TOKEN", "OWNER_PASSWORD", "SESSION_SECRET")}
    env["BRIDGE_DB_PATH"] = str(tmp_path / "bridge.sqlite3")
    application = bridge.create_app(env)
    if not any(route.path == "/window" for route in application.routes):
        public_window.install(application)
    with TestClient(application, base_url="https://testserver") as client:
        yield client, env["BRIDGE_DB_PATH"]


def seed_activity(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""INSERT INTO community_posts(id,author_id,title,text,created_at)
            VALUES('private-post','codex','PRIVATE TITLE','<script>PRIVATE BODY</script>',123)""")
        post = db.execute("SELECT sequence FROM community_posts").fetchone()[0]
        db.execute("""INSERT INTO community_comments(id,author_id,post_sequence,text,created_at)
            VALUES('private-comment','muse-mac',?,'PRIVATE COMMENT',123)""", (post,))
        db.execute("""INSERT INTO community_dms(id,sender_id,recipient_id,text,created_at)
            VALUES('private-dm','codex','owner','PRIVATE DM',123)""")
        db.execute("""UPDATE community_agents SET display_name='PRIVATE NAME',token_hash='PRIVATE HASH',
            issued_at=123,first_used_at=123,last_used_at=123 WHERE id='codex'""")
        for state, _ in public_window.JOB_STATES:
            db.execute("""INSERT INTO execution_jobs(id,submitter_id,worker_id,command,timeout_seconds,
                status,created_at,lease_expires_at,output,lease_hash)
                VALUES(?,'codex','grok-phone','PRIVATE COMMAND',30,?,123,1,'PRIVATE OUTPUT','PRIVATE LEASE')""",
                       (state, state))


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.iterdump())


def test_public_window_is_read_only_and_does_not_open_private_routes(window):
    client, path = window
    seed_activity(path)
    before = snapshot(path)
    response = client.get("/window")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert '<meta http-equiv="refresh" content="60">' in response.text
    assert '<a class="brand" href="/window">' in response.text
    assert "Activity summary available" in response.text
    assert "PRIVATE" not in response.text
    assert "grok-phone" not in response.text and "muse-mac" not in response.text
    assert "<form" not in response.text and "<script" not in response.text
    assert '<a href="/references">' in response.text
    assert '<a href="https://lab.dobeworks.com/login">Owner sign in</a>' in response.text
    assert '<a href="https://lab.dobeworks.com/agent/login">Agent sign in</a>' in response.text
    assert client.post("/window", json={"text": "cannot post"}).status_code == 405
    assert client.get("/api/posts").status_code == 401
    assert client.get("/api/dms").status_code == 401
    assert snapshot(path) == before  # Includes expired running jobs and auth timestamps.


def test_private_content_identity_and_dm_changes_cannot_change_public_output(window):
    client, path = window
    seed_activity(path)
    original = client.get("/window").content
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE community_posts SET title='changed title',text='changed content',author_id='owner'")
        db.execute("UPDATE community_comments SET text='changed comment',author_id='owner'")
        db.execute("UPDATE community_agents SET display_name='changed identity',last_used_at=999")
        db.execute("UPDATE execution_jobs SET command='changed command',output='changed error',worker_id='private-other',created_at=999")
        db.execute("""INSERT INTO community_dms(id,sender_id,recipient_id,text,created_at)
            VALUES('another-dm','owner','codex','changed private message',999)""")
    assert client.get("/window").content == original


def test_activity_bands_and_status_allowlist(window):
    client, path = window
    seed_activity(path)
    original = client.get("/window").content
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""INSERT INTO execution_jobs(id,submitter_id,worker_id,command,timeout_seconds,status,created_at)
            VALUES('unknown','codex','grok-phone','hidden',30,'<script>unknown state</script>',123)""")
        db.executemany("""INSERT INTO community_posts(id,author_id,title,text,created_at)
            VALUES(?,'codex','hidden','hidden',123)""", [(f"post-{i}",) for i in range(8)])
    assert client.get("/window").content == original  # 1 and 9 share one coarse band.
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""INSERT INTO community_posts(id,author_id,title,text,created_at)
            VALUES('tenth','codex','hidden','hidden',123)""")
    changed = client.get("/window").text
    assert "<dt>Posts</dt><dd>10–49</dd>" in changed
    assert "unknown state" not in changed and "<script>" not in changed


def test_missing_database_has_generic_failure_and_is_not_created(window, tmp_path):
    client, _ = window
    path = tmp_path / "PRIVATE-missing.sqlite3"
    object.__setattr__(client.app.state.settings, "db_path", str(path))
    response = client.get("/window")
    assert response.status_code == 503
    assert "Activity temporarily unavailable" in response.text
    assert "PRIVATE" not in response.text and str(tmp_path) not in response.text
    assert "sqlite" not in response.text.lower()
    assert not path.exists()


def test_activity_reader_can_only_read_aggregate_columns(window, monkeypatch):
    _, path = window
    seed_activity(path)
    connect = sqlite3.connect
    reads = set()

    def readonly_connection(*args, **kwargs):
        assert args[0].endswith("?mode=ro") and kwargs["uri"] is True
        db = connect(*args, **kwargs)

        def authorize(action, table, column, database, source):
            if action == sqlite3.SQLITE_READ:
                reads.add((table, column))
                if (table, column) not in {
                    ("community_posts", ""), ("community_comments", ""),
                    ("execution_jobs", "status"), ("execution_jobs", ""),
                }:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db.set_authorizer(authorize)
        return db

    monkeypatch.setattr(public_window.sqlite3, "connect", readonly_connection)
    assert public_window.activity_counts(path) == (1, 1, {state: 1 for state, _ in public_window.JOB_STATES})
    assert {table for table, _ in reads} == {"community_posts", "community_comments", "execution_jobs"}


@pytest.mark.parametrize('hostname', ['dobeworks.com', 'www.dobeworks.com'])
def test_main_domain_root_is_public_but_private_lab_root_stays_protected(window, hostname):
    client, path = window
    seed_activity(path)
    response = client.get('https://' + hostname + '/')
    assert response.status_code == 200 and 'Public window' in response.text
    assert 'PRIVATE TITLE' not in response.text and 'PRIVATE DM' not in response.text
    assert client.get('https://lab.dobeworks.com/', follow_redirects=False).status_code == 303
