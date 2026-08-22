# PDL-Standard-R6O — R6O MVVM Presentation Vertical (implementation repo)

Published R6O implementation repository for the R6O-1 MVVM vertical.

- Repository: paragon-ux/PDL-Standard-R6O
- Path: C:\Users\USER\Desktop\Frameworks\PDL-Standard-R6O
- Remote: https://github.com/paragon-ux/PDL-Standard-R6O
- Baseline oracle (READ-ONLY): C:\Users\USER\Desktop\Frameworks\PDL-Standard-REPL-Harness @ 60d982f3328b45a351879d67dc4bb525172b65fd

## Rules

- The frozen R6S repository is read-only. Any need to patch it is a STOP condition.
- R6O-1 scope: contracts, current MVVM Model binding adapter, ViewModel, artifact abstraction, parity tests.
- No TUI, no Sidecar, no Codex integration, no second protocol harness.
- Views are not implemented in R6O-1.

## Run

From this repository root:

```powershell
$env:PDL_R6S_BASELINE_REPO='C:\path\to\PDL-Standard-REPL-Harness'
python -m pytest r6o\tests -q
python scripts\verify_r6o1.py
```

The verifier clones the bound frozen oracle into temporary storage before
running its own verifier and pytest suite, preventing ignored-file writes in
the oracle checkout.

## R6O-2 — TUI and Sidecar Views

R6O-2 adds two disposable public Views over the accepted R6O-1 ViewModel:

- `python scripts/run_r6o2_tui.py` — terminal TUI View (free response via `TUI_TEXT`).
- `python scripts/run_r6o2_sidecar.py --harness --mode STANDARD|EXPANDED` — graphical Sidecar in the qualification harness (host composer routes `HOST_COMPOSER_TEXT`; the Sidecar panel has no text input).
- `python scripts/verify_r6o2.py [--display]` — mechanical H2 gates: baseline verifier/tests, R6O-1 regression, R6O-2 view tests, full suite, and live-oracle physical inventory. `--display` runs opt-in Tk checks.

Reference fidelity is pinned by `PDL-Archival/R6O-2-OFFICIAL-HANDOFF-2026-08-21-r2.md` and `R6O-2-VISUAL-GUIDE-REFERENCE.md`; the locked visual guide is `PDLt-R6O-Vertical-Presentation-Implementation-v2.0/references/`.
