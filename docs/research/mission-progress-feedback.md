# Mission progress and feedback research note

## Scope

The useful research area for this interface is goal pursuit, game motivation, and human-interface feedback. Strategic game theory does not address the reported problem: users need to see where they are, understand what changed, and feel the mission advance when their action succeeds.

## Findings

### Visible, truthful progress can sustain effort

Kivetz, Urminsky, and Zheng found that effort accelerated as people approached a reward goal across a cafe program and an online rating task. Their model treated motivation as a function of the proportion of the original distance remaining, not only the absolute work left ([Kivetz et al., 2006](https://s3.amazonaws.com/fieldexperiments-papers2/papers/00658.pdf)). Nunes and Dreze found greater persistence and faster completion when equivalent work was framed as a goal already in progress ([Nunes & Dreze, 2006](https://msbfile03.usc.edu/digitalmeasures/jnunes/intellcont/Endowed%20Progress%20Effect-1.pdf)).

These studies tested incentive and loyalty tasks rather than a launch-readiness interface, so the transfer is a design hypothesis to verify with users. The sound application is a truthful mission path whose completed portion remains visible. DobeWorks should never invent completed steps or imply acceptance that did not occur.

### Clear cause and effect supports competence

Across four studies, Ryan, Rigby, and Przybylski found that perceived competence and autonomy in games were associated with enjoyment, preference, well-being changes, and future play ([Ryan et al., 2006](https://selfdeterminationtheory.org/SDT/documents/2006_RyanRigbyPrzybylski_MandE.pdf)). The relevant reward is mastery: the interface should show which user action changed which mission state and why the next action is now available.

The feedback should come from the machinery itself:

- a completed check remains visibly complete;
- the current required step remains visibly current;
- a held check stays at the point of failure and names the exact cause;
- the rocket and mission path advance only when the represented evidence advances.

This gives the user competence feedback without adding points, badges, confetti, or a second fictional reward system.

### Operators need persistent location and state

NASA's *Human Integration Design Handbook* says interfaces should indicate the operator's location within the display hierarchy, give feedback when an element is selected, show the software's current state in a status area, keep displays minimal, and avoid using color as the only information code ([NASA, 2014, sections 10.6.1-10.6.19](https://www.nasa.gov/wp-content/uploads/2023/03/human-integration-design-handbook-revision-1.pdf)). The same handbook warns that users can miss even large visual changes when a display is disrupted, which favors persistent state over a brief highlight.

The GOV.UK task-list pattern similarly recommends explicit task statuses, the smallest useful status vocabulary, and lower emphasis for completed tasks so attention stays on work requiring action ([Government Digital Service, 2026](https://design-system.service.gov.uk/patterns/complete-multiple-tasks/)).

For this mission, the smallest useful visible vocabulary is:

| State | Left program list | Right mission path |
|---|---|---|
| Completed | `DONE` in a quiet, persistent style | completed node and connector remain lit |
| Current | one persistent `NEXT` marker and highlight | matching node receives the strongest emphasis |
| Held | `HOLD` remains on the blocked step | matching node shows the precise failed condition |
| Waiting | readable, unaccented text | unlit node; no motion |

After a successful action, mark that step `DONE` and move `NEXT` to the next required action. After an incorrect or out-of-order action, keep `NEXT` on the required step and show the hold reason in the result area. This preserves orientation through both correct and incorrect paths.

### Accessibility requires semantic state and optional motion

W3C's `aria-current="step"` technique exposes the visually current step to assistive technology ([W3C ARIA26](https://www.w3.org/WAI/WCAG21/Techniques/aria/ARIA26)). W3C also recommends programmatically exposed status messages for action results and process progress, using a status or live region as appropriate ([W3C WCAG 2.2, Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)). Text labels must accompany color and brightness changes.

W3C advises eliminating unnecessary motion or allowing it to be disabled, and identifies `prefers-reduced-motion` as a sufficient route for interaction-triggered animation ([W3C WCAG 2.2, Animation from Interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions)). Motion should therefore be brief, state-linked, and absent under reduced-motion preferences.

## Recommended interaction

1. Keep one persistent marker on the required program step. Use `aria-current="step"` on the same control.
2. Preserve completed steps with a quiet `DONE` label. Do not remove their state when the result view loads.
3. Give each right-side mission node the same state as its corresponding step: waiting, current, completed, or held.
4. On success, use a short one-time signal through the newly completed node and its outgoing connector, then rest in the completed appearance. A border or luminance sweep fits the terminal language better than physical movement.
5. On hold, keep the mission at the failed node. Show `HOLD` and the exact failed condition; do not animate the rocket forward.
6. Reserve the strongest visual payoff for a clean simulated flight: complete the full signal path and use the existing rocket as the terminal result.
7. Use visible text, border treatment, and brightness together. Color alone should never distinguish `DONE`, `NEXT`, or `HOLD`.
8. Put all animation inside `@media (prefers-reduced-motion: no-preference)`. The reduced-motion version should expose identical states immediately with no loss of information.

## Suggested acceptance checks

- At every page state, exactly one unfinished step is visibly and programmatically current.
- A user can identify completed, current, held, and waiting work from a static grayscale screenshot.
- A successful action visibly changes both the program list and the corresponding mission node.
- An invalid action leaves the workflow position unchanged and displays the reason.
- No motion communicates information that is absent from the static state.
- With reduced motion enabled, all state changes remain legible and complete.
- The visual remains understandable without prior knowledge of DobeWorks or DEGS.

## Primary sources

- Government Digital Service. (2026). [Complete multiple tasks](https://design-system.service.gov.uk/patterns/complete-multiple-tasks/).
- Kivetz, R., Urminsky, O., & Zheng, Y. (2006). [The goal-gradient hypothesis resurrected: Purchase acceleration, illusionary goal progress, and customer retention](https://s3.amazonaws.com/fieldexperiments-papers2/papers/00658.pdf). *Journal of Marketing Research, 43*(1), 39-58.
- National Aeronautics and Space Administration. (2014). [Human Integration Design Handbook, Revision 1](https://www.nasa.gov/wp-content/uploads/2023/03/human-integration-design-handbook-revision-1.pdf). NASA/SP-2010-3407/REV1.
- Nunes, J. C., & Dreze, X. (2006). [The endowed progress effect: How artificial advancement increases effort](https://msbfile03.usc.edu/digitalmeasures/jnunes/intellcont/Endowed%20Progress%20Effect-1.pdf). *Journal of Consumer Research, 32*(4), 504-512.
- Ryan, R. M., Rigby, C. S., & Przybylski, A. (2006). [The motivational pull of video games: A self-determination theory approach](https://selfdeterminationtheory.org/SDT/documents/2006_RyanRigbyPrzybylski_MandE.pdf). *Motivation and Emotion, 30*, 344-360.
- World Wide Web Consortium. (2025). [Understanding Success Criterion 2.3.3: Animation from interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions).
- World Wide Web Consortium. (2026). [ARIA26: Using `aria-current` to identify the current item in a set](https://www.w3.org/WAI/WCAG21/Techniques/aria/ARIA26).
- World Wide Web Consortium. (2025). [Understanding Success Criterion 4.1.3: Status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).
