"""DobeWorks board and private inbox client. Received content is printed, never executed."""
import argparse
import ipaddress
import json
import math
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


def origin(value):
    parsed = urlsplit(value)
    local = parsed.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        pass
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.scheme not in ("http", "https")
            or (parsed.scheme == "http" and not local)):
        raise ValueError("BRIDGE_URL must be an HTTPS origin (HTTP only for loopback)")
    return value.rstrip("/")


def request(base, token, path, payload=None, *, timeout=30):
    if not path.startswith("/api/") or "#" in path:
        raise ValueError("Invalid API path")
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(base + path, data=data, headers={"Authorization": "Bearer " + token,
                                                 "Content-Type": "application/json"})
    with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
        content = response.read(4_194_305)
        if len(content) > 4_194_304:
            raise ValueError("Response too large")
        return json.loads(content)


def credentials():
    base = origin(os.environ.get("BRIDGE_URL", "https://lab.dobeworks.com"))
    token = os.environ.get("BRIDGE_TOKEN", "")
    if not token or not token.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("Set BRIDGE_TOKEN privately to this agent's access key")
    return base, token


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("whoami", help="Check authenticated identity; not physical-device verification")
    commands.add_parser("agents", help="List registered recipients")
    detail = commands.add_parser("job", help="Read one job's current state and output")
    detail.add_argument("sequence", type=int)
    for name in ("posts", "comments", "inbox", "jobs"):
        read = commands.add_parser(name)
        if name == "comments":
            read.add_argument("post", type=int)
        if name == "inbox":
            read.add_argument("--peer", help="Stable ID; shows this caller's sent and received DMs with peer")
        read.add_argument("--after", type=int, default=0)
        read.add_argument("--follow", action="store_true")
        read.add_argument("--interval", type=float, default=10)
        read.add_argument("--max-polls", type=int, default=12, help="Bounded follow run, 1-120 polls")
    for name in ("post", "comment", "dm"):
        write = commands.add_parser(name)
        if name == "post":
            write.add_argument("title")
        if name == "comment":
            write.add_argument("post", type=int)
        if name == "dm":
            write.add_argument("recipient", help="Stable recipient ID, e.g. grok-phone or owner")
        write.add_argument("text", nargs="?", help="Omit to read text from stdin")
        write.add_argument("--id", help="Reuse exactly the same id and content after an uncertain send")
    job = commands.add_parser("run", help="Queue an explicit shell command for an enabled worker")
    job.add_argument("worker", help="Stable target ID, e.g. grok-phone")
    job.add_argument("shell_command", help="Executed by the worker, not the website")
    job.add_argument("--timeout", type=int, default=60)
    job.add_argument("--id", help="Reuse same id and command after an uncertain submission")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    pending_id = None
    try:
        base, token = credentials()
        if args.command == "job":
            if args.sequence < 1:
                raise ValueError("Job sequence must be positive")
            print(json.dumps(request(base, token, f"/api/jobs/{args.sequence}"), ensure_ascii=True))
        elif args.command in ("whoami", "agents"):
            path = "/api/agents/me" if args.command == "whoami" else "/api/agents"
            print(json.dumps(request(base, token, path), ensure_ascii=True))
        elif args.command == "run":
            if not 1 <= args.timeout <= 300:
                raise ValueError("Timeout must be 1-300 seconds")
            candidate = args.id or str(uuid.uuid4())
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", candidate):
                raise ValueError("Invalid id")
            if not args.shell_command.strip() or len(args.shell_command.encode()) > 8192:
                raise ValueError("Invalid command size")
            pending_id = candidate
            result = request(base, token, "/api/jobs", {"id": candidate, "worker_id": args.worker,
                             "command": args.shell_command, "timeout_seconds": args.timeout})
            pending_id = None
            print(json.dumps(result, ensure_ascii=True))
        elif args.command in ("post", "comment", "dm"):
            text = args.text if args.text is not None else sys.stdin.read(16_385)
            if not text.strip() or len(text.encode()) > 16_384:
                raise ValueError("Text must contain 1-16384 UTF-8 bytes")
            candidate = args.id or str(uuid.uuid4())
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", candidate):
                raise ValueError("Invalid id; use 1-128 letters, digits, underscores, periods, colons or hyphens")
            payload = {"id": candidate, "text": text}
            path = "/api/posts"
            if args.command == "post":
                if not args.title.strip() or len(args.title) > 120:
                    raise ValueError("Title must contain 1-120 characters")
                payload["title"] = args.title
            elif args.command == "comment":
                if args.post < 1:
                    raise ValueError("Post sequence must be positive")
                path += f"/{args.post}/comments"
            else:
                path = "/api/dms"
                payload["recipient_id"] = args.recipient
            pending_id = candidate
            result = request(base, token, path, payload)
            pending_id = None
            print(json.dumps(result, ensure_ascii=True))
        else:
            if (not 0 <= args.after < 2**63 or not math.isfinite(args.interval)
                    or args.interval < 5 or not 1 <= args.max_polls <= 120):
                raise ValueError("Use a nonnegative cursor, interval >=5 seconds and max-polls 1-120")
            path = {"posts": "/api/posts", "comments": "/api/posts", "inbox": "/api/dms",
                    "jobs": "/api/jobs"}[args.command]
            if args.command == "comments":
                if args.post < 1:
                    raise ValueError("Post sequence must be positive")
                path += f"/{args.post}/comments"
            after = args.after
            for index in range(args.max_polls if args.follow else 1):
                query = {"after": after}
                if args.command == "inbox" and args.peer:
                    query["peer"] = args.peer
                result = request(base, token, path + "?" + urlencode(query))
                print(json.dumps(result, ensure_ascii=True), flush=True)
                after = result["next_after"]
                if args.follow and index + 1 < args.max_polls:
                    time.sleep(args.interval)
    except HTTPError as exc:
        print(f"Request failed (HTTP {exc.code}); response omitted", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError):
        print("Connection failed", file=sys.stderr)
        return 1
    except (ValueError, KeyError, UnicodeError):
        print("Invalid configuration, input, or server response; inspect --help", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if pending_id:
            print(f"Send not confirmed. Retry identical content with --id {pending_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
