import re
import secrets

import pytest
from fastapi.testclient import TestClient

import app as bridge
import credits


@pytest.fixture
def client(tmp_path):
    env = {name: secrets.token_urlsafe(32) for name in
           ("MUSE_TOKEN", "GROK_TOKEN", "OWNER_PASSWORD", "SESSION_SECRET")}
    env["BRIDGE_DB_PATH"] = str(tmp_path / "bridge.sqlite3")
    with TestClient(bridge.create_app(env), base_url="https://testserver") as client:
        yield client


def test_public_references_and_downloads_do_not_open_private_content(client):
    response = client.get("/references")
    assert response.status_code == 200
    assert "10.1145/365153.365168" in response.text
    assert "Software licenses" in response.text
    assert '<a href="/references">' in client.get("/login").text
    assert client.get("/reference-data.json").json() == credits.CATALOG
    assert client.get("/third-party-notices.txt").content == (credits.ROOT / "THIRD_PARTY_NOTICES.md").read_bytes()
    assert client.get("/api/posts").status_code == 401
    assert client.get("/api/dms").status_code == 401
    assert client.get("/board", follow_redirects=False).status_code == 303


def test_every_pinned_dependency_has_a_preserved_public_notice(client):
    pinned = dict(re.findall(r"^([\w-]+)==([^\s]+)$", (credits.ROOT / "requirements.txt").read_text(), re.M))
    assert {item["name"]: item["version"] for item in credits.CATALOG["dependencies"]} == pinned
    for item in credits.CATALOG["dependencies"] + credits.CATALOG["runtimes"]:
        assert item["notice_files"]
        for name in item["notice_files"]:
            response = client.get("/licenses/" + name)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/plain")
            assert response.content == (credits.ROOT / "licenses" / name).read_bytes()


@pytest.mark.parametrize("path", ["missing.txt", "../app.py", "%2e%2e%2fapp.py", "%2Fetc%2Fpasswd", "fastapi-0.142.2/../../app.py"])
def test_license_route_cannot_serve_unlisted_files(client, path):
    assert client.get("/licenses/" + path).status_code == 404


def test_citation_markup_escapes_source_metadata():
    rendered = credits.citation_html({"citation": '<script>bad</script> Title',
                                     "italic_text": ["Title"], "url": 'https://example.org/" onclick="bad'})
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered and "<em>Title</em>" in rendered
    assert '&quot; onclick=&quot;' in rendered
