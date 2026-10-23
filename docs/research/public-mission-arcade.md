# Public mission arcade research note

## Scope

The stage needs to explain one claim to a first-time visitor: completed work can
still carry a reason to stop, and that reason must survive the handoff to the
next system or person. The rocket story is the public entry point. The existing
engineering station remains the inspectable evidence layer.

## Browser-game interaction findings

Addicting Games describes durable browser games as easy to begin within seconds
while retaining enough depth to invite another round. Its current catalogue
provides three useful patterns for this stage:

- [Helicopter Game](https://www.addictinggames.com/clicker/helicopter-game)
  uses one control, continuous cause-and-effect feedback, a visible failure, and
  an immediate retry.
- [The Impossible Quiz](https://www.addictinggames.com/puzzle/the-impossible-quiz)
  uses familiar-looking choices whose consequences teach the actual rule. Its
  trial-and-error loop makes a wrong choice memorable rather than explanatory
  prose alone.
- [Bubble Tanks 2](https://www.addictinggames.com/shooting/bubble-tanks-2)
  adds visible progression and new capabilities as the player succeeds.
- [A Dark Room](https://adarkroom.doublespeakgames.com/) opens with a very
  small action vocabulary and reveals the wider system only as the player needs
  it. That progressive disclosure is more useful here than displaying the full
  explanation beneath the first screen.

The accessibility and game-feel guidance adds two constraints. Teach the rule
inside the action rather than on a separate instruction screen, and leave the
causal result visible after any motion ends. The stage therefore preserves
keyboard control, text outcomes, reduced motion, and large spaced targets.

The application is not to copy their art, code, scoring, or difficulty. It is to
keep one obvious action at each state, make the consequence of a bypass visible,
and unlock the deeper engineering workflow after the short mission teaches the
core rule.

## Historical grounding

[NASA's Mariner 1 account](https://science.nasa.gov/mission/mariner-1/) records
that the Atlas rocket veered off course and was destroyed by the Range Safety
Officer at T+294.5 seconds. NASA attributes the failure to a guidance antenna
problem and a software error involving an omitted overbar on the radius symbol
R. NASA also explicitly says the omitted mark was not a hyphen.

[NASA's Mariner 2 account](https://science.nasa.gov/mission/mariner-2/) describes
the successor as humanity's first successful planetary science mission. It
launched 36 days after Mariner 1, completed a course correction, flew by Venus,
and returned data during a 42-minute scan. It carried no cameras.

The stage therefore uses these phrases:

- **Mariner 1: historical consequence.** The real launch was destroyed for
  safety after the trajectory departed course. The site does not model that
  trajectory and does not claim one missing mark was the only fault.
- **Mariner 2: successful corrected successor.** The site does not call the
  entire mission flawless or present its fictional flight as a reconstruction.
- **Teaching reconstruction.** The R-bar note is an original, supplied-reference
  handoff exercise. DobeWorks and DEGS did not exist in 1962.

NASA and JPL pages may be linked from the mission archive. Remote images or video
are not required for comprehension, and the stage should not depend on third-party
media at runtime.

## Plain-language translation

The public explanation should name the mechanism before its component names:

1. A check finds a problem or a human records an unresolved concern.
2. DobeWorks keeps the work staged and keeps that finding attached.
3. The handoff carries the finding to DEGS.
4. DEGS refuses readiness while the reason to stop remains open.
5. Correction evidence can close the finding; acceptance remains a separate
   decision.

This distinction prevents overclaiming. DobeWorks is not, by itself, a universal
DOI validator, context oracle, or flight-certification system. A DOI resolver can
flag a citation that does not resolve; a context checker can flag a dropped
instruction; a test or review can flag unsafe code. DobeWorks preserves the
finding and DEGS enforces the supplied stop across the handoff.

## Recommended first-time loop

1. Present the paradox first: the task claims to be finished while one warning
   is still open. Show the received `R` beside the required `R-bar`, a three-field
   status board, and one primary button: **SEND THE FINISHED WORK**. Do not
   explain the component names before the visitor plays.
2. Run the existing fixed DobeWorks/DEGS fixture. Show the causal result first:
   **WORK FINISHED. LAUNCH STOPPED.** Then name the three roles in short cards.
3. Show the fixture's controlled comparison immediately: the same finished work
   is BLOCKED when the warning travels and passes when only the warning field is
   removed. This is the teaching payoff.
4. Offer two choices: **TRY TO IGNORE IT** and **FIX THE ERROR**. Bypass reveals
   the historical Mariner 1 consequence while leaving the real demo gate blocked.
5. Fixing submits a new packet, preserves the failed candidate, reruns the same
   checks, and reaches a separate acceptance decision.
6. After acceptance, let the visitor launch a clearly fictional corrected-successor
   simulation. Only after success reveal the transferable mechanism, everyday
   examples, Mariner 2 archive, and advanced evidence station.

## Acceptance checks

- A first-time visitor can start with one obvious action and no instructions.
- The opening does not display the application cards or four-part explanation;
  those are earned after the visitor completes the loop.
- A static screenshot explains what was missing, who preserved it, and why the
  next stage stopped.
- The first result screen contrasts warning-preserved BLOCKED with warning-lost
  PASS for the same candidate, and states that no launch occurred in the comparison.
- The bypass path never changes the recorded `BLOCKED` result or successful-flight
  state.
- Historical copy names the antenna fault and omitted overbar together.
- Mariner 2 is described as successful, not flawless.
- The DOI, context, and safety-code examples identify the upstream checker and do
  not imply automatic capabilities that this exhibit does not demonstrate.
- The existing expert workflow, evidence routes, host separation, reduced-motion
  behavior, and no-JavaScript boundary remain available.

## Primary sources

- Addicting Games. [Most Addicting Games](https://www.addictinggames.com/most-addicting-games).
- Addicting Games. [Top 100 Games](https://www.addictinggames.com/top-games).
- Addicting Games. [Helicopter Game](https://www.addictinggames.com/clicker/helicopter-game).
- Addicting Games. [The Impossible Quiz](https://www.addictinggames.com/puzzle/the-impossible-quiz).
- Addicting Games. [Bubble Tanks 2](https://www.addictinggames.com/shooting/bubble-tanks-2).
- Doublespeak Games. [A Dark Room](https://adarkroom.doublespeakgames.com/).
- Game Accessibility Guidelines. [Include interactive tutorials](https://gameaccessibilityguidelines.com/include-interactive-tutorials/).
- Game Accessibility Guidelines. [Basic features](https://gameaccessibilityguidelines.com/basic/).
- World Wide Web Consortium. [Animation from Interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html).
- National Aeronautics and Space Administration. [Mariner 1](https://science.nasa.gov/mission/mariner-1/).
- National Aeronautics and Space Administration. [Mariner 2](https://science.nasa.gov/mission/mariner-2/).
- Jet Propulsion Laboratory. [Mariner 2 Launches](https://www.jpl.nasa.gov/videos/mariner-2-launches/).
