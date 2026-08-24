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

## H2-D1R current Codex compatibility refreeze

Run H2-D1R only from the isolated compatibility branch:

```text
codex/h2-d1r-host-compatibility-refreeze
```

Before qualification, verify that the checkout is at the intended D1R head and
that exactly one actual Codex top-level window is open, visible, and not
minimized. The installed/running identity must be exactly:

```text
package:         26.818.5229.0
ProductVersion:  151.0.7922.170
FileVersion:     151.0.7922.170
```

This gate permits `26.818.3698.0 -> 26.818.5229.0` and only the three
authorized selector metadata leaves. It does not permit selector/control/reset
semantic changes or changes to D1/D2 Python production code.

Generate the current redacted host evidence, update only the authorized package
version and two evidence hashes in `selectors.json`, then run the machine check
before resetting the actual host:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $ExpectedBranch = 'codex/h2-d1r-host-compatibility-refreeze'
    if ((git branch --show-current).Trim() -ne $ExpectedBranch) {
        throw "Wrong H2-D1R branch; expected $ExpectedBranch"
    }
    python -m pip install -r requirements-h2-d2.txt
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1R pinned dependency installation failed' }
    python scripts\h2\inspect_codex_host.py --discover --output r6o_evidence\H2-D1\host-environment.json
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1R host discovery failed' }
    python scripts\h2\dump_codex_uia.py --host-record r6o_evidence\H2-D1\host-environment.json --output r6o_evidence\H2-D1\codex-uia.json
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1R UIA capture failed' }
}
```

After the three selector leaves are refrozen, run the closed qualification
sequence. The D2 verifier writes only to D1R-owned evidence; the accepted
`r6o_evidence/H2-D2/**` record remains unchanged.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    python scripts\h2\verify_d1r_compatibility_refreeze.py --output r6o_evidence\H2-D1R\compatibility-refreeze.json
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1R allowed-delta verification failed' }
    python -c "from pathlib import Path; from r6o.host.codex.windows.uia import load_selectors; load_selectors(Path(r'r6o/host/codex/windows/selectors.json')); print('D1R SELECTOR PROVENANCE PASS')"
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1R selector provenance failed' }
    python scripts\h2\reset_codex_test_session.py --selectors r6o\host\codex\windows\selectors.json
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1R actual Codex reset failed' }
    python -m pytest r6o\tests\h2\test_d1r_compatibility_refreeze.py r6o\tests\h2\test_codex_discovery_contract.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1R/D1 focused tests failed' }
    $env:QT_QUICK_BACKEND = 'software'
    $env:QT_SCALE_FACTOR = '1'
    $env:QT_FONT_DPI = '96'
    python scripts\h2\verify_codex_attachment.py --host-record r6o_evidence\H2-D1\host-environment.json --selectors r6o\host\codex\windows\selectors.json --evidence-dir r6o_evidence\H2-D1R\d2-actual-host
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1R actual D2 attachment verification failed' }
    python -m pytest r6o\tests\h2\test_codex_binding_contract.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'H2-D1R D2 focused tests failed' }
}
```

Expected statuses include:

```text
D1R_COMPATIBILITY_REFREEZE_PASS
CODEX_TEST_SESSION_READY
H2_D2_ATTACHMENT_PASS
D1R COMPATIBILITY REFREEZE VERIFIED
```

## H2-E1 actual Codex input-routing checkout

Review and run H2-E1 only from this branch:

```text
codex/h2-e1-input-routing
```

Verify the branch and remote PR head before running the actual-host gate:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $ExpectedReviewBranch = 'codex/h2-e1-input-routing'
    git fetch origin --prune
    if ($LASTEXITCODE -ne 0) { throw 'Unable to fetch the H2-E1 review branch' }
    $ActualBranch = (git branch --show-current).Trim()
    if ($ActualBranch -ne $ExpectedReviewBranch) {
        throw "Wrong H2-E1 branch: $ActualBranch. Run: git switch $ExpectedReviewBranch"
    }
    $LocalHead = (git rev-parse HEAD).Trim()
    $RemoteHead = (git rev-parse "origin/$ExpectedReviewBranch").Trim()
    if ($LocalHead -ne $RemoteHead) {
        throw "Checkout is not at the current PR head. Run: git pull --ff-only origin $ExpectedReviewBranch"
    }
    "H2-E1 CHECKOUT VERIFIED: $ActualBranch@$LocalHead"
}
```

Keep the frozen H2-D1 Codex window open, visible, and not minimized. Its actual
composer must be empty. Do not type, press Enter, or click native Codex Send
while the verifier is running. The verifier clicks the actual Sidecar
`Something else...` action, proves Shift+Enter remains editing, then routes one
known nonsemantic string through one unmodified native Enter. The hook suppresses
that Enter before normal Codex dispatch and clears the actual composer.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    python -m pip install -r requirements-h2-d2.txt
    if ($LASTEXITCODE -ne 0) { throw 'H2-E1 dependency installation failed' }
    $env:QT_QUICK_BACKEND = 'software'
    $env:QT_SCALE_FACTOR = '1'
    $env:QT_FONT_DPI = '96'
    python scripts\h2\verify_codex_input_routing.py --host-record r6o_evidence\H2-D1\host-environment.json --selectors r6o\host\codex\windows\selectors.json
    if ($LASTEXITCODE -ne 0) { throw 'H2-E1 actual Codex input routing failed' }
    python -m pytest r6o\tests\h2\test_codex_input_binding_contract.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'H2-E1 focused pytest failed' }
}
```

Expected live status:

```text
H2_E1_INPUT_ROUTING_PASS
```

The E1 binding is presentation-only. It emits one `HOST_COMPOSER_TEXT`
`InputEnvelope` to a caller-supplied presentation boundary and contains no
fixture text, ViewModel call, controller call, host-model lease, automatic
invocation, or terminal handoff behavior.

## H2-E2 actual Codex G06 structured-action checkout

Run H2-E2 only from the code-frozen integration branch:

```text
codex/h2-e2-g06-integration
```

The runner rejects the wrong branch, a head that does not descend from accepted
H2-E1 head `8a85ac4214e7b3386c3c8079b0d45fb79a97e9ff`, and uncommitted changes outside
`r6o_evidence/H2-E2/`. Before invoking it, use the accepted D1 reset command to
prepare one fresh Codex test session with an empty composer. Then run exactly:

```powershell
python scripts\h2\run_codex_h2_e2.py --case G06 --record
```

Click `Confirm prompt`, then click `Confirm plan`. The Sidecar must move from
`PROMPT_REVIEW` to `PLAN_REVIEW`, dismiss at `CLOSED_SUCCESS`, and return focus
to the actual Codex composer. Both clicks emit only `STRUCTURED_ACTION`
envelopes; the E1 composer input binding is not armed and no native Codex
submission is part of this gate. Machine-readable projections, transition
records, Sidecar-only captures, host observations, and the exact live-attempt
count are written only under `r6o_evidence/H2-E2/actual-host/`.

Expected live status:

```text
H2_E2_G06_PASS
```

## H2-D2 actual Codex attachment checkout

Review and run H2-D2 only from this branch:

```text
codex/h2-d2-codex-attachment
```

Verify the branch and remote PR head before installing or running anything:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $ExpectedReviewBranch = 'codex/h2-d2-codex-attachment'
    git fetch origin --prune
    if ($LASTEXITCODE -ne 0) { throw 'Unable to fetch the H2-D2 review branch' }
    $ActualBranch = (git branch --show-current).Trim()
    if ($ActualBranch -ne $ExpectedReviewBranch) {
        throw "Wrong H2-D2 branch: $ActualBranch. Run: git switch $ExpectedReviewBranch"
    }
    $LocalHead = (git rev-parse HEAD).Trim()
    $RemoteHead = (git rev-parse "origin/$ExpectedReviewBranch").Trim()
    if ($LocalHead -ne $RemoteHead) {
        throw "Checkout is not at the current PR head. Run: git pull --ff-only origin $ExpectedReviewBranch"
    }
    "H2-D2 CHECKOUT VERIFIED: $ActualBranch@$LocalHead"
}
```

H2-D2 consumes the H2-C-approved Qt Quick Sidecar without changing its QML.
The later fidelity lock fixes Standard at 675x300 logical pixels and Expanded
at 412x806 logical pixels. Standard keeps the approved eight-pixel gap and
actual-composer left anchor; Expanded keeps the approved host-relative right
and top insets. This is the controlling reconciliation with the older
provisional composer-width and 30%-rail equations.
The D1 record remains the frozen host-identity anchor; D2 remeasures that exact
verified HWND's client rectangle, monitor work area, and DPI immediately before
each placement so a moved or resized Codex window cannot pass against stale D1
geometry.
The native Sidecar remains hidden while a projection is validated; successful
rendering is the only operation that reveals it.

Run the Windows-only live qualification while the frozen H2-D1 Codex window is
open, visible, and not minimized. The actual Codex composer must be empty. The
verifier types and removes only `H2D2NONINTERFERENCE`; it never submits it. Do
not press Enter or click Codex Send while this command is running.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    python -m pip install -r requirements-h2-d2.txt
    if ($LASTEXITCODE -ne 0) { throw 'H2-D2 dependency installation failed' }
    $env:QT_QUICK_BACKEND = 'software'
    $env:QT_SCALE_FACTOR = '1'
    $env:QT_FONT_DPI = '96'
    python scripts\h2\verify_codex_attachment.py --host-record r6o_evidence\H2-D1\host-environment.json --selectors r6o\host\codex\windows\selectors.json
    if ($LASTEXITCODE -ne 0) { throw 'H2-D2 actual Codex attachment qualification failed' }
    python -m pytest r6o\tests\h2\test_codex_binding_contract.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'H2-D2 focused pytest failed' }
}
```

Expected live status:

```text
H2_D2_ATTACHMENT_PASS
```

Evidence is written to `r6o_evidence/H2-D2/`: two cropped MP4 recordings, a
Win32/UIA event ledger, and the fail-closed attachment result. The recordings
cover only the Sidecar and composer/attachment surfaces; they do not capture
the conversation body. Evidence observation never foregrounds, raises, or
repairs the Sidecar immediately before a z-order check.

Windows normally redirects owner activation to its last active owned popup.
While this D2 binding is active, a scoped low-level mouse observer reacts only
to a left click inside the exact Codex window and outside the Sidecar. It queues
a focus transaction onto the Qt GUI thread, briefly attaches the two Windows
input queues, activates the exact Codex HWND, and detaches them immediately.
The Sidecar owner is never changed, no keyboard content is observed, and the
steady-state evidence remains read-only.

## H2-C Qt Quick replacement checkout

The active H2-C replacement supersedes the unmerged Tk prototype in PR #9.
Review and qualification must use this exact branch, never PR #9:

```text
codex/h2-c-qt-quick-sidecar
```

Verify the checkout before running any H2-C command:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $ExpectedReviewBranch = 'codex/h2-c-qt-quick-sidecar'
    git fetch origin --prune
    if ($LASTEXITCODE -ne 0) { throw 'Unable to fetch the H2-C Qt branch' }
    $ActualBranch = (git branch --show-current).Trim()
    if ($ActualBranch -ne $ExpectedReviewBranch) {
        throw "Wrong H2-C branch: $ActualBranch. Run: git switch $ExpectedReviewBranch"
    }
    $LocalHead = (git rev-parse HEAD).Trim()
    $RemoteHead = (git rev-parse "origin/$ExpectedReviewBranch").Trim()
    if ($LocalHead -ne $RemoteHead) {
        throw "Checkout is not at the current PR head. Run: git pull --ff-only origin $ExpectedReviewBranch"
    }
    "H2-C QT CHECKOUT VERIFIED: $ActualBranch@$LocalHead"
}
```

Install the pinned Qt dependency and run the complete Windows H2-C component
qualification:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    python -m pip install -r requirements-h2-sidecar.txt
    if ($LASTEXITCODE -ne 0) { throw 'H2-C Qt dependency installation failed' }
    $env:QT_QUICK_BACKEND = 'software'
    $env:QT_SCALE_FACTOR = '1'
    $env:QT_FONT_DPI = '96'
    python scripts\h2\verify_qt_sidecar_component.py --platform windows
    if ($LASTEXITCODE -ne 0) { throw 'H2-C Windows component qualification failed' }
    python -m pytest r6o\tests\h2\test_qt_sidecar_feasibility.py r6o\tests\h2\test_qt_sidecar_component.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'H2-C focused pytest failed' }
}
```

Expected automated status is
`MECHANICAL_PASS_PENDING_FINAL_REVIEW`. The production-window captures are
written beneath
`r6o_evidence/H2-C-QT-QUICK/qualification/windows/`. This status closes only
Q01-Q24 mechanical qualification; Q25-Q26 remain assigned to the independent
final PR review.

The replacement PR runs the same fail-closed qualification and focused tests
on Windows, Linux/X11, and Linux/Wayland. None of the display paths may silently
skip or fall back to another Qt platform backend.

## Checkout under review for H2-B2

PR #8 is reviewed from branch `codex/h2-b2-tui-a02-full`. Before running
qualification, verify that this checkout is at the current remote PR head:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $ExpectedReviewBranch = 'codex/h2-b2-tui-a02-full'
    git fetch origin --prune
    if ($LASTEXITCODE -ne 0) { throw 'Unable to fetch the H2-B2 review branch' }

    $ActualBranch = (git branch --show-current).Trim()
    if ($ActualBranch -ne $ExpectedReviewBranch) {
        throw "Wrong H2-B2 branch: $ActualBranch. Run: git switch $ExpectedReviewBranch"
    }
    $LocalHead = (git rev-parse HEAD).Trim()
    $RemoteHead = (git rev-parse "origin/$ExpectedReviewBranch").Trim()
    if ($LocalHead -ne $RemoteHead) {
        throw "Checkout is not at the current PR head. Run: git pull --ff-only origin $ExpectedReviewBranch"
    }
    "H2-B2 CHECKOUT VERIFIED: $ActualBranch@$LocalHead"
}
```

After PR #8 is merged, merged `main` replaces this branch as the authoritative
checkout for later gates.

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
