(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const csrf = $('meta[name="stage-csrf"]').content;
  const selectScreen = $('[data-screen="select"]');
  const intakeScreen = $('[data-screen="intake"]');
  const missionScreen = $('[data-screen="mission"]');
  let snapshot = null;
  let busy = false;
  let selectedReceipts = new Set();
  let findingMode = null;
  let lastAutomaticLine = '';
  let choosing = false;
  let selectedMode = null;
  let intakeRunId = null;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  async function request(path, payload) {
    const options = payload === undefined ? {} : {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({csrf, ...payload}),
    };
    const response = await fetch(path, options);
    let body = {};
    try { body = await response.json(); } catch (_) { /* status below is enough */ }
    if (!response.ok) throw new Error(body.error || `REQUEST STOPPED · ${response.status}`);
    return body;
  }

  function shortCandidate(id) {
    return id ? id.split('-').at(-1) : '—';
  }

  function shortHash(value) {
    return value ? value.slice(0, 10).toUpperCase() : '—';
  }

  function correctionLabel(value) {
    const number = value / 100;
    if (number === 0) return '0.00';
    return `${number > 0 ? '+' : '−'}${Math.abs(number).toFixed(2)}`;
  }

  function elapsedLabel(seconds) {
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  }

  function addTerminal(speaker, text, automatic = false) {
    const key = `${speaker}|${text}`;
    if (automatic && key === lastAutomaticLine) return;
    if (automatic) lastAutomaticLine = key;
    $('[data-terminal-speaker]').textContent = speaker;
    const line = element('p');
    line.append(element('span', '', speaker), document.createTextNode(` ${text}`));
    const output = $('[data-terminal-output]');
    output.append(line);
    while (output.children.length > 7) output.firstElementChild.remove();
    output.scrollTop = output.scrollHeight;
  }

  function acceptSnapshot(next) {
    const incoming = next.run;
    const current = snapshot && snapshot.run;
    if (current && incoming && current.run_id === incoming.run_id && incoming.version < current.version) return;
    snapshot = next;
    if (incoming) {
      const firstSnapshotForRun = !current || current.run_id !== incoming.run_id;
      const available = new Set(Object.keys(incoming.receipts));
      const record = incoming.record_id ? incoming.records[incoming.record_id] : null;
      if (firstSnapshotForRun && record) {
        selectedReceipts = new Set(record.receipts.map((receipt) => receipt.id));
        findingMode = incoming.gate?.adapter_classification === 'FINDING_OMITTED' ? 'omit' : 'carry';
      } else {
        selectedReceipts = new Set([...selectedReceipts].filter((id) => available.has(id)));
      }
    }
    if (next.terminal) addTerminal(next.terminal.speaker, next.terminal.text, true);
    render();
  }

  async function start(difficulty, mode = selectedMode) {
    if (busy || !mode) return;
    busy = true;
    try {
      selectedReceipts.clear();
      findingMode = null;
      lastAutomaticLine = '';
      const next = await request('/api/launch/new', {difficulty, mode});
      choosing = false;
      intakeRunId = next.run.run_id;
      acceptSnapshot(next);
    } catch (error) {
      addTerminal('CONTROL', error.message);
    } finally {
      busy = false;
      render();
    }
  }

  async function command(action, choices = {}) {
    if (busy || !snapshot?.run) return;
    busy = true;
    const before = snapshot.run;
    try {
      const next = await request('/api/launch/action', {
        run_id: before.run_id,
        version: before.version,
        action,
        choices,
      });
      if (action === 'check') {
        const previous = new Set(Object.keys(before.receipts));
        const newest = Object.keys(next.run.receipts).find((id) => !previous.has(id));
        if (newest) selectedReceipts.add(newest);
        findingMode = null;
      }
      if (['prompt', 'select'].includes(action)) {
        selectedReceipts.clear();
        findingMode = null;
      }
      if (action === 'retry') {
        selectedReceipts.clear();
        findingMode = null;
        lastAutomaticLine = '';
      }
      acceptSnapshot(next);
    } catch (error) {
      addTerminal('CONTROL', error.message);
    } finally {
      busy = false;
      render();
    }
  }

  function showSelection(mode = snapshot?.run?.mode || selectedMode) {
    choosing = true;
    selectedMode = mode;
    document.body.dataset.route = selectedMode || '';
    intakeScreen.hidden = true;
    missionScreen.hidden = true;
    selectScreen.hidden = false;
    $$('[data-mode-option]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.modeOption === selectedMode));
    });
    const governedDetails = {
      easy: ['1 CONDITION · 1 CHECK', 'ONE CHECK · FULL ASCENT'],
      medium: ['UNIT + CONDITION · 1 CHECK', 'UNIT CONVERSION'],
      hard: ['2 CLOCKS · 3 CHECKS', 'STATE + CLOCK BINDING'],
    };
    const directDetails = {
      easy: ['1 CONDITION · INSPECT BY EYE', 'NO EXECUTED CHECK'],
      medium: ['UNIT + CONDITION · INSPECT', 'NO EXECUTED CHECK'],
      hard: ['2 CLOCKS · INSPECT BY EYE', 'NO EXECUTED CHECK'],
    };
    $$('[data-start]').forEach((button) => {
      button.disabled = !selectedMode;
      const details = selectedMode === 'direct' ? directDetails[button.dataset.start] : governedDetails[button.dataset.start];
      $('[data-difficulty-detail]', button).textContent = details[0];
      $('[data-difficulty-note]', button).textContent = details[1];
    });
    $('[data-select-title]').textContent = selectedMode ? 'CHOOSE THE PACKET.' : 'CHOOSE THE CONTROL SYSTEM.';
    $('[data-select-copy]').textContent = selectedMode === 'governed'
      ? 'The check finds. DobeWorks stages. The handoff carries. DEGS enforces.'
      : selectedMode === 'direct'
        ? 'The agent output goes directly to your inspection and the vehicle.'
        : 'The same agent. The same packet. A different path to ignition.';
    (selectedMode ? $('[data-start="easy"]') : $('[data-mode-option="governed"]')).focus();
  }

  function showMission() {
    selectScreen.hidden = true;
    intakeScreen.hidden = true;
    missionScreen.hidden = false;
  }

  function showIntake(run) {
    const candidate = run.candidates[run.candidate_id];
    const direct = run.mode === 'direct';
    const speakers = {easy: 'ELIZA', medium: 'COLOSSUS', hard: 'GUARDIAN'};
    document.body.dataset.route = run.mode;
    selectScreen.hidden = true;
    missionScreen.hidden = true;
    intakeScreen.hidden = false;
    $('[data-intake-speaker]').textContent = speakers[run.difficulty];
    $('[data-intake-route-tag]').textContent = direct ? 'DIRECT ROUTE' : 'GOVERNED ROUTE';
    $('[data-intake-candidate]').textContent = shortCandidate(candidate.id);
    $('[data-intake-line]').textContent = direct
      ? 'A NEW CANDIDATE IS WAITING FOR HUMAN INSPECTION.'
      : 'A NEW CANDIDATE IS WAITING AT THE GOVERNED BOUNDARY.';
    $('[data-intake-level]').textContent = run.difficulty.toUpperCase();
    $('[data-intake-mode]').textContent = direct ? 'DIRECT' : 'DW + DEGS';
    $('[data-intake-hash]').textContent = shortHash(candidate.sha256);
    $('[data-intake-path]').dataset.route = run.mode;
    $('[data-intake-path]').setAttribute('aria-label', direct
      ? 'Agent to human to vehicle'
      : 'Agent to check bay to human to vehicle');
    $('[data-intake-receive]').textContent = `RECEIVE AGENT COPY ${shortCandidate(candidate.id)}`;
    $('[data-intake-receive]').focus();
  }

  function renderReference(run, packet) {
    $('[data-condition-title]').textContent = `MISSION CONDITION · ${run.difficulty.toUpperCase()}`;
    const list = $('[data-condition-list]');
    list.replaceChildren();
    const rows = [];
    const tLabel = (value) => `T${value < 0 ? '−' : '+'}${String(Math.abs(value)).padStart(3, '0')}`;
    packet.observations.forEach((item) => {
      const window = `${tLabel(item.valid_from_t)}–${tLabel(item.valid_through_t)}`;
      rows.push([`OBS ${item.id} · WIND`, `${correctionLabel(item.wind_cm_s)} m/s`]);
      rows.push([`OBS ${item.id} · BINDING`, `${item.config_id} · ${window}`]);
    });
    rows.push(['VEHICLE FRAME', `${packet.config} · SIGN ${packet.sign > 0 ? '+' : '−'}1`]);
    rows.push(['STEERING WINDOW', 'T+020–060']);
    rows.push(['CORRIDOR', '±500 cm']);
    rows.forEach(([term, value]) => {
      const row = element('div');
      row.append(element('dt', '', term), element('dd', '', value));
      list.append(row);
    });
  }

  function choiceButton(label, pressed, callback) {
    const button = element('button', '', label);
    button.type = 'button';
    button.setAttribute('aria-pressed', String(pressed));
    button.disabled = busy || isEnded();
    button.addEventListener('click', callback);
    return button;
  }

  function renderCandidate(run, packet) {
    const candidate = run.candidates[run.candidate_id];
    const label = shortCandidate(candidate.id);
    $('[data-candidate-id]').textContent = label;
    $('[data-candidate-label]').textContent = label;
    $('[data-candidate-hash]').textContent = shortHash(candidate.sha256);
    $('[data-correction-output]').textContent = correctionLabel(candidate.correction_cm_s);
    $('[data-candidate-config]').textContent = candidate.config_id;
    $('[data-candidate-observation]').textContent = candidate.condition_id;
    $('[data-candidate-cutoff]').textContent = candidate.cutoff_clock;
    const currentReceipts = Object.values(run.receipts).filter((item) => item.candidate_id === candidate.id);
    const checked = new Set(currentReceipts.map((item) => item.name));
    const complete = packet.checks.every((name) => checked.has(name));
    $('[data-candidate-state]').textContent = run.mode === 'direct'
      ? 'READ-ONLY · INSPECT BY EYE'
      : complete ? 'CHECK SET PRESENT' : 'RECEIVED · CHECKS OPEN';
    $('[data-stage-label]').textContent = run.mode === 'direct'
      ? 'DIRECT · NO GOVERNED RECORD'
      : run.staged_ids.includes(candidate.id) ? 'STAGED · COMPLETED_UNACCEPTED' : 'NOT STAGED';
    $('[data-acceptance-label]').textContent = run.authority ? run.authority.action : 'UNACCEPTED';

    const activePrompt = (group) => [...candidate.prompt_history].reverse().find((id) =>
      packet.prompts.some((prompt) => prompt.id === id && prompt.group === group));
    const promptButtons = (group) => packet.prompts.filter((prompt) => prompt.group === group).map((prompt) =>
      choiceButton(prompt.label, activePrompt(group) === prompt.id, () => command('prompt', {prompt_id: prompt.id})));

    const values = $('[data-value-bank]');
    values.replaceChildren(...promptButtons('correction'));

    const conditionLabel = $('[data-condition-label]');
    const conditionBank = $('[data-condition-bank]');
    const showConditions = packet.prompts.some((prompt) => prompt.group === 'observation');
    conditionLabel.hidden = !showConditions;
    conditionBank.hidden = !showConditions;
    conditionBank.replaceChildren(...promptButtons('observation'));

    const cutoffLabel = $('[data-cutoff-label]');
    const cutoffBank = $('[data-cutoff-bank]');
    const showCutoff = packet.prompts.some((prompt) => prompt.group === 'cutoff');
    cutoffLabel.hidden = !showCutoff;
    cutoffBank.hidden = !showCutoff;
    cutoffBank.replaceChildren(...promptButtons('cutoff'));
  }

  function renderReceipts(run, packet) {
    const rack = $('[data-receipt-rack]');
    const receipts = Object.values(run.receipts);
    if (!receipts.length) {
      rack.replaceChildren(element('div', 'empty-state', 'NO RECEIPT'));
    } else {
      rack.replaceChildren(...receipts.map((receipt) => {
        const button = element('button', `receipt ${receipt.result.toLowerCase()}`);
        button.type = 'button';
        button.setAttribute('aria-pressed', String(selectedReceipts.has(receipt.id)));
        button.append(
          element('small', '', `${receipt.id} · ${shortCandidate(receipt.candidate_id)}`),
          element('strong', '', `${receipt.name} · ${receipt.result}`),
          element('small', '', receipt.details.residual_cm_s == null ? shortHash(receipt.sha256) : `RESIDUAL ${receipt.details.residual_cm_s} cm/s`),
        );
        button.disabled = busy || isEnded();
        button.addEventListener('click', () => {
          if (selectedReceipts.has(receipt.id)) selectedReceipts.delete(receipt.id);
          else selectedReceipts.add(receipt.id);
          findingMode = null;
          render();
        });
        return button;
      }));
    }
    $('[data-check-summary]').textContent = `${packet.checks.length} REQUIRED · RECEIPTS ARE CANDIDATE-BOUND`;
  }

  function selectedFindings(run) {
    return [...selectedReceipts].flatMap((id) => run.receipts[id]?.finding_ids || []);
  }

  function renderHandoff(run) {
    const record = run.record_id ? run.records[run.record_id] : null;
    const selected = record ? record.receipts.map((receipt) => receipt.id) : [...selectedReceipts];
    const findings = record ? record.finding_ids : selectedFindings(run);
    const omitted = record && run.gate?.adapter_classification === 'FINDING_OMITTED';
    $('[data-path-receipt]').textContent = selected.length ? selected.join(' + ') : '—';
    $('[data-path-finding]').textContent = omitted ? 'OMITTED' : findings.length ? (record || findingMode === 'carry' ? findings.join(' + ') : findingMode === 'omit' ? 'OMITTED' : 'CHOOSE') : 'NONE';
    $('[data-path-projection]').textContent = record ? record.id : '—';
    const thread = $('[data-thread-state]');
    const custody = record ? (omitted ? 'omit' : 'carry') : findingMode || 'unset';
    thread.dataset.threadState = custody;
    thread.setAttribute('aria-label', `Finding custody is ${custody}`);
    $('[data-projection-thread]').dataset.threadState = record ? 'carry' : 'unset';
    $$('[data-finding]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.finding === (record ? custody : findingMode)));
      button.disabled = busy || isEnded() || findings.length === 0;
    });
  }

  function renderEngines(run, engine) {
    if (run.mode === 'direct') {
      $('[data-dobeworks-state]').textContent = 'NOT IN PATH';
      $('[data-dobeworks-detail]').textContent = 'DIRECT AGENT HANDOFF';
      $('[data-dobeworks-state]').closest('.system-card').dataset.state = 'none';
      $('[data-degs-state]').textContent = 'NOT IN PATH';
      $('[data-degs-detail]').textContent = 'NO GOVERNED GATE';
      $('[data-degs-label]').textContent = 'NO DECISION';
      $('[data-degs-state]').closest('.system-card').dataset.state = 'none';
      return;
    }
    const worker = engine.dobeworks;
    $('[data-dobeworks-state]').textContent = worker ? worker.state : 'NO STAGED WORK';
    $('[data-dobeworks-detail]').textContent = worker ? `${worker.promotion} · ${shortHash(worker.output_sha256)}` : '—';
    const workerCard = $('[data-dobeworks-state]').closest('.system-card');
    workerCard.dataset.state = worker ? 'pass' : 'none';
    const gate = engine.degs;
    $('[data-degs-label]').textContent = gate ? 'ADAPTER / RAW DEGS' : 'GOVERNED DECISION';
    $('[data-degs-state]').textContent = gate ? gate.decision : 'NO DECISION';
    $('[data-degs-detail]').textContent = gate ? `DEGS ${gate.raw_degs_decision} · ${gate.adapter_classification}` : '—';
    $('[data-degs-state]').closest('.system-card').dataset.state = gate ? gate.decision.toLowerCase() : 'none';
  }

  function isEnded() {
    return snapshot?.run && !['PAD', 'COUNTDOWN'].includes(snapshot.run.phase);
  }

  function renderActions(run, packet) {
    const ended = isEnded();
    const checkHost = $('[data-check-actions]');
    checkHost.replaceChildren(...packet.checks.map((name) => {
      const button = element('button', '', `RUN ${name}`);
      button.type = 'button';
      button.disabled = busy || ended;
      button.addEventListener('click', () => command('check', {name}));
      return button;
    }));
    const map = Object.fromEntries($$('[data-action]').map((button) => [button.dataset.action, button]));
    Object.values(map).forEach((button) => { button.disabled = busy || ended; });
    map.send.disabled = busy || ended;
    map.accept.disabled = busy || ended || (run.mode === 'governed' && !run.gate);
    map.override.disabled = busy || ended || !run.gate;
    map.condition.disabled = busy || ended || run.vehicle.conditioned || run.vehicle.conditioning_until != null;
    map.arm.disabled = busy || ended || run.vehicle.armed;
    map.ignite.disabled = busy || ended || (run.phase === 'COUNTDOWN' && !run.countdown.holding);
    map.accept.textContent = run.mode === 'direct' ? 'APPROVE AGENT COPY' : 'ACCEPT CURRENT';
    $('[data-action-deck]').dataset.mode = run.mode;
    $$('[data-governed-only]').forEach((item) => { item.hidden = run.mode === 'direct'; });
    $('[data-clock-hold]').disabled = busy || run.phase !== 'COUNTDOWN';
    $('[data-clock-hold]').setAttribute('aria-pressed', String(run.phase === 'COUNTDOWN' && run.countdown.holding));
  }

  function flightClock(run) {
    if (run.phase === 'COUNTDOWN') return `T−${String(run.countdown.remaining_s).padStart(3, '0')}`;
    if (run.flight) return `T+${String(run.flight.t).padStart(3, '0')}`;
    return 'T---';
  }

  function renderClocks(run) {
    $('[data-mission-clock]').textContent = elapsedLabel(run.elapsed_s);
    $('[data-flight-clock]').textContent = flightClock(run);
    $('[data-run-id]').textContent = run.run_id.replace('run-', '').slice(0, 8).toUpperCase();
    $('[data-mode]').textContent = run.mode === 'governed' ? 'DW + DEGS' : 'DIRECT';
    $('[data-level]').textContent = run.difficulty.toUpperCase();
  }

  function launchResidual(run) {
    if (!run.launch) return null;
    return run.launch.world_wind_cm_s + run.launch.body_to_world_sign * run.launch.candidate.correction_cm_s;
  }

  function renderFlight(run) {
    const monitor = $('[data-flight-monitor]');
    const rocket = $('[data-rocket]');
    const flight = run.flight;
    let state = 'pad';
    let event = 'THRUSTERS COLD';
    let x = 0;
    let y = 0;
    if (run.phase === 'COUNTDOWN') {
      state = run.countdown.engine_start ? 'ignition' : 'pad';
      event = run.countdown.holding ? 'COUNTDOWN HOLD' : run.countdown.engine_start ? `ENGINE START · T−${String(run.countdown.remaining_s).padStart(3, '0')}` : `COUNTDOWN · T−${String(run.countdown.remaining_s).padStart(3, '0')}`;
    } else if (flight) {
      state = run.phase === 'RANGE_ABORT' ? 'abort' : run.phase === 'COMPLETE' ? 'complete' : 'flight';
      x = Math.max(-145, Math.min(145, flight.x_cm / 500 * 130));
      y = Math.min(365, flight.t * 3.65);
      const latest = flight.events.at(-1);
      event = flight.t === 70 ? 'MAX Q · AUTHORED PROFILE CALL' : latest ? `${latest.event} · T+${String(latest.t).padStart(3, '0')}` : `ASCENT · T+${String(flight.t).padStart(3, '0')}`;
    } else if (run.outcome) {
      event = run.outcome.flight;
      state = run.outcome.flight === 'PAD_ABORT' ? 'abort' : 'pad';
    }
    monitor.dataset.flightState = state;
    rocket.style.setProperty('--rocket-x', `${x}px`);
    rocket.style.setProperty('--rocket-y', `${y}px`);
    rocket.setAttribute('aria-label', flight ? `Rocket at T plus ${flight.t} seconds` : 'Rocket on pad');
    $('[data-monitor-event]').textContent = event;

    const points = [[200, 465]];
    if (flight && run.launch) {
      const residual = launchResidual(run);
      for (let t = 5; t <= flight.t; t += 5) {
        const pathX = Math.max(55, Math.min(345, 200 + residual * Math.min(40, Math.max(0, t - 20)) / 500 * 130));
        points.push([pathX, Math.max(70, 465 - t * 3.65)]);
      }
    }
    $('[data-flight-path]').setAttribute('points', points.map((point) => point.join(',')).join(' '));
  }

  function renderHardware(run) {
    let condition = 'COLD';
    if (run.vehicle.conditioned) condition = 'CONDITIONED';
    else if (run.vehicle.conditioning_until != null) condition = `CONDITIONING · ${Math.max(0, run.vehicle.conditioning_until - run.elapsed_s)}s`;
    $('[data-condition-state]').textContent = condition;
    $('[data-arm-state]').textContent = run.vehicle.armed ? 'ARMED' : 'SAFE';
    $('[data-ignition-state]').textContent = run.phase === 'COUNTDOWN' ? (run.countdown.engine_start ? 'ENGINE START' : 'COUNTDOWN') : run.flight?.engine_on ? 'BURN' : 'INHIBITED';
    $('[data-vehicle-state]').textContent = run.phase === 'PAD' ? (run.vehicle.conditioned ? 'CONDITIONED' : 'THRUSTERS COLD') : run.phase.replaceAll('_', ' ');
  }

  function renderCause(run) {
    const candidate = run.launch?.candidate || run.candidates[run.candidate_id];
    $('[data-cause-packet]').textContent = shortCandidate(candidate.id);
    $('[data-cause-correction]').textContent = `${correctionLabel(candidate.correction_cm_s)} m/s`;
    const residual = launchResidual(run);
    $('[data-cause-residual]').textContent = residual == null ? '—' : `${residual} cm/s`;
    $('[data-cause-record]').textContent = run.launch?.record_support
      || (run.mode === 'direct' ? 'DIRECT · UNCHECKED' : run.gate?.decision || '—');
    $('[data-cause-authority]').textContent = run.launch?.authority?.action || run.authority?.action || '—';
  }

  function renderResult(run) {
    const card = $('[data-result]');
    const terminal = ['COMPLETE', 'RANGE_ABORT', 'NO_IGNITION'].includes(run.phase);
    const outcome = run.outcome;
    card.hidden = !outcome && !terminal;
    if (card.hidden) return;
    $('[data-result-record]').textContent = outcome?.record || 'UNRESOLVED';
    $('[data-result-flight]').textContent = outcome?.flight || run.phase;
    const chain = $('[data-causal-chain]');
    const lines = [];
    if (run.launch) {
      lines.push(`CANDIDATE ${shortCandidate(run.launch.candidate.id)} REACHED IGNITION`);
      lines.push(`HUMAN ACTION · ${run.launch.authority.action}`);
      if (run.launch.authority.action === 'OVERRIDE') {
        lines.push(`GOVERNANCE BYPASSED · ${run.launch.gate?.output?.decision || 'NO PASS'}`);
      }
    }
    (outcome?.reasons || []).forEach((reason) => lines.push(reason));
    (run.flight?.faults || []).forEach((fault) => lines.push(`${fault.code} · ${fault.status}`));
    if (!lines.length) lines.push('THE SERVER RETAINED THE TERMINAL EVENT.');
    chain.replaceChildren(...lines.map((line) => element('li', '', line)));
    $('[data-compare-mode]').textContent = run.mode === 'governed' ? 'RUN SAME PACKET DIRECT' : 'RUN SAME PACKET GOVERNED';
  }

  function renderRetained(run) {
    const candidates = Object.values(run.candidates);
    $('[data-retained-count]').textContent = String(candidates.length + run.prior_runs.length);
    const candidateList = $('[data-candidate-history]');
    candidateList.replaceChildren(...candidates.map((candidate) => {
      const item = element('li');
      const button = element('button', 'retained-choice', `${shortCandidate(candidate.id)} · ${correctionLabel(candidate.correction_cm_s)} m/s · ${shortHash(candidate.sha256)}`);
      button.type = 'button';
      button.disabled = busy || isEnded() || candidate.id === run.candidate_id;
      button.addEventListener('click', () => command('select', {candidate_id: candidate.id}));
      item.append(button);
      return item;
    }));
    const runList = $('[data-run-history]');
    runList.replaceChildren(...(run.prior_runs.length ? run.prior_runs.map((item) => element('li', '', `${item.run_id} · ${item.mode.toUpperCase()} · ${item.phase} · ${item.outcome?.flight || 'NO TERMINAL RESULT'}`)) : [element('li', '', 'NONE')]));
  }

  function renderStatus(run) {
    const gate = run.gate;
    let text = snapshot.terminal?.text || 'SERVER RECORD READY';
    let kind = 'neutral';
    if (run.outcome) {
      text = `${run.outcome.flight} · RECORD ${run.outcome.record}`;
      kind = run.outcome.flight === 'NOMINAL' ? 'good' : 'danger';
    } else if (gate) {
      text = `DEGS ${gate.decision} · ${gate.adapter_classification}`;
      kind = gate.decision === 'PASS' ? 'good' : 'warn';
    } else if (run.mode === 'direct') {
      text = run.authority ? 'DIRECT HANDOFF · HUMAN APPROVED' : 'DIRECT HANDOFF · INSPECT BY EYE';
      kind = run.authority ? 'warn' : 'neutral';
    }
    $('[data-status]').textContent = text;
    $('[data-status-lamp]').dataset.kind = kind;
  }

  function render() {
    const run = snapshot?.run;
    if (!run || choosing) {
      showSelection();
      return;
    }
    if (intakeRunId === run.run_id) {
      showIntake(run);
      return;
    }
    document.body.dataset.route = run.mode;
    showMission();
    renderReference(run, snapshot.packet);
    renderCandidate(run, snapshot.packet);
    if (run.mode === 'governed') {
      renderReceipts(run, snapshot.packet);
      renderHandoff(run);
    }
    renderEngines(run, snapshot.engine);
    renderActions(run, snapshot.packet);
    renderClocks(run);
    renderFlight(run);
    renderHardware(run);
    renderCause(run);
    renderResult(run);
    renderRetained(run);
    renderStatus(run);
  }

  $$('[data-mode-option]').forEach((button) => button.addEventListener('click', () => {
    showSelection(button.dataset.modeOption);
  }));
  $$('[data-start]').forEach((button) => button.addEventListener('click', () => start(button.dataset.start)));
  $$('[data-finding]').forEach((button) => button.addEventListener('click', () => {
    findingMode = button.dataset.finding;
    render();
  }));
  $('[data-action="stage"]').addEventListener('click', () => command('stage'));
  $('[data-action="send"]').addEventListener('click', () => {
    const run = snapshot.run;
    const findings = selectedFindings(run);
    if (findings.length && !findingMode) {
      addTerminal('ELIZA', 'THE SELECTED RECEIPT HAS A FINDING. CHOOSE WHETHER IT TRAVELS WITH THE OUTGOING RECORD.');
      return;
    }
    command('project', {receipt_ids: [...selectedReceipts], finding_ids: findingMode === 'carry' ? findings : []});
  });
  $('[data-action="accept"]').addEventListener('click', () => command('accept'));
  $('[data-action="override"]').addEventListener('click', () => command('override'));
  $('[data-action="condition"]').addEventListener('click', () => command('condition'));
  $('[data-action="arm"]').addEventListener('click', () => command('arm'));
  $('[data-action="ignite"]').addEventListener('click', () => command('ignite'));
  $('[data-clock-hold]').addEventListener('click', () => command('hold'));
  $('[data-retry]').addEventListener('click', () => command('retry'));
  $('[data-intake-receive]').addEventListener('click', () => {
    intakeRunId = null;
    render();
    $('[data-candidate-card]').focus({preventScroll: true});
  });
  $('[data-compare-mode]').addEventListener('click', () => start(snapshot.run.difficulty, snapshot.run.mode === 'governed' ? 'direct' : 'governed'));
  $('[data-change-difficulty]').addEventListener('click', () => showSelection());
  $('[data-terminal-form]').addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = $('[data-terminal-form] input');
    const question = input.value.trim();
    input.value = '';
    try {
      const answer = await request('/api/launch/terminal', {question});
      addTerminal(answer.speaker, answer.text);
    } catch (error) {
      addTerminal('CONTROL', error.message);
    }
  });

  async function poll() {
    if (busy) return;
    try {
      const next = await request('/api/launch/state');
      if (!busy) acceptSnapshot(next);
    } catch (_) { /* next pulse retries */ }
  }

  poll();
  window.setInterval(poll, 750);
})();
