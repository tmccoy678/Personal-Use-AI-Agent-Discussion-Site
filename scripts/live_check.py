#!/usr/bin/env python3
"""HTTPS smoke checks. Creates exactly three synthetic messages; never runs their text."""
import argparse
import html
import json
import os
import ssl
import sys
import uuid
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, HTTPSHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CSRFParser(HTMLParser):
    token = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "input" and fields.get("name") == "csrf" and self.token is None:
            self.token = fields.get("value")


class Checker:
    def __init__(self, receipt_path):
        raw = os.environ.get("BRIDGE_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")
        parsed = urlsplit(raw)
        assert (parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path in ("", "/"))
        self.origin = raw.rstrip("/")
        self.tokens = {who: os.environ[who.upper() + "_TOKEN"] for who in ("muse", "grok")}
        assert all(self.tokens.values())
        tls = ssl.create_default_context()  # Certificate and hostname verification always enabled.
        self.machine = build_opener(NoRedirect(), HTTPSHandler(context=tls))
        self.jar = CookieJar()
        self.browser = build_opener(NoRedirect(), HTTPSHandler(context=tls), HTTPCookieProcessor(self.jar))
        self.receipt_path = receipt_path
        self.receipt = {"origin": self.origin, "run_id": "smoke-" + uuid.uuid4().hex, "messages": []}

    def request(self, method, path, *, who=None, payload=None, fields=None, browser=False, origin=None):
        assert path.startswith("/") and not path.startswith("//")
        headers = {"Accept": "application/json, text/html"}
        if who:
            headers["Authorization"] = "Bearer " + self.tokens[who]
        if origin:
            headers["Origin"] = origin
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if fields is not None:
            data = urlencode(fields).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = Request(self.origin + path, data=data, headers=headers, method=method)
        opener = self.browser if browser else self.machine
        try:
            response = opener.open(req, timeout=30)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read(16_777_217)
            assert len(body) <= 16_777_216
            return response.status, response.headers, body.decode("utf-8")

    def save_message(self, row):
        self.receipt["messages"].append({key: row[key] for key in ("id", "sequence", "sender", "recipient")})
        self.receipt_path.write_text(json.dumps(self.receipt, indent=2) + "\n")

    def inbox(self, who, after, extra=""):
        status, _, body = self.request("GET", "/api/messages?" + urlencode({"after": after}) + extra, who=who)
        assert status == 200
        result = json.loads(body)
        assert all(row["recipient"] == who for row in result["messages"])
        return result["messages"]


def csrf_token(text):
    parser = CSRFParser()
    parser.feed(text)
    assert parser.token
    return parser.token


def run(args):
    name = "configuration"
    try:
        checker = Checker(Path(args.receipt))
        if args.verify_restart:
            checker.receipt = json.loads(checker.receipt_path.read_text())
            assert checker.receipt["origin"] == checker.origin
            assert len(checker.receipt["messages"]) == 3
        else:
            assert os.environ.get("OWNER_PASSWORD")
            # Avoid accidentally overwriting another run's receipt.
            with checker.receipt_path.open("x") as stream:
                stream.write(json.dumps(checker.receipt, indent=2) + "\n")
        print("PASS " + name)

        name = "health"
        status, _, body = checker.request("GET", "/healthz")
        assert status == 200 and json.loads(body) == {"ok": True}
        print("PASS " + name)

        if args.verify_restart:
            for entry in checker.receipt["messages"]:
                name = "restart_persistence_" + entry["sender"]
                rows = checker.inbox(entry["recipient"], entry["sequence"] - 1)
                assert any(all(row[key] == entry[key] for key in entry) for row in rows)
                print("PASS " + name)
            return 0

        prefix = checker.receipt["run_id"]
        name = "anonymous_rejected"
        assert checker.request("GET", "/api/messages")[0] == 401
        assert checker.request("POST", "/api/messages", payload={"id": prefix + "-anon", "text": "synthetic"})[0] == 401
        assert checker.request("POST", "/owner/messages", fields={"csrf": "invalid"})[0] == 401
        assert checker.request("GET", "/", browser=True)[0] == 303
        print("PASS " + name)

        for sender in ("muse", "grok"):
            name = sender + "_send"
            payload = {"id": prefix + "-" + sender, "text": "Synthetic bridge smoke check " + prefix + " " + sender}
            status, _, body = checker.request("POST", "/api/messages", who=sender, payload=payload)
            row = json.loads(body)
            recipient = "grok" if sender == "muse" else "muse"
            assert status == 201 and row["sender"] == sender and row["recipient"] == recipient
            assert row["id"] == payload["id"] and row["duplicate"] is False
            checker.save_message(row)
            print("PASS " + name)

            name = sender + "_retry_deduplicates"
            status, _, body = checker.request("POST", "/api/messages", who=sender, payload=payload)
            retry = json.loads(body)
            assert status == 200 and retry["duplicate"] is True and retry["sequence"] == row["sequence"]
            print("PASS " + name)

            name = sender + "_changed_retry_rejected"
            assert checker.request("POST", "/api/messages", who=sender,
                                   payload={**payload, "text": "changed synthetic retry"})[0] == 409
            print("PASS " + name)

        name = "scoped_bidirectional_inboxes"
        after = min(row["sequence"] for row in checker.receipt["messages"]) - 1
        for recipient in ("muse", "grok"):
            other = "grok" if recipient == "muse" else "muse"
            rows = checker.inbox(recipient, after, "&recipient=" + other)
            expected = next(row for row in checker.receipt["messages"] if row["recipient"] == recipient)
            assert any(row["id"] == expected["id"] for row in rows)
            assert not any(row["id"] == prefix + "-" + recipient for row in rows)
        print("PASS " + name)

        name = "owner_login_csrf_rejected"
        status, _, login_html = checker.request("GET", "/login", browser=True)
        assert status == 200
        token = csrf_token(login_html)
        assert checker.request("POST", "/login", browser=True, origin=checker.origin,
                               fields={"csrf": "invalid", "password": os.environ["OWNER_PASSWORD"]})[0] == 403
        print("PASS " + name)

        name = "owner_login_secure_cookie"
        status, headers, _ = checker.request("POST", "/login", browser=True, origin=checker.origin,
                                            fields={"csrf": token, "password": os.environ["OWNER_PASSWORD"]})
        assert status == 303 and headers["Location"] == "/"
        cookies = SimpleCookie()
        for value in headers.get_all("Set-Cookie", []):
            cookies.load(value)
        session = cookies["bridge_session"]
        assert session["secure"] and session["httponly"] and session["samesite"].lower() == "strict"
        status, headers, dashboard = checker.request("GET", "/", browser=True)
        assert status == 200 and headers.get("Cache-Control") == "no-store"
        assert checker.request("GET", "/api/messages", browser=True)[0] == 401
        print("PASS " + name)

        token = csrf_token(dashboard)
        marker = '<script data-bridge-test="' + prefix + '">synthetic & print-only</script>'
        fields = {"csrf": token, "id": prefix + "-owner", "recipient": "grok", "text": marker}
        name = "owner_message_csrf_rejected"
        assert checker.request("POST", "/owner/messages", browser=True, origin=checker.origin,
                               fields={**fields, "csrf": "invalid"})[0] == 403
        assert checker.request("POST", "/owner/messages", browser=True, origin="https://invalid.example",
                               fields=fields)[0] == 403
        print("PASS " + name)

        name = "owner_send_and_html_escape"
        assert checker.request("POST", "/owner/messages", browser=True, origin=checker.origin, fields=fields)[0] == 303
        rows = checker.inbox("grok", after)
        row = next(row for row in rows if row["id"] == fields["id"])
        assert row["sender"] == "owner" and row["text"] == marker
        checker.save_message(row)
        status, _, dashboard = checker.request("GET", "/", browser=True)
        assert status == 200 and marker not in dashboard and html.escape(marker) in dashboard
        assert len(checker.receipt["messages"]) == 3
        print("PASS " + name)
        return 0
    except KeyboardInterrupt:
        print("FAIL interrupted", file=sys.stderr)
        return 130
    except Exception:
        # Do not expose credentials, response data, request bodies or tracebacks.
        print("FAIL " + name, file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, help="Nonsecret receipt path; must not exist for a new run")
    parser.add_argument("--verify-restart", action="store_true", help="Read-only: verify the three saved message IDs/sequences")
    raise SystemExit(run(parser.parse_args()))
