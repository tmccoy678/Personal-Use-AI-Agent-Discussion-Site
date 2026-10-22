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
from stage_lesson import render as render_lesson

ROOT = Path(__file__).resolve().parent
SCENARIOS = {"altered": "TRANSCRIPTION EXERCISE", "clean": "INTACT BASELINE", "stale": "STALE TELEMETRY",
             "missing": "MISSING EVIDENCE", "unresolved": "OPEN REVIEW ITEM", "rbar": "R-BAR HANDOFF", "rbar-fixed": "R-BAR CORRECTED"}
PROGRAMS = {"01": ("CONFIGURATION ENGINEER", "ESTABLISH PACKAGE BASELINE"),
            "02": ("TELEMETRY ENGINEER", "DOBEWORKS — CHECK OBSERVATIONS"),
            "03": ("PACKAGE ENGINEER", "DOBEWORKS — STAGE THE WORK"),
            "04": ("VERIFICATION ENGINEER", "VERIFY BOTH FROZEN CORES"),
            "05": ("INDEPENDENT REVIEWER", "REVIEWER — INSPECT THE DEGS DECISION"),
            "06": ("MISSION TEAM", "POLL LAUNCH READINESS"),
            "07": ("LAUNCH DIRECTOR", "RUN THE ROCKET SIMULATION"),
            "08": ("EVIDENCE", "OPEN THE HANDOFF RECORD")}
POLL = {"vehicle": "VEHICLE TEAM", "weather": "WEATHER TEAM", "range": "RANGE TEAM", "director": "LAUNCH DIRECTOR"}
CASE_ACTIONS = {"restore", "keep", "hold", "accept", "what-if", "clear-weather"} | {"go-" + key for key in POLL}
LESSON_ACTIONS = {"lesson-start", "lesson-fix", "lesson-compare", "lesson-mission"}
CACHE = {}
SESSIONS = OrderedDict()
LOCK = asyncio.Lock()
ATTEMPTS = deque(maxlen=60)
COOKIE = "stage_mission"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
TEMPLATE = (ROOT / "stage_assets/index.html").read_text()
VOICES = json.loads((ROOT / "stage_vendor/DobeWorks/interface/workbench-voices.json").read_text())


def new_state():
    return {"csrf": secrets.token_urlsafe(24), "scenario": "rbar", "lesson_mode": True, "comparison": False, "completed": [], "poll": {}, "events": [],
            "report": None, "cores": None, "launched": False, "busy": False, "tested_package": None,
            "case_history": [], "weather_clear": False, "counterfactual": False, "seen": time.monotonic()}


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
    return {"simulation": True, "operational_authority": "NONE", "component": "R-BAR-NOTE" if state["scenario"].startswith("rbar") else "TM-CRC-001",
            "completed_handoffs": state["completed"], "fictional_role_poll": state["poll"],
            "simulated_flight_completed": state["launched"], "handoff_record": state["events"],
            "fixed_engine_run": state["report"], "core_verification": state["cores"],
            "prior_candidate_runs": state["case_history"], "counterfactual_flight_with_errors": state["counterfactual"]}


def dialogue(question, report=None):
    """Original exhibit script: ordered keywords and an honest no-match fallback."""
    words = set(re.findall(r"[a-z]+", question.lower()))
    if "dobeworks" in words:
        return "DOBEWORKS CHECKS OBSERVATIONS AND BOUNDS THE WORKER'S TASK. A SUCCESSFUL WORKER RESULT STAYS STAGED AND UNACCEPTED; COMPLETION DOES NOT PROMOTE IT."
    if "degs" in words:
        return "DEGS CHECKS THE SUPPLIED ENGINEERING RECORD. AN UNRESOLVED WARNING BLOCKS READINESS; CONSISTENT CLOSURE NEEDS AN EVIDENCE REFERENCE. ACCEPTANCE REMAINS SEPARATE."
    if report and "notation_check" in report and words & {"why", "blocked", "hold", "bar", "mariner"}:
        return "THE WORKER FINISHED, BUT THE NOTE LOST ITS REQUIRED OVERBAR. THE ADAPTER PRESERVES THAT OPEN FINDING AND DEGS BLOCKS THE NEXT STEP." if report["notation_check"]["result"] == "FAIL" else "THE CORRECTED NOTE HAS CHECK EVIDENCE. DEGS READINESS AND YOUR SEPARATE DEMO ACCEPTANCE ARE DISTINCT STEPS."
    if words & {"launch", "fire", "ignite", "override", "bypass"}:
        return "USE 06 TO REVIEW THE TEAM POLL, THEN 07 FOR THE FICTIONAL FLIGHT. DIALOGUE CANNOT CHANGE A GATE OR AUTHORIZE A LAUNCH."
    if words & {"ai", "human", "alive", "feel", "model"}:
        return "I AM A SMALL RULE-BASED SCRIPT. YOU ARE PLAYING SEVERAL FICTIONAL TEAM ROLES. THE ENGINE RESULTS COME FROM THE FROZEN CODE."
    if words & {"why", "blocked", "hold"} and report:
        if report["source_behavior"]["result"] == "FAIL":
            return "ONE DIGIT IN THE CRC GENERATOR CHANGED. THE C PROGRAM STILL COMPILES, BUT ITS KNOWN-ANSWER TEST FAILS. USE 03 TO INVESTIGATE; DEGS KEEPS THE HANDOFF BLOCKED."
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
    if "notation_check" in report:
        return "R-BAR HANDOFF NOTE\n\nREQUIREMENT\nPreserve the required overbar through the handoff.\nKeep the finding open until correction has check evidence.\nAccept the output separately.\n\nTEACHING RECONSTRUCTION · NOT HISTORICAL FLIGHT CODE"
    return ("TM-CRC-001 · NASA/JPL F PRIME CRC32\n\nREQUIREMENT\n"
            "Receive a CRC32 component for the telemetry team.\nIt must reproduce 123456789 → CBF43926.\nRetain the source, requirement and test evidence together.\n\n"
            f'SOURCE FILES          TableGenerator.c + Crc32.cpp\nPACKAGE SHA256        {report["package_sha256"]}\n'
            f'BASELINE FILES        {len(report["packet"]["expected_manifest"])}\nNEXT ROLE             TELEMETRY ENGINEER')


def impact_view(state):
    report = state["report"]
    tested = report is not None and state["tested_package"] == report["package_sha256"]
    behavior = report["source_behavior"] if tested else None
    failed = tested and behavior["result"] == "FAIL"
    nodes = [("01 · SOURCE", "One component received"), ("02 · BEHAVIOR", "Awaiting the known-answer check"),
             ("03 · DEGS", "Awaiting checked record"), ("04 · RECEIVING TEAM", "Waiting for verification"),
             ("05 · COUNTDOWN", "HOLD · package not accepted")]
    if tested:
        nodes[0] = ("01 · SOURCE", f'Polynomial {behavior["polynomial"]} · C compilation PASS')
        nodes[1] = ("02 · BEHAVIOR", f'123456789 → {behavior["actual_crc32"]} · {behavior["result"]}')
        nodes[2] = ("03 · DEGS", report["degs"]["decision"] + " · submitted engineering record")
        nodes[3] = ("04 · RECEIVING TEAM", "Rejects this checksum result" if failed else "Known-answer check verified")
    if state["counterfactual"]:
        nodes[4] = ("05 · WHAT-IF FLIGHT", "Launched with error · telemetry rejected")
    if "05" in state["completed"]:
        nodes[4] = ("05 · COUNTDOWN", "Package accepted · awaiting other teams")
    if state["launched"]:
        nodes[4] = ("05 · COUNTDOWN", "Simulated flight · corrected component received" if state["case_history"] else "Simulated flight · verified baseline received")
    caption = ("Exercise consequence: launched with a failed checksum; the receiver rejects the result." if state["counterfactual"]
               else "All exercise checks pass; the receiver obtains the expected result." if state["launched"]
               else "This check passed. Package review and the other teams still govern countdown." if tested and not failed
               else "Exercise consequence: unverified telemetry keeps this mission on the pad.")
    cards = ''.join(f'<li><small>{escape(title)}</small><span>{escape(value)}</span></li>' for title, value in nodes)
    difference = ""
    if failed:
        difference = (f'<details class="difference"><summary>INVESTIGATE THE ONE-CHARACTER DIFFERENCE</summary>'
            f'<p>source/TableGenerator.c · line {behavior["line"]}. Modified demo copy.</p>'
            '<p>PUBLISHED <code>0xEDB8832<mark>0</mark></code><br>RECEIVED  <code>0xEDB8832<mark>1</mark></code></p>'
            '<p>Both compile. Both have the same file size. They compute different results.</p>'
            f'<p>The exercise receiver expects {behavior["receiver_expected_crc32"]}; the changed component computes '
            f'{behavior["candidate_packet_crc32"]} for the same telemetry sample. Its integrity result cannot be accepted.</p></details>')
    return ('<section class="impact" aria-label="Effect on this fictional mission"><h2>ONE CHARACTER · DOWNSTREAM</h2>'
            f'<ol class="{"held" if failed else ""}">{cards}</ol>{difference}'
            f'<p class="impact-caption">{caption}</p></section>')


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
    descriptions.update({"handoff/guidance-note.md": "The note received by the next stage", "handoff/context.md": "Scope and historical context",
                         "handoff/acceptance.md": "The required stop and acceptance conditions", "evidence/reference.md": "NASA historical reference"})
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
            if path == "source/TableGenerator.c":
                identity += '\nMODIFIED DEMO COPY · ONE CHARACTER CHANGED'
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
    component = "R-BAR-NOTE" if "notation_check" in report else "TM-CRC-001"
    return (f'<section class="package" id="package" aria-labelledby="package-title"><h3 id="package-title">PACKET TRAY · {component}</h3>'
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
    if state["lesson_mode"]:
        extra = package_view(state, package_query, focus_package) if show_package and state["report"] else ""
        if details is not None:
            extra += f'<section class="comparison"><h2>{escape(title)}</h2><details class="raw" open><summary>FULL RECORDED EVIDENCE</summary><pre>{escape(json.dumps(details, indent=2, sort_keys=True))}</pre></details></section>'
        return render_lesson(state, voice, reply, question, extra)
    scenario = state["scenario"]
    if lines is None:
        lines = ("YOUR ASSIGNMENT\n\nA CRC32 source component has arrived for telemetry integration.\n"
                 "One character was mistyped in the exercise copy. The C program still compiles.\n\n"
                 "DOBEWORKS supplies checked observations and stages bounded work for review.\n"
                 "The test harness checks behavior. DEGS stops the handoff while the finding is open.\n\n"
                 "Begin with 01. Investigate in 03, correct the source, then repeat the reviews.")
    options = "".join(f'<option value="{key}" {"selected" if key == scenario else ""}>{value}</option>' for key, value in SCENARIOS.items())
    programs = "".join(f'<button name="command" value="{key}">{key}  {label}</button>' for key, (_, label) in PROGRAMS.items())
    controls = "".join(f'<button class="enter" name="command" value="{key}">{escape(label)}</button>' for key, label in actions)
    raw = f'<details class="raw"><summary>FULL RECORDED EVIDENCE</summary><pre>{escape(json.dumps(details, indent=2, sort_keys=True))}</pre></details>' if details is not None else ""
    milestones = ("PACKAGE IDENTIFIED", "OBSERVATIONS RECEIVED", "WORK STAGED FOR REVIEW", "ENGINE TESTS VERIFIED", "REVIEWER RECEIVED PACKAGE")
    progress = '<ol class="handoffs">' + ''.join(
        f'<li class="{"received" if key in state["completed"] else "waiting"}"><span>{key} · {milestone}</span>'
        f'<small>{"RECEIVED" if key in state["completed"] else "AWAITING HANDOFF"}</small></li>'
        for key, milestone in zip(("01", "02", "03", "04", "05"), milestones)) + '</ol>'
    mission_state = ("CLEAN SIMULATED FLIGHT" if state["launched"] else "WHAT-IF FLIGHT · CHECKSUM ERROR" if state["counterfactual"]
                     else "PACKAGE ACCEPTED · TEAM POLL OPEN" if "05" in state["completed"] else "PACKAGE HANDOFF IN PROGRESS" if state["completed"] else "AWAITING PACKAGE")
    replacements = {"quote": f'“{voice["text"]}”', "attribution": voice["attribution"], "reply": reply,
        "question": question, "result": lines, "title": title, "mission_state": mission_state,
        "scenario": scenario, "csrf": state["csrf"],
        "command_focus": "" if show_package else "autofocus",
        "flight_class": "flight" if state["launched"] else "fault-flight" if state["counterfactual"] else "",
        "flight_label": "CLEAN FLIGHT" if state["launched"] else "WHAT-IF · TELEMETRY ERROR" if state["counterfactual"] else "THE PAD"}
    html = TEMPLATE
    for key, value in replacements.items():
        html = html.replace("{{" + key + "}}", escape(str(value)))
    return (html.replace("{{options}}", options).replace("{{programs}}", programs).replace("{{actions}}", controls)
            .replace("{{details}}", raw).replace("{{progress}}", progress)
            .replace("{{impact}}", impact_view(state))
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
    if command in {"restore", "keep", "hold", "what-if"}:
        report = state["report"]
        if (report is None or state["scenario"] != "altered" or state["tested_package"] != report["package_sha256"]):
            return {"title": "INVESTIGATE FIRST", "lines": "RUN 03 ON THE TRANSCRIPTION EXERCISE BEFORE CHOOSING A RESPONSE."}
        if command == "restore":
            corrected = await mission("clean")
            state["case_history"].append(report)
            record(state, "PACKAGE ENGINEER", "RESTORE PUBLISHED POLYNOMIAL: 1 → 0", "CORRECTED COPY SUBMITTED")
            state.update(scenario="clean", report=corrected, completed=[], poll={}, cores=None, launched=False,
                         tested_package=None, weather_clear=False, counterfactual=False)
            result = await program(state, "01")
            result["reply"] = "ONE CHARACTER RESTORED. PRIOR REVIEWS ARE INVALIDATED. REPEAT 02–05 ON THE CORRECTED COPY; THE ORIGINAL FAILURE REMAINS IN 08."
            return result
        if command == "what-if":
            if not state["counterfactual"]:
                record(state, "COUNTERFACTUAL", "ILLUSTRATE LAUNCH DESPITE BLOCKED CHECK", "TELEMETRY CHECKSUM REJECTED")
                state["counterfactual"] = True
            behavior = report["source_behavior"]
            return {"title": "WHAT-IF · LAUNCH WITH ERROR", "lines":
                "T+00  THE FICTIONAL VEHICLE LEAVES THE PAD\n"
                f'T+01  CHANGED COMPONENT COMPUTES {behavior["candidate_packet_crc32"]}\n'
                f'T+02  RECEIVER EXPECTS {behavior["receiver_expected_crc32"]}\n'
                "T+03  TELEMETRY INTEGRITY CHECK FAILS\n\n"
                "The team cannot accept this telemetry result.\nThe wider vehicle outcome is unspecified in this exercise.\n\n"
                f'DEGS REMAINS {report["degs"]["decision"]}. NO PACKAGE ACCEPTANCE WAS RECORDED.',
                "actions": [("hold", "RETURN TO COUNTDOWN HOLD"), ("restore", "CORRECT THE DIGIT AND RETEST")],
                "reply": "THIS IS THE CONSEQUENCE BRANCH: A LAUNCH CAN OCCUR WHILE ITS ENGINEERING RECORD IS STILL BLOCKED."}
        if command == "hold":
            state["counterfactual"] = False
            record(state, "LAUNCH DIRECTOR", "PRESERVE THE ENGINEERING HOLD", "COUNTDOWN HELD")
            result = await program(state, "03")
            result["reply"] = "COUNTDOWN HELD. THE FINDING AND ITS EVIDENCE REMAIN OPEN FOR CORRECTION."
            return result
        record(state, "INDEPENDENT REVIEWER", "KEEP THE ONE-CHARACTER CHANGE", "BLOCKED — FAILING CHECK REMAINS")
        result = await program(state, "03")
        result["reply"] = "SAME FILE SIZE AND SUCCESSFUL COMPILATION DO NOT SATISFY THE KNOWN-ANSWER REQUIREMENT. THE HANDOFF STAYS BLOCKED."
        return result
    if command == "06" or command in POLL or command.startswith("go-") or command == "clear-weather":
        reply = "SELECT A TEAM TO INSPECT ITS FICTIONAL READINESS RECORD."
        if command == "clear-weather":
            if not state["weather_clear"]:
                state["weather_clear"] = True
                record(state, POLL["weather"], "RECEIVE FIXTURE T+05 WEATHER REPORT", "WIND 9 · LIMIT 15")
            command = "weather"
        role = command.removeprefix("go-")
        conditions = {"vehicle": "05" in state["completed"], "weather": state["weather_clear"], "range": True,
                      "director": "05" in state["completed"] and all(state["poll"].get(k) == "GO" for k in ("vehicle", "weather", "range"))}
        facts = {"vehicle": "Package acceptance is required before this fixture's vehicle report can be GO.",
                 "weather": f'Fixture wind: {9 if state["weather_clear"] else 22}. Limit: 15. Window: {"T+05" if state["weather_clear"] else "T+00"}.',
                 "range": "Fixed exercise report: exclusion area CLEAR. This is a separate mission-team record.",
                 "director": "Requires package acceptance plus vehicle, weather and range decisions."}
        if command.startswith("go-") and role in POLL:
            if conditions[role] and state["poll"].get(role) != "GO":
                state["poll"][role] = "GO"
                record(state, POLL[role], "FICTIONAL READINESS DECISION", "GO")
                reply = "GO RECORDED AGAINST THE DISPLAYED CONDITIONS."
            elif not conditions[role]:
                reply = "HOLD. THE DISPLAYED CONDITION IS NOT SATISFIED."
        if role in POLL:
            recorded = state["poll"].get(role) == "GO"
            if not conditions[role]:
                missing = [POLL[k] for k in ("vehicle", "weather", "range") if state["poll"].get(k) != "GO"]
                reason = ("Complete and accept package review 05." if role == "vehicle" else "Wind 22 exceeds limit 15; receive the T+05 report."
                          if role == "weather" else "Package review 05 and these team decisions are required: " + ", ".join(missing))
                reply = "HOLD · " + reason
            actions = [("06", "RETURN TO TEAM POLL")] if recorded else ([("clear-weather", "RECEIVE THE T+05 WEATHER REPORT")] if role == "weather" and not state["weather_clear"] else []) + [("go-" + role, "RECORD GO AGAINST THIS REPORT"), ("06", "RETURN TO TEAM POLL")]
            return {"title": POLL[role], "lines": f'DECISION              {"GO RECORDED" if recorded else "HOLD · NO GO RECORDED"}\n\n' + facts[role] + "\n\nThese are fictional mission-team conditions, separate from DobeWorks and DEGS.",
                    "reply": reply, "actions": actions}
        lines = "FICTIONAL LAUNCH READINESS POLL\n\n" + f'CRC32 PACKAGE         {"ACCEPTED" if "05" in state["completed"] else "HOLD"}\n'
        lines += "\n".join(f'{label:<22}{state["poll"].get(key, "HOLD — AWAITING REVIEW")}' for key, label in POLL.items())
        lines += "\n\nYOU ARE PLAYING EACH ROLE IN THIS ILLUSTRATIVE MISSION."
        ready = "05" in state["completed"] and all(state["poll"].get(k) == "GO" for k in POLL)
        return {"title": "MISSION TEAM", "lines": lines, "reply": "ALL REQUIRED DECISIONS ARE RECORDED. THE CLEAN FLIGHT IS READY IN 07." if ready else reply,
                "actions": [("07", "RUN THE CLEAN SIMULATED FLIGHT")] if ready else [(key, "INSPECT " + label) for key, label in POLL.items() if state["poll"].get(key) != "GO"]}
    if command == "07":
        state["counterfactual"] = False
        if state["completed"] != ["01", "02", "03", "04", "05"] or not all(state["poll"].get(k) == "GO" for k in POLL):
            return {"title": "COUNTDOWN HOLD", "lines": "PACKAGE ACCEPTANCE AND THE COMPLETE TEAM POLL ARE REQUIRED.", "reply": "RETURN TO THE FIRST WAITING HANDOFF OR OPEN 06."}
        if not state["launched"]:
            record(state, "LAUNCH DIRECTOR", "FICTIONAL FLIGHT", "COMPLETE")
            state["launched"] = True
        correction = "One mistyped digit was corrected; the failed candidate remains in the record." if state["case_history"] else "The intact baseline satisfied the exercise checks."
        return {"title": "CLEAN SIMULATED FLIGHT", "lines": "T-03  CRC KNOWN-ANSWER CHECK PASSED\nT-02  DEGS RECORD CHECK AND REVIEW COMPLETE\nT-01  TEAM POLL COMPLETE\nT+00  FICTIONAL IGNITION\nT+03  THE ROCKET CLEARS THE PAD\n\n" + correction +
                "\n\nThe receiver obtains the expected checksum.\nMISSION SIMULATION · ALL EXERCISE CHECKS PASS",
                "reply": "THE TEST FINDING, CORRECTION AND NEW REVIEW TRAVEL TOGETHER. OPEN 08 TO FOLLOW THE EVIDENCE."}
    accepting = command == "accept"
    if accepting:
        command = "05"
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
                 f'OBSERVER              {observer["status"]}\nFRESHNESS             {observer["freshness"]}\n'
                 f'LAST SUCCESS          {observer["self_health"]["last_success_at"]}\nCHECKED AT            {observer["observed_at"]}\n'
                 f'SIGNAL DECISION MAP   {len(observer["decision_map"])} ALLOWED SIGNALS\n\nTELEMETRY HANDOFF · {"PASS" if passed else "HOLD"}')
        if not passed:
            reply = "THE OBSERVER CANNOT SUPPLY FRESH EVIDENCE. RESTORE THE INTACT PACKET TO START A NEW BASELINE."
    elif command == "03":
        state["tested_package"] = report["package_sha256"]
        passed = report["packet"]["integrity"] == "PASS"
        behavior = report["source_behavior"]
        envelope = report["worker_envelope"]
        lines = ("DOBEWORKS WORKER\nThe inventory is staged for review. The packet is compared with its baseline.\n\n"
                 f'WORKER                {report["worker"]["state"]}\nPROMOTION             {report["worker"]["promotion"]}\n'
                 f'WORK CONTRACT         {envelope["side_effects"]}\nAUTOMATIC RETRIES     {envelope["retry_limit"]}\n'
                 f'NASA TABLE CONTROL    {report["nasa"]["generated_values_checked"]} VALUES · VERIFIED\nKNOWN CRC CONTROL     {report["nasa"]["known_vector"]}\n'
                 f'PACKET CRC            {report["packet"]["actual_crc32"]}\nSOURCE / MANIFEST     {report["packet"]["integrity"]}\n\n'
                 f'CANDIDATE C COMPILES   PASS\nINPUT                 {behavior["test_input"]}\nEXPECTED CRC          {behavior["expected_crc32"]}\nACTUAL CRC            {behavior["actual_crc32"]}\nKNOWN-ANSWER TEST     {behavior["result"]}\n'
                 f'DEGS RECORD CHECK     {report["degs"]["decision"]}\n'
                 + '\n'.join(item["rule_id"] + ': ' + item["message"] for item in report["degs"]["unmet_requirements"]) + '\n\n'
                 f'PACKAGE HANDOFF · {"READY FOR VERIFICATION" if passed else "HOLD"}')
        if not passed:
            reply = "INVESTIGATE THE SOURCE AND ITS TEST RESULT. THE FINDING TRAVELS WITH THE WORK; A FINISHED WORKER JOB DOES NOT CLOSE IT."
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
        reply = "REVIEW THE KNOWN-ANSWER RESULT AND THE DEGS DECISION BEFORE RECORDING YOUR SEPARATE ACCEPTANCE." if passed else "THE ENGINEERING RECORD STILL HAS AN OPEN FINDING. ACCEPTANCE IS HELD."
        if passed and not accepting:
            return {"title": title, "lines": lines.replace("ACCEPTED FOR SIMULATED INTEGRATION", "READY FOR YOUR DECISION"), "reply": reply,
                    "actions": [("accept", "ACCEPT THE REVIEWED PACKAGE"), ("08", "INSPECT THE EVIDENCE FIRST")]}
        if passed:
            reply = ("DEMO ACCEPTANCE RECORDED. THE ORIGINAL FINDING AND ITS CLOSURE REMAIN IN THE RECORD."
                     if state["lesson_mode"] else "REVIEWER ACCEPTANCE RECORDED. CONTINUE TO THE OTHER MISSION TEAMS IN 06.")
    if command not in state["completed"]:
        record(state, role, "FICTIONAL REVIEWER ACCEPTANCE" if accepting else title, "RECEIVED" if passed else "HOLD")
        if passed:
            state["completed"].append(command)
    if passed and command in {"01", "02", "03", "04"}:
        reply = {"01": "CONFIGURATION → TELEMETRY. THE PACKAGE NOW HAS A RECORDED IDENTITY.",
                 "02": "TELEMETRY → PACKAGE ENGINEER. FRESH OBSERVATIONS RECEIVED.",
                 "03": "PACKAGE ENGINEER → VERIFICATION. THE SAME FILES ARE READY FOR THE NEXT REVIEW.",
                 "04": "VERIFICATION → INDEPENDENT REVIEWER. THE ENGINE TEST RECORD TRAVELS WITH THE PACKAGE."}[command]
    actions = [("hold", "HOLD THE COUNTDOWN"), ("what-if", "SEE A LAUNCH WITH THIS ERROR"),
               ("restore", "RESTORE THE PUBLISHED DIGIT 0")] if command == "03" and state["scenario"] == "altered" else []
    if passed and not actions:
        following = {"01": "02", "02": "03", "03": "04", "04": "05", "05": "06"}[command]
        actions = [(following, "NEXT · " + PROGRAMS[following][1])]
    return {"title": title, "lines": lines, "reply": reply, "show_package": command == "01", "actions": actions}


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
            state.update(scenario=scenario, completed=[], poll={}, report=None, cores=None, launched=False,
                         tested_package=None, weather_clear=False, counterfactual=False, lesson_mode=scenario.startswith("rbar"), comparison=False)
            record(state, "CONFIGURATION ENGINEER", "PACKAGE REPLACED — ALL RECEIPTS INVALIDATED", "NEW BASELINE REQUIRED")
        if question in LESSON_ACTIONS:
            result = await lesson_program(state, question)
        elif question == "inspect" and state["report"]:
            result = {"title": "PACKAGE INSPECTION", "lines": baseline_lines(state["report"]),
                      "show_package": True, "package_query": query, "focus_package": True,
                      "reply": "INSPECT THE PACKAGE. SEARCH DOES NOT ADVANCE A HANDOFF."}
        elif state["lesson_mode"] and question in PROGRAMS and question != "08":
            result = await lesson_program(state, "lesson-start") if question == "01" else {"reply": "USE THE DEMO BUTTONS TO FOLLOW THE HANDOFF. THE LONGER ROCKET WORKFLOW OPENS AFTER ACCEPTANCE."}
        elif question in PROGRAMS or question in POLL or question in CASE_ACTIONS:
            result = await program(state, question)
        else:
            result = {"reply": dialogue(question, state["report"]), "question": question}
        return page(request, key, state, **result)
    except (RuntimeError, ValueError, KeyError):
        return page(request, key, state, title="PROGRAM ERROR", lines="NO HANDOFF WAS ACCEPTED.", reply="THE CHECK COULD NOT COMPLETE. PLEASE TRY THE PROGRAM AGAIN.")
    finally:
        state["busy"] = False


async def lesson_program(state, command):
    if command == "lesson-start":
        state.update(new_state())
        for step in ("01", "02", "03"):
            await program(state, step)
        return {"reply": "THE TASK COMPLETED. THE OPEN FINDING STILL BLOCKS THE HANDOFF."}
    if command == "lesson-mission":
        state.update(new_state())
        state.update(lesson_mode=False, scenario="altered")
        return {"reply": "OPTIONAL, SEPARATE ROCKET WORKFLOW. BEGIN WITH 01."}
    if not state["report"] or "notation_check" not in state["report"]:
        return {"reply": "HAND OFF THE WORK FIRST TO SEE THE RECORDED STOP CONDITION."}
    if command == "lesson-compare":
        state["comparison"] = True
        return {"reply": "THE NOTE STAYS THE SAME. THE COMPARISON CHANGES ONLY THE WARNING FIELD IN A SEPARATE READ-ONLY GATE EVALUATION."}
    if state["scenario"] != "rbar":
        return {"reply": "THE NOTE IS ALREADY CORRECTED. ACCEPTANCE IS A SEPARATE STEP."}
    corrected = await mission("rbar-fixed")
    state["case_history"].append(state["report"])
    record(state, "DEMO PARTICIPANT", "RESTORE THE REQUIRED R-BAR", "CORRECTED NOTE SUBMITTED")
    state.update(scenario="rbar-fixed", report=corrected, completed=[], poll={}, cores=None,
                 tested_package=None, launched=False, counterfactual=False, comparison=False)
    for step in ("01", "02", "03", "04", "05"):
        await program(state, step)
    return {"reply": "THE FINDING HAS CHECK EVIDENCE AND CONSISTENT CLOSURE. THE HANDOFF STILL AWAITS YOUR SEPARATE DEMO ACCEPTANCE."}


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
