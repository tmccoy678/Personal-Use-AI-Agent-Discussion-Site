"""Public fictional mission. Bounded visitor progress; no bridge data or model calls."""
import asyncio
from collections import deque, OrderedDict
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

from stage_mission import digest, encode

ROOT = Path(__file__).resolve().parent
SCENARIOS = {"clean": "INTACT PACKET", "stale": "STALE TELEMETRY", "missing": "MISSING EVIDENCE",
             "unresolved": "OPEN REVIEW ITEM", "altered": "ALTERED SOURCE"}
PROGRAMS = {"01": ("CONFIGURATION ENGINEER", "ESTABLISH PACKAGE BASELINE"),
            "02": ("TELEMETRY ENGINEER", "CHECK OBSERVER FRESHNESS"),
            "03": ("PACKAGE ENGINEER", "STAGE AND CHECK THE PACKAGE"),
            "04": ("VERIFICATION ENGINEER", "VERIFY BOTH FROZEN CORES"),
            "05": ("INDEPENDENT REVIEWER", "REVIEW AND ACCEPT THE PACKAGE"),
            "06": ("MISSION TEAM", "POLL LAUNCH READINESS"),
            "07": ("LAUNCH DIRECTOR", "RUN THE ROCKET SIMULATION"),
            "08": ("EVIDENCE", "OPEN THE HANDOFF RECORD")}
POLL = {"vehicle": "VEHICLE TEAM", "weather": "WEATHER TEAM", "range": "RANGE TEAM", "director": "LAUNCH DIRECTOR"}
CACHE = {}
SESSIONS = OrderedDict()
LOCK = asyncio.Lock()
ATTEMPTS = deque(maxlen=60)
COOKIE = "stage_mission"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
TEMPLATE = (ROOT / "stage_assets/index.html").read_text()
VOICES = json.loads((ROOT / "stage_vendor/DobeWorks/interface/workbench-voices.json").read_text())


def new_state():
    return {"csrf": secrets.token_urlsafe(24), "scenario": "clean", "completed": [], "poll": {}, "events": [],
            "report": None, "cores": None, "launched": False, "busy": False, "seen": time.monotonic()}


def session(request):
    now = time.monotonic()
    for key in list(SESSIONS):
        if now - SESSIONS[key]["seen"] > 7200:
            del SESSIONS[key]
    key = request.cookies.get(COOKIE)
    if key not in SESSIONS:
        key = secrets.token_urlsafe(32)
        while len(SESSIONS) >= 256:
            SESSIONS.popitem(last=False)
        SESSIONS[key] = new_state()
    state = SESSIONS[key]
    state["seen"] = now
    SESSIONS.move_to_end(key)
    return key, state


def record(state, role, action, outcome):
    previous = state["events"][-1]["sha256"] if state["events"] else "0" * 64
    event = {"sequence": len(state["events"]) + 1, "role": role, "action": action, "outcome": outcome,
             "scenario": state["scenario"], "simulation": True, "previous_sha256": previous,
             "engine_run_sha256": digest(encode(state["report"])) if state["report"] else None,
             "core_run_sha256": digest(encode(state["cores"])) if state["cores"] else None,
             "package_sha256": state["report"]["package_sha256"] if state["report"] else None}
    event["sha256"] = digest(encode(event))
    state["events"].append(event)


def evidence_record(state):
    return {"simulation": True, "operational_authority": "NONE", "component": "TM-CRC-001",
            "completed_handoffs": state["completed"], "fictional_role_poll": state["poll"],
            "simulated_flight_completed": state["launched"], "handoff_record": state["events"],
            "fixed_engine_run": state["report"], "core_verification": state["cores"]}


def dialogue(question, report=None):
    """Original exhibit script: ordered keywords and an honest no-match fallback."""
    words = set(re.findall(r"[a-z]+", question.lower()))
    if words & {"launch", "fire", "ignite", "override", "bypass"}:
        return "USE 06 TO REVIEW THE TEAM POLL, THEN 07 FOR THE FICTIONAL FLIGHT. DIALOGUE CANNOT CHANGE A GATE OR AUTHORIZE A LAUNCH."
    if words & {"ai", "human", "alive", "feel", "model"}:
        return "I AM A SMALL RULE-BASED SCRIPT. YOU ARE PLAYING SEVERAL FICTIONAL TEAM ROLES. THE ENGINE RESULTS COME FROM THE FROZEN CODE."
    if words & {"why", "blocked", "hold"} and report:
        unmet = report["degs"].get("unmet_requirements", [])
        return "THE GATE RECORDED: " + (str(unmet[0].get("message", "A REQUIRED CONTROL IS MISSING.")).upper() if unmet else "PASS FOR THE SUBMITTED RECORD. COMPLETE THE REMAINING HANDOFFS AND TEAM POLL.")
    if words & {"nasa", "rocket", "crc", "checksum", "packet"}:
        return "OUR PACKAGE CARRIES THE REAL NASA/JPL F PRIME CRC32 SOURCES, THEIR IDENTITIES, REQUIREMENT, AND CHECK EVIDENCE. IT IS ONE COMPONENT OF THIS FICTIONAL MISSION."
    if words & {"context", "handoff", "evidence", "source"}:
        return "08 OPENS THE RECORDED HANDOFFS, SOURCE COMMITS, PACKAGE HASHES, INPUTS, AND ACTUAL OUTPUTS. A CHANGED PACKAGE REQUIRES NEW REVIEWS."
    if words & {"hello", "hi", "help"}:
        return "BEGIN WITH 01. FOLLOW THE PACKAGE THROUGH 05, THEN REVIEW THE MISSION TEAM IN 06. SELECT A FAULT TO SEE WHICH HANDOFF HOLDS."
    return "I DO NOT HAVE A RULE FOR THAT REQUEST. SHALL WE INSPECT THE PACKAGE OR CONTINUE A NUMBERED PROGRAM?"


def render(state, title="MISSION TERMINAL", lines=None, reply="PLEASE GO ON.", question="", actions=(), details=None):
    voice = secrets.choice(VOICES)
    scenario = state["scenario"]
    if lines is None:
        lines = ("PACKAGE  TM-CRC-001\nNASA/JPL F PRIME CRC32 SOURCE HANDOFF\n\n"
                 "Preserve the source, requirement, identities, and evidence.\n"
                 "Begin with 01. Each role receives the same package.\n"
                 "Other mission teams still have their own decisions to make.")
    options = "".join(f'<option value="{key}" {"selected" if key == scenario else ""}>{value}</option>' for key, value in SCENARIOS.items())
    programs = "".join(f'<button name="command" value="{key}">{key}  {label}</button>' for key, (_, label) in PROGRAMS.items())
    controls = "".join(f'<button class="enter" name="command" value="{key}">{escape(label)}</button>' for key, label in actions)
    raw = f'<details class="raw"><summary>FULL RECORDED EVIDENCE</summary><pre>{escape(json.dumps(details, indent=2, sort_keys=True))}</pre></details>' if details is not None else ""
    progress = "\n".join(f'{key}  {"RECEIVED" if key in state["completed"] else "WAITING "}  {role}' for key, role in
                         zip(("01", "02", "03", "04", "05"), ("CONFIGURATION", "TELEMETRY", "PACKAGE", "VERIFICATION", "REVIEW")))
    mission_state = "SIMULATED FLIGHT COMPLETE" if state["launched"] else ("PACKAGE ACCEPTED · TEAM POLL OPEN" if "05" in state["completed"] else "PACKAGE HANDOFF IN PROGRESS" if state["completed"] else "AWAITING PACKAGE")
    replacements = {"quote": f'“{voice["text"]}”', "attribution": voice["attribution"], "reply": reply,
        "question": question, "result": lines, "title": " ".join(title), "mission_state": mission_state,
        "scenario": scenario, "csrf": state["csrf"], "progress": progress,
        "flight_class": "flight" if state["launched"] else "", "flight_label": "THE CLIMB" if state["launched"] else "THE PAD"}
    html = TEMPLATE
    for key, value in replacements.items():
        html = html.replace("{{" + key + "}}", escape(str(value)))
    return html.replace("{{options}}", options).replace("{{programs}}", programs).replace("{{actions}}", controls).replace("{{details}}", raw)


def page(request, key, state, **kwargs):
    response = HTMLResponse(render(state, **kwargs))
    response.set_cookie(COOKIE, key, max_age=7200, secure=request.url.scheme == "https", httponly=True, samesite="strict")
    return response


async def mission(scenario):
    if scenario in CACHE:
        return CACHE[scenario]
    if LOCK.locked():
        raise RuntimeError("ANOTHER CHECK IS RUNNING. PLEASE TRY AGAIN.")
    async with LOCK:
        environment = {"PATH": os.defpath, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
        argument = "--read-core-verification" if scenario == "cores" else scenario
        process = await asyncio.create_subprocess_exec(sys.executable, "-B", str(ROOT / "stage_mission.py"), argument,
                    cwd=ROOT, env=environment, start_new_session=True,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60 if scenario == "cores" else 15)
        except (TimeoutError, asyncio.CancelledError):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
            raise RuntimeError("THE CHECK STOPPED AT ITS TIME LIMIT.") from None
        if process.returncode or stderr or len(stdout) > 256_000:
            raise RuntimeError("THE CHECK COULD NOT COMPLETE. NO RESULT WAS ACCEPTED.")
        report = json.loads(stdout)
        if report.get("operational_authority") != "NONE" or (scenario != "cores" and report.get("scenario") != scenario):
            raise RuntimeError("THE RESULT DID NOT MATCH THIS EXHIBIT.")
        CACHE[scenario] = report
        return report


async def program(state, command):
    if command == "08":
        lines = "NO HANDOFFS HAVE BEEN RECORDED. BEGIN WITH 01."
        if state["events"]:
            lines = "RECORDED TEAM HANDOFFS\n\n" + "\n".join(f'{e["sequence"]:02}  {e["role"]}\n    {e["action"]} · {e["outcome"]}\n    {e["sha256"][:24]}' for e in state["events"])
        return {"title": "RUN EVIDENCE", "lines": lines, "details": evidence_record(state), "reply": "RECORDED EVIDENCE. NO CHECK WAS RERUN."}
    if command == "06" or command in POLL:
        reply = "SELECT A TEAM TO INSPECT ITS FICTIONAL READINESS RECORD."
        if command in POLL:
            if command == "director" and ("05" not in state["completed"] or not all(state["poll"].get(k) == "GO" for k in ("vehicle", "weather", "range"))):
                reply = "DIRECTOR HOLD. THE PACKAGE AND ALL THREE OTHER TEAM REPORTS ARE REQUIRED."
            elif state["poll"].get(command) != "GO":
                state["poll"][command] = "GO"
                record(state, POLL[command], "FICTIONAL READINESS POLL", "GO")
                reply = {"vehicle": "VEHICLE TEAM: THE FIXED PREFLIGHT CHECKLIST IS COMPLETE. GO.",
                         "weather": "WEATHER TEAM: HOLD AT FIXTURE T+00, WIND 22. ADVANCE TO T+05, WIND 9, LIMIT 15. GO.",
                         "range": "RANGE TEAM: THE FICTIONAL EXCLUSION AREA IS CLEAR. GO.",
                         "director": "DIRECTOR: PACKAGE ACCEPTANCE AND ALL TEAM REPORTS RECEIVED. GO FOR SIMULATION."}[command]
        lines = "FICTIONAL LAUNCH READINESS POLL\n\n" + f'CRC32 PACKAGE         {"ACCEPTED" if "05" in state["completed"] else "HOLD"}\n'
        lines += "\n".join(f'{label:<22}{state["poll"].get(key, "HOLD — AWAITING REVIEW")}' for key, label in POLL.items())
        lines += "\n\nYOU ARE PLAYING EACH ROLE IN THIS ILLUSTRATIVE MISSION."
        return {"title": "MISSION TEAM", "lines": lines, "reply": reply,
                "actions": [(key, "INSPECT " + label) for key, label in POLL.items() if state["poll"].get(key) != "GO"]}
    if command == "07":
        if state["completed"] != ["01", "02", "03", "04", "05"] or not all(state["poll"].get(k) == "GO" for k in POLL):
            return {"title": "COUNTDOWN HOLD", "lines": "PACKAGE ACCEPTANCE AND THE COMPLETE TEAM POLL ARE REQUIRED.", "reply": "RETURN TO THE FIRST WAITING HANDOFF OR OPEN 06."}
        if not state["launched"]:
            record(state, "LAUNCH DIRECTOR", "FICTIONAL FLIGHT", "COMPLETE")
            state["launched"] = True
        return {"title": "SIMULATED FLIGHT", "lines": "T-03  PACKAGE IDENTITY RETAINED\nT-02  REVIEW RECORD RETAINED\nT-01  TEAM POLL COMPLETE\nT+00  FICTIONAL IGNITION\nT+03  THE ROCKET CLEARS THE PAD\n\nMISSION SIMULATION · COMPLETE",
                "reply": "ONE SMALL PACKAGE MADE IT THROUGH EVERY HANDOFF. OPEN 08 TO FOLLOW ITS RECORD."}
    previous = [key for key in PROGRAMS if key < command and key <= "05"]
    if any(key not in state["completed"] for key in previous):
        missing = next(key for key in previous if key not in state["completed"])
        return {"title": "HANDOFF HOLD", "lines": f'REQUIRED RECEIPT: {missing} · {PROGRAMS[missing][1]}', "reply": "THE RECEIVING ROLE NEEDS THE EARLIER HANDOFF FIRST."}
    report = state["report"] or await mission(state["scenario"])
    state["report"] = report
    role, title = PROGRAMS[command]
    passed = True
    reply = "HANDOFF RECORDED. CONTINUE TO THE NEXT ROLE."
    if command == "01":
        lines = ("TM-CRC-001 · NASA/JPL F PRIME CRC32\n\nREQUIREMENT\n"
                 "Retain exact source and sequence-7 telemetry identities.\nReject changed bytes or missing evidence at handoff.\n\n"
                 f'SOURCE FILES          TableGenerator.c + Crc32.cpp\nPACKAGE SHA256        {report["package_sha256"]}\n'
                 f'BASELINE FILES        {len(report["packet"]["expected_manifest"])}\nNEXT ROLE             TELEMETRY ENGINEER')
    elif command == "02":
        observer = report["observer"]
        passed = observer["status"] == "VALIDATED" and observer["freshness"] == "FRESH"
        lines = f'OBSERVER              {observer["status"]}\nFRESHNESS             {observer["freshness"]}\n\nTELEMETRY HANDOFF · {"PASS" if passed else "HOLD"}'
        if not passed:
            reply = "THE OBSERVER CANNOT SUPPLY FRESH EVIDENCE. RESTORE THE INTACT PACKET TO START A NEW BASELINE."
    elif command == "03":
        passed = report["packet"]["integrity"] == "PASS"
        lines = (f'WORKER                {report["worker"]["state"]}\nPROMOTION             {report["worker"]["promotion"]}\n'
                 f'NASA TABLE CONTROL    {report["nasa"]["generated_values_checked"]} VALUES · VERIFIED\nKNOWN CRC CONTROL     {report["nasa"]["known_vector"]}\n'
                 f'PACKET CRC            {report["packet"]["actual_crc32"]}\nSOURCE / MANIFEST     {report["packet"]["integrity"]}\n\n'
                 f'PACKAGE HANDOFF · {"READY FOR VERIFICATION" if passed else "HOLD"}')
        if not passed:
            reply = "THE MANIFEST OR CHECKSUM DIFFERS. RESTORE THE INTACT PACKET AND REPEAT THE HANDOFFS."
    elif command == "04":
        state["cores"] = await mission("cores")
        passed = state["cores"]["result"] == "PASS"
        lines = "RETAINED RELEASE-PREPARATION TEST RESULTS.\n\n" + "\n".join(f'{name.upper() + " CORE":<22}{"PASS" if item["passed"] else "FAIL"} · {item["tests"]} TESTS' for name, item in state["cores"]["results"].items())
        lines += "\n\nCORE VERIFICATION · " + state["cores"]["result"]
    elif command == "05":
        passed = report["degs"]["decision"] == "PASS" and report["degs_exit"] == 0
        lines = (f'DEGS RECORD CHECK     {report["degs"]["decision"]} · EXIT {report["degs_exit"]}\n'
                 f'PACKAGE IDENTITY      {report["package_sha256"]}\nCORE VERIFICATION     {state["cores"]["result"]}\n'
                 f'REVIEW ITEM           {"CLOSED" if passed else "OPEN"}\n\n'
                 f'PACKAGE REVIEW · {"ACCEPTED FOR SIMULATED INTEGRATION" if passed else "HOLD"}')
        reply = "YOU RECORDED THE FICTIONAL REVIEWER'S ACCEPTANCE. THE ENGINE'S WORKER RESULT REMAINS UNACCEPTED. CONTINUE TO THE OTHER MISSION TEAMS IN 06." if passed else "AN OPEN REVIEW ITEM PREVENTS ACCEPTANCE. RESTORE THE INTACT PACKET AND REPEAT THE REVIEWS."
    if command not in state["completed"]:
        record(state, role, title, "RECEIVED" if passed else "HOLD")
        if passed:
            state["completed"].append(command)
    return {"title": title, "lines": lines, "reply": reply}


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})
    return response


@app.get("/")
async def home(request: Request):
    key, state = session(request)
    return page(request, key, state)


@app.get("/stage.css")
async def css():
    return Response((ROOT / "stage_assets/stage.css").read_text(), media_type="text/css")


@app.post("/")
async def interact(request: Request):
    now = time.monotonic()
    while ATTEMPTS and ATTEMPTS[0] < now - 60:
        ATTEMPTS.popleft()
    if len(ATTEMPTS) >= 60:
        return Response("THE TERMINAL IS BUSY. PLEASE RETURN IN A MINUTE.", status_code=429)
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
        fields = parse_qs(body.decode("utf-8"), max_num_fields=3, strict_parsing=True, keep_blank_values=True)
        if set(fields) != {"command", "scenario", "csrf"} or any(len(value) != 1 for value in fields.values()):
            raise ValueError()
        scenario = fields["scenario"][0]
        question = fields["command"][0].strip()
        if scenario not in SCENARIOS or len(question) > 160:
            raise ValueError()
    except (ValueError, UnicodeError):
        return Response("Choose a listed packet and a short command", status_code=422)
    key, state = session(request)
    if not secrets.compare_digest(fields["csrf"][0], state["csrf"]):
        return page(request, key, state, reply="THIS SESSION EXPIRED. PLEASE RUN THE PROGRAM AGAIN.")
    if state["busy"]:
        return Response("A program is already running in this session", status_code=409)
    if question == "00":
        SESSIONS[key] = state = new_state()
        return page(request, key, state)
    if len(state["events"]) >= 63:
        return page(request, key, state, reply="THIS MISSION RECORD IS FULL. USE 00 FOR A NEW MISSION.")
    state["busy"] = True
    try:
        if scenario != state["scenario"]:
            state.update(scenario=scenario, completed=[], poll={}, report=None, cores=None, launched=False)
            record(state, "CONFIGURATION ENGINEER", "PACKAGE REPLACED — ALL RECEIPTS INVALIDATED", "NEW BASELINE REQUIRED")
        if question in PROGRAMS or question in POLL:
            result = await program(state, question)
        else:
            result = {"reply": dialogue(question, state["report"]), "question": question}
        return page(request, key, state, **result)
    except (RuntimeError, ValueError, KeyError):
        return page(request, key, state, title="PROGRAM ERROR", lines="NO HANDOFF WAS ACCEPTED.", reply="THE CHECK COULD NOT COMPLETE. PLEASE TRY THE PROGRAM AGAIN.")
    finally:
        state["busy"] = False


@app.get("/evidence")
async def evidence(request: Request):
    key, state = session(request)
    return page(request, key, state, **await program(state, "08"))


@app.get("/api/evidence")
async def evidence_json(request: Request):
    _, state = session(request)
    return JSONResponse(evidence_record(state))


@app.get("/sources")
def sources(request: Request):
    key, state = session(request)
    records = {"engines": json.loads((ROOT / "stage_vendor/sources.json").read_text()),
               "nasa": json.loads((ROOT / "stage_vendor/nasa-fprime/provenance.json").read_text())}
    return page(request, key, state, title="FROZEN SOURCES", lines="\n\n".join(f'{name}\n{item["repository"]}\n{item["commit"]}' for name, item in records["engines"].items()), details=records)


@app.get("/source/{name}")
def source_code(name: str):
    allowed = {"harness": ROOT / "stage_mission.py", "dialogue": ROOT / "stage.py",
               "nasa": ROOT / "stage_vendor/nasa-fprime/TableGenerator.c",
               "nasa-crc": ROOT / "stage_vendor/nasa-fprime/Crc32.cpp",
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
