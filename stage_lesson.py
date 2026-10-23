"""Plain-language, server-rendered front door for the fixed handoff records."""
from html import escape


def render(state, voice, reply, question, extra=""):
    report = state["report"]
    check = report.get("notation_check") if report else None
    fixed = check is not None and check["result"] == "PASS"
    accepted = "05" in state["completed"]
    launched = state["launched"]
    bypassed = state["counterfactual"] and not fixed

    def form(command, label, secondary=False):
        return (f'<form action="/" method="post"><input type="hidden" name="csrf" value="{state["csrf"]}">'
                f'<input type="hidden" name="scenario" value="{state["scenario"]}">'
                f'<button class="enter {"secondary" if secondary else ""}" name="command" value="{command}">{label}</button></form>')

    document_title = "DobeWorks · The Finished Task"
    title = "THE TASK SAYS FINISHED. ONE WARNING IS STILL OPEN."
    explanation = ("The left copy is correct. The right copy lost one mark. What will reach the next team: "
                   "only the finished work, or the reason to stop too?")
    actions = form("lesson-start", "SEND THE FINISHED WORK")
    step = 0
    step_label = "MOVE 0 OF 4 · READY TO HAND OFF"
    rocket_label = "FINISHED WORK ON THE PAD"
    phase = "ready"
    error_status = "OPEN · R-BAR BECAME R"
    work_status = "CLAIMED FINISHED"
    launch_status = "LOCKED"
    checker = "Waiting for the two copies"
    dobe = "Waiting for completed work"
    degs = "Waiting for a handoff record"
    human = "Not requested"
    historical = ""
    successor = ""

    if check and not fixed:
        document_title = "DobeWorks · Launch Stopped"
        title = "WORK FINISHED. LAUNCH STOPPED."
        explanation = ("The completion message arrived, but it did not erase the known error. The warning crossed the handoff "
                       "with the work, so the next step stayed closed.")
        actions = (form("lesson-fix", "FIX THE ERROR")
                   + form("lesson-bypass", "TRY TO IGNORE IT", True))
        step = 1
        step_label = "MOVE 1 OF 4 · STOP SAVED"
        rocket_label = "BLOCKED BEFORE LAUNCH"
        phase = "held"
        error_status = "OPEN · STILL ATTACHED"
        work_status = "FINISHED"
        launch_status = "BLOCKED"
        checker = "FAIL · required R-bar, received R"
        dobe = "FINISHED · staged · warning still attached"
        degs = "BLOCKED · open finding"
        human = "Held while the error is open"

    if bypassed:
        document_title = "DobeWorks · Why the Stop Matters"
        title = "YOU TRIED TO IGNORE IT. THE GATE STILL SAYS STOP."
        explanation = ("This choice reveals the historical consequence; it does not secretly clear the demo gate or launch a vehicle. "
                       "The recorded error is still open. Fix it to continue.")
        actions = form("lesson-fix", "FIX IT AND TRY AGAIN")
        rocket_label = "IGNORE ATTEMPT · STILL BLOCKED"
        phase = "bypassed"
        historical = ('<section class="history-alert" aria-labelledby="mariner-one-title">'
            '<p class="eyebrow">THE REAL MARINER 1 OUTCOME</p>'
            '<h2 id="mariner-one-title">The rocket veered off course and was destroyed for safety at T+294.5 seconds.</h2>'
            '<p>NASA identifies two problems: a guidance-antenna fault and a software error involving an omitted overbar on R. '
            'It was not a missing hyphen. The real team did not use this demo and did not make the choice shown above. '
            'DobeWorks and DEGS did not exist in 1962.</p><p><a href="https://science.nasa.gov/mission/mariner-1/">READ NASA\'S MARINER 1 ACCOUNT</a></p></section>')

    if fixed:
        document_title = "DobeWorks · Human Review Required"
        title = "ERROR FIXED. LAUNCH STILL NEEDS A HUMAN."
        explanation = ("The new copy passes the same check. The failed copy, the repair, and the evidence stayed together. "
                       "Now decide whether to accept that reviewed handoff.")
        actions = form("accept", "I REVIEWED IT · ACCEPT")
        step = 2
        step_label = "MOVE 2 OF 4 · ERROR CLOSED"
        rocket_label = "CHECKS PASS · YOUR REVIEW REQUIRED"
        phase = "corrected"
        error_status = "CLOSED · EVIDENCE ATTACHED"
        work_status = "FINISHED"
        launch_status = "AWAITING YOUR REVIEW"
        checker = "PASS · R-bar restored"
        dobe = "FINISHED · failed and corrected copies retained"
        degs = "READY · no supplied stop remains open"
        human = "Awaiting your acceptance"

    if accepted:
        document_title = "DobeWorks · Your Launch Decision"
        title = "YOU REVIEWED THE EVIDENCE. LAUNCH IS NOW YOUR DECISION."
        explanation = ("The error is closed, the stop record is intact, and you accepted the corrected handoff. "
                       "The fictional rocket is ready for your final move.")
        actions = form("lesson-launch", "LAUNCH THE SUCCESSFUL SIMULATION")
        step = 3
        step_label = "MOVE 3 OF 4 · REVIEW ACCEPTED"
        rocket_label = "READY FOR YOUR LAUNCH COMMAND"
        phase = "accepted"
        error_status = "CLOSED · EVIDENCE ATTACHED"
        work_status = "ACCEPTED"
        launch_status = "READY"
        human = "ACCEPTED · for this demonstration"

    if launched:
        document_title = "DobeWorks · Mission Complete"
        title = "THE ROCKET CLEARS THE PAD. THE STOP WAS FIXED, NOT FORGOTTEN."
        explanation = ("You did not win by deleting the warning. You won by carrying it forward, fixing the error, "
                       "preserving the evidence, and making acceptance a separate decision.")
        actions = form("00", "PLAY AGAIN")
        step = 4
        step_label = "MOVE 4 OF 4 · MISSION COMPLETE"
        rocket_label = "SUCCESSFUL FICTIONAL FLIGHT"
        phase = "launched"
        error_status = "CLOSED · HISTORY PRESERVED"
        work_status = "ACCEPTED"
        launch_status = "SUCCESS"
        successor = ('<section class="successor-archive" aria-labelledby="mariner-two-title">'
            '<p class="eyebrow">THE REAL MARINER 2 FOLLOW-ON</p>'
            '<h2 id="mariner-two-title">Thirty-six days later, Mariner 2 launched and became humanity\'s first successful planetary science mission.</h2>'
            '<p>It completed a course correction, flew by Venus, and returned data during a 42-minute scan. This game is not a replay '
            'of that flight and does not call the entire spacecraft flawless.</p><p>'
            '<a href="https://science.nasa.gov/mission/mariner-2/">READ NASA\'S MARINER 2 ACCOUNT</a> · '
            '<a href="https://www.jpl.nasa.gov/videos/mariner-2-launches/">WATCH JPL\'S LAUNCH FILM</a></p></section>')

    segments = "".join(
        f'<span class="arcade-segment {"is-complete" if number <= step else ""}" aria-hidden="true"></span>'
        for number in range(1, 5)
    )
    mission_meter = (f'<div class="arcade-progress" role="progressbar" aria-label="{escape(step_label)}" '
                     f'aria-valuemin="0" aria-valuemax="4" aria-valuenow="{step}"><div>{segments}</div>'
                     f'<p>{escape(step_label)}</p></div>')
    status_board = ('<dl class="mission-status" aria-label="Current mission status">'
        f'<div><dt>ERROR</dt><dd>{escape(error_status)}</dd></div>'
        f'<div><dt>WORK</dt><dd>{escape(work_status)}</dd></div>'
        f'<div><dt>LAUNCH</dt><dd>{escape(launch_status)}</dd></div></dl>')
    received_label = "CORRECTED COPY" if fixed else "AI RECEIVED"

    reveal = ""
    contrast = ""
    if check:
        reveal_title = "THE COMPLETION MESSAGE DID NOT ERASE THE ERROR."
        cards = (f'<article><small>1</small><h3>THE CHECK FOUND IT</h3><p>{escape(checker)}</p></article>'
                 f'<article><small>2</small><h3>DOBEWORKS KEPT IT</h3><p>{escape(dobe)}</p></article>'
                 f'<article><small>3</small><h3>DEGS STOPPED IT</h3><p>{escape(degs)}</p></article>')
        if fixed:
            reveal_title = "THE REPAIR CHANGED THE RESULT; IT DID NOT ERASE THE FIRST FAILURE."
            cards = (f'<article><small>1</small><h3>THE CHECK VERIFIED IT</h3><p>{escape(checker)}</p></article>'
                     f'<article><small>2</small><h3>DOBEWORKS KEPT BOTH</h3><p>{escape(dobe)}</p></article>'
                     f'<article><small>3</small><h3>DEGS OPENED THE GATE</h3><p>{escape(degs)}</p></article>')
        reveal = (f'<section class="lesson-reveal" aria-labelledby="reveal-title"><p class="eyebrow">WHAT JUST HAPPENED</p>'
                  f'<h2 id="reveal-title">{reveal_title}</h2><div>{cards}</div>'
                  f'<p class="human-line"><b>YOUR PART:</b> {escape(human)}.</p></section>')
        if not fixed:
            kept_decision = report["degs"]["decision"]
            lost_decision = report["translation_comparison"]["completion_only_decision"]["decision"]
            contrast = ('<section class="controlled-comparison" aria-labelledby="comparison-title">'
                '<p class="eyebrow">THE WHOLE POINT</p>'
                '<h2 id="comparison-title">SAME FINISHED WORK. DIFFERENT HANDOFF RECORD.</h2><div>'
                f'<article><small>WARNING TRAVELS</small><strong>{escape(kept_decision)}</strong>'
                '<p>The known error reaches the next gate, so work stops.</p></article>'
                f'<article><small>WARNING DISAPPEARS</small><strong>{escape(lost_decision)}</strong>'
                '<p>A read-only comparison removes only the warning field. The gate no longer sees the reason to stop.</p></article>'
                '</div><p>Nothing launched in this comparison. It shows why preserving the warning changes the next decision.</p></section>')

    mechanism = ""
    applications = ""
    unlocked = ""
    guide = ""
    if launched:
        mechanism = ('<section class="plain-mechanism" aria-labelledby="mechanism-title"><p class="eyebrow">NOW NAME THE MACHINERY</p>'
            '<h2 id="mechanism-title">DobeWorks carries the reason to stop. DEGS keeps the next step closed until that reason is resolved.</h2><ol>'
            '<li><b>FIND</b><span>A named check or person records a problem.</span></li>'
            '<li><b>CARRY</b><span>DobeWorks keeps the finding attached when work moves.</span></li>'
            '<li><b>STOP</b><span>DEGS refuses the next step while the finding is open.</span></li>'
            '<li><b>PROVE</b><span>Repair evidence closes it; human acceptance stays separate.</span></li>'
            '</ol></section>')
        applications = ('<section class="applications" aria-labelledby="applications-title"><p class="eyebrow">THE SAME RULE ANYWHERE WORK MOVES</p>'
            '<h2 id="applications-title">The named check finds the problem. DobeWorks and DEGS keep it from disappearing.</h2><div>'
            '<article><small>DOI RESOLVER</small><h3>Faulty citation</h3><p>A resolver flags a DOI that does not lead to the claimed paper. '
            'The finding travels with the draft until the source is verified.</p></article>'
            '<article><small>CONTEXT CHECK</small><h3>New AI window</h3><p>A comparison flags a required instruction missing from a handoff. '
            'The next agent receives the missing requirement, not just the finished output.</p></article>'
            '<article><small>TEST OR REVIEW</small><h3>Safety-critical code</h3><p>A test, hazard review, or person finds a defect. '
            'Readiness stays blocked while that finding remains open.</p></article>'
            '</div><p class="application-limit">This exhibit demonstrates preservation and enforcement with one fixed notation check. '
            'It is not a universal DOI validator, context oracle, or flight-certification system.</p></section>')
        unlocked = ('<section class="mission-unlocked"><p class="eyebrow">NEW LEVEL UNLOCKED</p>'
            '<h2>Want every receipt, source identity, frozen engine test, and decision?</h2>'
            '<p>The full engineering station turns this four-move lesson into an eight-program inspection desk.</p>'
            f'{form("lesson-mission", "OPEN THE FULL ENGINEERING STATION")}</section>')
        guide = (f'<div class="conversation guide"><form action="/" method="post" class="command">'
            f'<input type="hidden" name="csrf" value="{state["csrf"]}"><input type="hidden" name="scenario" value="{state["scenario"]}">'
            '<label for="command">RULE-BASED GUIDE · ASK A QUESTION &gt;</label>'
            '<input id="command" name="command" maxlength="160" placeholder="What is DobeWorks?" autocomplete="off"><button class="enter">RETURN</button></form>'
            '<p class="guide-prompts">TRY: WHAT IS DOBEWORKS? · WHAT IS DEGS? · WHY IS IT BLOCKED?</p>'
            f'<p class="question">{escape(question)}</p><p class="reply" role="status" aria-live="polite">{escape(reply)}</p></div>')

    return ('''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'''
        f'<title>{document_title}</title><link rel="icon" type="image/png" sizes="16x16" href="/dobeworks-favicon-015c1a2f70b6-16.png">'
        '<link rel="icon" type="image/png" sizes="32x32" href="/dobeworks-favicon-45fd62c64976-32.png"><link rel="stylesheet" href="/stage.css"></head><body><main>'
        '<header><div class="wordmark">D O B E W O R K S</div>'
        f'<div class="voice">“{escape(voice["text"])}”</div><div class="attribution">{escape(voice["attribution"])}</div></header>'
        '<p class="station">MARINER 1 TEACHING RECONSTRUCTION · ONE MARK · FOUR MOVES · TWO ENDINGS</p>'
        f'<section class="arcade-stage phase-{phase}" aria-label="Mission arcade"><div class="arcade-copy">{mission_meter}'
        f'<h1 class="lesson-title">{title}</h1><p class="lesson-copy">{explanation}</p>{status_board}'
        '<div class="notation"><div><small>CORRECT REFERENCE</small><span aria-label="R bar" class="bar">R</span></div>'
        f'<div><small>{received_label}</small><span {"class=bar aria-label=R-bar" if fixed else "aria-label=R"}>R</span></div></div>'
        f'<div class="lesson-actions">{actions}</div></div><div class="arcade-vehicle">'
        '<pre class="lesson-rocket" aria-label="Text rocket carrying the DobeWorks logo">'
        '       /\\\n      /  \\\n     /    \\\n     | DW |\n     |----|\n     |    |\n    /|    |\\\n   /_|____|_\\\n      /__\\\n'
        '<img class="lesson-rocket-logo" src="/dobeworks-logo-a56f5aab2111.svg" alt="DobeWorks logo" width="40" height="40"></pre>'
        f'<p class="arcade-pad">────────────<br>{escape(rocket_label)}</p></div></section>{historical}{successor}{reveal}{contrast}'
        f'{mechanism}{unlocked}{applications}{guide}'
        '<details class="lesson-info"><summary>SOURCES, LIMITS &amp; EVIDENCE</summary>'
        '<p>NASA describes a guidance-antenna fault and an omitted overbar in <a href="https://science.nasa.gov/mission/mariner-1/">Mariner 1</a>. '
        'This site uses an original note and exact supplied-reference check; it does not contain historical guidance code or model a flight trajectory.</p>'
        '<p>The DobeWorks Worker performs its fixed synthetic inventory and remains COMPLETED_UNACCEPTED with promotion NOT_PERFORMED. '
        'DEGS evaluates the adapted read-only warning record. The comparison never executes or promotes work.</p>'
        '<p><a href="/evidence">RECORDED INPUTS &amp; OUTPUTS</a> · <a href="/package">INSPECT THE NOTE AND CONTEXT</a> · '
        '<a href="/sources">FROZEN SOURCE IDENTITIES</a></p></details>' + extra +
        '<footer><img class="footer-logo" src="/dobeworks-logo-a56f5aab2111.svg" alt="DobeWorks logo — Marie surrounded by hearts" width="80" height="80" loading="lazy">'
        'REAL FROZEN COMPONENTS · FICTIONAL MISSION · NO MODEL CALLS<br>'
        '<a href="https://doi.org/10.1145/365153.365168">ELIZA, WEIZENBAUM 1966</a> · '
        '<a href="https://catalog.afi.com/Film/23505-THE-FORBIN-PROJECT">COLOSSUS: THE FORBIN PROJECT, 1970</a><br>'
        '<a href="https://dobeworks.com">DOBEWORKS</a> · <a href="https://lab.dobeworks.com">LAB</a></footer></main></body></html>')
