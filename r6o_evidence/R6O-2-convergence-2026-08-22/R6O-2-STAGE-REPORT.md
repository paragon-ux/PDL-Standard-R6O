# R6O-2 Convergence Stage Report

Date: 2026-08-22  
PR: [#3](https://github.com/paragon-ux/PDL-Standard-R6O/pull/3)  
Resolution freeze: `R6O2-RF-2026-08-22-01`  
Frozen code: `f9d3a569c066486d6f621901097c75d477197a79`  
Frozen tree: `fcb217b869d852c8cc2880d3e065a4bbc3993ff3`

## Outcome

The finite approved resolution matrix is mechanically converged. The first independent review of superseded head `ebe5f9c` found one bounded P1: stale TUI text replacement projections did not run terminal/action-index lifecycle reconciliation. Head `f9d3a56` fixes that path and adds real stale-to-terminal plus stale-action-clamp regressions. No approved divergence remains open after the bounded repair, protected R6O-1 paths are unchanged, and the frozen R6S oracle remains clean at `60d982f3328b45a351879d67dc4bb525172b65fd`.

The official Expanded composition is artifact TOP / Review Options BELOW. This implements human decision `DR-R6O-2R-1`; the rejected horizontal alternative visibly compressed the UI.

The previous `r6o_evidence/R6O-2` visual mechanical PASS is historical and incomplete for the present contract: it did not prove live Standard→Expand→Collapse, floating-window placement, Close ownership, terminal dismissal, composer focus, or TUI post-revision action focus. Those files were not edited. This new evidence set is generated only after the converged code freeze.

## Qualification

`python scripts/verify_r6o2.py --display` on the exact frozen head:

- baseline verifier: PASS;
- baseline pytest: 9 passed;
- protected R6O-1 regression: 87 passed;
- R6O-2 Views: 25 passed;
- full suite: 112 passed, 5 display-gated skips;
- local display: 5 passed;
- public Standard and Expanded Sidecar display smokes: PASS;
- all six PR checks on GitHub Ubuntu and Windows: PASS for the replacement head.

The public runners support deterministic `--case G06|A02`, default G06. An unmatched recorded input preserves projection state, never falls back to a live model, and presents a fixture-specific notice without exposing `ReplayMissError` in the normal UI.

## Gate status

```text
NORMATIVE_RESOLUTIONS = FROZEN
APPROVED_DIVERGENCES_OPEN = 0
R6O2_CONVERGED_CODE_HEAD = f9d3a569c066486d6f621901097c75d477197a79
VISUAL_MECHANICAL_CONFORMANCE = PASS
INDEPENDENT_LUNA_REVIEW_1 = DOES_NOT_CONFORM_FOR_H2_REVIEW
INDEPENDENT_LUNA_REVIEW_2 = CONFORMS_FOR_H2_REVIEW
H2_HUMAN_VISUAL_DISPOSITION = PENDING
R6O_3 = BLOCKED
```

No mechanical or Luna result self-promotes H2. The next action is the human H2 exercise of the exact public commands against the frozen candidate.
