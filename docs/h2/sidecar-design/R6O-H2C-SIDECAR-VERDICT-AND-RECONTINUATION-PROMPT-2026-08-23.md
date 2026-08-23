# R6O H2-C Sidecar — Verdict and Recontinuation Prompt

**Date:** 2026-08-23  
**Applies to:** PR #9 / H2-C-QUALIFICATION  
**Goal:** unchanged  
**TUI:** out of scope  
**Design authority:** `R6O-SIDECAR-DESIGN-SPEC-v1-2026-08-23.md`  
**Machine-readable authority:** `R6O-SIDECAR-DESIGN-CONTRACT-v1-2026-08-23.json`

## Gate verdict

```text
PR #9:
    REQUEST_CHANGES

H2-C COMPONENT / ARCHITECTURE BOUNDARY:
    PASS

H2-C SIDECAR VISUAL LOCK:
    FAIL / NOT YET APPROVED

H2-C HUMAN DESIGN APPROVAL:
    PENDING

KNOWN SIDECAR VISUAL DIVERGENCES:
    > 0

OVERALL H2:
    NOT AUTHORIZED
```

This is not an architecture failure. Do not reopen R6O-1, the TUI, D1, D2, E-series host E2E, or R6O-3.

The remaining work is a bounded **Sidecar design-conformance implementation**.

## Controlling references

Read these first:

```text
R6O-SIDECAR-DESIGN-SPEC-v1-2026-08-23.md
R6O-SIDECAR-DESIGN-CONTRACT-v1-2026-08-23.json
REFERENCE_SIDECAR_STANDARD.png
REFERENCE_SIDECAR_EXPANDED.png
```

The full `REFERENCE_UI-HARNESS.png` is provenance only. H2-C visual approval compares the Sidecar itself, not the surrounding host scene.

The synthetic qualification parent is not part of the visual approval boundary.

## Recontinuation instruction

You are continuing PR #9 as the H2-C Sidecar design-lock implementation.

The existing goal remains unchanged.

Your job is now narrower:

> **Make the Sidecar itself conform completely to the approved Sidecar design specification in both STANDARD and EXPANDED, with zero known Sidecar-owned visual deviations.**

Do not redesign the architecture.  
Do not reinterpret the reference.  
Do not declare an element optional because it is inconvenient to implement.  
Do not defer a known Sidecar-owned visual mismatch to D2 or E.

## First action — read-only conformance inventory

Before editing code, compare the current PR #9 Sidecar against the two canonical images and the design specification/contract.

Produce a finite conformance matrix with:

```text
ID
mode
reference element
current implementation
status
required implementation change
test/assertion
```

Allowed status:

```text
CONFORMANT
NONCONFORMANT
DESIGN_DECISION_REQUIRED
```

Do not use fuzzy statuses such as `close enough`, `acceptable difference`, or `defer to D2`.

If a requirement cannot be implemented without contradicting a protected functional contract:

```text
DESIGN_DECISION_REQUIRED
STOP THAT ITEM
ASK HUMAN
```

Otherwise fix it.

## Required STANDARD result

Target:

```text
REFERENCE_SIDECAR_STANDARD.png
675 × 300
```

Required visible design:

```text
PDLt Review
PROMPT REVIEW badge
green ACTIVE status
custom Expand control
custom Close control

Authoritative Prompt (PDL.md)
Open in Editor
external-link icon
artifact content surface
Source: Workspace File
/workspace/pdlt/PDL.md
Copy

Review Options
four reference action rows
number badges with reference emphasis
Tip text
```

Composition:

```text
artifact LEFT
Review Options RIGHT
```

The reference image controls visible proportions.

## Required EXPANDED result

Target:

```text
REFERENCE_SIDECAR_EXPANDED.png
412 × 806
```

Required composition:

```text
header

artifact TOP
    flexible / dominant visual area

Review Options BELOW
    natural content region
    not a stretched scroll container
```

The canonical reference visibly contains no public:

```text
LOCK
MOVE
Collapse button
```

Do not add one unless the human revises the design reference.

## Required removals

The canonical Sidecar must not visibly contain:

```text
LOCK
MOVE
native Tk/Windows scrollbars
native dotted focus rectangle
Projection snapshot footer
artifact:// debug reference
qualification labels
synthetic-parent labels
native Windows title bar
native minimize/maximize controls
native Windows close control
```

These may exist in logs/test fixtures if needed, but not in the Sidecar visual capture.

## Required additions/restorations

If absent, implement the visible reference controls:

```text
Open in Editor
external-link affordance
Copy
Tip text
reference action-number badges
reference action-row treatment
custom Sidecar chrome
```

Do not omit them and still claim conformance.

Keep their behavior presentation-only; use callbacks/interfaces rather than creating protocol authority.

## Canonical visual fixture

For design-lock captures, use the exact canonical fixture from the design contract, not the long qualification stress prompt.

Canonical content:

```text
# Prompt

Build a task manager with:
- User authentication
- Project management
- Task tracking
- Due dates and reminders

Target tech stack: React + FastAPI + SQLite
```

Actions:

```text
1 Confirm this prompt
2 Change the task
3 Change the approach
4 Something else...
```

Source:

```text
Source: Workspace File
/workspace/pdlt/PDL.md
```

Tip:

```text
Tip: Type directly in the chat below
to provide other feedback.
```

Stress/overflow fixtures stay separate.

## Scroll behavior

Canonical captures show no visible native scrollbar.

Therefore:

```text
canonical STANDARD:
    no visible native scrollbar

canonical EXPANDED:
    no visible native scrollbar

four normal Review Options:
    no scrollbar
```

Artifact overflow remains functionally testable in a separate stress case.

Do not introduce a new visible overflow design without human approval.

## Focus behavior

Keyboard accessibility remains required.

Canonical screenshots must not expose toolkit-default dotted/native focus chrome. Use Sidecar-owned focus styling consistent with the reference.

## Synthetic fixture rule

A synthetic parent may remain internally for:

```text
unit tests
geometry tests
component lifecycle tests
overflow tests
```

It is **not** H2-C visual approval evidence.

Visual approval captures the **Sidecar window only** at canonical dimensions.

## Preserve already-correct behavior

Do not regress:

```text
projection authority
projection-driven actions
FREE_RESPONSE_FOCUS semantics
close = View-only
terminal dismissal
expand behavior
artifact scrolling functionality
keyboard accessibility
stale handling
protected R6O-1 paths
```

Do not modify TUI code in this continuation.

## Required tests

Keep existing behavioral/component tests and add design-contract assertions.

At minimum:

### STANDARD

```text
675 × 300 canonical capture
horizontal artifact/options layout
Open in Editor present
Copy present
Tip present
Expand present
Close present
exactly four canonical action rows
LOCK absent
MOVE absent
debug footer absent
native scrollbar absent in canonical state
```

### EXPANDED

```text
412 × 806 canonical capture
artifact above Review Options
Open in Editor present
Copy present
Tip present
Close present
visible Collapse absent
LOCK absent
MOVE absent
Review Options not stretched as a scroll region
native scrollbar absent in canonical state
debug footer absent
```

### Both

```text
no native title bar
no native window controls
no toolkit-default dotted focus artifact in canonical capture
stage badge present
ACTIVE treatment present
reference action-badge structure present
```

Add overflow tests separately.

## Evidence capture

Produce:

```text
H2-C-STANDARD-SIDECAR.png
H2-C-EXPANDED-SIDECAR.png
H2-C-DESIGN-CONFORMANCE.json
```

The screenshots contain only the Sidecar.

Do not use a single fuzzy image-similarity score as pass/fail authority.

A raster diff may be generated diagnostically.

Approval requires:

```text
all explicit design requirements conform
AND
zero known Sidecar-owned visual differences remain
AND
human direct comparison approves both captures
```

## Completion report

Report:

```text
PR head
tree
changed files

STANDARD reference hash
STANDARD implementation capture hash

EXPANDED reference hash
EXPANDED implementation capture hash

design matrix:
    conformant count
    nonconformant count
    decision-required count

functional regression tests
design-contract tests
protected-path check
CI status

known Sidecar visual divergences
```

Required status before human review:

```text
H2-C_IMPLEMENTATION_CONFORMS_FOR_HUMAN_VISUAL_REVIEW
KNOWN_SIDECAR_VISUAL_DIVERGENCES = 0
```

Do not self-declare `H2-C HUMAN_PASS`.

## Independent Luna review

After code/evidence freeze, run a separate Luna review with fixed scope:

```text
1. protected-boundary integrity
2. Sidecar design-contract conformance
3. canonical STANDARD capture
4. canonical EXPANDED capture
5. required/forbidden element inventory
6. no evidence overclaim
7. no TUI/D2/E/R6O-3 leakage
```

For each design requirement Luna returns:

```text
CLOSED
REMAINS
EVIDENCE_INSUFFICIENT
```

Only after Luna reports no remaining P0/P1/design requirement does the candidate return to the human.

## Human approval boundary

The human compares:

```text
REFERENCE_SIDECAR_STANDARD.png
vs
H2-C-STANDARD-SIDECAR.png
```

and:

```text
REFERENCE_SIDECAR_EXPANDED.png
vs
H2-C-EXPANDED-SIDECAR.png
```

Approval means:

```text
100% SIDECAR DESIGN CONFORMANCE
ZERO KNOWN SIDECAR VISUAL DIVERGENCES
```

If any visible Sidecar-owned difference remains:

```text
REQUEST_CHANGES
```

No known visual debt is carried into D2.

## Final invariant

```text
H2-C locks what the Sidecar looks like.

D2 may later prove where that exact locked Sidecar lives.

D2 may not redesign it.
```
