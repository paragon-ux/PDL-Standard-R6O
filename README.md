# PDL-Standard-R6O

Published R6O implementation repository for the accepted R6O-1 MVVM vertical
and its independently gated H2 presentation work.

- Repository: `paragon-ux/PDL-Standard-R6O`
- Frozen R6S oracle commit: `60d982f3328b45a351879d67dc4bb525172b65fd`
- Frozen R6S oracle tree: `b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6`
- Oracle mutation policy: read-only

## Rules

- The frozen R6S repository is read-only. Any need to patch it is a STOP condition.
- R6O-1 protected scope: contracts, Model binding adapter, ViewModel,
  artifact abstraction, and parity tests.
- H2 work proceeds through independent gates and dedicated pull requests.
- A later H2 gate must not be inferred to have passed from an earlier gate.

## Bind and verify the frozen oracle

Run from this repository root in PowerShell. The prompt requires the real
absolute path to your local frozen oracle checkout; do not enter a sample or
placeholder path.

```powershell
$OracleRoot = Read-Host 'Absolute path to the frozen PDL-Standard-REPL-Harness checkout'
$OracleRoot = (Resolve-Path -LiteralPath $OracleRoot -ErrorAction Stop).Path

$ExpectedCommit = '60d982f3328b45a351879d67dc4bb525172b65fd'
$ExpectedTree = 'b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6'
$ActualCommit = (git -C $OracleRoot rev-parse HEAD).Trim()
$ActualTree = (git -C $OracleRoot rev-parse 'HEAD^{tree}').Trim()

if ($ActualCommit -ne $ExpectedCommit) {
    throw "Wrong frozen-oracle commit: $ActualCommit"
}
if ($ActualTree -ne $ExpectedTree) {
    throw "Wrong frozen-oracle tree: $ActualTree"
}
if (-not (Test-Path -LiteralPath "$OracleRoot\scripts\verify_repl_baseline.py" -PathType Leaf)) {
    throw "Not an R6S oracle checkout: $OracleRoot"
}

$env:PDL_R6S_BASELINE_REPO = $OracleRoot
python -m pytest r6o\tests -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw 'R6O pytest failed' }
python scripts\verify_r6o1.py
if ($LASTEXITCODE -ne 0) { throw 'R6O-1 verification failed' }
```

The verifier clones the bound frozen oracle into temporary storage before
running its own verifier and pytest suite, preventing ignored-file writes in
the oracle checkout.

## H2-A2 qualification

H2-A2 freezes the complete deterministic `A02-FULL` fixture. After binding and
verifying the oracle above, run:

```powershell
python scripts\h2\verify_a02_full_fixture.py --baseline-repo $OracleRoot
if ($LASTEXITCODE -ne 0) { throw 'H2-A2 fixture verification failed' }
python -m pytest r6o\tests\h2\test_a02_full_fixture.py -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw 'H2-A2 focused pytest failed' }
```

Expected terminal status from the first command:

```text
"status": "A02_FULL_FIXTURE_PASS"
```

The `--record` mode is not an ordinary qualification command. It replaces the
frozen fixture using a live worker and therefore additionally requires the
explicit `--approve-live-recording` acknowledgement.
