# R6O-2 H2 Follow-up Stage Report

Date: 2026-08-22

PR: [#3](https://github.com/paragon-ux/PDL-Standard-R6O/pull/3)

Resolution freeze: `R6O2-RF-2026-08-22-01`

Frozen code: `b1802d49e33e8a6449c27a2839aa682083d11666`

Frozen tree: `e1b6d58023afde47f836b6674d7a74c5055cf8d7`

## Outcome

The prior H2 candidate was rejected after the public GUI displayed only the fullscreen parent/composer in both modes and A02 did not expose the exact deterministic response it required. Those were two valid P1 findings against the prior freeze. The old evidence directories are preserved unchanged.

The bounded follow-up fixes native Win32 ownership and owned-window Z-order for the frameless Sidecar, adds a capture path that fails closed unless the Sidecar is actually above its owner, and adds a pixel-level live regression. Standard now visibly renders as the horizontal artifact-left/options-right surface. Expanded visibly renders as the human-approved artifact-TOP/options-BELOW right rail.

A02 now preloads the exact recorded revision in both public Views, selects it in the Sidecar composer, displays case-specific instructions, and uses case-specific replay-miss guidance. Real TUI and Sidecar tests submit through the public semantic path and reach the revised prompt.

## Qualification

`python scripts/verify_r6o2.py --display` on the exact frozen head:

- baseline verifier: PASS;
- baseline pytest: 9 passed;
- protected R6O-1 regression: 87 passed;
- R6O-2 Views: 26 passed;
- full suite: 113 passed, 6 display-gated skips;
- local display gate: 6 passed;
- public Standard and Expanded Sidecar display smokes: PASS;
- all six PR checks on GitHub Ubuntu and Windows: PASS;
- independent Luna Max review: `CONFORMS_FOR_H2_REVIEW`.

## Gate status

```text
NORMATIVE_RESOLUTIONS = FROZEN
EXPANDED_COMPOSITION = ARTIFACT_TOP_OPTIONS_BELOW
H2_4_F1 = FIXED
H2_4_F2 = FIXED
R6O2_H2_FOLLOWUP_CODE_HEAD = b1802d49e33e8a6449c27a2839aa682083d11666
VISUAL_MECHANICAL_CONFORMANCE = PASS
INDEPENDENT_LUNA_REVIEW_3 = CONFORMS_FOR_H2_REVIEW
H2_HUMAN_VISUAL_DISPOSITION = PENDING_RETEST
R6O_3 = BLOCKED
```

The next action is a new human H2 exercise of the exact public commands against this frozen candidate. No mechanical, CI, or Luna result self-promotes H2.
