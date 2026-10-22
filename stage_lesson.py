"""A short, server-rendered explanation of the real fixed handoff records."""
from html import escape


def render(state, voice, reply, question, extra=""):
    report = state["report"]
    check = report.get("notation_check") if report else None
    fixed = check is not None and check["result"] == "PASS"
    accepted = "05" in state["completed"]

    def form(command, label, secondary=False):
        return (f'<form action="/" method="post"><input type="hidden" name="csrf" value="{state["csrf"]}">'
                f'<input type="hidden" name="scenario" value="{state["scenario"]}">'
                f'<button class="enter {"secondary" if secondary else ""}" name="command" value="{command}">{label}</button></form>')

    document_title = "DobeWorks · The Handoff"
    title = "AN AGENT CAN FINISH. THE WORK MAY STILL NEED TO STOP."
    explanation = "A required overbar disappeared from a guidance note. Follow what happens when the completed work reaches the next stage."
    action = form("lesson-start", "HAND OFF THE WORK")
    observer = "Awaiting the supplied snapshot"
    worker = "Awaiting bounded work"
    finding = "Awaiting the adapted record"
    finding_detail = "The handoff contract has not been evaluated."
    gate = "Awaiting the record"
    acceptance = "Not requested"
    if check:
        document_title = "DobeWorks · Handoff Held" if not fixed else "DobeWorks · Ready for Acceptance"
        title = "THE AGENT FINISHED. THE OPEN ISSUE SURVIVED." if not fixed else "THE ISSUE IS CLOSED. ACCEPTANCE IS STILL YOUR DECISION."
        explanation = ("DobeWorks observed the supplied snapshot, completed one bounded attempt, and kept the result staged. The handoff carried the unresolved notation finding into DEGS, so readiness stays blocked."
                       if not fixed else "The corrected note passes its check. The handoff retains the finding, its consistent closure, and the evidence reference. DEGS permits readiness; separate acceptance is still required.")
        observer = f'{report["observer"]["status"]} · {report["observer"]["freshness"]}'
        worker = f'{report["worker"]["state"]} · {report["worker"]["promotion"]}'
        finding = "RESOLVED · required overbar restored" if fixed else "UNRESOLVED · required overbar missing"
        warning = report["degs_task"]["warnings"][0]
        finding_detail = (f'{warning["severity"]} · closure {str(warning["resolved"]).lower()} · '
                          f'{warning["evidence_path"]}')
        gate = report["degs"]["decision"]
        acceptance = "Awaiting your demo acceptance" if fixed else "Held while the issue is open"
        action = form("accept", "ACCEPT THIS DEMO HANDOFF") if fixed else form("lesson-fix", "RESTORE THE BAR AND RECHECK")
    if accepted:
        document_title = "DobeWorks · Handoff Accepted"
        title = "A COMPLETED TASK BECAME A REVIEWED HANDOFF."
        explanation = "The original finding remains in the record. Its correction and check evidence closed the issue. Your separate demo acceptance allowed the simulated handoff to proceed."
        acceptance = "RECORDED · for this demonstration"
        action = form("00", "REPLAY THE DEMONSTRATION")

    cards = (f'<li><small>DOBEWORKS · OBSERVER</small><strong>{escape(observer)}</strong>'
             '<p>Validates the supplied snapshot and records freshness.</p></li>'
             f'<li><small>DOBEWORKS · WORKER</small><strong>{escape(worker)}</strong>'
             '<p>Performs one bounded attempt and keeps completed output staged.</p></li>'
             f'<li><small>HANDOFF CONTRACT · ADAPTED RECORD</small><strong>{escape(finding)}</strong>'
             f'<p>{escape(finding_detail)}</p></li>'
             f'<li><small>DEGS · READINESS CHECK</small><strong>{escape(gate)}</strong>'
             '<p>Checks the supplied engineering record against its rules.</p></li>'
             f'<li><small>HUMAN ACCEPTANCE</small><strong>{escape(acceptance)}</strong></li>')

    comparison = ""
    stop_conditions = ""
    if report:
        original = state["case_history"][0] if fixed and state["case_history"] else report
        trial = original["translation_comparison"]
        comparison = ('<section class="comparison"><h2>SAME WORK. DIFFERENT HANDOFF RECORD.</h2>'
            '<div><p><b>STOP PRESERVED</b><br>Worker finished. Warning remains.<br>DEGS: '
            + escape(original["degs"]["decision"]) + '</p><p><b>COMPLETION-ONLY SUMMARY</b><br>Worker finished. Warning was dropped.<br>DEGS: '
            + escape(trial["completion_only_decision"]["decision"]) + '</p></div>'
            '<p>The candidate is identical in both evaluations. The record on the left preserves the unresolved warning. '
            'The summary on the right loses it, so DEGS receives no stop to enforce.</p></section>')
        warning_status = "CLOSED IN THIS EXAMPLE" if fixed else "CURRENT STOP"
        acceptance_status = "ACCEPTED IN THIS DEMONSTRATION" if accepted else "STILL SEPARATE"
        stop_conditions = ('<section class="stop-conditions"><h2>WHAT CAN HOLD A HANDOFF?</h2><div>'
            '<article><small>STOP CONDITION 01</small><strong>STALE OBSERVATION</strong><p>Fresh evidence is required.</p></article>'
            f'<article class="current"><small>{warning_status}</small><strong>UNRESOLVED WARNING</strong><p>Valid closure evidence is required.</p></article>'
            f'<article><small>{acceptance_status}</small><strong>UNACCEPTED OUTPUT</strong><p>Acceptance is a separate decision.</p></article>'
            '</div></section>')

    advanced = ""
    if accepted:
        advanced = ('<div class="advanced"><p>ADVANCED EVIDENCE WALKTHROUGH · 8 STEPS<br>'
                    '<span>Source identity, freshness, staged output, DEGS readiness, acceptance, and downstream effect.</span></p>'
                    + form("lesson-mission", "OPEN THE ADVANCED EVIDENCE WALKTHROUGH", True) + '</div>')
    lesson_step = "3 / 3 · ACCEPTED" if accepted else "2 / 3 · CORRECTED" if fixed else "1 / 3 · HELD" if check else "A SHORT INTERACTIVE DEMO"
    return ('''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'''
        f'<title>{document_title}</title><link rel="stylesheet" href="/stage.css"></head><body><main>'
        '<header><div class="wordmark">D O B E W O R K S</div>'
        f'<div class="voice">“{escape(voice["text"])}”</div><div class="attribution">{escape(voice["attribution"])}</div></header>'
        f'<p class="station">MISSION 001 · THE HANDOFF · {lesson_step}</p>'
        '<ol class="boundary-map" aria-label="Handoff sequence"><li>AGENT FINISHES</li>'
        '<li>DOBEWORKS OBSERVES AND STAGES</li><li>HANDOFF PRESERVES</li>'
        '<li>DEGS CHECKS READINESS</li><li>HUMAN ACCEPTANCE</li></ol>'
        '<p class="degs-name">DEGS · DOBEWORKS ENGINEERING GOVERNANCE SYSTEM</p>'
        '<div class="lesson-layout"><section>'
        f'<h1 class="lesson-title">{title}</h1><p class="lesson-copy">{explanation}</p>'
        '<div class="notation"><div><small>REQUIRED NOTE</small><span aria-label="R bar" class="bar">R</span></div>'
        f'<div><small>RECEIVED NOTE</small><span {"class=bar aria-label=R-bar" if fixed else "aria-label=R"}>R</span></div></div>'
        f'<div class="lesson-actions">{action}</div>{comparison}{stop_conditions}'
        '<p class="lesson-takeaway">The protected handoff carries the work, its unresolved conditions, the evidence that closes them, and the acceptance still required.</p>'
        f'{advanced}<div class="conversation"><form action="/" method="post" class="command"><input type="hidden" name="csrf" value="{state["csrf"]}">'
        f'<input type="hidden" name="scenario" value="{state["scenario"]}"><label for="command">RULE-BASED GUIDE · PLEASE GO ON. &gt;</label>'
        '<input id="command" name="command" maxlength="160" placeholder="What is DobeWorks?" autocomplete="off"><button class="enter">RETURN</button></form>'
        '<p class="guide-prompts">TRY: WHAT IS DOBEWORKS? · WHAT IS DEGS? · WHY IS IT BLOCKED?</p>'
        f'<p class="question">{escape(question)}</p><p class="reply" role="status" aria-live="polite">{escape(reply)}</p></div></section>'
        f'<aside class="lesson-flow"><h2>THE HANDOFF, STEP BY STEP</h2><ol>{cards}</ol></aside></div>'
        '<details class="lesson-info"><summary>INFORMATION &amp; EVIDENCE</summary>'
        '<p>NASA describes an omitted overbar and a guidance antenna fault in '
        '<a href="https://science.nasa.gov/mission/mariner-1/">Mariner 1</a>. This teaching reconstruction models notation loss with an original note.</p>'
        '<p>The notation check compares the note with its supplied reference. DobeWorks stages a synthetic inventory; DEGS evaluates the adapted record. '
        'The Worker result remains COMPLETED_UNACCEPTED and unpromoted. The final step records visitor acceptance within this public simulation.</p>'
        '<p>The comparison uses the same candidate and the real gate, changing only the warning field in a separate read-only evaluation. It performs no execution or promotion.</p>'
        '<p><a href="/evidence">RECORDED INPUTS &amp; OUTPUTS</a> · <a href="/package">INSPECT THE NOTE AND CONTEXT</a> · <a href="/sources">FROZEN SOURCE IDENTITIES</a></p></details>' + extra +
        '<footer>REAL FROZEN COMPONENTS · SIMULATED ACCEPTANCE · NO MODEL CALLS<br>'
        '<a href="https://dobeworks.com">DOBEWORKS</a> · <a href="https://lab.dobeworks.com">LAB</a></footer></main></body></html>')
