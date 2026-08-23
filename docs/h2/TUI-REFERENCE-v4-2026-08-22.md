# PDLt TUI Reference v4
## H2 Visual / Interaction Reference

**Date:** 2026-08-22  
**Status:** Proposed replacement for the superseded TUI Reference v3  
**Basis:** Current working H2 TUI direction as observed in Screenshot #521, plus the approved H2-A1 interaction contract  
**Scope:** Presentation and keyboard behavior only; no Model/ViewModel authority

---

# 1. Design direction

The current single-column TUI direction is preferred over the older v3 two-column mock.

The TUI should feel like a compact terminal review workspace, not like a printed transcript and not like a terminal imitation of the GUI Sidecar.

The primary hierarchy is:

```text
PDLt / stage / status
    ↓
authoritative artifact
    ↓
review actions
    ↓
contextual keyboard help
    ↓
free-response input only when focused/active
```

The View remains a persistent event-loop screen.

---

# 2. Canonical normal review state

Preferred wide-terminal presentation:

```text
┌─ PDLt · PLAN REVIEW ─────────────────────────────────────────── ACTIVE ─┐
│                                                                        │
│ Authoritative Response Plan (PDL.md)                                   │
│ ────────────────────────────────────────────────────────────────────── │
│ IDENTIFY the target audience as senior developers                      │
│ INTRODUCE the subject of concurrency control                           │
│ DEFINE optimistic locking                                              │
│ DEFINE pessimistic locking                                             │
│ COMPARE the two approaches                                             │
│ SUMMARIZE the differences                                              │
│                                                                        │
│ Review Options                                                         │
│                                                                        │
│  > 1  Confirm plan                                                     │
│    2  Change the task                                                  │
│    3  Change approach                                                  │
│    4  Something else...                                                │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│ ↑↓ / Tab  Move     Enter  Select     F5  Refresh     Ctrl+Q  Close     │
└────────────────────────────────────────────────────────────────────────┘
```

The selected action uses a single consistent cursor:

```text
>
```

Do not duplicate selection state with both:

```text
>
[Enter]
*
highlight text
```

unless the terminal toolkit provides a native accessible highlight.

---

# 3. Prompt Review

Prompt and Plan use the same shell.

Only the stage and authoritative artifact label change.

```text
┌─ PDLt · PROMPT REVIEW ───────────────────────────────────────── ACTIVE ─┐
│                                                                        │
│ Authoritative Prompt (PDL.md)                                          │
│ ────────────────────────────────────────────────────────────────────── │
│ COMPARE Kafka and RabbitMQ for event delivery.                         │
│ - delivery guarantees                                                  │
│ - throughput                                                           │
│ - consumer model                                                       │
│ - operations burden                                                    │
│ - ecosystem maturity                                                   │
│ - operational complexity                                               │
│                                                                        │
│ Review Options                                                         │
│                                                                        │
│  > 1  Confirm prompt                                                   │
│    2  Change the task                                                  │
│    3  Change approach                                                  │
│    4  Something else...                                                │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│ ↑↓ / Tab  Move     Enter  Select     F5  Refresh     Ctrl+Q  Close     │
└────────────────────────────────────────────────────────────────────────┘
```

Do not render a second standalone line such as:

```text
PDLt REVIEW
===========
PROMPT REVIEW
```

The stage belongs in the single top frame/header.

---

# 4. Free-response focus state

H2-A1 Option A remains authoritative:

```text
Something else...
    -> FREE_RESPONSE_FOCUS
    -> no semantic review text is submitted by the action
```

When free-response focus is active, the same screen remains visible and the input replaces the ordinary help footer.

```text
┌─ PDLt · PROMPT REVIEW ───────────────────────────────────────── ACTIVE ─┐
│                                                                        │
│ Authoritative Prompt (PDL.md)                                          │
│ ────────────────────────────────────────────────────────────────────── │
│ ...                                                                    │
│                                                                        │
│ Review Options                                                         │
│    1  Confirm prompt                                                   │
│    2  Change the task                                                  │
│    3  Change approach                                                  │
│  > 4  Something else...                                                │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│ Review > The audience should be data engineers, not backend engineers. │
├────────────────────────────────────────────────────────────────────────┤
│ Enter  Submit review        Esc  Return to actions        Ctrl+Q Close │
└────────────────────────────────────────────────────────────────────────┘
```

Normative:

```text
Enter
    -> exactly one TUI_TEXT submission

Esc
    -> presentation focus only
    -> no semantic submission
```

After a successful revised review projection:

```text
input closes/collapses
artifact redraws
actions redraw
focus returns to primary structured action
```

No restart is required.

---

# 5. Artifact scrolling

When the artifact does not fit:

```text
Authoritative Response Plan (PDL.md)                            4–18 / 31
──────────────────────────────────────────────────────────────────────────
...
```

or an equivalent compact scroll indicator may be shown.

Requirements:

- scrolling must not move action focus;
- the selected review action must remain visible;
- the artifact is independently scrollable;
- the footer remains fixed;
- no line-number gutter is required;
- no debug revision hash is shown by default.

Preferred navigation:

```text
PgUp / PgDn
or
toolkit-native artifact scroll keys
```

Do not overload Up/Down if those keys are currently moving action selection unless focus is explicitly in the artifact region.

---

# 6. Visual hierarchy

## Required hierarchy

Use three levels only:

### Level 1 — screen identity

```text
PDLt · <STAGE>                                      <STATUS>
```

### Level 2 — section labels

```text
Authoritative Prompt (PDL.md)
Authoritative Response Plan (PDL.md)
Review Options
```

### Level 3 — content/actions/help

No additional title layer is needed.

## Avoid

```text
PDLt REVIEW
===========
PLAN REVIEW
-----------
Authoritative Response Plan
```

That produces unnecessary visual repetition and is the primary polish issue visible in Screenshot #521.

---

# 7. Borders and separators

Preferred:

```text
single outer frame
one thin artifact divider
one footer divider
```

Avoid full-width repeated:

```text
==============================
------------------------------
```

unless the terminal does not support box-drawing characters.

Fallback for ASCII-only terminals is allowed:

```text
+------------------------------+
| ...
+------------------------------+
```

The View must remain usable without Unicode box drawing.

---

# 8. Spacing

Use compact but deliberate vertical rhythm.

Preferred:

```text
header
blank
artifact label
divider
artifact
blank
Review Options
blank
actions
blank
footer
```

Do not leave large unused blank terminal regions merely because the terminal window is taller.

The outer application may occupy the current terminal viewport, but content should remain top-biased and compact.

---

# 9. Width / reflow behavior

## Normal width

At sufficient width:

```text
single-column artifact-then-actions layout
```

is canonical.

Do not revert automatically to the older v3 artifact-left/actions-right design.

## Narrow width

On narrow terminals:

- preserve the same semantic order;
- wrap artifact lines;
- wrap long action labels with hanging indentation if necessary;
- every projected action remains reachable;
- footer help may abbreviate.

Example:

```text
↑↓ move  Enter select  Q close
```

No enabled action may disappear because the viewport is small.

---

# 10. Action rendering

Canonical action shape:

```text
  > 1  Confirm prompt
    2  Change the task
    3  Change approach
    4  Something else...
```

Requirements:

- ordinal comes from the projection;
- label comes from the projection;
- selection is presentation state only;
- primary semantic action may receive subtle emphasis if terminal capabilities support it;
- color is optional, never semantically required;
- do not append `[Enter]` only to the selected action;
- do not hard-code Prompt labels for Plan Review.

---

# 11. Status

Allowed top-right status examples:

```text
ACTIVE
STALE
WAITING
```

Do not display:

```text
CLOSED_SUCCESS
```

as a persistent third review screen.

On terminal completion:

```text
View exits
terminal restores
control returns to caller
```

Errors/stale notices may appear transiently in the footer or dedicated status line without becoming an authoritative artifact.

---

# 12. Error / stale presentation

Example:

```text
┌─ PDLt · PROMPT REVIEW ───────────────────────────────────────── STALE ──┐
...
├────────────────────────────────────────────────────────────────────────┤
│ State changed. Refreshing authoritative review...                      │
└────────────────────────────────────────────────────────────────────────┘
```

Requirements:

- no semantic guessing;
- no raw Python exception as primary UI;
- no worker fixture traceback in normal presentation;
- preserve current authoritative artifact when safe;
- refresh through accepted ViewModel behavior.

---

# 13. Keyboard contract

Normal review:

```text
Up / Down    previous / next action
Tab          next focusable region
Shift+Tab    previous focusable region
Enter        activate selected structured/focus action
F5           refresh current projection
Ctrl+Q       close TUI View only
```

Free-response focus:

```text
Enter        submit one TUI_TEXT envelope
Esc          return to review actions without submission
Ctrl+Q       close TUI View only
```

Artifact-focus keys may be added by the implementation if they do not conflict with the above.

---

# 14. Terminal lifecycle

The TUI must use a persistent terminal/event-loop View.

It must not:

```text
print frame
read line
print another complete frame
```

as its public interaction model.

On View close:

```text
restore terminal
return to invoker
do not mutate protocol state merely because View closed
```

On PDLt terminal state:

```text
restore terminal
return to invoker
```

---

# 15. Reference relationship to Sidecar

TUI and Sidecar share:

```text
same FocusProjection
same projected actions
same InputEnvelope semantics
same authoritative artifact
same terminal semantics
```

They do NOT need identical visual composition.

The Sidecar reference remains:

```text
REFERENCE_UI-HARNESS.png
```

The TUI reference is this document.

Parity is semantic/behavioral, not pixel identity.

---

# 16. What Screenshot #521 gets right

The current implementation direction already improves on TUI Reference v3 by providing:

- a straightforward artifact-first reading order;
- actions immediately following the artifact;
- clear selected-action cursor;
- no fake GUI-like columns;
- simple terminal-native interaction;
- stage-specific Plan content;
- a persistent interaction screen rather than transcript output.

Those properties should be retained.

---

# 17. What should be polished from Screenshot #521

Before treating the TUI as visually frozen:

1. collapse `PDLt REVIEW` + `PLAN REVIEW` into one framed header;
2. replace stacked `====` / `----` separators with one coherent frame/divider system;
3. remove `[Enter]` from the selected action because the cursor already conveys selection;
4. use `Review Options` rather than generic `ACTIONS`;
5. place navigation help in a fixed footer;
6. add explicit status at top-right;
7. add a distinct free-response-focus footer/input state;
8. avoid large unused lower screen area where the toolkit can size content more naturally;
9. ensure scroll state is visible only when needed;
10. keep action labels and artifact text projection-driven.

---

# 18. H2 qualification evidence for the TUI

A screenshot is presentation evidence only.

H2-B1/B2 must additionally prove:

```text
real public process
real keyboard events
actual projection changes
actual worker operation sequence
artifact hashes
terminal exit
```

Required visual evidence should include:

```text
Prompt Review / action focus
Prompt Review / free-response focus
Revised Prompt / action focus
Plan Review / action focus
```

The exact same TUI process must progress between these states.

---

# 19. Reference status

If human-approved:

```text
TUI-REFERENCE-v4 = controlling H2 TUI presentation reference
TUI-REFERENCE-v3 = superseded
```

This reference does not authorize H2-B implementation before its gate dependencies are satisfied.
