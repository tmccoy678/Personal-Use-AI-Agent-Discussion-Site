"""Command queue isolation and ambiguous execution behavior."""
import contextlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from html import escape
from urllib.parse import parse_qs

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

import execution


class TestHub:
    __test__ = False

    def __init__(self, path):
        self.path = path
        self.tokens = {name: name + '-credential' for name in ('muse-mac', 'grok-phone', 'codex')}
        self.revoked = set()
        self.version = {name: 1 for name in self.tokens}

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def find_agent(self, db, name):
        if name not in self.tokens:
            return None
        return {'id': name, 'display_name': name, 'role': 'agent', 'credential_issued': True,
                'status': 'revoked' if name in self.revoked else 'active', '_version': self.version[name]}

    def agents(self, db):
        return [self.find_agent(db, name) for name in self.tokens]

    def api_actor(self, request):
        for name, token in self.tokens.items():
            if request.headers.get('authorization') == 'Bearer ' + token and name not in self.revoked:
                return self.find_agent(None, name)
        raise HTTPException(401, 'Agent authentication required')

    def owner_actor(self, request):
        if request.cookies.get('owner') != 'yes':
            raise HTTPException(401, 'Owner authentication required')
        return {'id': 'owner', 'role': 'owner', 'display_name': 'Owner', '_session': {'csrf': 'nonce'}}

    def browser_actor(self, request):
        return self.owner_actor(request) if request.cookies.get('owner') == 'yes' else self.api_actor(request)

    def check_actor(self, db, actor):
        if actor['role'] != 'owner' and (actor['id'] in self.revoked or actor['_version'] != self.version[actor['id']]):
            raise HTTPException(401, 'Credential revoked')

    async def json(self, request):
        return await request.json()

    async def form(self, request):
        return {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}

    def check_csrf(self, request, fields, actor):
        if fields.get('csrf') != actor['_session']['csrf'] or request.headers.get('origin', 'https://testserver') != 'https://testserver':
            raise HTTPException(403, 'Invalid CSRF')

    def page(self, title, content):
        return HTMLResponse('<h1>' + escape(title) + '</h1>' + content)

    def nav(self, actor):
        return '<a href="/jobs">Jobs</a>'


@pytest.fixture
def setup(tmp_path):
    hub = TestHub(str(tmp_path / 'queue.sqlite3'))
    with hub.db() as db:
        db.execute('PRAGMA journal_mode=WAL')
        execution.initialize(db)
    app = FastAPI()
    execution.install(app, hub)
    with TestClient(app, base_url='https://testserver') as client:
        yield client, hub, app


def headers(name='muse-mac'):
    return {'Authorization': 'Bearer ' + name + '-credential'}


def owner(client):
    client.cookies.set('owner', 'yes')


def enable(client, name='grok-phone', enabled='1', **overrides):
    owner(client)
    return client.post('/owner/execution/workers', data={'csrf': 'nonce', 'worker_id': name, 'enabled': enabled, **overrides}, follow_redirects=False)


def submit(client, id='command-1', **overrides):
    payload = {'id': id, 'worker_id': 'grok-phone', 'command': 'printf hello', 'timeout_seconds': 60, **overrides}
    return client.post('/api/jobs', headers=headers(), json=payload)


def claim(client, name='grok-phone'):
    return client.post('/api/worker/claim', headers=headers(name), json={})


def result(client, job, **overrides):
    return client.post(f'/api/jobs/{job["sequence"]}/result', headers=headers('grok-phone'), json={
        'lease_token': job['lease_token'], 'status': 'succeeded', 'exit_code': 0, 'output': 'hello', 'truncated': False, **overrides})


def test_disabled_default_owner_only_controls_and_csrf(setup):
    client, hub, _ = setup
    assert submit(client).status_code == 409
    assert claim(client).status_code == 409
    assert client.post('/owner/execution/workers', headers=headers(), data={'csrf': 'nonce', 'worker_id': 'grok-phone', 'enabled': '1'}).status_code == 401
    assert enable(client, csrf='wrong').status_code == 403
    assert client.post('/owner/execution/workers', headers={'Origin': 'https://evil.test'}, data={'csrf': 'nonce', 'worker_id': 'grok-phone', 'enabled': '1'}).status_code == 403
    assert enable(client, name='missing').status_code == 422
    assert enable(client).status_code == 303
    assert submit(client).status_code == 201
    assert client.post('/api/jobs', json={}).status_code == 401  # owner cookie is not an agent key


def test_idempotency_visibility_and_author_spoofing(setup):
    client, hub, _ = setup
    enable(client)
    first = submit(client)
    assert first.status_code == 201 and first.json()['submitter_id'] == 'muse-mac'
    assert submit(client).status_code == 200
    assert submit(client, command='different').status_code == 409
    assert submit(client, submitter_id='owner').status_code == 422
    seq = first.json()['sequence']
    assert client.get(f'/api/jobs/{seq}', headers=headers('codex')).status_code == 404
    assert client.get('/api/jobs', headers=headers('codex')).json()['jobs'] == []
    assert client.get(f'/api/jobs/{seq}', headers=headers('grok-phone')).status_code == 200
    assert client.get('/api/jobs?after=-1', headers=headers()).status_code == 422
    assert client.get('/api/jobs', headers=headers()).json()['next_after'] == seq
    assert 'output' not in client.get('/api/jobs', headers=headers()).json()['jobs'][0]


def test_claim_is_atomic_and_one_running_per_worker(setup):
    client, hub, app = setup
    enable(client)
    for n in range(3):
        assert submit(client, id=f'job-{n}').status_code == 201
    barrier = threading.Barrier(5)
    def run_claim():
        with TestClient(app, base_url='https://testserver') as parallel:
            barrier.wait()
            return claim(parallel).json()['job']
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = list(pool.map(lambda _: run_claim(), range(5)))
    assert sum(job is not None for job in jobs) == 1
    job = next(job for job in jobs if job)
    assert job['status'] == 'running'
    assert 'lease_hash' not in job
    with hub.db() as db:
        row = db.execute('SELECT lease_hash FROM execution_jobs WHERE sequence=?', (job['sequence'],)).fetchone()
        assert row['lease_hash'] != job['lease_token']
    assert claim(client).json()['job'] is None
    assert result(client, job).status_code == 200
    assert claim(client).json()['job']['sequence'] != job['sequence']


def test_result_is_worker_and_lease_scoped_idempotent_and_bounded(setup):
    client, hub, _ = setup
    enable(client)
    submit(client)
    job = claim(client).json()['job']
    payload = {'lease_token': job['lease_token'], 'status': 'succeeded', 'exit_code': 0, 'output': 'hello', 'truncated': False}
    for name in ('muse-mac', 'codex'):
        assert client.post(f'/api/jobs/{job["sequence"]}/result', headers=headers(name), json=payload).status_code == 404
    assert result(client, job, lease_token='wrong').status_code == 403
    assert result(client, job, output='é' * 32769).status_code == 413
    assert client.post(f'/api/jobs/{job["sequence"]}/result', headers={**headers('grok-phone'), 'Content-Type': 'application/json'}, content=json.dumps({**payload, 'output': '\ud800'})).status_code == 422
    assert client.post(f'/api/jobs/{job["sequence"]}/heartbeat', headers={**headers('grok-phone'), 'Content-Type': 'application/json'}, content=json.dumps({'lease_token': '\ud800'})).status_code == 403
    assert result(client, job, exit_code=True).status_code == 422
    assert result(client, job, status='pending').status_code == 422
    assert result(client, job, output='é' * 32768, truncated=True).status_code == 200
    assert result(client, job, output='é' * 32768, truncated=True).status_code == 200
    assert result(client, job).status_code == 409
    assert client.get(f'/api/jobs/{job["sequence"]}', headers=headers()).json()['truncated'] is True


def test_expired_lease_is_lost_never_requeued_and_survives_restart(setup, monkeypatch):
    client, hub, app = setup
    monkeypatch.setattr(execution, 'now', lambda: 1000)
    enable(client)
    submit(client)
    job = claim(client).json()['job']
    monkeypatch.setattr(execution, 'now', lambda: 1031)
    response = client.post(f'/api/jobs/{job["sequence"]}/heartbeat', headers=headers('grok-phone'), json={'lease_token': job['lease_token']})
    assert response.status_code == 409
    with hub.db() as db:
        assert db.execute('SELECT status FROM execution_jobs').fetchone()[0] == 'lost'
        execution.initialize(db)
    assert result(client, job).status_code == 409
    assert claim(client).json()['job'] is None
    with TestClient(app, base_url='https://testserver') as restarted:
        assert restarted.get(f'/api/jobs/{job["sequence"]}', headers=headers()).json()['status'] == 'lost'
    assert submit(client).json()['status'] == 'lost'  # same id does not cause execution again


def test_heartbeat_deadline_and_stop_cancel_behavior(setup, monkeypatch):
    client, hub, _ = setup
    current = [1000]
    monkeypatch.setattr(execution, 'now', lambda: current[0])
    enable(client)
    submit(client, timeout_seconds=15)
    submit(client, id='queued')
    job = claim(client).json()['job']
    current[0] = 1020
    beat = client.post(f'/api/jobs/{job["sequence"]}/heartbeat', headers=headers('grok-phone'), json={'lease_token': job['lease_token']})
    assert beat.json() == {'cancel_requested': False, 'lease_expires_at': 1045}
    assert enable(client, enabled='0').status_code == 303
    beat = client.post(f'/api/jobs/{job["sequence"]}/heartbeat', headers=headers('grok-phone'), json={'lease_token': job['lease_token']})
    assert beat.json()['cancel_requested'] is True
    assert claim(client).status_code == 409
    jobs = client.get('/api/jobs', headers=headers()).json()['jobs']
    assert jobs[1]['status'] == 'cancelled'
    assert result(client, job, status='cancelled', exit_code=-15).status_code == 200
    enable(client)
    assert claim(client).json()['job'] is None


def test_owner_submit_cancel_escape_and_agent_cannot_cancel(setup):
    client, hub, _ = setup
    enable(client)
    response = client.post('/owner/execution/jobs', data={'csrf': 'nonce', 'id': 'owner-1', 'worker_id': 'grok-phone', 'command': '<script>alert(1)</script>', 'timeout_seconds': '60'}, follow_redirects=False)
    assert response.status_code == 303
    job = client.get('/api/jobs', headers=headers('grok-phone')).json()['jobs'][0]
    assert job['submitter_id'] == 'owner'
    assert '<script>' not in client.get('/owner/execution').text
    assert '&lt;script&gt;' in client.get('/owner/execution').text
    client.cookies.clear()
    assert client.post(f'/owner/execution/jobs/{job["sequence"]}/cancel', headers=headers('grok-phone'), data={'csrf': 'nonce'}).status_code == 401
    owner(client)
    assert client.post(f'/owner/execution/jobs/{job["sequence"]}/cancel', data={'csrf': 'nonce'}, follow_redirects=False).status_code == 303
    assert claim(client).json()['job'] is None


def test_revocation_check_and_limits(setup, monkeypatch):
    client, hub, _ = setup
    enable(client)
    for timeout in (0, 301, True, '60'):
        assert submit(client, timeout_seconds=timeout).status_code == 422
    assert submit(client, command='x' * 8193).status_code == 413
    assert submit(client, command='a\0b').status_code == 422
    assert submit(client).status_code == 201
    monkeypatch.setattr(execution, 'MAX_JOBS', 1)
    assert submit(client, id='over-cap').status_code == 507
    assert submit(client).status_code == 200
    stale = hub.find_agent(None, 'muse-mac')
    hub.version['muse-mac'] += 1
    with pytest.raises(HTTPException) as error:
        execution.submit(hub, stale, {'id': 'stale', 'worker_id': 'grok-phone', 'command': 'true', 'timeout_seconds': 60})
    assert error.value.status_code == 401
    hub.revoked.add('grok-phone')
    assert claim(client).status_code == 401


def test_revocation_cancels_submitted_and_targeted_jobs_and_owner_can_stop(setup):
    client, hub, _ = setup
    enable(client)
    submit(client)
    submit(client, id='queued')
    job = claim(client).json()['job']
    hub.revoked.add('muse-mac')
    with hub.db() as db:
        execution.revoke_agent(db, 'muse-mac')
        rows = db.execute('SELECT status,cancel_requested FROM execution_jobs ORDER BY sequence').fetchall()
        assert [(r['status'], r['cancel_requested']) for r in rows] == [('running', 1), ('cancelled', 1)]
    hub.revoked.add('grok-phone')
    with hub.db() as db:
        execution.revoke_agent(db, 'grok-phone')
        assert db.execute('SELECT enabled FROM execution_workers').fetchone()[0] == 0
    assert enable(client, enabled='0').status_code == 303
    assert enable(client).status_code == 422


def test_real_app_pending_provision_enable_and_atomic_revocation(tmp_path):
    import re
    import secrets
    import app as bridge

    settings = {name: secrets.token_urlsafe(32) for name in
                ('MUSE_TOKEN', 'GROK_TOKEN', 'OWNER_PASSWORD', 'SESSION_SECRET')}
    settings['BRIDGE_DB_PATH'] = str(tmp_path / 'real.sqlite3')
    with TestClient(bridge.create_app(settings), base_url='https://testserver') as client:
        nonce = re.search(r'name="csrf" value="([^"]+)"', client.get('/login').text).group(1)
        assert client.post('/login', data={'csrf': nonce, 'password': settings['OWNER_PASSWORD']}, follow_redirects=False).status_code == 303
        owner_page = client.get('/owner/agents').text
        nonce = re.search(r'name="csrf" value="([^"]+)"', owner_page).group(1)
        response = client.post('/owner/agents/grok-phone/credential', data={'csrf': nonce, 'action': 'generate'})
        assert response.status_code == 200
        token = re.search(r'<code id="new-agent-key">([^<]+)</code>', response.text).group(1)
        with sqlite3.connect(settings['BRIDGE_DB_PATH']) as db:
            assert db.execute("SELECT first_used_at FROM community_agents WHERE id='grok-phone'").fetchone()[0] is None
        # Deliberately allow the owner to prepare a worker before its first request.
        assert client.post('/owner/execution/workers', data={'csrf': nonce, 'worker_id': 'grok-phone', 'enabled': '1'}, follow_redirects=False).status_code == 303
        for n in range(2):
            assert client.post('/owner/execution/jobs', data={'csrf': nonce, 'id': f'owner-{n}', 'worker_id': 'grok-phone', 'command': 'true', 'timeout_seconds': '60'}, follow_redirects=False).status_code == 303
        auth = {'Authorization': 'Bearer ' + token}
        claimed = client.post('/api/worker/claim', headers=auth, json={})
        assert claimed.status_code == 200 and claimed.json()['job']['submitter_id'] == 'owner'
        assert client.get('/owner/execution').status_code == 200
        assert client.post('/owner/agents/grok-phone/credential', data={'csrf': nonce, 'action': 'revoke'}, follow_redirects=False).status_code == 303
        assert client.post('/api/worker/claim', headers=auth, json={}).status_code == 401
        with sqlite3.connect(settings['BRIDGE_DB_PATH']) as db:
            assert db.execute('SELECT enabled FROM execution_workers').fetchone()[0] == 0
            assert db.execute('SELECT status,cancel_requested FROM execution_jobs ORDER BY sequence').fetchall() == [('running', 1), ('cancelled', 1)]
