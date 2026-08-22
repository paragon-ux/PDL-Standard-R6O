# PDL-Standard-R6O — R6O MVVM Presentation Vertical

Published R6O implementation repository. R6O-1 supplies the accepted and
protected Model Port/ViewModel; R6O-2 adds disposable public Views over it.

- Repository: paragon-ux/PDL-Standard-R6O
- Path: C:\Users\USER\Desktop\Frameworks\PDL-Standard-R6O
- Remote: https://github.com/paragon-ux/PDL-Standard-R6O
- Baseline oracle (READ-ONLY): C:\Users\USER\Desktop\Frameworks\PDL-Standard-REPL-Harness @ 60d982f3328b45a351879d67dc4bb525172b65fd

## Rules

- The frozen R6S repository is read-only. Any need to patch it is a STOP condition.
- R6O-1 contracts, Model binding, and ViewModel are protected.
- R6O-2 Views contain no controller, runtime, worker, or artifact authority.
- The R6O-2 Sidecar is a qualification harness; real host lifecycle integration remains R6O-3 scope.

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

## R6O-2 public Views

From the repository root, with the frozen sibling baseline present or
`PDL_R6S_BASELINE_REPO` set:

```powershell
python scripts\run_r6o2_tui.py --recorded
python scripts\run_r6o2_tui.py --recorded --case A02
python scripts\run_r6o2_sidecar.py --recorded --harness --mode STANDARD
python scripts\run_r6o2_sidecar.py --recorded --harness --mode EXPANDED
python scripts\run_r6o2_sidecar.py --recorded --harness --case A02 --mode STANDARD
python scripts\verify_r6o2.py --display
```

`G06` is the default structured Prompt/Plan case. `A02` is the recorded
free-response revision case. Its exact deterministic revision starts preloaded
in the TUI input line or Sidecar host composer: choose `4 Something else...`,
then press `Enter`/`Send` without editing the selected text. An unrecorded
qualification input reports a friendly deterministic-fixture notice and never
falls back to a live worker.
The TUI is a persistent raw-key event-loop screen. The Sidecar is a separate,
owned floating window over a neutral fullscreen parent and uses the parent
composer for free-response input, with no duplicate text box. Closing the
Sidecar leaves the parent running; press `Ctrl+Q` to exit the parent harness.
Mechanical visual conformance does not constitute human H2 acceptance.
