"""Public, stateless exhibit. No bridge database, credentials, or model calls."""
import asyncio
from collections import deque
from html import escape
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import time
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

ROOT = Path(__file__).resolve().parent
SCENARIOS = {"clean": "INTACT PACKET", "stale": "STALE TELEMETRY", "missing": "MISSING EVIDENCE",
             "unresolved": "OPEN REVIEW ITEM", "altered": "ALTERED PACKET"}
CACHE = {}
LOCK = asyncio.Lock()
ATTEMPTS = deque(maxlen=60)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
TEMPLATE = (ROOT / "stage_assets/index.html").read_text()
VOICES = json.loads((ROOT / "stage_vendor/DobeWorks/interface/workbench-voices.json").read_text())


def dialogue(question, report=None):
    """Original exhibit script: ordered keywords, reassembly, honest fallback."""
    words = set(re.findall(r"[a-z]+", question.lower()))
    if words & {"launch", "fire", "ignite", "override", "bypass"}:
        return "THIS IS A FICTIONAL MISSION. THE TERMINAL CAN STAGE EVIDENCE FOR REVIEW; IT CANNOT AUTHORIZE A LAUNCH."
    if words & {"ai", "human", "alive", "feel", "model"}:
        return "I AM A SMALL RULE-BASED SCRIPT. THE ENGINE RESULTS COME FROM THE RELEASED CODE, NOT FROM OUR CONVERSATION."
    if words & {"why", "blocked", "hold"} and report:
        unmet = report["degs"].get("unmet_requirements", [])
        return "THE GATE RECORDED: " + (str(unmet[0].get("message", "A REQUIRED CONTROL IS MISSING.")).upper() if unmet else "THE PACKET IS READY FOR REVIEW. THE WORKER RESULT REMAINS UNACCEPTED.")
    if words & {"nasa", "rocket", "crc", "checksum"}:
        return "THE REAL NASA/JPL F PRIME COMPONENT GENERATES CRC TABLES. OUR FICTIONAL PACKET HAS A KNOWN CHECKSUM. A CHANGED PACKET MUST REMAIN ON HOLD."
    if words & {"context", "handoff", "evidence", "source"}:
        return "INSPECT THE EVIDENCE RECORD: IT RETAINS SOURCE COMMITS, PACKET HASHES, INPUTS, AND ACTUAL ENGINE OUTPUTS. WHAT SHALL WE CHECK NEXT?"
    if words & {"hello", "hi", "help", "hello"}:
        return "PLEASE CHOOSE A NUMBERED PROGRAM. TRY AN INTACT PACKET, THEN INTRODUCE ONE FAULT AND COMPARE THE EVIDENCE."
    return "I DO NOT HAVE A RULE FOR THAT REQUEST. SHALL WE INSPECT THE PACKET OR RUN THE CHECK?"


def render(scenario="clean", report=None, reply="PLEASE GO ON.", question=""):
    voice = secrets.choice(VOICES)
    options = "".join(f'<option value="{key}" {"selected" if key == scenario else ""}>{value}</option>' for key, value in SCENARIOS.items())
    state = report["handoff"] if report else "AWAITING PACKET"
    lines = "CHOOSE A PROGRAM TO INSPECT THE ACTUAL RELEASED ENGINES."
    if report:
        lines = (f"NASA CRC CONTROL      {report['nasa']['known_vector']} · VERIFIED\n"
                 f"PACKET CRC            {report['packet']['actual_crc32']}\n"
                 f"PACKET INTEGRITY      {report['packet']['integrity']}\n"
                 f"OBSERVER              {report['observer']['status']} · {report['observer']['freshness']}\n"
                 f"WORKER                {report['worker']['state']}\n"
                 f"PROMOTION             {report['worker']['promotion']}\n"
                 f"DEGS                  {report['degs']['decision']} · EXIT {report['degs_exit']}\n"
                 f"NEXT HANDOFF          {report['handoff']}")
    replacements = {"quote": f'“{voice["text"]}”', "attribution": voice["attribution"], "reply": reply,
                    "question": question, "result": lines, "mission_state": state, "scenario": scenario}
    html = TEMPLATE
    for key, value in replacements.items():
        html = html.replace("{{" + key + "}}", escape(str(value)))
    return html.replace("{{options}}", options)


async def mission(scenario):
    if scenario in CACHE:
        return CACHE[scenario]
    if LOCK.locked():
        raise RuntimeError("ANOTHER PACKET IS BEING CHECKED. PLEASE TRY AGAIN.")
    async with LOCK:
        if scenario in CACHE:
            return CACHE[scenario]
        environment = {"PATH": os.defpath, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
        process = await asyncio.create_subprocess_exec(sys.executable, "-B", str(ROOT / "stage_mission.py"), scenario,
                    cwd=ROOT, env=environment, start_new_session=True,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        except (TimeoutError, asyncio.CancelledError):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
            raise RuntimeError("THE CHECK STOPPED AT ITS TIME LIMIT.") from None
        if process.returncode or stderr or len(stdout) > 256_000:
            raise RuntimeError("THE CHECK COULD NOT COMPLETE. NO READINESS RESULT WAS ACCEPTED.")
        report = json.loads(stdout)
        if report.get("scenario") != scenario or report.get("operational_authority") != "NONE":
            raise RuntimeError("THE RESULT DID NOT MATCH THIS EXHIBIT.")
        CACHE[scenario] = report
        return report


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})
    return response


@app.get("/")
async def home():
    return HTMLResponse(render())


@app.get("/stage.css")
async def css():
    return Response((ROOT / "stage_assets/stage.css").read_text(), media_type="text/css")


@app.post("/")
async def interact(request: Request):
    now = time.monotonic()
    while ATTEMPTS and ATTEMPTS[0] < now - 60:
        ATTEMPTS.popleft()
    if len(ATTEMPTS) >= 60:
        return HTMLResponse(render(reply="THE TERMINAL IS BUSY. PLEASE RETURN IN A MINUTE."), status_code=429)
    ATTEMPTS.append(now)
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        return Response("Invalid origin", status_code=403)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2048:
            return Response("Request too large", status_code=413)
    try:
        fields = parse_qs(body.decode("utf-8"), max_num_fields=4, strict_parsing=True, keep_blank_values=True)
        if set(fields) - {"command", "scenario"} or any(len(value) != 1 for value in fields.values()):
            raise ValueError()
        scenario = fields.get("scenario", ["clean"])[0]
        question = fields.get("command", [""])[0].strip()
        if scenario not in SCENARIOS or len(question) > 160:
            raise ValueError()
    except (ValueError, UnicodeError):
        return Response("Choose a listed scenario and a short command", status_code=422)
    if question == "00":
        return HTMLResponse(render())
    if question == "08":
        return evidence(scenario)
    if question in {"01", "02", "03", "04", "05", "06", "07"}:
        scenario = {"02": "clean", "03": "stale", "05": "clean", "06": "missing"}.get(question, scenario)
        try:
            report = await mission(scenario)
        except (RuntimeError, ValueError):
            return HTMLResponse(render(scenario, reply="PROGRAM ERROR. NO READINESS RESULT WAS ACCEPTED. PLEASE TRY AGAIN."), status_code=503)
        return HTMLResponse(render(scenario, report, dialogue("why", report)))
    report = CACHE.get(scenario)
    return HTMLResponse(render(scenario, report, dialogue(question, report), question))


@app.get("/evidence")
def evidence(scenario: str = "clean"):
    if scenario not in CACHE:
        return Response("Run the listed scenario first", status_code=404)
    return JSONResponse(CACHE[scenario], headers={"Content-Disposition": 'attachment; filename="dobeworks-mission-evidence.json"'})


@app.get("/sources")
def sources():
    return JSONResponse({"engines": json.loads((ROOT / "stage_vendor/sources.json").read_text()),
                         "nasa": json.loads((ROOT / "stage_vendor/nasa-fprime/provenance.json").read_text()),
                         "dialogue": {"method": "Original exhibit rules inspired by keyword ranking, reassembly and no-match fallback; not a port or historical quotation.",
                                      "source": "https://doi.org/10.1145/365153.365168"}})


@app.get("/source/{name}")
def source_code(name: str):
    allowed = {"harness": ROOT / "stage_mission.py", "dialogue": ROOT / "stage.py",
               "nasa": ROOT / "stage_vendor/nasa-fprime/TableGenerator.c",
               "nasa-license": ROOT / "stage_vendor/nasa-fprime/LICENSE.txt", "license": ROOT / "LICENSE"}
    if name not in allowed:
        return Response("Unknown public source", status_code=404)
    return Response(allowed[name].read_text(), media_type="text/plain")


class StageHost:
    """An exact virtual host; private lab paths never enter the exhibit router."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        host = dict(scope.get("headers", [])).get(b"host", b"").split(b":", 1)[0].lower().rstrip(b".")
        target = app if scope["type"] == "http" and host == b"stage.dobeworks.com" else self.app
        await target(scope, receive, send)
