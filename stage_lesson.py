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

    title = "AN AGENT CAN FINISH. THE WORK MAY STILL NEED TO STOP."
    explanation = "A required overbar disappeared from a guidance note. Follow what happens when the completed work reaches the next stage."
    action = form("lesson-start", "HAND OFF THE WORK")
    finding, gate, acceptance = "Awaiting the handoff", "Awaiting the record", "Not requested"
    if check:
        title = "THE AGENT FINISHED. THE OPEN ISSUE SURVIVED." if not fixed else "THE ISSUE IS CLOSED. ACCEPTANCE IS STILL YOUR DECISION."
        explanation = ("DobeWorks completed its bounded task and kept the result staged. The adapter carried the unresolved notation finding into DEGS. The next action stays held."
                       if not fixed else "The corrected note passes its check. The same warning now records consistent closure and an evidence reference. DEGS permits readiness; separate acceptance is still required.")
        finding = "RESOLVED · check evidence retained" if fixed else "UNRESOLVED · required overbar missing"
        gate = report["degs"]["decision"]
        acceptance = "Awaiting your demo acceptance" if fixed else "Held while the issue is open"
        action = form("accept", "ACCEPT THIS DEMO HANDOFF") if fixed else form("lesson-fix", "RESTORE THE BAR AND RECHECK")
    if accepted:
        title = "A COMPLETED TASK BECAME A REVIEWED HANDOFF."
        explanation = "The original finding remains in the record. Its correction and check evidence closed the issue. Your separate demo acceptance allowed the simulated handoff to proceed."
        acceptance = "RECORDED · for this demonstration"
        action = form("00", "REPLAY THE DEMONSTRATION")

    cards = '<li><small>AGENT / DOBEWORKS</small><strong>Work awaits the handoff</strong></li>'
    if report:
        cards = ('<li><small>DOBEWORKS · BOUNDED WORK</small><strong>COMPLETED · STILL STAGED</strong>'
                 '<p>One inventory attempt. No automatic retry. No promotion.</p></li>')
    cards += (f'<li><small>FINDING CARRIED TO THE NEXT STAGE</small><strong>{finding}</strong></li>'
              f'<li><small>DEGS · READINESS CHECK</small><strong>{gate}</strong><p>Checks the supplied engineering record against its rules.</p></li>'
              f'<li><small>SEPARATE ACCEPTANCE</small><strong>{acceptance}</strong></li>')
    comparison = ""
    if state.get("comparison") and report:
        original = state["case_history"][0] if fixed and state["case_history"] else report
        trial = original["translation_comparison"]
        comparison = ('<section class="comparison"><h2>SAME WORK. DIFFERENT HANDOFF RECORD.</h2>'
            '<div><p><b>STOP PRESERVED</b><br>Worker finished. Warning remains.<br>DEGS: '
            + escape(original["degs"]["decision"]) + '</p><p><b>COMPLETION-ONLY SUMMARY</b><br>Worker finished. Warning was dropped.<br>DEGS: '
            + escape(trial["completion_only_decision"]["decision"]) + '</p></div>'
            '<p>The note is identical in both evaluations. A gate can enforce only the record it receives. '
            'Preserving the stop condition is part of the handoff contract. This fixed comparison performs no execution or promotion.</p></section>')
    optional = form("lesson-compare", "SEE WHAT A ‘DONE’ SUMMARY LOSES", True) if check else ""
    if accepted:
        optional += form("lesson-mission", "OPEN THE OPTIONAL ROCKET WORKFLOW", True)
    lesson_step = "3 / 3 · ACCEPTED" if accepted else "2 / 3 · CORRECTED" if fixed else "1 / 3 · HELD" if check else "A SHORT INTERACTIVE DEMO"
    return ('''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DobeWorks · The Handoff</title><link rel="stylesheet" href="/stage.css"></head><body><main>
<header><div class="wordmark">D O B E W O R K S</div>'''
        f'<div class="voice">“{escape(voice["text"])}”</div><div class="attribution">{escape(voice["attribution"])}</div></header>'
        f'<p class="station">MISSION 001 · THE HANDOFF · {lesson_step}</p><div class="lesson-layout"><section>'
        f'<h1 class="lesson-title">{title}</h1><p class="lesson-copy">{explanation}</p>'
        '<div class="notation"><div><small>REQUIRED NOTE</small><span aria-label="R bar" class="bar">R</span></div>'
        f'<div><small>RECEIVED NOTE</small><span {"class=bar aria-label=R-bar" if fixed else "aria-label=R"}>R</span></div></div>'
        f'<div class="lesson-actions">{action}{optional}</div>{comparison}'
        '<p class="lesson-takeaway">The protected handoff carries more than the file: what is unresolved, what evidence closes it, and which acceptance is still required.</p>'
        f'<div class="conversation"><form action="/" method="post" class="command"><input type="hidden" name="csrf" value="{state["csrf"]}">'
        f'<input type="hidden" name="scenario" value="{state["scenario"]}"><label for="command">PLEASE GO ON. &gt;</label>'
        '<input id="command" name="command" maxlength="160" placeholder="Ask about the handoff" autocomplete="off"><button class="enter">RETURN</button></form>'
        f'<p class="question">{escape(question)}</p><p class="reply">{escape(reply)}</p></div></section>'
        f'<aside class="lesson-flow"><h2>THE STOP MUST SURVIVE</h2><ol>{cards}</ol></aside></div>'
        '<details class="lesson-info"><summary>INFORMATION &amp; EVIDENCE</summary>'
        '<p>NASA describes an omitted overbar and a guidance antenna fault in '
        '<a href="https://science.nasa.gov/mission/mariner-1/">Mariner 1</a>. This is a teaching reconstruction of notation loss, not recovered flight code or a flight model.</p>'
        '<p>The notation check compares this note with its supplied reference. DobeWorks stages a synthetic inventory; DEGS evaluates the translated record. '
        'The underlying Worker result remains COMPLETED_UNACCEPTED and unpromoted. The final step records your acceptance within this public simulation.</p>'
        '<p>The comparison uses the same note and the real gate, changing only the warning field. It is a fixed illustration, not a completed live-agent study or a guarantee that every unsafe action is prevented.</p>'
        '<p><a href="/evidence">RECORDED INPUTS &amp; OUTPUTS</a> · <a href="/package">INSPECT THE NOTE AND CONTEXT</a> · <a href="/sources">FROZEN SOURCE IDENTITIES</a></p></details>' + extra +
        '<footer>REAL FROZEN COMPONENTS · SIMULATED ACCEPTANCE · NO MODEL CALLS<br>'
        '<a href="https://dobeworks.com">DOBEWORKS</a> · <a href="https://lab.dobeworks.com">LAB</a></footer></main></body></html>')
