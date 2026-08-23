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

## Checkout under review for H2-C-QUALIFICATION

PR #9 is reviewed from branch `codex/h2-c-sidecar-qualification`. Before running
qualification, verify that this checkout is at the current remote PR head:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $ExpectedReviewBranch = 'codex/h2-c-sidecar-qualification'
    git fetch origin --prune
    if ($LASTEXITCODE -ne 0) { throw 'Unable to fetch the H2-C review branch' }

    $ActualBranch = (git branch --show-current).Trim()
    if ($ActualBranch -ne $ExpectedReviewBranch) {
        throw "Wrong H2-C branch: $ActualBranch. Run: git switch $ExpectedReviewBranch"
    }
    $LocalHead = (git rev-parse HEAD).Trim()
    $RemoteHead = (git rev-parse "origin/$ExpectedReviewBranch").Trim()
    if ($LocalHead -ne $RemoteHead) {
        throw "Checkout is not at the current PR head. Run: git pull --ff-only origin $ExpectedReviewBranch"
    }
    "H2-C CHECKOUT VERIFIED: $ActualBranch@$LocalHead"
}
```

After PR #9 is merged, merged `main` replaces this branch as the authoritative
checkout for later gates.

## Accepted H2-B2 review branch

H2-B2 was human-approved and merged through PR #8 from branch
`codex/h2-b2-tui-a02-full`. Its merged `main` lineage, not the old review
worktree, is the base for H2-C.

## Accepted H2-D1 review branch

PR #7 is reviewed from branch `codex/h2-d1-codex-discovery`. Before running
qualification, use this non-destructive identity check from the repository
root. It proves both the branch name and that the checkout is at the current
remote PR head:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $ExpectedReviewBranch = 'codex/h2-d1-codex-discovery'
    git fetch origin --prune
    if ($LASTEXITCODE -ne 0) { throw 'Unable to fetch the H2-D1 review branch' }

    $ActualBranch = (git branch --show-current).Trim()
    if ($ActualBranch -ne $ExpectedReviewBranch) {
        throw "Wrong H2-D1 branch: $ActualBranch. Run: git switch $ExpectedReviewBranch"
    }

    $LocalHead = (git rev-parse HEAD).Trim()
    $RemoteHead = (git rev-parse "origin/$ExpectedReviewBranch").Trim()
    if ($LocalHead -ne $RemoteHead) {
        throw "Checkout is not at the current PR head. Run: git pull --ff-only origin $ExpectedReviewBranch"
    }
    "H2-D1 CHECKOUT VERIFIED: $ActualBranch@$LocalHead"
}
```

After PR #7 is merged, the merged `main` branch replaces this review branch as
the authoritative checkout for later gates.

## Bind and verify the frozen oracle

Run from this repository root in PowerShell. First run the following command by
itself. At its prompt, type the real absolute path of the frozen oracle checkout
and press Enter. Wait for the command to return before copying the next block.
Because this is a separate one-line block, the prompt cannot consume a later
qualification command as its response.

```powershell
$env:PDL_R6S_BASELINE_REPO = (Resolve-Path -LiteralPath (Read-Host 'Absolute path to the frozen PDL-Standard-REPL-Harness checkout') -ErrorAction Stop).Path
```

Do not enter a sample or placeholder path. The assignment overwrites any stale
value from a previous PowerShell attempt. Then run the noninteractive
qualification block:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    if ([string]::IsNullOrWhiteSpace($env:PDL_R6S_BASELINE_REPO)) {
        throw 'Set $env:PDL_R6S_BASELINE_REPO to the real frozen-oracle path before running this block'
    }
    $OracleRoot = (Resolve-Path -LiteralPath $env:PDL_R6S_BASELINE_REPO -ErrorAction Stop).Path

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
}
```

The verifier clones the bound frozen oracle into temporary storage before
running its own verifier and pytest suite, preventing ignored-file writes in
the oracle checkout.

The frozen verifier currently emits this advisory before its PASS marker:

```text
WARN forbidden-term 'architecture-decisions' in scripts/verify_repl_baseline.py
```

It is non-blocking only when the same invocation subsequently prints
`REPL BASELINE VERIFICATION PASS` and exits 0. The warning originates in the
read-only frozen oracle and must not be repaired from this repository.

## H2-A2 qualification

H2-A2 freezes the complete deterministic `A02-FULL` fixture. After binding and
verifying the oracle above, run:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    if ([string]::IsNullOrWhiteSpace($env:PDL_R6S_BASELINE_REPO)) {
        throw 'Bind and verify PDL_R6S_BASELINE_REPO before H2-A2 qualification'
    }
    $OracleRoot = (Resolve-Path -LiteralPath $env:PDL_R6S_BASELINE_REPO -ErrorAction Stop).Path
    $ExpectedCommit = '60d982f3328b45a351879d67dc4bb525172b65fd'
    $ExpectedTree = 'b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6'
    $ActualCommit = (git -C $OracleRoot rev-parse HEAD).Trim()
    $ActualTree = (git -C $OracleRoot rev-parse 'HEAD^{tree}').Trim()
    if ($ActualCommit -ne $ExpectedCommit) {
        throw "Wrong frozen-oracle commit before H2-A2: $ActualCommit"
    }
    if ($ActualTree -ne $ExpectedTree) {
        throw "Wrong frozen-oracle tree before H2-A2: $ActualTree"
    }
    if (-not (Test-Path -LiteralPath "$OracleRoot\scripts\verify_repl_baseline.py" -PathType Leaf)) {
        throw "Not an R6S oracle checkout before H2-A2: $OracleRoot"
    }
    python scripts\h2\verify_a02_full_fixture.py --baseline-repo $OracleRoot
    if ($LASTEXITCODE -ne 0) { throw 'H2-A2 fixture verification failed' }
    python -m pytest r6o\tests\h2\test_a02_full_fixture.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'H2-A2 focused pytest failed' }
}
```

Expected terminal status from the first command:

```text
"status": "A02_FULL_FIXTURE_PASS"
```

The `--record` mode is not an ordinary qualification command. It replaces the
frozen fixture using a live worker and therefore additionally requires the
explicit `--approve-live-recording` acknowledgement.

## H2-B2 qualification

H2-B2 proves the complete A02-FULL workflow through the public TUI process and
real stdin keyboard boundary. After binding and verifying the frozen oracle,
run this fail-fast block from the H2-B2 checkout:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    if ([string]::IsNullOrWhiteSpace($env:PDL_R6S_BASELINE_REPO)) {
        throw 'Bind and verify PDL_R6S_BASELINE_REPO before H2-B2 qualification'
    }
    $OracleRoot = (Resolve-Path -LiteralPath $env:PDL_R6S_BASELINE_REPO -ErrorAction Stop).Path
    $ExpectedCommit = '60d982f3328b45a351879d67dc4bb525172b65fd'
    $ExpectedTree = 'b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6'
    if ((git -C $OracleRoot rev-parse HEAD).Trim() -ne $ExpectedCommit) {
        throw 'Wrong frozen-oracle commit before H2-B2'
    }
    if ((git -C $OracleRoot rev-parse 'HEAD^{tree}').Trim() -ne $ExpectedTree) {
        throw 'Wrong frozen-oracle tree before H2-B2'
    }

    python scripts\h2\verify_tui_a02_full.py --baseline-repo $OracleRoot
    if ($LASTEXITCODE -ne 0) { throw 'H2-B2 process qualification failed' }
    python -m pytest r6o\tests\h2\test_tui_a02_full_process.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'H2-B2 focused pytest failed' }
}
```

Expected automated status:

```text
"status": "MECHANICAL_PASS_PENDING_HUMAN"
```

For the human-equivalent run, use:

```powershell
python scripts\run_r6o2_tui.py --recorded --case A02-FULL --baseline-repo $env:PDL_R6S_BASELINE_REPO
```

In the initial Prompt review, press Tab three times, press Enter on
`Something else...`, type the following exact review text, and press Enter
once:

```text
This is not confirmed. The audience should be data engineers, not backend engineers.
```

Confirm the revised Prompt with Enter, then confirm the Plan with Enter. The
same process must return to PowerShell with `R6O TUI PASS: CLOSED_SUCCESS`.
There is no relaunch and no qualification-harness Send step.

## H2-C Sidecar component qualification

H2-C qualifies only the reusable Sidecar component. The synthetic Tk owner is
retained for functional ownership, placement, lifecycle, and overflow tests;
it is not visual-approval evidence. Canonical visual approval compares only the
Sidecar window against the vendored design references:

```text
docs/h2/sidecar-design/REFERENCE_SIDECAR_STANDARD.png  675 x 300
docs/h2/sidecar-design/REFERENCE_SIDECAR_EXPANDED.png  412 x 806
```

The controlling machine-readable contract is
`docs/h2/sidecar-design/R6O-SIDECAR-DESIGN-CONTRACT-v1-2026-08-23.json`.
H2-C does not test Codex and cannot authorize overall H2 PASS.

Install the pinned display/screenshot dependencies, then run the exact gate
command:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    python -m pip install -r requirements-h2-sidecar.txt
    if ($LASTEXITCODE -ne 0) { throw 'H2-C dependency installation failed' }
    python scripts\h2\verify_sidecar_component.py --display
    if ($LASTEXITCODE -ne 0) { throw 'H2-C display qualification failed' }
    python scripts\h2\verify_sidecar_component.py --validate-evidence r6o_evidence\H2-C-QUALIFICATION\component-result.json
    if ($LASTEXITCODE -ne 0) { throw 'H2-C evidence validation failed' }
    python -m pytest r6o\tests\h2\test_sidecar_component_display.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'H2-C focused pytest failed' }
}
```

The display command briefly shows and captures STANDARD and EXPANDED modes. To
hold each mode longer for visual inspection, rerun it with
`--hold-seconds 5`. It produces only these canonical visual-approval captures:

```text
r6o_evidence/H2-C-QUALIFICATION/H2-C-STANDARD-SIDECAR.png
r6o_evidence/H2-C-QUALIFICATION/H2-C-EXPANDED-SIDECAR.png
```

It also produces the finite structural matrix in
`H2-C-DESIGN-CONFORMANCE.json`. The expected component authority fields remain
exactly:

```json
{
  "gate": "H2-C-QUALIFICATION",
  "status": "MECHANICAL_PASS",
  "overall_h2_pass_authorized": false,
  "real_codex_host_tested": false
}
```

The verifier rejects evidence that claims Codex attachment, Codex z-order,
Codex focus, Codex composer behavior, Sidecar E2E, or overall H2 PASS.
Before human approval, compare each implementation capture directly with its
same-sized reference. The automated readiness status is only:

```text
H2-C_IMPLEMENTATION_CONFORMS_FOR_HUMAN_VISUAL_REVIEW
KNOWN_SIDECAR_VISUAL_DIVERGENCES = 0
H2-C HUMAN DESIGN APPROVAL = PENDING
```

No fuzzy image-similarity score can authorize the gate.

## H2-D1 qualification (Windows only)

H2-D1 binds to the installed Codex desktop application. Run these commands from
the repository root on Windows with exactly one Codex top-level window open:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    python -m pip install -r requirements-r6o2-host.txt
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1 host dependency installation failed' }

    python scripts\h2\reset_codex_test_session.py --selectors r6o\host\codex\windows\selectors.json
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1 live Codex reset failed' }

    python -m pytest r6o\tests\h2\test_codex_discovery_contract.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1 contract qualification failed' }
}
```

Expected terminal status from the reset command:

```text
CODEX_TEST_SESSION_READY
```

The reset is fail-closed: it refuses to invoke New chat if the actual Codex
composer is not proven empty. On success it invokes the native New chat control,
proves one visible home surface, zero visible turn groups, and an empty focused
composer, then refreshes `r6o_evidence/H2-D1/reset-session.log`.

`COMPOSER_NOT_EMPTY` is a protective stop, not a test regression. Manually
preserve, submit, or clear the unsent text in the actual Codex composer as you
choose, then rerun the complete D1 block. Do not continue to the focused test
after a reset failure: every reset attempt refreshes `reset-session.log`, so the
evidence test must remain red until a later successful reset records
`CODEX_TEST_SESSION_READY`. Never restore the prior READY log with Git to make
the evidence test pass.

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
