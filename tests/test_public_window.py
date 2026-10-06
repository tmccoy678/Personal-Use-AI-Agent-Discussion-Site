import sqlite3
from contextlib import closing

import pytest

import app as bridge
import public_window
from test_community import env, system, owner_login, headers, csrf, credential, agent_login


def publish(client, token, text="A public update", id="update-1", **extra):
    return client.post("/api/stream", headers=headers(token), json={"id": id, "text": text, **extra})


def seed_private(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""INSERT INTO community_posts(id,author_id,title,text,created_at)
            VALUES('private-post','codex','PRIVATE TITLE','PRIVATE BODY',123)""")
        db.execute("""INSERT INTO community_comments(id,author_id,post_sequence,text,created_at)
            VALUES('private-comment','muse-mac',1,'PRIVATE COMMENT',123)""")
        db.execute("""INSERT INTO community_dms(id,sender_id,recipient_id,text,created_at)
            VALUES('private-dm','codex','owner','PRIVATE DM',123)""")
        db.execute("""INSERT INTO execution_jobs(id,submitter_id,worker_id,command,timeout_seconds,
            status,created_at,lease_expires_at,output,lease_hash)
            VALUES('private-job','codex','grok-phone','PRIVATE COMMAND',30,'running',123,1,'PRIVATE OUTPUT','PRIVATE LEASE')""")


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.iterdump())


def test_public_reads_are_read_only_and_private_content_never_appears(system, env):
    client, tokens = system
    seed_private(env["BRIDGE_DB_PATH"])
    response = publish(client, tokens["codex"])
    assert response.status_code == 201
    client.cookies.clear()
    before = snapshot(env["BRIDGE_DB_PATH"])
    response = client.get("/window")
    assert response.status_code == 200
    assert "A public update" in response.text and "Codex" in response.text
    assert '<meta http-equiv="refresh" content="60">' in response.text
    assert '<form' not in response.text and '<script' not in response.text
    assert 'PRIVATE' not in response.text and 'private agent lab' not in response.text
    assert 'window-grid' not in response.text and 'Activity summary' not in response.text
    assert response.headers['cache-control'] == 'no-store' and 'set-cookie' not in response.headers
    result = client.get('/api/stream').json()
    assert set(result['entries'][0]) == {'sequence', 'display_name', 'text', 'reply_to', 'created_at'}
    assert result['next_after'] == 1
    assert client.post('/api/stream', json={'id':'anonymous','text':'no'}).status_code == 401
    assert client.post('/window', json={'text':'no'}).status_code == 405
    for path in ('/api/posts', '/api/dms', '/api/agents', '/api/jobs'):
        assert client.get(path).status_code == 401
    assert snapshot(env['BRIDGE_DB_PATH']) == before
    original = response.content
    with closing(sqlite3.connect(env['BRIDGE_DB_PATH'])) as db, db:
        db.execute("UPDATE community_posts SET text='CHANGED PRIVATE'")
        db.execute("UPDATE community_agents SET display_name='CHANGED PRIVATE',last_used_at=999")
        db.execute("UPDATE execution_jobs SET command='CHANGED PRIVATE',output='CHANGED PRIVATE'")
    assert client.get('/window').content == original


def test_authenticated_public_replies_idempotency_and_escaping(system, env):
    client, tokens = system
    seed_private(env['BRIDGE_DB_PATH'])
    # A private post with the same sequence does not make a valid public reply target.
    assert publish(client, tokens['codex'], reply_to=1).status_code == 404
    first = publish(client, tokens['codex'], '<script>alert(1)</script>')
    assert first.status_code == 201 and first.json()['display_name'] == 'Codex'
    assert publish(client, tokens['codex'], '<script>alert(1)</script>').json()['duplicate'] is True
    assert publish(client, tokens['codex'], 'changed').status_code == 409
    assert publish(client, tokens['codex'], '<script>alert(1)</script>', reply_to=1).status_code == 409
    reply = publish(client, tokens['muse-phone'], 'A reply', reply_to=1)
    assert reply.status_code == 201 and reply.json()['display_name'] == 'Muse Phone'
    body = client.get('/window').text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in body and '<script>' not in body
    assert '↳ #1' in body and '/window?before=2#entry-1' in body
    assert body.index('A reply') < body.index('&lt;script&gt;')
    assert [row['sequence'] for row in client.get('/api/stream').json()['entries']] == [1, 2]
    assert client.get('/api/stream?after=2').json() == {'entries': [], 'next_after': 2}
    for extra in ({'author_id':'muse-mac'}, {'display_name':'Muse'}, {'reply_to':True}, {'reply_to':None}, {'reply_to':0}, {'reply_to':2**63}):
        assert publish(client, tokens['codex'], id='bad', **extra).status_code == 422
    assert publish(client, tokens['codex'], text='x'*16385).status_code == 413
    credential(client, 'codex', action='revoke')
    assert publish(client, tokens['codex'], id='revoked').status_code == 401
    assert 'alert(1)' in client.get('/api/stream').json()['entries'][0]['text']


def test_browser_publish_requires_signin_and_csrf(system):
    client, tokens = system
    response = client.get('/stream')
    assert 'Post publicly' in response.text and 'Public on dobeworks.com' in response.text
    data = {'id':'owner-update', 'text':'Owner update'}
    assert client.post('/stream', data=data).status_code == 403
    data['csrf'] = csrf(response)
    assert client.post('/stream', data=data, follow_redirects=False).status_code == 303
    assert client.get('/api/stream').json()['entries'][0]['display_name'] == 'Owner'
    client.cookies.clear()
    assert client.get('/stream', follow_redirects=False).status_code == 303
    assert client.post('/stream', data=data).status_code == 401
    agent_login(client, tokens['codex-blu-private'])
    data = {'id':'blu-public', 'text':'Public reply', 'reply_to':'1', 'csrf':csrf(client.get('/stream'))}
    assert client.post('/stream', data=data, follow_redirects=False).status_code == 303
    assert client.get('/api/stream?after=1').json()['entries'][0]['display_name'] == 'Blu Private'


def test_pagination_limits_and_storage_cap(system, env, monkeypatch):
    client, tokens = system
    monkeypatch.setattr(public_window, 'PAGE_SIZE', 2)
    for i in range(3):
        assert publish(client, tokens['codex'], id=f'message-{i}', text=f'body-{i}').status_code == 201
    first = client.get('/api/stream').json()
    assert [row['sequence'] for row in first['entries']] == [1, 2]
    assert [row['sequence'] for row in client.get('/api/stream?after=2').json()['entries']] == [3]
    current = client.get('/window').text
    assert 'body-2' in current and 'body-1' in current and 'body-0' not in current
    older = client.get('/window?before=2').text
    assert 'body-0' in older and 'body-1' not in older and 'http-equiv="refresh"' not in older
    monkeypatch.setattr(public_window, 'MAX_ENTRIES', 3)
    assert publish(client, tokens['codex'], id='full').status_code == 507
    assert publish(client, tokens['codex'], id='message-0', text='body-0').status_code == 200
    monkeypatch.setattr(public_window, 'MAX_ENTRIES', 4)
    with closing(sqlite3.connect(env['BRIDGE_DB_PATH'])) as db, db:
        db.execute('UPDATE community_usage SET content_bytes=?', (public_window.community.MAX_CONTENT_BYTES,))
    assert publish(client, tokens['codex'], id='full-bytes').status_code == 507


@pytest.mark.parametrize('cursor', ['-1', str(2**63), 'bad'])
def test_public_cursor_bounds(system, cursor):
    client, _ = system
    for path in ('/window?before=', '/api/stream?after=', 'https://dobeworks.com/?before='):
        assert client.get(path + cursor).status_code == 422


def test_missing_database_is_generic_and_not_created(system, tmp_path):
    client, _ = system
    path = tmp_path / 'PRIVATE-missing.sqlite3'
    object.__setattr__(client.app.state.settings, 'db_path', str(path))
    for route in ('/window', '/api/stream'):
        response = client.get(route)
        assert response.status_code == 503
        assert 'Stream temporarily unavailable' in response.text
        assert 'PRIVATE' not in response.text and 'sqlite' not in response.text.lower()
    assert not path.exists()


def test_public_reader_cannot_read_private_tables_or_fields(system, env, monkeypatch):
    client, tokens = system
    publish(client, tokens['codex'])
    connect = sqlite3.connect
    reads = set()
    def readonly_connection(*args, **kwargs):
        assert args[0].endswith('?mode=ro') and kwargs['uri'] is True
        db = connect(*args, **kwargs)
        def authorize(action, table, column, database, source):
            if action == sqlite3.SQLITE_READ:
                reads.add((table, column))
                if table != 'public_stream' or column not in public_window.PUBLIC_FIELDS.split(', '):
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(public_window.sqlite3, 'connect', readonly_connection)
    assert public_window.read_stream(env['BRIDGE_DB_PATH'])[0]['text'] == 'A public update'
    assert {table for table, _ in reads} == {'public_stream'}


def test_migration_is_additive_repeatable_and_does_not_publish_old_content(system, env):
    client, _ = system
    seed_private(env['BRIDGE_DB_PATH'])
    before = snapshot(env['BRIDGE_DB_PATH'])
    bridge.initialize(env['BRIDGE_DB_PATH'])
    bridge.initialize(env['BRIDGE_DB_PATH'])
    assert snapshot(env['BRIDGE_DB_PATH']) == before
    assert client.get('/api/stream').json()['entries'] == []
    assert 'Quiet for now.' in client.get('/window').text


@pytest.mark.parametrize('hostname', ['dobeworks.com', 'www.dobeworks.com'])
def test_apex_public_private_hostname_protected(system, env, hostname):
    client, tokens = system
    publish(client, tokens['codex'])
    client.cookies.clear()
    assert 'A public update' in client.get('https://' + hostname + '/').text
    assert client.get('https://lab.dobeworks.com/', follow_redirects=False).status_code == 303
