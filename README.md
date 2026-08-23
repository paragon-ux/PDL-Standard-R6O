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

## H2-D1 qualification (Windows only)

H2-D1 binds to the installed Codex desktop application. Run these commands from
the repository root on Windows with exactly one Codex top-level window open:

```powershell
python -m pip install -r requirements-r6o2-host.txt
if ($LASTEXITCODE -ne 0) { throw 'H2-D1 host dependency installation failed' }

python scripts\h2\reset_codex_test_session.py --selectors r6o\host\codex\windows\selectors.json
if ($LASTEXITCODE -ne 0) { throw 'H2-D1 live Codex reset failed' }

python -m pytest r6o\tests\h2\test_codex_discovery_contract.py -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw 'H2-D1 contract qualification failed' }
```

Expected terminal status from the reset command:

```text
CODEX_TEST_SESSION_READY
```

The reset is fail-closed: it refuses to invoke New chat if the actual Codex
composer is not proven empty. On success it invokes the native New chat control,
proves one visible home surface, zero visible turn groups, and an empty focused
composer, then refreshes `r6o_evidence/H2-D1/reset-session.log`.

The following commands regenerate frozen discovery evidence; they are not
routine qualification commands:

```powershell
python scripts\h2\inspect_codex_host.py --discover --output r6o_evidence\H2-D1\host-environment.json
python scripts\h2\dump_codex_uia.py --host-record r6o_evidence\H2-D1\host-environment.json --output r6o_evidence\H2-D1\codex-uia.json
```

Regeneration changes evidence hashes. The hashes in
`r6o/host/codex/windows/selectors.json` must then be explicitly re-frozen and
reviewed before the reset command or contract tests can pass. Do not overwrite
the frozen evidence merely to run qualification.
