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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from stage_mission import check_sources, digest, encode, mission_package

ROOT = Path(__file__).resolve().parent
SCENARIOS = {"clean": "INTACT PACKET", "stale": "STALE TELEMETRY", "missing": "MISSING EVIDENCE",
             "unresolved": "OPEN REVIEW ITEM", "altered": "ALTERED SOURCE"}
PROGRAMS = {"01": ("CONFIGURATION ENGINEER", "ESTABLISH PACKAGE BASELINE"),
            "02": ("TELEMETRY ENGINEER", "DOBEWORKS — CHECK OBSERVATIONS"),
            "03": ("PACKAGE ENGINEER", "DOBEWORKS — STAGE THE WORK"),
            "04": ("VERIFICATION ENGINEER", "VERIFY BOTH FROZEN CORES"),
            "05": ("INDEPENDENT REVIEWER", "REVIEWER — CHECK DEGS AND ACCEPT"),
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


def baseline_lines(report):
    return ("TM-CRC-001 · NASA/JPL F PRIME CRC32\n\nREQUIREMENT\n"
            "Retain exact source and sequence-7 telemetry identities.\nReject changed bytes or missing evidence at handoff.\n\n"
            f'SOURCE FILES          TableGenerator.c + Crc32.cpp\nPACKAGE SHA256        {report["package_sha256"]}\n'
            f'BASELINE FILES        {len(report["packet"]["expected_manifest"])}\nNEXT ROLE             TELEMETRY ENGINEER')


def package_view(state, query, focus=False):
    sources, nasa = check_sources()
    artifacts, expected = mission_package(state["scenario"], sources, nasa)
    actual = {path: digest(data) for path, data in artifacts.items()}
    report = state["report"]
    if actual != report["packet"]["actual_manifest"] or expected != report["packet"]["expected_manifest"]:
        raise RuntimeError("The displayed packet differs from the checked packet")
    descriptions = {"source/TableGenerator.c": "NASA/JPL lookup-table generator",
                    "source/Crc32.cpp": "NASA/JPL CRC32 reference implementation",
                    "source/LICENSE.txt": "Upstream license",
                    "mission/context.md": "Requirement and handoff context",
                    "mission/plan.md": "Fictional mission handoff plan",
                    "mission/telemetry.md": "Fictional telemetry sample",
                    "evidence/nasa-source.md": "Pinned NASA source identity"}
    files = []
    for path in sorted(expected):
        data = artifacts.get(path)
        text = data.decode("utf-8") if data is not None else ""
        matches = [(number, line) for number, line in enumerate(text.splitlines(), 1)
                   if query and query.casefold() in line.casefold()]
        if query and query.casefold() not in path.casefold() and not matches:
            continue
        if data is None:
            files.append(f'<p class="missing">{escape(path)} · MISSING</p>')
            continue
        identity = f'{len(data):,} bytes · SHA256 {actual[path]}'
        if actual[path] != expected[path]:
            identity += f'\nIDENTITY DIFFERS · BASELINE SHA256 {expected[path]}'
        contents = f'<pre class="file-content">{escape(text)}</pre>'
        if matches:
            found = "\n".join(f"{number:4}  {line}" for number, line in matches[:60])
            contents = (f'<p>{len(matches)} MATCHING LINES · LINE NUMBERS SHOWN'
                        + (' · FIRST 60' if len(matches) > 60 else '') + '</p>'
                        + f'<pre class="file-content">{escape(found)}</pre>'
                        + f'<details><summary>COMPLETE FILE</summary>{contents}</details>')
        files.append(f'<details class="package-file" {"open" if query else ""}>'
                     f'<summary>{escape(path)}</summary><p>{descriptions[path]}</p>'
                     f'<pre class="file-identity">{identity}</pre>{contents}</details>')
    result = f'{len(files)} FILES MATCH' if query else f'{len(artifacts)} FILES PRESENT · {len(expected)} EXPECTED'
    return ('<section class="package" id="package" aria-labelledby="package-title"><h3 id="package-title">PACKET TRAY · TM-CRC-001</h3>'
            '<form action="/" method="post" class="package-search"><label for="package-query">SEARCH THIS PACKET</label>'
            f'<input type="hidden" name="csrf" value="{state["csrf"]}"><input type="hidden" name="scenario" value="{state["scenario"]}">'
            '<input type="hidden" name="command" value="inspect">'
            f'<input id="package-query" name="q" value="{escape(query)}" maxlength="120" placeholder="Filename or text" {"autofocus" if focus else ""}>'
            '<button class="enter">SEARCH</button></form>'
            f'<p>{result} · OPEN A FILE TO INSPECT ITS CONTENTS.</p>'
            + ('<p><a href="/package#package">CLEAR SEARCH</a></p>' if query else '')
            + (''.join(files) if files else '<p>NO MATCHES IN THIS PACKET.</p>') + '</section>')


def render(state, title="MISSION TERMINAL", lines=None, reply="PLEASE GO ON.", question="", actions=(), details=None,
           show_package=False, package_query="", focus_package=False):
    voice = secrets.choice(VOICES)
    scenario = state["scenario"]
    if lines is None:
        lines = ("YOUR ASSIGNMENT\n\nDeliver one NASA/JPL checksum component to the next team with its context intact.\n\n"
                 "DOBEWORKS checks that observations are fresh and stages bounded work for review.\n\n"
                 "DEGS checks whether the engineering record meets the rules for its next handoff.\n\n"
                 "YOU inspect the package and play the people who receive it. Begin with 01.")
    options = "".join(f'<option value="{key}" {"selected" if key == scenario else ""}>{value}</option>' for key, value in SCENARIOS.items())
    programs = "".join(f'<button name="command" value="{key}">{key}  {label}</button>' for key, (_, label) in PROGRAMS.items())
    controls = "".join(f'<button class="enter" name="command" value="{key}">{escape(label)}</button>' for key, label in actions)
    raw = f'<details class="raw"><summary>FULL RECORDED EVIDENCE</summary><pre>{escape(json.dumps(details, indent=2, sort_keys=True))}</pre></details>' if details is not None else ""
    milestones = ("PACKAGE IDENTIFIED", "OBSERVATIONS RECEIVED", "WORK STAGED FOR REVIEW", "ENGINE TESTS VERIFIED", "REVIEWER RECEIVED PACKAGE")
    progress = '<ol class="handoffs">' + ''.join(
        f'<li class="{"received" if key in state["completed"] else "waiting"}"><span>{key} · {milestone}</span>'
        f'<small>{"RECEIVED" if key in state["completed"] else "AWAITING HANDOFF"}</small></li>'
        for key, milestone in zip(("01", "02", "03", "04", "05"), milestones)) + '</ol>'
    mission_state = "SIMULATED FLIGHT COMPLETE" if state["launched"] else ("PACKAGE ACCEPTED · TEAM POLL OPEN" if "05" in state["completed"] else "PACKAGE HANDOFF IN PROGRESS" if state["completed"] else "AWAITING PACKAGE")
    replacements = {"quote": f'“{voice["text"]}”', "attribution": voice["attribution"], "reply": reply,
        "question": question, "result": lines, "title": title, "mission_state": mission_state,
        "scenario": scenario, "csrf": state["csrf"],
        "command_focus": "" if show_package else "autofocus",
        "flight_class": "flight" if state["launched"] else "", "flight_label": "THE CLIMB" if state["launched"] else "THE PAD"}
    html = TEMPLATE
    for key, value in replacements.items():
        html = html.replace("{{" + key + "}}", escape(str(value)))
    return (html.replace("{{options}}", options).replace("{{programs}}", programs).replace("{{actions}}", controls)
            .replace("{{details}}", raw).replace("{{progress}}", progress)
            .replace("{{package}}", package_view(state, package_query, focus_package) if state["report"] else "<p class=empty-tray>PACKET TRAY · TM-CRC-001<br>USE 01 TO OPEN THE PACKAGE.</p>"))


def page(request, key, state, **kwargs):
    if request.method == "GET" and request.url.path == "/":
        response = HTMLResponse(render(state, **kwargs))
    else:
        state["pending_view"] = kwargs
        response = RedirectResponse("/#package" if kwargs.get("focus_package") else "/", status_code=303)
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
        lines = baseline_lines(report)
    elif command == "02":
        observer = report["observer"]
        passed = observer["status"] == "VALIDATED" and observer["freshness"] == "FRESH"
        lines = ("DOBEWORKS OBSERVER\nThe next engineer needs fresh observations to judge this handoff.\n\n"
                 f'OBSERVER              {observer["status"]}\nFRESHNESS             {observer["freshness"]}\n\nTELEMETRY HANDOFF · {"PASS" if passed else "HOLD"}')
        if not passed:
            reply = "THE OBSERVER CANNOT SUPPLY FRESH EVIDENCE. RESTORE THE INTACT PACKET TO START A NEW BASELINE."
    elif command == "03":
        passed = report["packet"]["integrity"] == "PASS"
        lines = ("DOBEWORKS WORKER\nThe inventory is staged for review. The packet is compared with its baseline.\n\n"
                 f'WORKER                {report["worker"]["state"]}\nPROMOTION             {report["worker"]["promotion"]}\n'
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
        lines = ("DEGS HANDOFF CHECK\nDEGS checks the engineering record. You receive the package as its fictional reviewer.\n\n"
                 f'DEGS RECORD CHECK     {report["degs"]["decision"]} · EXIT {report["degs_exit"]}\n'
                 f'PACKAGE IDENTITY      {report["package_sha256"]}\nCORE VERIFICATION     {state["cores"]["result"]}\n'
                 f'REVIEW ITEM           {"CLOSED" if passed else "OPEN"}\n\n'
                 f'PACKAGE REVIEW · {"ACCEPTED FOR SIMULATED INTEGRATION" if passed else "HOLD"}')
        reply = "YOU RECORDED THE FICTIONAL REVIEWER'S ACCEPTANCE. THE ENGINE'S WORKER RESULT REMAINS UNACCEPTED. CONTINUE TO THE OTHER MISSION TEAMS IN 06." if passed else "AN OPEN REVIEW ITEM PREVENTS ACCEPTANCE. RESTORE THE INTACT PACKET AND REPEAT THE REVIEWS."
    if command not in state["completed"]:
        record(state, role, title, "RECEIVED" if passed else "HOLD")
        if passed:
            state["completed"].append(command)
    if passed and command in {"01", "02", "03", "04"}:
        reply = {"01": "CONFIGURATION → TELEMETRY. THE PACKAGE NOW HAS A RECORDED IDENTITY.",
                 "02": "TELEMETRY → PACKAGE ENGINEER. FRESH OBSERVATIONS RECEIVED.",
                 "03": "PACKAGE ENGINEER → VERIFICATION. THE SAME FILES ARE READY FOR THE NEXT REVIEW.",
                 "04": "VERIFICATION → INDEPENDENT REVIEWER. THE ENGINE TEST RECORD TRAVELS WITH THE PACKAGE."}[command]
    return {"title": title, "lines": lines, "reply": reply, "show_package": command == "01"}


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
    pending = state.pop("pending_view", None)
    if pending is None:
        SESSIONS[key] = state = new_state()
    return page(request, key, state, **(pending or {}))


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
        fields = parse_qs(body.decode("utf-8"), max_num_fields=4, strict_parsing=True, keep_blank_values=True)
        if set(fields) not in ({"command", "scenario", "csrf"}, {"command", "scenario", "csrf", "q"}) or any(len(value) != 1 for value in fields.values()):
            raise ValueError()
        scenario = fields["scenario"][0]
        question = fields["command"][0].strip()
        query = fields.get("q", [""])[0].strip()
        if scenario not in SCENARIOS or len(question) > 160 or len(query) > 120 or ("q" in fields and question != "inspect"):
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
        if question == "inspect" and state["report"]:
            result = {"title": "PACKAGE INSPECTION", "lines": baseline_lines(state["report"]),
                      "show_package": True, "package_query": query, "focus_package": True,
                      "reply": "INSPECT THE PACKAGE. SEARCH DOES NOT ADVANCE A HANDOFF."}
        elif question in PROGRAMS or question in POLL:
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


@app.get("/package")
def inspect_package(request: Request):
    fields = request.query_params
    if len(request.scope["query_string"]) > 2048:
        return Response("Search too long", status_code=413)
    query = fields.get("q", "").strip()
    if set(fields) - {"q"} or len(fields.getlist("q")) > 1 or len(query) > 120:
        return Response("Use one search of at most 120 characters", status_code=422)
    key, state = session(request)
    if state["report"] is None:
        return page(request, key, state, reply="USE 01 TO ESTABLISH THE PACKAGE BEFORE INSPECTING IT.")
    try:
        return page(request, key, state, title="PACKAGE INSPECTION", lines=baseline_lines(state["report"]),
                    show_package=True, package_query=query, focus_package=True,
                    reply="INSPECT THE PACKAGE. SEARCH DOES NOT ADVANCE A HANDOFF.")
    except (RuntimeError, ValueError, KeyError):
        return Response("The package could not be verified for display", status_code=503)


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
        # Render probes the newest custom hostname over internal HTTP.
        # Keep the existing database health check available on every hostname.
        target = app if (scope["type"] == "http" and host == b"stage.dobeworks.com"
                         and scope["path"] != "/healthz") else self.app
        await target(scope, receive, send)
