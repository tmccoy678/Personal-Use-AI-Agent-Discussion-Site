import json
import os
import sys
import subprocess
import time
from urllib.error import URLError

import pytest

import agent_client
import command_worker


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("BRIDGE_URL", "https://lab.example")
    monkeypatch.setenv("BRIDGE_TOKEN", "private-agent-key")


def test_client_retry_and_plain_text(configured, monkeypatch, capsys):
    sent = []
    def lose(base, token, path, payload):
        sent.append((path, payload))
        raise URLError("private-agent-key should never print")
    monkeypatch.setattr(agent_client, "request", lose)
    assert agent_client.main(["dm", "muse-phone", "private text", "--id", "retry-1"]) == 1
    output = capsys.readouterr()
    assert "--id retry-1" in output.err
    assert "private text" not in output.err and "private-agent-key" not in output.err
    assert sent == [("/api/dms", {"id": "retry-1", "text": "private text", "recipient_id": "muse-phone"})]


def test_client_bounded_poll_keeps_cursor_and_escapes_terminal(configured, monkeypatch, capsys):
    calls = []
    def read(base, token, path):
        calls.append(path)
        return {"dms": [{"text": "\x1b[31m$(touch unwanted)"}], "next_after": len(calls)}
    monkeypatch.setattr(agent_client, "request", read)
    monkeypatch.setattr(agent_client.time, "sleep", lambda _: None)
    assert agent_client.main(["inbox", "--follow", "--max-polls", "2"]) == 0
    output = capsys.readouterr().out
    assert "\x1b" not in output and "\\u001b" in output
    assert calls == ["/api/dms?after=0", "/api/dms?after=1"]


def test_explicit_job_submission_is_separate_from_dm(configured, monkeypatch, capsys):
    calls = []
    def send(base, token, path, payload):
        calls.append((path, payload))
        return {"sequence": 1, "state": "pending"}
    monkeypatch.setattr(agent_client, "request", send)
    assert agent_client.main(["run", "grok-phone", "pwd", "--id", "job-1", "--timeout", "12"]) == 0
    assert calls == [("/api/jobs", {"id": "job-1", "worker_id": "grok-phone", "command": "pwd", "timeout_seconds": 12})]


@pytest.mark.parametrize("url", ["http://public.example", "https://x@y.example", "https://lab.example?key=a", "https://lab.example/api"])
def test_agent_client_rejects_unsafe_origins(url):
    with pytest.raises(ValueError):
        agent_client.origin(url)


def test_worker_executes_only_explicit_job_and_strips_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_TOKEN", "do-not-inherit")
    monkeypatch.setenv("OWNER_PASSWORD", "also-private")
    job = {"command": "printf '%s/%s' \"${BRIDGE_TOKEN-unset}\" \"${OWNER_PASSWORD-unset}\"", "timeout_seconds": 2}
    result = command_worker.execute(job, tmp_path, lambda: False)
    assert result == {"status": "succeeded", "exit_code": 0, "output": "unset/unset", "truncated": False}


def test_worker_limits_output_and_time(tmp_path):
    import shlex
    command = shlex.quote(sys.executable) + " -c 'print(\"x\"*100000)'"
    result = command_worker.execute({"command": command, "timeout_seconds": 2}, tmp_path, lambda: False)
    assert result["status"] == "succeeded" and result["truncated"]
    assert len(result["output"].encode()) <= command_worker.OUTPUT_LIMIT
    result = command_worker.execute({"command": "sleep 30", "timeout_seconds": 1}, tmp_path, lambda: False)
    assert result["status"] == "timed_out"


def test_worker_cancels_on_stop_or_lost_authorization(tmp_path):
    result = command_worker.execute({"command": "sleep 30", "timeout_seconds": 30}, tmp_path, lambda: True)
    assert result["status"] == "cancelled"
    def lost():
        raise URLError("secret must not print")
    result = command_worker.execute({"command": "sleep 30", "timeout_seconds": 30}, tmp_path, lost)
    assert result["status"] == "cancelled"


def test_worker_setup_failure_still_stops_child(tmp_path, monkeypatch):
    from types import SimpleNamespace
    stopped = []
    child = SimpleNamespace(stdout=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(command_worker.subprocess, "Popen", lambda *a, **k: child)
    def fail():
        raise OSError("selector unavailable")
    monkeypatch.setattr(command_worker.selectors, "DefaultSelector", fail)
    monkeypatch.setattr(command_worker, "stop", lambda process: stopped.append(process))
    with pytest.raises(OSError):
        command_worker.execute({"command": "true", "timeout_seconds": 1}, tmp_path, lambda: False)
    assert stopped == [child]


def test_worker_requires_explicit_opt_in_and_expected_identity(configured, monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit):
        command_worker.main(["--worker-id", "grok-phone", "--workdir", str(tmp_path)])
    calls = []
    def wrong(*args, **kwargs):
        calls.append(args[2])
        return {"id": "codex"}
    monkeypatch.setattr(command_worker, "request", wrong)
    assert command_worker.main(["--allow-command-execution", "--worker-id", "grok-phone", "--workdir", str(tmp_path)]) == 1
    assert calls == ["/api/agents/me"]


def test_normal_worker_termination_stops_its_job_group(tmp_path):
    import shlex
    start = tmp_path / "started"
    escaped = tmp_path / "escaped"
    command = f"touch {shlex.quote(str(start))}; sleep 1; touch {shlex.quote(str(escaped))}"
    code = f'''
import command_worker
def request(base, token, path, payload=None, **kwargs):
    if path == '/api/agents/me': return {{'id': 'codex-test'}}
    if path == '/api/worker/claim': return {{'job': {{'sequence': 1, 'worker_id': 'codex-test', 'lease_token': 'lease', 'command': {command!r}, 'timeout_seconds': 10}}}}
    return {{'cancel_requested': False}}
command_worker.request = request
raise SystemExit(command_worker.main(['--allow-command-execution', '--worker-id', 'codex-test', '--workdir', {str(tmp_path)!r}]))
'''
    process = subprocess.Popen([sys.executable, "-c", code], env={**os.environ, "BRIDGE_TOKEN": "test-only"},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 3
        while not start.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert start.exists()
        process.terminate()
        assert process.wait(timeout=3) == 130
        time.sleep(1.1)
        assert not escaped.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()


def test_client_public_stream_is_an_explicit_separate_destination(configured, monkeypatch, capsys):
    calls = []
    def send(base, token, path, payload=None):
        calls.append((path, payload))
        return {'entries': [], 'next_after': 7}
    monkeypatch.setattr(agent_client, 'request', send)
    assert agent_client.main(['publish', 'Public update', '--id', 'public-1']) == 0
    assert agent_client.main(['publish', 'Public reply', '--id', 'public-2', '--reply-to', '7']) == 0
    assert agent_client.main(['stream', '--after', '7']) == 0
    assert calls == [('/api/stream', {'id':'public-1', 'text':'Public update'}),
                     ('/api/stream', {'id':'public-2', 'text':'Public reply', 'reply_to':7}),
                     ('/api/stream?after=7', None)]
    calls.clear()
    assert agent_client.main(['publish', 'Bad reply', '--reply-to', '0']) == 1
    assert not calls
