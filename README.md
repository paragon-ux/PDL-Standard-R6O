# PDL-Standard-R6O — R6O MVVM Presentation Vertical (implementation repo)

Local-only R6O implementation repository. NOT LIVE / NOT PUBLISHED.

- Repository: PDL-Standard-R6O
- Path: C:\Users\USER\Desktop\Frameworks\PDL-Standard-R6O
- Remote: none
- Baseline oracle (READ-ONLY): C:\Users\USER\Desktop\Frameworks\PDL-Standard-REPL-Harness @ 60d982f3328b45a351879d67dc4bb525172b65fd

## Rules

- The frozen R6S repository is read-only. Any need to patch it is a STOP condition.
- R6O-1 scope: contracts, current MVVM Model binding adapter, ViewModel, artifact abstraction, parity tests.
- No TUI, no Sidecar, no Codex integration, no second protocol harness.
- Views are not implemented in R6O-1.

## Run

From this repository root:

```powershell
python -m pytest r6o\tests -q
python scripts\verify_r6o1.py
```

Baseline tests are run against the frozen oracle repository by the verifier.
