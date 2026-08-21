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
