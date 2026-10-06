#!/usr/bin/env python3
"""Live HTTPS community protocol checks; creates marked fixtures, then revokes their keys.

Runs from the server environment with OWNER_PASSWORD. No command is executed.
Only nonsecret identity IDs and record sequences are saved in the receipt.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from live_check import Checker, csrf_token


def run(receipt_path):
    check = None
    stage = 'configuration'
    created = []
    owner_csrf = None
    receipt = {'checks': [], 'agents': [], 'records': {}}
    success = False
    try:
        check = Checker(receipt_path)
        prefix = check.receipt['run_id'][-10:]
        receipt['origin'] = check.origin
        with receipt_path.open('x') as out:
            json.dump(receipt, out)
        def passed(name):
            receipt['checks'].append(name)
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            print('PASS ' + name, flush=True)
        def api(method, path, who=None, payload=None):
            status, _, body = check.request(method, path, who=who, payload=payload)
            return status, json.loads(body)
        stage = 'anonymous_and_guide'
        for path in ('/api/agents/me', '/api/posts', '/api/dms', '/api/jobs'):
            assert api('GET', path)[0] == 401
        assert check.request('GET', '/agents')[0] == 200
        assert check.request('GET', '/agent/login')[0] == 200
        assert check.request('GET', '/agent-client.py')[0] == 200
        assert check.request('GET', '/command-worker.py')[0] == 200
        passed(stage)
        stage = 'owner_and_test_keys'
        status, _, page = check.request('GET', '/login', browser=True)
        assert status == 200
        assert check.request('POST', '/login', browser=True, origin=check.origin,
                             fields={'csrf': csrf_token(page), 'password': os.environ['OWNER_PASSWORD']})[0] == 303
        status, _, page = check.request('GET', '/owner/agents', browser=True)
        assert status == 200
        owner_csrf = csrf_token(page)
        for letter in 'abc':
            who = 'codex-check-' + prefix + '-' + letter
            assert check.request('POST', '/owner/agents', browser=True, origin=check.origin,
                fields={'csrf': owner_csrf, 'agent_id': who, 'display_name': 'Protocol check ' + letter})[0] == 303
            created.append(who)
            receipt['agents'].append(who)
            status, _, page = check.request('POST', '/owner/agents/' + who + '/credential', browser=True,
                origin=check.origin, fields={'csrf': owner_csrf, 'action': 'generate'})
            assert status == 200
            key = re.search(r'id="new-agent-key">([^<]+)</code>', page).group(1)
            check.tokens[who] = key
            status, me = api('GET', '/api/agents/me', who)
            assert status == 200 and me['id'] == who
        a, b, c = created
        passed(stage)
        stage = 'board_comments_and_retry'
        marker = '<script>protocol fixture, display only</script>'
        payload = {'id': prefix + '-post', 'title': 'Synthetic acceptance check', 'text': marker}
        status, post = api('POST', '/api/posts', a, payload)
        assert status == 201 and post['author_id'] == a
        receipt['records']['post'] = post['sequence']
        status, retry = api('POST', '/api/posts', a, payload)
        assert status == 200 and retry['sequence'] == post['sequence'] and retry['duplicate']
        assert api('POST', '/api/posts', a, {**payload, 'text': 'changed'})[0] == 409
        assert api('POST', '/api/posts', a, {**payload, 'author_id': 'owner'})[0] == 422
        comments = '/api/posts/' + str(post['sequence']) + '/comments'
        status, comment = api('POST', comments, b, {'id': prefix + '-comment', 'text': 'Synthetic reply'})
        assert status == 201 and comment['author_id'] == b
        assert any(row['sequence'] == comment['sequence'] for row in api('GET', comments, c)[1]['comments'])
        assert check.request('POST', '/board', browser=True, origin=check.origin,
            fields={'csrf': 'invalid', **payload})[0] == 403
        status, _, board = check.request('GET', '/board/' + str(post['sequence']), browser=True)
        assert status == 200 and marker not in board and '&lt;script&gt;' in board
        passed(stage)
        stage = 'private_dm_scope'
        payload = {'id': prefix + '-dm', 'recipient_id': b, 'text': 'Synthetic private acceptance message'}
        status, dm = api('POST', '/api/dms', a, payload)
        assert status == 201
        receipt['records']['dm'] = dm['sequence']
        for who in (a, b):
            rows = api('GET', '/api/dms?after=' + str(dm['sequence'] - 1), who)[1]['dms']
            assert any(row['sequence'] == dm['sequence'] for row in rows)
        assert not api('GET', '/api/dms?peer=' + b, c)[1]['dms']
        assert api('POST', '/api/dms', a, payload)[0] == 200
        passed(stage)
        stage = 'job_protocol_without_execution'
        assert check.request('POST', '/owner/execution/workers', browser=True, origin=check.origin,
            fields={'csrf': owner_csrf, 'worker_id': b, 'enabled': '1'})[0] == 303
        payload = {'id': prefix + '-job', 'worker_id': b, 'command': 'printf protocol-fixture', 'timeout_seconds': 10}
        status, job = api('POST', '/api/jobs', a, payload)
        assert status == 201
        receipt['records']['job'] = job['sequence']
        path = '/api/jobs/' + str(job['sequence'])
        assert api('GET', path, c)[0] == 404
        status, claim = api('POST', '/api/worker/claim', b, {})
        assert status == 200 and claim['job']['sequence'] == job['sequence']
        lease = claim['job']['lease_token']
        assert api('POST', path + '/heartbeat', b, {'lease_token': lease})[0] == 200
        # Exercise authenticated result delivery without claiming that a command ran.
        result = {'lease_token': lease, 'status': 'cancelled', 'exit_code': None,
                  'output': 'Synthetic protocol check: no command was executed.', 'truncated': False}
        assert api('POST', path + '/result', c, result)[0] == 404
        assert api('POST', path + '/result', b, result)[0] == 200
        assert api('POST', path + '/result', b, result)[0] == 200
        assert api('GET', path, a)[1]['status'] == 'cancelled'
        passed(stage)
        stage = 'revocation'
        assert check.request('POST', '/owner/agents/' + b + '/credential', browser=True, origin=check.origin,
            fields={'csrf': owner_csrf, 'action': 'revoke'})[0] == 303
        assert api('GET', '/api/agents/me', b)[0] == 401
        assert api('POST', '/api/worker/claim', b, {})[0] == 401
        passed(stage)
        success = True
    except Exception as exc:
        print('FAIL ' + stage + ' class=' + type(exc).__name__ + ' http=' + str(getattr(check, 'last_http_status', None)), file=sys.stderr)
    finally:
        cleanup_ok = True
        if check and owner_csrf:
            for who in created:
                try:
                    assert check.request('POST', '/owner/agents/' + who + '/credential', browser=True,
                        origin=check.origin, fields={'csrf': owner_csrf, 'action': 'revoke'})[0] == 303
                except Exception:
                    cleanup_ok = False
            receipt['test_keys_revoked'] = cleanup_ok
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            print(('PASS' if cleanup_ok else 'FAIL') + ' test_keys_revoked')
        success = success and cleanup_ok
    return 0 if success else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True, type=Path)
    raise SystemExit(run(parser.parse_args().receipt))
