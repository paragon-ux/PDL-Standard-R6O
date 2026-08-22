# Independent Luna Max R6O-2 Follow-up Review

Read-only review. No files, commits, branches, PR state, or external state were modified.

## Frozen scope

- Review range: `87717ea77975a9b9ac7637850926944e6ab4d48a..f9d3a569c066486d6f621901097c75d477197a79`
- Frozen tree: `fcb217b869d852c8cc2880d3e065a4bbc3993ff3`
- Repaired delta: `ebe5f9cab34dce928f22ec6a047c7fc9bf0cbdee..f9d3a569c066486d6f621901097c75d477197a79`
- Delta files only:
  - `r6o/views/tui/controller.py`
  - `r6o/tests/test_tui_view.py`
- Protected-path diff: empty.
- Frozen oracle: `60d982f3328b45a351879d67dc4bb525172b65fd`, clean.
- Resolution freeze: `R6O2-RF-2026-08-22-01`.
- All six current GitHub Ubuntu/Windows check runs pass.

The updated convergence evidence, including the superseded Luna review, code-freeze record, closure ledger, finding disposition, stage report, tests, six screenshots, and geometry evidence, was read completely.

## Former P1 closure

The prior review found that stale text projections bypassed TUI terminal closure and action-index reconciliation.

The repair now routes every text-submission result carrying a replacement projection through `_projection_changed()`.

Independent verification:

```text
real G06 stale text:
result=STALE_PROJECTION
projection=CLOSED_SUCCESS
closed=True
actions=0
```

The new regression tests pass:

- real stale G06 text projection reaches `CLOSED_SUCCESS` and closes the TUI;
- stale replacement projection with fewer actions clamps the action index;
- targeted tests: 2 passed;
- full verifier: baseline 9, R6O-1 87, R6O-2 25, full 112 passed, 5 display skips;
- local display gate: 5 passed;
- public Standard and Expanded Sidecar smokes: passed.

No delta regression was found.

## Approved resolution disposition

All 74 approved IDs are unique and mechanically closed. `CLOSED` here means implementation and supplied evidence conform; it does not self-promote human H2 approval. H2 remains pending externally. No ID is `REMAINS` or `EVIDENCE_INSUFFICIENT`.

| Approved IDs | Status | Evidence |
|---|---|---|
| NR-0.1, NR-0.2, NR-0.3 | CLOSED | Protected diff empty; boundary/parity tests pass; no duplicate authority or R6O-3 machinery. |
| NR-1.1, NR-1.2, NR-1.3, NR-1.4 | CLOSED | Standard horizontal and Expanded artifact-TOP/options-BELOW geometry, live controls, and layout reset pass. |
| NR-2.1, NR-2.2, NR-2.3 | CLOSED | View-only Close, composer focus, no launcher, and fresh reconstruction pass. |
| NR-3.1, NR-3.2, NR-3.3, NR-3.4 | CLOSED | Free-response focus, A02 revision focus, navigation, normal terminal exit, and repaired stale-terminal exit pass. |
| NR-4.1a, NR-4.1b, NR-4.2a, NR-4.2b, NR-4.2c, NR-4.2d, NR-4.3, NR-4.4a, NR-4.4b, NR-4.5a, NR-4.5b, NR-4.5c, NR-4.6, NR-4.7, NR-4.8, NR-4.9, NR-4.10a, NR-4.10b, NR-4.10c, NR-4.10d, NR-4.10e, NR-4.11, NR-4.12 | CLOSED | Separate owned/transient frameless window; exact work-area, DPI, composer-anchor, 30% Expanded, inset, clearance, lock, transition, and screenshot evidence pass. |
| NR-5.1, NR-5.2a, NR-5.2b, NR-5.3 | CLOSED | No model-response fallback; Sidecar and normal/stale TUI terminal dismissal pass; no handoff authority. |
| NR-6.1 | CLOSED | Frozen human decision is preserved: Expanded artifact TOP / Review Options BELOW. |
| NR-7.1, NR-7.2, NR-7.3, NR-7.4, NR-7.5 | CLOSED | Required transition/lifecycle evidence passes and correctly leaves H2 pending. |
| NR-8.1, NR-8.2, NR-8.3 | CLOSED | Public G06/A02 cases, friendly replay-miss handling, no mutation, and no live fallback pass. |
| NR-9.1 | CLOSED | Default UI has no revision footer; diagnostics are explicit debug-only behavior. |
| NR-10.1, NR-10.2, NR-11.1 | CLOSED | Minimum viewport action reachability/cues and width invariants pass. |
| NR-12.1, NR-12.2, NR-12.3, NR-12.4, NR-12.5, NR-12.6, NR-12.7 | CLOSED | Real G06/A02 projection, action, composer, terminal, Close, and reconstruction flows pass. |
| NR-13.1, NR-13.2, NR-13.3, NR-13.4, NR-13.5, NR-13.6, NR-13.7 | CLOSED | Public TUI lifecycle, keyboard behavior, structured flow, and repaired stale-terminal replacement flow pass. |
| NR-14.1, NR-14.2 | CLOSED | Harness ownership and neutral-fixture boundary checks pass. |
| NR-15.1 | CLOSED | Updated completion checklist is mechanically satisfied. |
| NR-16.1 | CLOSED | Historical evidence remains untouched; separate post-freeze evidence records the prior incomplete PASS and repaired head. |
| NR-17.1 | CLOSED | Repair is bounded to the approved View/test delta; protected paths and R6O-3 boundary remain unchanged. |
| NR-18.1 | CLOSED | Mechanical/Luna results do not promote H2; H2 remains pending and R6O-3 remains blocked. |

## Prior finding triage

All prior findings, including lower-severity findings, remain explicitly accounted for:

- Luna F1 P2 TUI border width: fixed.
- Luna F2 P2 minimum-viewport action reachability: fixed.
- H2-3-F1 P1 horizontal Expanded guidance: superseded only where conflicting; transition/layout defect fixed.
- H2-3-F2 through H2-3-F6 P1 findings: fixed.
- H2-3-F7 and H2-3-F8 P2 findings: fixed.
- V3-01 through V3-08 P1 findings: fixed.
- V3-09 P2 footer finding: fixed.
- New convergence C1 P1 stale text projection finding: fixed by `f9d3a56` and covered by real regressions.

No lower-severity finding was discarded. The historical tracked stage report's trailing whitespace remains a non-functional P3 observation.

## Independent architecture checks

| Check | Result |
|---|---|
| Duplicate authority | PASS |
| Semantic bypass | PASS |
| Protected R6O-1 mutation | PASS |
| Frozen-oracle mutation | PASS |
| R6O-3 leakage | PASS |
| Public executable viability | PASS |
| Baseline/environment containment | PASS |
| Interaction/parity/stale | PASS after bounded repair |
| Visual/geometry fidelity | PASS mechanically; Expanded is vertical per frozen human resolution |
| Qualification/evidence truthfulness | PASS; H2 remains explicitly pending |

CONFORMS_FOR_H2_REVIEW
