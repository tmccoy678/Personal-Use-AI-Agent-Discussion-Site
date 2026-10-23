"""Fast public arcade layered over the fixed DobeWorks/DEGS evidence record."""

from html import escape


def hidden(state, command):
    return (
        f'<input type="hidden" name="csrf" value="{state["csrf"]}">'
        f'<input type="hidden" name="scenario" value="{state["scenario"]}">'
        f'<input type="hidden" name="command" value="{command}">'
    )


def render(state, voice, reply, question, extra=""):
    report = state["report"]
    check = report.get("notation_check") if report else None
    fixed = check is not None and check["result"] == "PASS"
    accepted = "05" in state["completed"]
    launched = state["launched"]
    flight_active = state.get("flight_active", False)
    bypassed = state["counterfactual"] and not fixed

    def form(command, label, css="game-button", form_id=""):
        identifier = f' id="{form_id}"' if form_id else ""
        return (
            f'<form action="/" method="post"{identifier}>{hidden(state, command)}'
            f'<button class="{css}">{escape(label)}</button></form>'
        )

    phase = "scan"
    step = 0
    game = scan_game(state)
    if check and not fixed:
        phase = "lost" if bypassed else "blocked"
        step = 1
        game = loss_game(form) if bypassed else blocked_game(state, form)
    if fixed:
        phase = "review"
        step = 2
        game = review_game(form)
    if accepted:
        phase = "flight" if flight_active else "accepted"
        step = 3
        game = flight_game(state) if flight_active else accepted_game(form)
    if launched:
        phase = "won"
        step = 4
        game = won_game(form)

    progress = "".join(
        f'<span class="{"done" if number <= step else "active" if number == step + 1 else ""}">{label}</span>'
        for number, label in enumerate(("FIND", "CARRY", "FIX", "FLY"), start=1)
    )
    optional = (
        '<details class="source-drawer"><summary>SOURCES + ACCESS</summary>'
        '<p>Zariner is an original arcade game inspired by the handoff lesson in '
        '<a href="https://science.nasa.gov/mission/mariner-1/">NASA’s Mariner 1 account</a>. '
        'The game uses an original note and an exact supplied-reference check.</p>'
        '<p><a href="/evidence">RECORDED INPUTS + OUTPUTS</a> · '
        '<a href="/package">INSPECT THE NOTE</a> · <a href="/sources">FROZEN SOURCE IDENTITIES</a></p>'
        '</details>'
    )
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>DobeWorks · Save the Signal</title>'
        '<link rel="icon" type="image/png" sizes="16x16" href="/dobeworks-favicon-015c1a2f70b6-16.png">'
        '<link rel="icon" type="image/png" sizes="32x32" href="/dobeworks-favicon-45fd62c64976-32.png">'
        '<link rel="stylesheet" href="/stage.css"><script src="/stage-game.js" defer></script></head>'
        '<body><main class="arcade-main">'
        '<header class="arcade-header"><div class="wordmark">D O B E W O R K S</div>'
        '<div class="game-name">ZARINER · SAVE THE SIGNAL</div>'
        f'<div class="voice">“{escape(voice["text"])}” · {escape(voice["attribution"])}</div></header>'
        f'<nav class="game-progress" aria-label="Mission progress">{progress}</nav>'
        f'{extra}<section class="game-shell phase-{phase}" data-game-phase="{phase}">{game}</section>'
        f'{optional}<footer>ARCADE MISSION · REAL FROZEN COMPONENTS<br>'
        '<a href="https://dobeworks.com">DOBEWORKS</a> · <a href="https://lab.dobeworks.com">LAB</a></footer>'
        '</main></body></html>'
    )


def scan_game(state):
    tokens = []
    for index in range(13):
        if index == 7:
            tokens.append(
                f'<form action="/" method="post" class="signal-form">{hidden(state, "lesson-start")}'
                '<button class="signal-token signal-target" aria-label="R without bar">R</button></form>'
            )
        else:
            tokens.append(
                f'<button type="button" class="signal-token signal-safe" data-signal-wrong '
                f'aria-label="R bar, position {index + 1}"><span>R</span></button>'
            )
    return (
        '<div class="game-panel scan-panel" data-scan-game data-seconds="7">'
        '<div class="game-kicker">ZARINER 1 · GUIDANCE STRIP</div>'
        '<h1>FIND R WITHOUT BAR</h1>'
        '<div class="scan-head"><output class="game-status" aria-live="polite" data-game-status>7</output>'
        '<button type="button" class="quiet-button" data-no-timer>NO TIMER</button></div>'
        f'<div class="signal-window"><div class="signal-track">{"".join(tokens)}</div></div>'
        '<button type="button" class="game-button scan-retry" data-scan-retry hidden>RETRY</button>'
        '<noscript><p class="noscript-note">Select the only R without a bar. The target remains a normal button.</p></noscript>'
        '</div>'
    )


def blocked_game(state, form):
    repair = (
        f'<form action="/" method="post" class="repair-board" data-repair-form>{hidden(state, "lesson-fix")}'
        '<div class="retained-candidate"><small>FAILED PACKET · RETAINED</small><strong>R</strong></div>'
        '<div class="repair-target" data-repair-target tabindex="0" role="button" aria-label="Apply bar to R">'
        '<small>CORRECT THIS</small><strong>R</strong></div>'
        '<button type="button" class="bar-tool" data-bar-tool aria-pressed="false">━</button>'
        '<button type="submit" class="game-button apply-bar">APPLY BAR</button></form>'
    )
    return (
        '<div class="game-panel"><div class="game-kicker">WARNING FOUND</div><h1>GATE BLOCKED</h1>'
        '<div class="handoff-run" aria-label="Warning-bearing work enters the DobeWorks staging dock and stops at the DEGS gate">'
        '<div class="conveyor"><div class="work-packet">WORK<span class="warning-tag">WARNING</span></div></div>'
        '<div class="dock"><small>DOBEWORKS</small><strong>WORK STAGED</strong></div>'
        '<div class="degs-gate"><small>DEGS</small><i></i><strong>BLOCKED</strong></div></div>'
        '<div class="micro-sequence" aria-live="polite"><span>WARNING FOUND</span><span>WORK STAGED</span><span>GATE BLOCKED</span></div>'
        f'{repair}<div class="danger-choice">{form("lesson-bypass", "DROP WARNING", "quiet-button danger")}</div>'
        '</div>'
    )


def loss_game(form):
    return (
        '<div class="game-panel loss-panel"><div class="game-kicker">WARNING DROPPED</div><h1>MISSION LOST</h1>'
        '<div class="loss-sky" aria-label="Fictional trajectory veers and Range Safety closes the run">'
        '<div class="lost-packet">WORK</div><div class="veer-line"></div><div class="lost-rocket">▲</div>'
        '<div class="range-line">RANGE SAFETY</div></div>'
        '<div class="loss-code">RANGE SAFETY · RUN CLOSED</div>'
        f'{form("lesson-recover", "RETRY", "game-button")}'
        '<details class="history-mini"><summary>HISTORICAL INSPIRATION</summary><p>The Range Safety Officer destroyed '
        'Mariner 1 at T+294.5 seconds after its trajectory became unsafe. NASA identifies both a guidance-antenna '
        'fault and an omitted overbar. This is a teaching reconstruction, not a replay.</p>'
        '<a href="https://science.nasa.gov/mission/mariner-1/">NASA SOURCE</a></details></div>'
    )


def review_game(form):
    return (
        '<div class="game-panel"><div class="game-kicker">FAULT REPAIRED</div><h1>REVIEW THE FIX</h1>'
        '<div class="candidate-pair"><div class="candidate failed"><small>FAILED · RETAINED</small><strong>R</strong></div>'
        '<div class="candidate passed"><small>CORRECTED · PASS</small><strong class="barred">R</strong></div></div>'
        '<div class="ready-gate"><span>DOBEWORKS · STAGED</span><i></i><span>DEGS · READY</span></div>'
        f'{form("accept", "ACCEPT", "game-button accept-button")}</div>'
    )


def accepted_game(form):
    return (
        '<div class="game-panel accepted-panel"><div class="game-kicker">HUMAN ACCEPTED</div><h1>YOU HOLD THE KEY</h1>'
        '<div class="launch-key" aria-hidden="true"><span>HUMAN</span><i></i><span>LAUNCH</span></div>'
        f'{form("lesson-flight", "LAUNCH", "game-button launch-button")}</div>'
    )


def flight_game(state):
    return (
        '<div class="game-panel flight-panel" data-flight-game data-duration="12">'
        '<div class="game-kicker">ZARINER 2 · VENUS RUN</div><h1>HOLD TO CLIMB</h1>'
        '<div class="flight-hud"><output data-flight-status aria-live="polite">READY</output>'
        '<output data-flight-time>12.0</output></div>'
        '<div class="flight-field" data-flight-field tabindex="0" aria-label="One-input flight field">'
        '<div class="stars"></div><div class="flight-rocket" data-flight-rocket>▲</div>'
        '<div class="telemetry-gate" data-gate="1" style="--gap:32;--top:14%;--bottom:50%;--gate-index:1"><i></i><b></b><span>1</span></div>'
        '<div class="telemetry-gate" data-gate="2" style="--gap:67;--top:49%;--bottom:15%;--gate-index:2"><i></i><b></b><span>2</span></div>'
        '<div class="telemetry-gate" data-gate="3" style="--gap:43;--top:25%;--bottom:39%;--gate-index:3"><i></i><b></b><span>3</span></div>'
        '<div class="venus">VENUS</div></div>'
        '<button type="button" class="game-button thrust-button" data-flight-control>START FLIGHT</button>'
        f'<form action="/" method="post" class="flight-complete" data-flight-complete>{hidden(state, "lesson-win")}'
        '<button class="quiet-button no-script-flight">COMPLETE ACCESSIBLE FLIGHT</button></form></div>'
    )


def won_game(form):
    return (
        '<div class="game-panel win-panel"><div class="game-kicker">VENUS REACHED</div><h1>STOP FIXED. SIGNAL SAVED.</h1>'
        '<div class="final-score"><small>SCORE</small><strong data-final-score>2000</strong></div>'
        '<div class="win-actions">'
        f'{form("lesson-reflight", "REPLAY FLIGHT", "game-button")}{form("00", "REPLAY MISSION", "quiet-button")}</div>'
        '<details class="post-win"><summary>HOW IT WORKED</summary><ol>'
        '<li><b>FIND</b><span>A named check found the missing mark.</span></li>'
        '<li><b>STAGE</b><span>DobeWorks kept completed work unaccepted and unpromoted.</span></li>'
        '<li><b>CARRY</b><span>The handoff record kept the warning attached.</span></li>'
        '<li><b>ENFORCE</b><span>DEGS kept the gate closed until the warning was resolved.</span></li>'
        '</ol></details>'
        '<details class="post-win"><summary>HISTORICAL INSPIRATION</summary><p>Thirty-six days after Mariner 1, '
        'Mariner 2 launched and became humanity’s first successful planetary science mission.</p>'
        '<p><a href="https://science.nasa.gov/mission/mariner-2/">NASA ACCOUNT</a> · '
        '<a href="https://www.jpl.nasa.gov/videos/mariner-2-launches/">JPL LAUNCH FILM</a></p></details>'
        '<details class="post-win terminal-post"><summary>OPEN TERMINAL</summary>'
        '<div class="terminal-tape" aria-label="Compact mission terminal">'
        '<p>PLEASE GO ON. &gt;</p><dl>'
        '<div><dt>&gt; FIND R-BAR</dt><dd>WARNING FOUND</dd></div>'
        '<div><dt>&gt; STAGE WORK</dt><dd>UNACCEPTED</dd></div>'
        '<div><dt>&gt; CARRY WARNING</dt><dd>GATE BLOCKED</dd></div>'
        '<div><dt>&gt; ACCEPT FIX</dt><dd>LAUNCH READY</dd></div>'
        '</dl></div></details></div>'
    )
