# R6O-2 Rewrite Stage Report

Status: **IMPLEMENTATION FROZEN FOR INDEPENDENT H2 REVIEW**  
Human gate: **H2 NOT SELF-APPROVED**

## Frozen anchors

- Base: `87717ea77975a9b9ac7637850926944e6ab4d48a` / tree `ef4aa93eb75043227ade2cfffffd58d5b0efa9ac`
- Qualified code: `51456ba321c059c717aeefdba83b14f0d002cebe` / tree `24221ae218795dd7e210073a54e94fae77603dc6`
- Branch: `codex/r6o-2-view-rewrite`
- Frozen R6S oracle: `60d982f3328b45a351879d67dc4bb525172b65fd` / tree `b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6`

## Implementation

- Cross-platform persistent raw-key/ANSI TUI event loop with responsive wide/stacked layout, editable input, keyboard focus/action navigation, resize redraw, artifact scrolling, and stale/error notices.
- Custom-styled Tk Sidecar qualification harness with no Sidecar-owned input.
- Standard: fixed 280 px panel above the host composer, horizontal artifact/options composition, measured 70/30 internal split.
- Expanded: right-anchored 48.7% panel, host and composer confined left, artifact above content-height options.
- Narrow mechanical `PresentationAdapter` exposing only current projection and `InputEnvelope` submission.
- Provenance-validated recorded worker composition that does not require ambient `PYTHONPATH` and uses the public session returned by `start_or_resume()`.

## Public commands

```powershell
python scripts\run_r6o2_tui.py --recorded
python scripts\run_r6o2_sidecar.py --recorded --harness --mode STANDARD
python scripts\run_r6o2_sidecar.py --recorded --harness --mode EXPANDED
python scripts\verify_r6o2.py --display
```

All commands passed their applicable launch/qualification gates. The exact runner smoke tests execute in clean subprocess environments without `PYTHONPATH`.

## Semantic qualification

- G06 TUI and Sidecar: `PROMPT_REVIEW -> PLAN_REVIEW -> CLOSED_SUCCESS`.
- G06 authoritative Prompt and Plan outputs are equivalent across Views.
- A02 TUI `TUI_TEXT` and Sidecar harness `HOST_COMPOSER_TEXT` produce the same revised Prompt Review state.
- NEW activation is submitted exactly once; Views begin from the first projection returned after `start_or_resume(task_text=...)`.
- Cross-View stale action fails closed, replaces the projection, displays a mechanical notice, and does not retry.

## Verification

- Frozen baseline verifier: PASS.
- Frozen baseline pytest: 9 passed.
- Accepted R6O-1 regression: 87 passed.
- R6O-2 View suite: 19 passed.
- Full suite: 106 passed; four display tests explicitly gated locally.
- Local display gate: 4 passed.
- GitHub Actions push run `32550627928`: Ubuntu and Windows PASS.
- Protected R6O-1 paths: unchanged from accepted merge.
- Frozen oracle physical inventory: unchanged.

## Visual evidence

Screenshots under `r6o_evidence/R6O-2/screenshots/` were generated from the public runners after code freeze. Their hashes and measured geometry are recorded in `R6O-2-VISUAL-MECHANICAL-CONFORMANCE.json`.

```text
VISUAL_MECHANICAL_CONFORMANCE = PASS
H2_HUMAN_VISUAL_DISPOSITION = PENDING
```

## Finding status

- A1: **fixed** — the implementation packet now explicitly makes View Contract v3 sections 4/11 and `REFERENCE_UI-HARNESS.png` authoritative for Expanded composition; the older horizontal Expanded inset is superseded for layout. Amended View Contract SHA-256: `91202d65892ccebfcffaa647d928cd4acb49b615d671d21a4c977ca266ee625c`.
- CI-1: **fixed** — canonical CI now fetches full history so the accepted protected-baseline comparison can resolve `87717ea` on both platforms.

## Remaining gates

- Independent fixed-scope read-only review: pending.
- Human direct use and H2 disposition: pending.
- R6O-3: blocked until human H2 promotion.

No `DECISION_REQUEST` was required. No known P0/P1 remains from implementation qualification. The GitHub Node.js action-runtime deprecation annotation is a provider/tooling P3 observation and does not affect View behavior.

```text
IMPLEMENTATION FROZEN FOR INDEPENDENT H2 REVIEW
H2 NOT SELF-APPROVED
```
