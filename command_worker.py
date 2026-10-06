"""Opt-in DobeWorks shell worker. Run only on the intended test computer/account."""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from agent_client import credentials, request

OUTPUT_LIMIT = 65_536


def interrupted(signum, frame):
    # Normal supervisor shutdown and terminal hangup must unwind execute() cleanup.
    raise KeyboardInterrupt


def stop(process):
    """End the whole job process group, including background children."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def execute(job, workdir, heartbeat, secret_to_redact=""):
    command, timeout = job["command"], job["timeout_seconds"]
    if (not isinstance(command, str) or not command.strip() or len(command.encode()) > 8192
            or type(timeout) is not int or not 1 <= timeout <= 300):
        raise ValueError("Invalid command job")
    # Start from an allowlist: no bridge/owner/API secrets are inherited by the child.
    allowed = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP", "USER", "LOGNAME")
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    process = subprocess.Popen(["/bin/sh", "-c", command], cwd=workdir, env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    captured = bytearray()
    truncated = False
    state = None
    started = time.monotonic()
    next_heartbeat = started  # Confirm owner stop state immediately after starting.
    selector = None
    try:
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        os.set_blocking(process.stdout.fileno(), False)
        while True:
            now = time.monotonic()
            if now - started >= timeout:
                state = "timed_out"
                break
            if now >= next_heartbeat:
                try:
                    should_cancel = heartbeat()
                except Exception:
                    # Losing authorization/lease/contact stops local execution, never retries the command.
                    state = "cancelled"
                    break
                if should_cancel:
                    state = "cancelled"
                    break
                next_heartbeat = time.monotonic() + 5
            for key, _ in selector.select(timeout=0.1):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    room = OUTPUT_LIMIT - len(captured)
                    captured.extend(chunk[:room])
                    truncated |= len(chunk) > room
            if process.poll() is not None and not selector.get_map():
                state = "succeeded" if process.returncode == 0 else "failed"
                break
    finally:
        # Also remove descendants left running after a shell exits successfully.
        stop(process)
        if selector is not None:
            selector.close()
        process.stdout.close()
    output = captured.decode("utf-8", errors="replace")
    if secret_to_redact:
        output = output.replace(secret_to_redact, "[credential redacted]")
    encoded = output.encode()
    if len(encoded) > OUTPUT_LIMIT:
        output = encoded[:OUTPUT_LIMIT].decode("utf-8", errors="ignore")
        truncated = True
    return {"status": state, "exit_code": process.returncode, "output": output, "truncated": truncated}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-command-execution", action="store_true", required=True,
                        help="Explicitly allow assigned jobs to run shell commands with this account's privileges")
    parser.add_argument("--worker-id", required=True, help="Expected authenticated ID, normally grok-phone")
    parser.add_argument("--workdir", type=Path, required=True, help="Existing job directory; not a filesystem sandbox")
    parser.add_argument("--max-jobs", type=int, default=10)
    parser.add_argument("--max-idle-polls", type=int, default=60)
    args = parser.parse_args(argv)
    previous_handlers = {}
    try:
        for signum in (signal.SIGTERM, signal.SIGHUP):
            previous_handlers[signum] = signal.signal(signum, interrupted)
        if os.name != "posix" or not args.workdir.is_dir():
            raise ValueError("Requires a POSIX test computer and existing workdir")
        if not 1 <= args.max_jobs <= 100 or not 1 <= args.max_idle_polls <= 360:
            raise ValueError("Invalid run budget")
        base, token = credentials()
        who = request(base, token, "/api/agents/me")
        if who["id"] != args.worker_id:
            raise ValueError("Authenticated identity does not match worker-id")
        count, idle = 0, 0
        print(json.dumps({"worker_id": who["id"], "state": "ready", "max_jobs": args.max_jobs}), flush=True)
        while count < args.max_jobs and idle < args.max_idle_polls:
            job = request(base, token, "/api/worker/claim", {})["job"]
            if job is None:
                idle += 1
                time.sleep(5)
                continue
            if job["worker_id"] != args.worker_id:
                raise ValueError("Claim returned wrong worker")
            job_path = f"/api/jobs/{int(job['sequence'])}"
            lease = job["lease_token"]
            def heartbeat():
                return request(base, token, job_path + "/heartbeat", {"lease_token": lease},
                               timeout=3)["cancel_requested"]
            # A preflight stop check avoids starting a job disabled immediately after claim.
            if heartbeat():
                result = {"status": "cancelled", "exit_code": None, "output": "", "truncated": False}
            else:
                result = execute(job, args.workdir.resolve(), heartbeat, token)
            request(base, token, job_path + "/result", {"lease_token": lease, **result})
            print(json.dumps({"sequence": job["sequence"], "state": result["status"]}), flush=True)
            count += 1
            idle = 0
        print(json.dumps({"state": "stopped", "completed_jobs": count}), flush=True)
        return 0
    except KeyboardInterrupt:
        print("Worker stopped", file=sys.stderr)
        return 130
    except Exception:
        # Do not print commands, credentials, responses or exception strings.
        print("Worker stopped: connection, authorization, configuration or result error. Check job status before retrying.",
              file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
