(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const csrf = $('meta[name="stage-csrf"]').content;
  const selectScreen = $('[data-screen="select"]');
  const intakeScreen = $('[data-screen="intake"]');
  const missionScreen = $('[data-screen="mission"]');
  const hasInitialRun = $('meta[name="stage-has-run"]').content === '1';
  let snapshot = null;
  let busy = false;
  let selectedReceipts = new Set();
  let findingMode = null;
  let lastAutomaticLine = '';
  let choosing = !hasInitialRun;
  let selectedMode = null;
  let selectedDifficulty = null;
  let briefingPreview = null;
  let lastAnnouncement = '';

  const BRIEFINGS = {
    easy: {
      label: 'WIND',
    },
    medium: {
      label: 'UNITS',
    },
    hard: {
      label: 'STATE',
    },
  };

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
    if (!automatic) announce(`${speaker}. ${text}`);
  }

  function announce(text) {
    if (!text || text === lastAnnouncement) return;
    lastAnnouncement = text;
    $('[data-live-announcer]').textContent = text;
  }

  function acceptSnapshot(next, focusScene = false) {
    const incoming = next.run;
    const current = snapshot && snapshot.run;
    const priorScene = current ? storyScene(current) : null;
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
    const scene = render();
    if (focusScene && scene) {
      if (scene !== priorScene) $('[data-story-title]').focus({preventScroll: true});
      announce(`${$('[data-story-title]').textContent} ${$('[data-story-line]').textContent}`);
    }
  }

  async function previewFor(difficulty) {
    if (!briefingPreview || briefingPreview.difficulty !== difficulty) {
      briefingPreview = await request('/api/launch/preview', {difficulty});
    }
    return briefingPreview;
  }

  async function start(difficulty, mode) {
    if (busy || !mode) return;
    busy = true;
    try {
      selectedDifficulty = difficulty;
      selectedMode = mode;
      selectedReceipts.clear();
      findingMode = null;
      lastAutomaticLine = '';
      const preview = await previewFor(difficulty);
      const next = await request('/api/launch/new', {
        difficulty,
        mode,
        expected_candidate_sha256: preview.candidate.sha256,
      });
      if (preview.candidate.sha256 !== next.run.candidates[next.run.candidate_id].sha256) {
        throw new Error('THE ROUTED ARTIFACT DID NOT MATCH THE INSPECTED COPY. THE RUN WAS STOPPED.');
      }
      choosing = false;
      acceptSnapshot(next, true);
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
      acceptSnapshot(next, true);
    } catch (error) {
      addTerminal('CONTROL', error.message);
    } finally {
      busy = false;
      render();
    }
  }

  function showSelection() {
    choosing = true;
    selectedMode = null;
    selectedDifficulty = null;
    briefingPreview = null;
    document.body.dataset.route = '';
    document.body.dataset.scene = '';
    intakeScreen.hidden = true;
    missionScreen.hidden = true;
    selectScreen.hidden = false;
    $('[data-start="easy"]').focus();
  }

  function showMission() {
    selectScreen.hidden = true;
    intakeScreen.hidden = true;
    missionScreen.hidden = false;
  }

  function observationLine(item) {
    const tLabel = (value) => `T${value < 0 ? '−' : '+'}${String(Math.abs(value)).padStart(3, '0')}`;
    return `${item.id} · WIND ${correctionLabel(item.wind_cm_s)} m/s · ${item.config_id} · ${tLabel(item.valid_from_t)}–${tLabel(item.valid_through_t)}`;
  }

  async function showBriefing(difficulty) {
    const briefing = BRIEFINGS[difficulty];
    choosing = true;
    selectedDifficulty = difficulty;
    selectedMode = null;
    briefingPreview = null;
    document.body.dataset.route = '';
    document.body.dataset.scene = 'artifact';
    selectScreen.hidden = true;
    missionScreen.hidden = true;
    intakeScreen.hidden = false;
    $('[data-intake-speaker]').textContent = 'RECEIVING AUTONOMOUS ARTIFACT';
    $('[data-intake-route-tag]').textContent = 'ROUTE UNASSIGNED';
    $('[data-intake-candidate]').textContent = 'A1';
    $('[data-intake-line]').textContent = 'REQUESTING THE MODE-NEUTRAL AGENT COPY FROM THE MISSION SERVER.';
    $('[data-intake-level]').textContent = briefing.label;
    $('[data-intake-mode]').textContent = '—';
    $('[data-intake-hash]').textContent = 'RECEIVING';
    $('[data-intake-path]').dataset.route = '';
    $('[data-intake-path]').setAttribute('aria-label', 'Agent artifact awaiting the player\'s route');
    $('[data-arrival-response]').hidden = true;
    $('[data-arrival-response]').textContent = '';
    $('[data-route-choice]').hidden = true;
    $('[data-arrival-actions]').hidden = false;
    $$('[data-arrival-action]').forEach((button) => { button.disabled = true; });
    try {
      briefingPreview = await previewFor(difficulty);
      const candidate = briefingPreview.candidate;
      $('[data-intake-speaker]').textContent = `${candidate.generated_by} · AUTONOMOUS AUTHOR`;
      $('[data-intake-candidate]').textContent = shortCandidate(candidate.id);
      $('[data-intake-line]').textContent = `${candidate.generated_by} MADE COPY ${shortCandidate(candidate.id)}.`;
      $('[data-intake-mode]').textContent = candidate.generated_by;
      $('[data-intake-hash]').textContent = `UNACCEPTED · ${shortHash(candidate.sha256)}`;
      $('[data-route-candidate]').textContent = shortCandidate(candidate.id);
      $$('[data-arrival-action]').forEach((button) => { button.disabled = false; });
      $('#intake-title').focus({preventScroll: true});
    } catch (error) {
      const response = $('[data-arrival-response]');
      response.textContent = error.message;
      response.hidden = false;
      $('[data-arrival-back]').focus();
    }
  }

  function storyScene(run) {
    if (['COMPLETE', 'RANGE_ABORT', 'NO_IGNITION'].includes(run.phase)) return 'record';
    if (run.phase === 'COUNTDOWN' && run.countdown?.holding) return 'authority';
    if (run.phase === 'COUNTDOWN' || run.flight
        || ['ACCEPT', 'OVERRIDE', 'MANUAL_ACCEPT'].includes(run.authority?.action)) return 'flight';
    if (run.gate) return 'authority';
    const currentReceipts = Object.values(run.receipts)
      .filter((receipt) => receipt.candidate_id === run.candidate_id);
    if (run.mode === 'direct' || run.record_id || currentReceipts.length) return 'handoff';
    return 'investigation';
  }

  function storyCopy(run, scene) {
    const candidate = shortCandidate(run.candidate_id);
    if (run.phase === 'COUNTDOWN' && run.countdown?.holding) return {
      kicker: 'HOLD',
      title: 'COUNTDOWN HELD.',
      line: 'Authorize again to resume.',
    };
    if (scene === 'investigation') return {
      kicker: 'CHECK',
      title: `CHECK COPY ${candidate}.`,
      line: 'What did the agent use?',
    };
    if (scene === 'handoff') return run.mode === 'direct' ? {
      kicker: 'DIRECT ROUTE',
      title: `CHECK ${candidate} BY EYE.`,
      line: 'No mission check will run. You decide.',
    } : {
      kicker: 'HANDOFF',
      title: 'BUILD THE RECORD.',
      line: `What should go with ${candidate}?`,
    };
    if (scene === 'authority') return run.mode === 'direct' ? {
      kicker: 'DECIDE',
      title: `AUTHORIZE ${candidate}?`,
      line: 'No gate checked this copy.',
    } : {
      kicker: 'YOU DECIDE',
      title: `BOUNDARY: ${run.gate?.decision || '—'}.`,
      line: 'The gate does not launch the rocket.',
    };
    if (scene === 'flight') {
      if (run.outcome?.flight === 'PAD_HOLD' || run.outcome?.flight === 'PAD_ABORT') return {
        kicker: 'STOP',
        title: 'LAUNCH STOPPED.',
        line: 'You can still fix it.',
      };
      if (run.flight) return {
        kicker: 'FLIGHT',
        title: `T+${String(run.flight.t).padStart(3, '0')}.`,
        line: `${candidate} is flying.`,
      };
      if (run.phase === 'COUNTDOWN') return {
        kicker: 'COUNTDOWN',
        title: `T−${String(run.countdown.remaining_s).padStart(3, '0')}.`,
        line: run.countdown.holding ? 'The clock is on hold.' : 'Watch the rocket or hold the clock.',
      };
      return {
        kicker: 'ROCKET',
        title: 'GET THE ROCKET READY.',
        line: 'It is cold. What do you do?',
      };
    }
    return {
      kicker: 'RESULT',
      title: run.outcome?.flight === 'NOMINAL' ? 'T+100. FLIGHT COMPLETE.' : `${run.outcome?.flight || run.phase.replaceAll('_', ' ')}.`,
      line: 'Which choice caused this result?',
    };
  }

  function renderTrack(run, scene) {
    const track = $('[data-route-track]');
    const direct = run.mode === 'direct';
    track.dataset.mode = run.mode;
    const check = $('[data-route-stop="check"]');
    const record = $('[data-route-stop="record"]');
    const recordLink = record.nextElementSibling;
    check.textContent = direct ? 'YOU' : 'CHECK';
    record.hidden = direct;
    recordLink.hidden = direct;
    const current = scene === 'investigation' ? 'check'
      : scene === 'handoff' ? (direct ? 'check' : 'record')
        : scene === 'authority' ? 'record' : 'vehicle';
    const order = direct ? ['agent', 'check', 'vehicle'] : ['agent', 'check', 'record', 'vehicle'];
    $$('[data-route-stop]').forEach((stop) => {
      const position = order.indexOf(stop.dataset.routeStop);
      const active = order.indexOf(current);
      stop.dataset.state = position < active ? 'done' : position === active ? 'current' : 'next';
    });
    const left = direct
      ? {agent: '0%', check: '50%', vehicle: '100%'}[current]
      : {agent: '0%', check: '33.33%', record: '66.66%', vehicle: '100%'}[current];
    track.style.setProperty('--copy-position', left);
    $('[data-track-candidate]').textContent = shortCandidate(run.candidate_id);
  }

  function renderStory(run) {
    const scene = storyScene(run);
    const copy = storyCopy(run, scene);
    document.body.dataset.scene = scene;
    $('[data-mission-story]').dataset.scene = scene;
    $('[data-story-kicker]').textContent = copy.kicker;
    $('[data-story-title]').textContent = copy.title;
    $('[data-story-line]').textContent = copy.line;
    return scene;
  }

  function renderReference(run, packet) {
    $('[data-condition-title]').textContent = `MISSION DATA · ${{easy: 'WIND', medium: 'UNITS', hard: 'STATE'}[run.difficulty]}`;
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
    $('[data-candidate-author]').textContent = candidate.generated_by;
    $('[data-prompt-agent]').textContent = `PROMPT ${candidate.generated_by}`;
    $('[data-candidate-hash]').textContent = shortHash(candidate.sha256);
    $('[data-correction-output]').textContent = correctionLabel(candidate.correction_cm_s);
    $('[data-candidate-config]').textContent = candidate.config_id;
    $('[data-candidate-observation]').textContent = candidate.condition_id;
    $('[data-candidate-cutoff]').textContent = candidate.cutoff_clock;
    const currentReceipts = Object.values(run.receipts).filter((item) => item.candidate_id === candidate.id);
    const checked = new Set(currentReceipts.map((item) => item.name));
    const complete = packet.checks.every((name) => checked.has(name));
    $('[data-candidate-state]').textContent = run.mode === 'direct'
      ? 'CHECK BY EYE'
      : complete ? 'CHECKED' : 'UNCHECKED';
    $('[data-stage-label]').textContent = run.mode === 'direct'
      ? 'DIRECT ROUTE'
      : run.staged_ids.includes(candidate.id) ? 'STAGED · NOT APPROVED' : 'NOT STAGED';
    $('[data-acceptance-label]').textContent = run.authority ? run.authority.action : 'UNACCEPTED';

    const activePrompt = (group) => [...candidate.prompt_history].reverse().find((id) =>
      packet.prompts.some((prompt) => prompt.id === id && prompt.group === group));
    const promptButtons = (group) => packet.prompts.filter((prompt) => prompt.group === group).map((prompt) => {
      const button = choiceButton(prompt.label, activePrompt(group) === prompt.id,
        () => command('prompt', {prompt_id: prompt.id}));
      return button;
    });

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
    const receipts = Object.values(run.receipts)
      .filter((receipt) => receipt.candidate_id === run.candidate_id);
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
    const completed = new Set(receipts.map((receipt) => receipt.name));
    const remaining = packet.checks.filter((name) => !completed.has(name)).length;
    $('[data-check-summary]').textContent = remaining
      ? `${remaining} CHECK${remaining === 1 ? '' : 'S'} LEFT`
      : `${packet.checks.length} CHECK${packet.checks.length === 1 ? '' : 'S'} COMPLETE`;
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
      $('[data-dobeworks-state]').textContent = 'NOT USED';
      $('[data-dobeworks-detail]').textContent = 'DIRECT ROUTE';
      $('[data-dobeworks-state]').closest('.system-card').dataset.state = 'none';
      $('[data-degs-state]').textContent = 'NOT USED';
      $('[data-degs-detail]').textContent = 'NO GATE';
      $('[data-degs-label]').textContent = 'NO DECISION';
      $('[data-degs-state]').closest('.system-card').dataset.state = 'none';
      return;
    }
    const worker = engine.dobeworks;
    $('[data-dobeworks-state]').textContent = worker ? 'STAGED · NOT APPROVED' : 'NOT STAGED';
    $('[data-dobeworks-detail]').textContent = worker ? `${worker.promotion} · ${shortHash(worker.output_sha256)}` : '—';
    const workerCard = $('[data-dobeworks-state]').closest('.system-card');
    workerCard.dataset.state = worker ? 'pass' : 'none';
    const gate = engine.degs;
    $('[data-degs-label]').textContent = gate ? 'BOUNDARY / RAW DEGS' : 'GOVERNED DECISION';
    $('[data-degs-state]').textContent = gate ? `BOUNDARY ${gate.decision}` : 'NO DECISION';
    $('[data-degs-detail]').textContent = gate ? `RAW DEGS ${gate.raw_degs_decision} · ${gate.adapter_classification}` : '—';
    $('[data-degs-state]').closest('.system-card').dataset.state = gate ? gate.decision.toLowerCase() : 'none';
  }

  function isEnded() {
    return snapshot?.run && !['PAD', 'COUNTDOWN'].includes(snapshot.run.phase);
  }

  function renderActions(run, packet, scene) {
    const ended = isEnded();
    const checkHost = $('[data-check-actions]');
    checkHost.replaceChildren(...packet.checks.map((name) => {
      const labels = {
        WIND_BALANCE: 'RUN WIND CHECK',
        UNIT_AND_WIND_BALANCE: 'RUN UNIT CHECK',
        STATE_BINDING: 'RUN STATE CHECK',
        CUTOFF_EPOCH: 'RUN CLOCK CHECK',
      };
      const button = element('button', '', labels[name] || `RUN ${name.replaceAll('_', ' ')}`);
      button.type = 'button';
      button.dataset.check = name;
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
    const launchAuthorized = ['ACCEPT', 'OVERRIDE', 'MANUAL_ACCEPT'].includes(run.authority?.action);
    map.ignite.disabled = busy || ended
      || (run.phase === 'COUNTDOWN' && (!run.countdown.holding || !launchAuthorized));
    const candidate = shortCandidate(run.candidate_id);
    map.stage.textContent = `STAGE ${candidate}`;
    map.send.textContent = 'SEND RECORD';
    map.accept.textContent = run.phase === 'COUNTDOWN' && run.countdown.holding
      ? 'AUTHORIZE AGAIN'
      : run.mode === 'direct' ? `AUTHORIZE ${candidate}` : 'ACCEPT';
    map.override.textContent = 'OVERRIDE';
    map.ignite.textContent = run.phase === 'COUNTDOWN' && run.countdown.holding
      ? 'RESUME COUNTDOWN'
      : 'IGNITE';
    $('[data-action-deck]').dataset.mode = run.mode;
    $$('[data-governed-only]').forEach((item) => { item.hidden = run.mode === 'direct'; });
    $('[data-clock-hold]').disabled = busy || run.phase !== 'COUNTDOWN';
    $('[data-clock-hold]').setAttribute('aria-pressed', String(run.phase === 'COUNTDOWN' && run.countdown.holding));
    const packetBank = $('[data-action-bank="packet"]');
    const authorityBank = $('[data-action-bank="authority"]');
    const vehicleBank = $('[data-action-bank="vehicle"]');
    packetBank.hidden = run.mode === 'direct' || !['investigation', 'handoff'].includes(scene);
    authorityBank.hidden = scene !== 'authority' && !(run.mode === 'direct' && scene === 'handoff');
    vehicleBank.hidden = ended;
    if (scene === 'flight') vehicleBank.open = true;
    map.condition.hidden = false;
    map.arm.hidden = false;
    map.ignite.hidden = false;
    $('[data-action-deck]').hidden = packetBank.hidden && authorityBank.hidden && vehicleBank.hidden;
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
    $('[data-level]').textContent = {easy: 'WIND', medium: 'UNITS', hard: 'STATE'}[run.difficulty];
    $('[data-hud-candidate]').textContent = shortCandidate(run.candidate_id);
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
    $('[data-ignition-state]').textContent = run.phase === 'COUNTDOWN' ? (run.countdown.engine_start ? 'ON' : 'COUNTDOWN') : run.flight?.engine_on ? 'ON' : 'OFF';
    $('[data-vehicle-state]').textContent = run.phase === 'PAD' ? (run.vehicle.conditioned ? 'READY' : 'COLD') : run.phase.replaceAll('_', ' ');
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

  function renderResult(run, packet) {
    const card = $('[data-result]');
    const terminal = ['COMPLETE', 'RANGE_ABORT', 'NO_IGNITION'].includes(run.phase);
    const outcome = run.outcome;
    card.hidden = !terminal;
    if (card.hidden) return;
    $('[data-result-record]').textContent = outcome?.record || 'UNRESOLVED';
    $('[data-result-flight]').textContent = outcome?.flight || run.phase;
    const chain = $('[data-causal-chain]');
    const lines = [];
    if (run.launch) {
      const promptId = run.launch.candidate.prompt_history.at(-1);
      const prompt = packet.prompts.find((item) => item.id === promptId);
      if (prompt) lines.push(`AGENT REVISION · ${prompt.label}`);
      lines.push(`CANDIDATE ${shortCandidate(run.launch.candidate.id)} REACHED IGNITION`);
      if (run.launch.record) {
        lines.push(`HANDOFF · ${run.launch.record.receipts.length} RECEIPT${run.launch.record.receipts.length === 1 ? '' : 'S'} · ${run.launch.record.finding_ids.length} FINDING${run.launch.record.finding_ids.length === 1 ? '' : 'S'}`);
      } else {
        lines.push('HANDOFF · DIRECT TO VEHICLE INTEGRATION');
      }
      lines.push(`HUMAN ACTION · ${run.launch.authority.action}`);
      if (run.launch.authority.action === 'OVERRIDE') {
        lines.push(`GOVERNANCE BYPASSED · ${run.launch.gate?.output?.decision || 'NO PASS'}`);
      }
    }
    (outcome?.reasons || []).forEach((reason) => lines.push(reason));
    (run.flight?.faults || []).forEach((fault) => lines.push(`${fault.code} · ${fault.status}`));
    if (!lines.length) lines.push('THE SERVER RETAINED THE TERMINAL EVENT.');
    chain.replaceChildren(...lines.map((line) => element('li', '', line)));
    $('[data-compare-mode]').textContent = 'OTHER ROUTE';
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
    const receiptList = $('[data-receipt-history]');
    const receipts = Object.values(run.receipts);
    receiptList.replaceChildren(...(receipts.length ? receipts.map((receipt) =>
      element('li', '', `${receipt.id} · ${shortCandidate(receipt.candidate_id)} · ${receipt.name} · ${receipt.result}`)
    ) : [element('li', '', 'NONE')]));
  }

  function renderStatus(run) {
    const gate = run.gate;
    const currentReceipts = Object.values(run.receipts)
      .filter((receipt) => receipt.candidate_id === run.candidate_id);
    let text = `COPY ${shortCandidate(run.candidate_id)} · ${run.authority?.action || 'UNACCEPTED'}`;
    let kind = 'neutral';
    if (run.outcome) {
      text = `${run.outcome.flight} · RECORD ${run.outcome.record}`;
      kind = run.outcome.flight === 'NOMINAL' ? 'good' : 'danger';
    } else if (gate) {
      text = `BOUNDARY: ${gate.decision}. YOU DECIDE.`;
      kind = gate.decision === 'PASS' ? 'good' : 'warn';
    } else if (run.mode === 'direct') {
      text = run.authority ? 'DIRECT COPY AUTHORIZED' : 'NO GATE CHECKED THIS COPY';
      kind = run.authority ? 'warn' : 'neutral';
    } else if (run.staged_ids.includes(run.candidate_id)) {
      text = `${shortCandidate(run.candidate_id)} IS STAGED. IT IS NOT APPROVED.`;
    } else if (currentReceipts.length) {
      const latest = currentReceipts.at(-1);
      text = latest.result === 'PASS'
        ? 'CHECK PASSED.'
        : `CHECK FAILED. RESIDUAL: ${latest.details.residual_cm_s > 0 ? '+' : ''}${latest.details.residual_cm_s} cm/s.`;
      kind = latest.result === 'PASS' ? 'good' : 'warn';
    }
    $('[data-status]').textContent = text;
    $('[data-status-lamp]').dataset.kind = kind;
  }

  function render() {
    const run = snapshot?.run;
    if (!run || choosing) {
      showSelection();
      return null;
    }
    document.body.dataset.route = run.mode;
    showMission();
    const scene = renderStory(run);
    renderTrack(run, scene);
    renderReference(run, snapshot.packet);
    renderCandidate(run, snapshot.packet);
    if (run.mode === 'governed') {
      renderReceipts(run, snapshot.packet);
      renderHandoff(run);
    }
    renderEngines(run, snapshot.engine);
    renderActions(run, snapshot.packet, scene);
    renderClocks(run);
    renderFlight(run);
    renderHardware(run);
    renderCause(run);
    renderResult(run, snapshot.packet);
    renderRetained(run);
    renderStatus(run);
    return scene;
  }

  $$('[data-start]').forEach((button) => button.addEventListener('click', () => showBriefing(button.dataset.start)));
  $$('[data-arrival-action]').forEach((button) => button.addEventListener('click', () => {
    const preview = briefingPreview;
    if (!preview) return;
    const candidate = preview.candidate;
    const response = $('[data-arrival-response]');
    if (button.dataset.arrivalAction === 'route') {
      $('[data-arrival-actions]').hidden = true;
      $('[data-route-choice]').hidden = false;
      $('[data-intake-route-tag]').textContent = 'CHOOSE THE NEXT BOUNDARY';
      $('[data-route="governed"]').focus();
      return;
    }
    response.textContent = button.dataset.arrivalAction === 'ask'
      ? `${candidate.generated_by}: I USED OBSERVATION ${candidate.condition_id}, VEHICLE FRAME ${candidate.config_id}, STEERING ${correctionLabel(candidate.correction_cm_s)} m/s, AND THE ${candidate.cutoff_clock} CUTOFF CLOCK.`
      : preview.packet.observations.map(observationLine).join(' · ');
    response.hidden = false;
  }));
  $$('[data-route]').forEach((button) => button.addEventListener('click', () => {
    start(selectedDifficulty, button.dataset.route);
  }));
  $('[data-arrival-back]').addEventListener('click', showSelection);
  $$('[data-finding]').forEach((button) => button.addEventListener('click', () => {
    findingMode = button.dataset.finding;
    render();
  }));
  $('[data-action="stage"]').addEventListener('click', () => command('stage'));
  $('[data-action="send"]').addEventListener('click', () => {
    const run = snapshot.run;
    const findings = selectedFindings(run);
    if (findings.length && !findingMode) {
      addTerminal('CONTROL', 'THE SELECTED RECEIPT HAS A FINDING. CHOOSE WHETHER IT TRAVELS WITH THE OUTGOING RECORD.');
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
    if (busy || choosing) return;
    try {
      const next = await request('/api/launch/state');
      if (!busy) acceptSnapshot(next);
    } catch (_) { /* next pulse retries */ }
  }

  if (hasInitialRun) window.setTimeout(poll, 100);
  window.setInterval(poll, 750);
})();
