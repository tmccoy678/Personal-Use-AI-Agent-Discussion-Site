(() => {
  'use strict';

  const scoreKey = 'dobeworks-save-the-signal-score';
  const readScore = () => Number.parseInt(sessionStorage.getItem(scoreKey) || '0', 10) || 0;
  const writeScore = (value) => sessionStorage.setItem(scoreKey, String(Math.max(0, Math.round(value))));

  function setupScan() {
    const game = document.querySelector('[data-scan-game]');
    if (!game) return;
    const status = game.querySelector('[data-game-status]');
    const target = game.querySelector('.signal-target');
    const targetForm = target.closest('form');
    const retry = game.querySelector('[data-scan-retry]');
    const noTimer = game.querySelector('[data-no-timer]');
    const track = game.querySelector('.signal-track');
    let seconds = Number(game.dataset.seconds);
    let misses = 0;
    let untimed = false;
    let ended = false;
    let timer;
    let started = performance.now();

    function begin() {
      clearInterval(timer);
      seconds = Number(game.dataset.seconds);
      misses = 0;
      ended = false;
      started = performance.now();
      retry.hidden = true;
      target.disabled = false;
      status.textContent = untimed ? 'NO TIMER' : String(seconds);
      track.classList.remove('signal-lost');
      track.classList.add('signal-restart');
      requestAnimationFrame(() => track.classList.remove('signal-restart'));
      if (untimed) return;
      timer = setInterval(() => {
        seconds -= 1;
        status.textContent = String(seconds);
        if (seconds > 0) return;
        clearInterval(timer);
        ended = true;
        target.disabled = true;
        status.textContent = 'SIGNAL LOST';
        track.classList.add('signal-lost');
        retry.hidden = false;
        retry.focus();
      }, 1000);
    }

    game.querySelectorAll('[data-signal-wrong]').forEach((button) => {
      button.addEventListener('click', () => {
        if (ended) return;
        misses += 1;
        status.textContent = 'SIGNAL MISREAD';
        track.classList.remove('signal-misread');
        requestAnimationFrame(() => track.classList.add('signal-misread'));
        setTimeout(() => {
          track.classList.remove('signal-misread');
          status.textContent = untimed ? 'NO TIMER' : String(seconds);
        }, 420);
      });
    });
    target.addEventListener('click', (event) => {
      if (ended) return;
      event.preventDefault();
      ended = true;
      clearInterval(timer);
      const elapsed = (performance.now() - started) / 1000;
      writeScore((untimed ? 600 : 1100 - elapsed * 70) - misses * 100);
      status.textContent = 'WARNING FOUND';
      target.classList.add('found');
      setTimeout(() => targetForm.submit(), 180);
    });
    noTimer.addEventListener('click', () => {
      untimed = !untimed;
      noTimer.setAttribute('aria-pressed', String(untimed));
      noTimer.textContent = untimed ? 'USE TIMER' : 'NO TIMER';
      begin();
    });
    retry.addEventListener('click', begin);
    begin();
  }

  function setupRepair() {
    const form = document.querySelector('[data-repair-form]');
    if (!form) return;
    const tool = form.querySelector('[data-bar-tool]');
    const target = form.querySelector('[data-repair-target]');
    let selected = false;
    let dragging = false;
    let origin = null;

    function select() {
      selected = true;
      tool.setAttribute('aria-pressed', 'true');
      form.classList.add('bar-selected');
    }
    function finish() {
      if (form.classList.contains('repaired')) return;
      form.classList.add('repaired');
      target.setAttribute('aria-label', 'R bar repaired');
      writeScore(readScore() + 400);
      setTimeout(() => form.submit(), 260);
    }
    function resetTool() {
      dragging = false;
      tool.style.transform = '';
      origin = null;
    }
    tool.addEventListener('click', select);
    target.addEventListener('click', () => selected && finish());
    target.addEventListener('keydown', (event) => {
      if (selected && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        finish();
      }
    });
    tool.addEventListener('pointerdown', (event) => {
      select();
      dragging = true;
      origin = {x: event.clientX, y: event.clientY};
      tool.setPointerCapture(event.pointerId);
    });
    tool.addEventListener('pointermove', (event) => {
      if (!dragging) return;
      tool.style.transform = `translate(${event.clientX - origin.x}px,${event.clientY - origin.y}px)`;
    });
    tool.addEventListener('pointerup', (event) => {
      if (!dragging) return;
      const rect = target.getBoundingClientRect();
      const inside = event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
      resetTool();
      if (inside) finish();
    });
  }

  function setupCarry() {
    const game = document.querySelector('[data-carry-game]');
    if (!game) return;
    const prompt = game.querySelector('[data-carry-prompt]');
    const correct = game.querySelector('[data-carry-correct]');
    const drop = game.querySelector('#carry-drop button');
    const complete = game.querySelector('[data-carry-complete]');
    const checkpoints = [...game.querySelectorAll('.carry-checkpoints i')];
    const prompts = ['BUILD SAYS DONE', 'WORKER SAYS COMPLETE', 'NEXT TEAM SEES PASS'];
    const keeps = ['CARRY WARNING', 'KEEP UNACCEPTED', 'KEEP GATE CLOSED'];
    const drops = ['TRUST DONE', 'MARK ACCEPTED', 'CLEAR GATE'];
    let step = 0;

    function update() {
      game.dataset.carryStep = String(step);
      checkpoints.forEach((checkpoint, index) => checkpoint.classList.toggle('done', index < step));
      if (step === 3) {
        prompt.textContent = 'WARNING SURVIVED';
        correct.disabled = true;
        drop.disabled = true;
        writeScore(readScore() + 500);
        setTimeout(() => complete.submit(), 320);
        return;
      }
      prompt.textContent = prompts[step];
      correct.textContent = keeps[step];
      drop.textContent = drops[step];
    }
    correct.addEventListener('click', () => {
      step += 1;
      update();
    });
    game.classList.add('carry-ready');
    update();
  }

  function setupFlight() {
    const game = document.querySelector('[data-flight-game]');
    if (!game) return;
    const field = game.querySelector('[data-flight-field]');
    const rocket = game.querySelector('[data-flight-rocket]');
    const control = game.querySelector('[data-flight-control]');
    const status = game.querySelector('[data-flight-status]');
    const clock = game.querySelector('[data-flight-time]');
    const complete = game.querySelector('[data-flight-complete]');
    const gates = [...game.querySelectorAll('[data-gate]')];
    const duration = Number(game.dataset.duration);
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    let active = false;
    let pressed = false;
    let y = 50;
    let startTime = 0;
    let lastTime = 0;
    let strikes = 0;
    let reducedGate = 0;
    let pausedAt = 0;
    let generation = 0;

    function setPressed(value) {
      pressed = value;
      control.classList.toggle('pressed', value);
    }
    function finish() {
      active = false;
      generation += 1;
      status.textContent = 'VENUS REACHED';
      writeScore(readScore() + 1500 - strikes * 100);
      setTimeout(() => complete.submit(), 350);
    }
    function collide() {
      active = false;
      generation += 1;
      strikes += 1;
      writeScore(readScore() - 100);
      status.textContent = 'RANGE SAFETY';
      control.textContent = 'REPLAY FLIGHT';
      game.classList.add('flight-lost');
    }
    function reset() {
      y = 50;
      rocket.style.top = '50%';
      gates.forEach((gate) => gate.style.left = '110%');
      game.classList.remove('flight-lost', 'flight-active');
      clock.textContent = duration.toFixed(1);
      status.textContent = 'READY';
      control.textContent = reduced ? 'CLEAR GATE 1' : 'START FLIGHT';
      reducedGate = 0;
      pausedAt = 0;
      setPressed(false);
    }
    function schedule() {
      const current = generation;
      requestAnimationFrame((now) => frame(now, current));
    }
    function frame(now, current) {
      if (!active || current !== generation || pausedAt) return;
      const elapsed = (now - startTime) / 1000;
      const dt = Math.min((now - lastTime) / 1000, 0.05);
      lastTime = now;
      y += (pressed ? -25 : 19) * dt;
      rocket.style.top = `${y}%`;
      clock.textContent = Math.max(0, duration - elapsed).toFixed(1);
      const gateTimes = [3, 6, 9];
      const gapCenters = [32, 67, 43];
      gates.forEach((gate, index) => {
        const x = 20 + (gateTimes[index] - elapsed) * 22;
        gate.style.left = `${x}%`;
        if (Math.abs(elapsed - gateTimes[index]) < 0.16 && Math.abs(y - gapCenters[index]) > 17) collide();
      });
      if (!active) return;
      if (y < 4 || y > 96) return collide();
      if (elapsed >= duration) return finish();
      schedule();
    }
    function start() {
      if (reduced) {
        reducedGate += 1;
        status.textContent = `GATE ${reducedGate} CLEAR`;
        control.textContent = reducedGate < 3 ? `CLEAR GATE ${reducedGate + 1}` : 'VENUS REACHED';
        if (reducedGate === 3) finish();
        return;
      }
      if (active) return;
      reset();
      active = true;
      game.classList.add('flight-active');
      status.textContent = 'FLY';
      control.textContent = 'HOLD TO CLIMB';
      startTime = performance.now();
      lastTime = startTime;
      generation += 1;
      schedule();
    }
    control.addEventListener('click', () => {
      if (!active) start();
    });
    control.addEventListener('pointerdown', (event) => {
      if (reduced) return;
      if (!active) start();
      setPressed(true);
      control.setPointerCapture(event.pointerId);
    });
    control.addEventListener('pointerup', () => setPressed(false));
    control.addEventListener('pointercancel', () => setPressed(false));
    window.addEventListener('keydown', (event) => {
      if (event.key !== ' ' && event.key !== 'Enter') return;
      if (document.activeElement && /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
      event.preventDefault();
      if (!active) start();
      setPressed(true);
    });
    window.addEventListener('keyup', (event) => {
      if (event.key === ' ' || event.key === 'Enter') setPressed(false);
    });
    document.addEventListener('visibilitychange', () => {
      if (!active || reduced) return;
      if (document.hidden) {
        pausedAt = performance.now();
        generation += 1;
        status.textContent = 'PAUSED';
        return;
      }
      if (!pausedAt) return;
      const now = performance.now();
      startTime += now - pausedAt;
      lastTime = now;
      pausedAt = 0;
      status.textContent = 'FLY';
      generation += 1;
      schedule();
    });
    reset();
    game.classList.add('flight-ready');
  }

  function setupWin() {
    const output = document.querySelector('[data-final-score]');
    if (output) output.textContent = String(readScore() || 2000);
  }

  setupScan();
  setupCarry();
  setupRepair();
  setupFlight();
  setupWin();
})();
