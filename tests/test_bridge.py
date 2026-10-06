import json
import re
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import app as bridge
import bridge_client


@pytest.fixture
def env(tmp_path):
    values = {name: secrets.token_urlsafe(32) for name in
              ("MUSE_TOKEN", "GROK_TOKEN", "OWNER_PASSWORD", "SESSION_SECRET")}
    return {**values, "BRIDGE_DB_PATH": str(tmp_path / "bridge.sqlite3")}


@pytest.fixture
def client(env):
    with TestClient(bridge.create_app(env), base_url="https://testserver") as client:
        yield client


def auth(env, who):
    return {"Authorization": "Bearer " + env[who.upper() + "_TOKEN"]}


def send(client, env, who="muse", id="one", text="hello", **extra):
    return client.post("/api/messages", headers=auth(env, who), json={"id": id, "text": text, **extra})


def csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def login(client, env):
    token = csrf(client.get("/login").text)
    return client.post("/login", data={"csrf": token, "password": env["OWNER_PASSWORD"]}, follow_redirects=False)


def test_fail_closed_secrets_and_duplicates(env):
    for name in ("MUSE_TOKEN", "GROK_TOKEN", "OWNER_PASSWORD", "SESSION_SECRET"):
        for invalid in ("", "short", "a" * 60):
            with pytest.raises(RuntimeError, match=name):
                with TestClient(bridge.create_app({**env, name: invalid})):
                    pass
    with pytest.raises(RuntimeError, match="different"):
        with TestClient(bridge.create_app({**env, "GROK_TOKEN": env["MUSE_TOKEN"]})):
            pass


def test_unauthenticated_and_minimal_health(client):
    assert client.get("/").url.path == "/login"
    assert client.get("/api/messages").status_code == 401
    assert client.post("/api/messages", json={}).status_code == 401
    assert client.post("/owner/messages", data={}).status_code == 401
    assert client.get("/healthz").json() == {"ok": True}
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    response = client.get("/login")
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_scoped_inboxes_and_no_identity_override(client, env):
    assert send(client, env).status_code == 201
    assert send(client, env, "grok", text="reply").status_code == 201
    assert send(client, env, sender="owner").status_code == 422
    assert send(client, env, recipient="muse").status_code == 422
    muse = client.get("/api/messages", headers=auth(env, "muse")).json()
    grok = client.get("/api/messages", headers=auth(env, "grok")).json()
    assert [(m["sender"], m["recipient"], m["text"]) for m in muse["messages"]] == [("grok", "muse", "reply")]
    assert [m["text"] for m in grok["messages"]] == ["hello"]
    assert client.get("/api/messages", headers={"Authorization": "Bearer " + env["OWNER_PASSWORD"]}).status_code == 401
    assert client.get("/api/messages?after=" + str(grok["next_after"]), headers=auth(env, "grok")).json()["messages"] == []


def test_idempotency_conflict_and_persistence(client, env):
    first = send(client, env).json()
    retry = send(client, env)
    assert retry.status_code == 200 and retry.json()["duplicate"] is True
    assert retry.json()["sequence"] == first["sequence"]
    assert send(client, env, text="changed").status_code == 409
    assert send(client, env, "grok").status_code == 201
    with TestClient(bridge.create_app(env), base_url="https://testserver") as restarted:
        incoming = restarted.get("/api/messages", headers=auth(env, "grok")).json()
        assert len(incoming["messages"]) == 1
        assert incoming["messages"][0]["sequence"] == first["sequence"]


def test_limits_and_validation(client, env):
    assert send(client, env, text="é" * 8193).status_code == 413
    assert send(client, env, text="x" * bridge.MAX_TEXT_BYTES).status_code == 201
    assert send(client, env, id="bad space").status_code == 422
    assert send(client, env, id="empty", text=" ").status_code == 422
    assert client.post("/api/messages", headers={**auth(env, "muse"), "Content-Type": "application/json"},
                       content=b'{"id":"surrogate","text":"\\ud800"}').status_code == 422
    assert client.post("/api/messages", headers={**auth(env, "muse"), "Content-Type": "application/json"},
                       content=b" " * (bridge.MAX_BODY_BYTES + 1)).status_code == 413
    for after in ("-1", str(2**63), "bad"):
        assert client.get("/api/messages?after=" + after, headers=auth(env, "muse")).status_code == 422


def test_bounded_reads_and_retention(client, env, monkeypatch):
    for index in range(105):
        assert send(client, env, id=str(index)).status_code == 201
    assert len(client.get("/api/messages", headers=auth(env, "grok")).json()["messages"]) == 100
    monkeypatch.setattr(bridge, "MAX_MESSAGES", 5)
    rows = client.get("/api/messages", headers=auth(env, "grok")).json()["messages"]
    assert len(rows) == 5 and rows[0]["id"] == "100"
    with sqlite3.connect(env["BRIDGE_DB_PATH"]) as db:
        db.execute("UPDATE messages SET created_at=0")
    assert client.get("/api/messages", headers=auth(env, "grok")).json()["messages"] == []


def test_owner_csrf_secure_cookies_and_xss(client, env):
    assert client.post("/login", data={"password": env["OWNER_PASSWORD"]}).status_code == 403
    response = login(client, env)
    assert response.status_code == 303
    cookie = response.headers.get_list("set-cookie")[0]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert client.get("/api/messages").status_code == 401  # browser session never grants agent identity
    token = csrf(client.get("/").text)
    fields = {"csrf": token, "recipient": "grok", "id": "owner-one", "text": '<script>alert("x")</script>\x1b[31m'}
    assert client.post("/owner/messages", data={**fields, "csrf": "bad"}).status_code == 403
    assert client.post("/owner/messages", headers={"Origin": "https://evil.test"}, data=fields).status_code == 403
    assert client.post("/owner/messages", data=fields, follow_redirects=False).status_code == 303
    html = client.get("/").text
    assert "<script>" not in html and "&lt;script&gt;" in html
    incoming = client.get("/api/messages", headers=auth(env, "grok")).json()["messages"]
    assert incoming[0]["sender"] == "owner" and incoming[0]["text"] == fields["text"]
    assert client.get("/api/messages", headers=auth(env, "muse")).json()["messages"] == []
    assert client.post("/logout", data={"csrf": ""}).status_code == 403
    assert client.post("/logout", data={"csrf": token}, follow_redirects=False).status_code == 303
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_rate_limit(client, env):
    token = csrf(client.get("/login").text)
    for _ in range(5):
        assert client.post("/login", data={"csrf": token, "password": "wrong"}).status_code == 401
    response = client.post("/login", data={"csrf": token, "password": env["OWNER_PASSWORD"]})
    assert response.status_code == 429 and response.headers["Retry-After"] == "600"


def test_https_and_explicit_loopback_only(env):
    with TestClient(bridge.create_app(env), base_url="http://127.0.0.1", client=("127.0.0.1", 80)) as client:
        assert client.get("/login").status_code == 400
        assert client.get("/healthz").status_code == 200
    local = {**env, "BRIDGE_ALLOW_LOOPBACK_HTTP": "1"}
    with TestClient(bridge.create_app(local), base_url="http://127.0.0.1", client=("127.0.0.1", 80)) as client:
        assert client.get("/login").status_code == 200
        assert "Secure" not in client.get("/login").headers["set-cookie"]
    with TestClient(bridge.create_app(local), base_url="http://127.0.0.1", client=("203.0.113.10", 80)) as client:
        assert client.get("/login").status_code == 400
    with TestClient(bridge.create_app(local), base_url="http://public.test", client=("127.0.0.1", 80)) as client:
        assert client.get("/login").status_code == 400
    with TestClient(bridge.create_app(local), base_url="https://public.test", client=("203.0.113.10", 80)) as client:
        assert client.get("/login").status_code == 400


def test_client_redirect_refused_and_never_forwards_token():
    hits = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/redirect-target")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError, match="Redirect refused"):
            bridge_client.request(f"http://127.0.0.1:{server.server_port}/api/messages", "secret")
        assert hits == ["/api/messages"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_trusted_reverse_proxy_preserves_https_login_and_csrf(env):
    app = ProxyHeadersMiddleware(bridge.create_app(env), trusted_hosts=["10.0.0.1"])
    with TestClient(app, base_url="http://bridge.example", client=("10.0.0.1", 80)) as client:
        headers = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.10",
                   "Origin": "https://bridge.example"}
        assert client.get("/login").status_code == 400
        response = client.get("/login", headers=headers)
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
        # Simulate the outer HTTPS browser: the test client's transport URL is internal HTTP.
        headers["Cookie"] = "bridge_login=" + client.cookies["bridge_login"]
        response = client.post("/login", headers=headers,
                               data={"csrf": csrf(response.text), "password": env["OWNER_PASSWORD"]},
                               follow_redirects=False)
        assert response.status_code == 303
        headers["Cookie"] = "bridge_session=" + client.cookies["bridge_session"]
        token = csrf(client.get("/", headers=headers).text)
        assert client.post("/owner/messages", headers=headers,
                           data={"csrf": token, "id": "proxy", "recipient": "grok", "text": "hello"},
                           follow_redirects=False).status_code == 303
    with TestClient(app, base_url="http://bridge.example", client=("203.0.113.10", 80)) as client:
        assert client.get("/login", headers={"X-Forwarded-Proto": "https"}).status_code == 400


def test_client_prints_escaped_text(monkeypatch, capsys):
    monkeypatch.setenv("BRIDGE_URL", "https://bridge.example")
    monkeypatch.setenv("BRIDGE_TOKEN", "test-token")
    monkeypatch.setattr("sys.argv", ["bridge_client.py", "poll"])
    text = "\x1b[31m$(touch example)\ntext"
    monkeypatch.setattr(bridge_client, "request", lambda *args: {"messages": [{"text": text}], "next_after": 1})
    assert bridge_client.main() == 0
    output = capsys.readouterr().out
    assert "\x1b" not in output and "\\u001b" in output
    assert json.loads(output)["text"] == text


def test_client_lost_reply_exposes_retry_id_and_preserves_idempotency(client, env, monkeypatch, capsys):
    monkeypatch.setenv("BRIDGE_URL", "https://bridge.example")
    monkeypatch.setenv("BRIDGE_TOKEN", env["MUSE_TOKEN"])
    monkeypatch.setattr("sys.argv", ["bridge_client.py", "send", "private text"])
    committed = []
    def lose_first_reply(url, token, payload):
        response = client.post("/api/messages", headers=auth(env, "muse"), json=payload)
        committed.append(response.json())
        if len(committed) == 1:
            raise URLError("Simulate network loss after commit")
        return response.json()
    monkeypatch.setattr(bridge_client, "request", lose_first_reply)
    assert bridge_client.main() == 1
    failed = capsys.readouterr()
    assert not failed.out
    assert "private text" not in failed.err and env["MUSE_TOKEN"] not in failed.err
    retry_id = re.search(r"--id ([A-Za-z0-9_.:-]+)", failed.err).group(1)
    assert retry_id == committed[0]["id"]
    monkeypatch.setattr("sys.argv", ["bridge_client.py", "send", "private text", "--id", retry_id])
    assert bridge_client.main() == 0
    retried = capsys.readouterr()
    assert json.loads(retried.out)["duplicate"] is True and not retried.err
    assert committed[0]["sequence"] == committed[1]["sequence"]
    assert len(client.get("/api/messages", headers=auth(env, "grok")).json()["messages"]) == 1


@pytest.mark.parametrize("url", ["http://public.test", "https://name:password@example.com", "https://example.com?token=x",
                                 "https://example.com/api", "file:///tmp/example"])
def test_client_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        bridge_client.endpoint(url)
