# Independent Luna Max R6O-2 Conformance Review — Superseded Head

Review mode: read-only. No files, commits, branches, PR state, or external state were modified.

## Frozen scope

- Review range: `87717ea77975a9b9ac7637850926944e6ab4d48a..ebe5f9cab34dce928f22ec6a047c7fc9bf0cbdee`
- Frozen tree: `ddd89f27f75ae5b6fa4ba30a0eb768a4ff229940`
- PR: [paragon-ux/PDL-Standard-R6O#3](https://github.com/paragon-ux/PDL-Standard-R6O/pull/3)
- Resolution freeze: `R6O2-RF-2026-08-22-01`
- Frozen oracle: `60d982f3328b45a351879d67dc4bb525172b65fd`, clean
- Protected-path diff: empty

Implementation packet documents 00–05, routing instructions, convergence documents, freeze record, locked references, all six new convergence screenshots, evidence JSON/Markdown, exact diff, and current PR reviews were read.

## Executive result

The frozen candidate passed the geometry, public-runner, protected-boundary, baseline, and prior-finding repair checks. The official Expanded resolution was correctly implemented as artifact TOP / Review Options BELOW.

One new P1 interaction/stale defect remained:

`TuiController.submit_input()` only called `_projection_changed()` for `REVISION` results. `ProjectionViewState._apply()` updated the projection for `STALE_PROJECTION`, including a terminal projection, while the event loop exited only when `closed` became true.

A read-only real-session reproduction produced:

```text
result=STALE_PROJECTION
projection=TERMINAL
closed=False
state.closed=False
actions=0
```

Thus, a submitted stale free-response that yielded the authoritative terminal projection left the TUI running. A contract-shaped stale projection with fewer actions also left the old action index invalid and reproduced `IndexError` on subsequent action selection. This P1 View semantics/parity/stale failure blocked H2 presentation.

## Approved resolution disposition

| Approved IDs | Status | Concise evidence |
|---|---|---|
| NR-0.1, NR-0.2, NR-0.3 | CLOSED | Protected diff empty; boundary/parity tests passed; no R6O-3 machinery. |
| NR-1.1, NR-1.2, NR-1.3, NR-1.4 | CLOSED | Standard/Expanded geometry and live controls passed. |
| NR-2.1, NR-2.2, NR-2.3 | CLOSED | View-only Close, composer focus, no launcher, fresh reconstruction. |
| NR-3.1, NR-3.2, NR-3.3 | CLOSED | Free-response and navigation behavior passed. |
| NR-3.4 | REMAINS | Stale free-response terminal projection did not close/yield the TUI. |
| NR-4.1a through NR-4.12 | CLOSED | Window, work-area, DPI, placement, lock, transition, and screenshot evidence passed. |
| NR-5.1, NR-5.2a, NR-5.3 | CLOSED | Sidecar terminal and authority behavior passed. |
| NR-5.2b | REMAINS | TUI did not exit for the stale terminal projection. |
| NR-6.1 through NR-12.7 | CLOSED | Frozen composition, qualification, replay, footer, width/action, and Sidecar lifecycle requirements passed. |
| NR-13.1 through NR-13.5, NR-13.7 | CLOSED | Public event loop and normal interaction behavior passed. |
| NR-13.6 | REMAINS | Terminal projection from stale free-response did not stop the event loop. |
| NR-14.1, NR-14.2 | CLOSED | Harness boundaries passed. |
| NR-15.1 | REMAINS | Completion checklist was incomplete while stale terminal remained. |
| NR-16.1, NR-17.1, NR-18.1 | CLOSED | Evidence history, bounded scope, and H2 boundary passed. |

Disposition count: 70 `CLOSED`, 4 `REMAINS`, 0 `EVIDENCE_INSUFFICIENT`.

## Independent checks

| Check | Result |
|---|---|
| Duplicate authority | PASS |
| Semantic bypass | PASS |
| Protected R6O-1 mutation | PASS |
| Frozen-oracle mutation | PASS |
| R6O-3 leakage | PASS |
| Public executable viability | PASS |
| Baseline/environment containment | PASS |
| Visual/geometry conformance | PASS mechanically; H2 pending |
| Interaction/parity/stale | FAIL — P1 stale terminal TUI defect |
| Qualification/evidence truthfulness | FAIL for the then-current zero-P1 claim |

## Required disposition

The P1 stale terminal behavior required a bounded View-layer repair and a new exact code freeze/review. It was repaired in follow-up commit `f9d3a569c066486d6f621901097c75d477197a79`; this review remains preserved as the reason for that bounded delta.

DOES_NOT_CONFORM_FOR_H2_REVIEW
