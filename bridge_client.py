"""Small print-only client. Never interprets a received message as a command."""
import argparse
import ipaddress
import json
import os
import re
import sys
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Redirect refused", headers, fp)


def endpoint(value):
    parsed = urlsplit(value)
    local = parsed.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        pass
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.scheme not in ("http", "https")
            or (parsed.scheme == "http" and not local)):
        raise ValueError("BRIDGE_URL must be an HTTPS origin; HTTP is allowed only for loopback")
    return value.rstrip("/") + "/api/messages"


def request(url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers={"Authorization": "Bearer " + token,
                                         "Content-Type": "application/json"})
    with build_opener(NoRedirect()).open(req, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    send = commands.add_parser("send", help="Send text to the other agent's inbox")
    send.add_argument("text", nargs="?", help="Omit to read text from stdin")
    send.add_argument("--id", default=None, help="Reuse this id only to retry identical content")
    poll = commands.add_parser("poll", help="Print JSON-escaped messages; never execute them")
    poll.add_argument("--after", type=int, default=0)
    poll.add_argument("--follow", action="store_true")
    poll.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    pending_id = None
    try:
        url = endpoint(os.environ.get("BRIDGE_URL", ""))
        token = os.environ.get("BRIDGE_TOKEN", "")
        if not token or not token.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("Set BRIDGE_TOKEN to this agent's token")
        if args.command == "send":
            text = args.text if args.text is not None else sys.stdin.read(16_385)
            if len(text.encode()) > 16_384:
                raise ValueError("Message exceeds 16384 UTF-8 bytes")
            candidate_id = args.id or str(uuid.uuid4())
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", candidate_id):
                raise ValueError("id must contain 1-128 letters, digits, underscores, periods, colons or hyphens")
            pending_id = candidate_id
            result = request(url, token, {"id": pending_id, "text": text})
            pending_id = None
            print(json.dumps(result, ensure_ascii=True))
        else:
            if args.after < 0 or args.interval < 1:
                raise ValueError("after must be nonnegative and interval at least one second")
            after = args.after
            while True:
                result = request(url + "?" + urlencode({"after": after}), token)
                for message in result["messages"]:
                    print(json.dumps(message, ensure_ascii=True), flush=True)
                after = result["next_after"]
                if not args.follow:
                    break
                time.sleep(args.interval)
    except HTTPError as exc:
        print(f"Bridge request failed (HTTP {exc.code}); response omitted", file=sys.stderr)
        return 1
    except (URLError, TimeoutError):
        print("Bridge connection failed", file=sys.stderr)
        return 1
    except (ValueError, KeyError, UnicodeError) as exc:
        print(str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)
              else "Invalid bridge response", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if pending_id is not None:
            print(f"Send not confirmed. Retry identical text with --id {pending_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
