# R6O H2-C — Qt Quick Authorization and Continuation Prompt

**Date:** 2026-08-23  
**Status:** HUMAN-AUTHORIZED ARCHITECTURE DECISION  
**Applies to:** H2-C Sidecar GUI only  
**TUI:** unchanged / out of scope  
**Framework decision:** PySide6 + Qt Quick/QML  
**PR #9:** superseded prototype; do not merge  
**D2:** remains blocked until H2-C HUMAN_PASS

---

# 1. Human architecture decision

I approve the Codex architecture recommendation:

```text
RECOMMEND_QT_QUICK
```

The H2-C Sidecar implementation is now authorized as:

```text
Authoritative PDLt runtime
        ↓
accepted R6O-1 ViewModel / FocusProjection
        ↓
Python Sidecar presentation adapter
        ↓
narrow QObject properties + signals/slots
        ↓
PySide6 Qt Quick Window
        ↓
QML presentation components
```

This is now the active Sidecar architecture.

Electron + React is not selected.

The current Tk/Canvas/Pillow direction is not selected for the production H2-C Sidecar.

---

# 2. Supersession

The following prior implementation directions are superseded insofar as they prescribe the Sidecar rendering framework:

```text
Tk Canvas visual implementation
Tk + Pillow custom raster-renderer direction
Windows-only native-region rendering direction
custom Windows/X11/Wayland raster shell architecture
Electron + React proposal
```

Retain useful design requirements, references, assets, behavioral contracts, and negative evidence from those packages.

Do not retain their framework-specific implementation prescriptions.

The controlling visual references remain:

```text
REFERENCE_SIDECAR_STANDARD.png
REFERENCE_SIDECAR_EXPANDED.png
```

The comprehensive Sidecar design specification remains the visual approval boundary unless explicitly revised by the human.

---

# 3. PR #9 disposition

PR #9 is not to be repaired further and is not to be merged.

Record:

```text
PR #9 = SUPERSEDED_TK_PROTOTYPE
H2-C_VISUAL_CONFORMANCE = NOT_APPROVED
MERGE = NO
```

Preserve PR #9 and its evidence as historical implementation/negative evidence.

Do not rewrite or squash its nine-commit history into the replacement.

Close it only after the replacement H2-C branch/PR exists and its provenance records PR #9 as superseded.

---

# 4. Replacement branch

Start a fresh H2-C implementation directly from the accepted base:

```text
main@4928e73612048fac4b7486b24b7785a79d287e20
```

Do not branch from PR #9.

Suggested branch identity:

```text
codex/h2-c-qt-quick-sidecar
```

The exact branch name may differ if repository convention requires it.

The new PR must explicitly state:

```text
supersedes PR #9
does not merge PR #9 implementation
protected R6O-1 paths unchanged
H2-C only
D2 not implemented
```

---

# 5. Protected architecture

Do not modify or reopen:

```text
r6o/model_binding/**
r6o/viewmodel/**
r6o/contracts/**
r6o_evidence/R6O-1/**
```

Do not change:

```text
MVVM Model authority
ViewModel semantics
InputEnvelope semantics
ReviewDecision authority
WorkerAdapter isolation
workspace authority
TUI behavior
H2-D1
D2 host attachment
E-series E2E
R6O-3 lifecycle
```

The problem being solved is the disposable Sidecar View.

---

# 6. Presentation authority boundary

The QML layer may own only presentation state:

```text
hover state
keyboard focus
scroll offset
STANDARD / EXPANDED presentation mode
transient animation state
local visual affordance state
```

The QML layer may not own:

```text
protocol stage authority
Prompt authority
Plan authority
confirmation authority
ReviewDecision
worker state
workspace state
filesystem authority
controller authority
session-engine authority
```

The Python adapter exposes only projection-safe data and approved presentation callbacks.

---

# 7. First phase — bounded Qt Quick feasibility slice

Before implementing the complete Sidecar, build a deliberately small shell feasibility slice.

This phase exists only to falsify framework/platform risk early.

It must prove the production framework itself, not a mock renderer.

## Required platforms

```text
Windows
Linux/X11
Linux/Wayland
```

## Required canonical windows

```text
STANDARD:
    675 × 300

EXPANDED:
    412 × 806
```

## Required feasibility proof

On all three platform paths prove:

```text
frameless Qt Quick top-level window
transparent outer window
visually rounded Sidecar silhouette
correct logical dimensions
local font loading
local SVG loading
QML rounded rectangles/cards
QML custom chrome
keyboard focus delivery
mouse input delivery
Sidecar-only window capture
```

The feasibility slice does NOT need full artifact/action semantics yet.

It does need enough canonical chrome/card content to prove the reference can be represented without native-toolkit artifacts.

---

# 8. Cross-platform visual contract

Do not require byte-identical cross-platform screenshots.

The approved invariant is:

```text
same QML source
same design tokens
same local font assets
same local SVG assets
same logical geometry
same component hierarchy
same visible controls
same reference-defined composition
same perceptual design
```

Permissible differences are limited to unavoidable graphics-stack rasterization details such as:

```text
subpixel antialiasing
font edge rasterization
GPU/compositor sampling
```

These may not change:

```text
text wrapping
text placement
component bounds
icon geometry
border/radius geometry
control inventory
layout
colors in source tokens
```

Human visual review remains authoritative for the final design lock.

---

# 9. Wayland boundary

Wayland restrictions on arbitrary global top-level positioning do not block H2-C.

H2-C proves:

```text
Sidecar surface
visual design
transparency
rounded silhouette
input
focus within the Sidecar
canonical dimensions
```

D2 later owns:

```text
actual Codex-relative placement
ownership
z-order
focus transfer
host non-interference
```

Do not smuggle D2 placement requirements into the H2-C feasibility slice.

---

# 10. Feasibility CI

Add display-capable qualification for all required environments.

## Windows

Prove the actual Qt Quick window.

## Linux/X11

Use a real display-capable X11 test environment, such as:

```text
Xvfb
+
explicit compositor if transparency requires one
```

Do not silently skip display tests.

## Linux/Wayland

Use a nested/headless Wayland compositor, such as:

```text
Weston headless backend
```

Force the Qt Wayland backend explicitly.

Do not silently fall back to X11.

If the selected Qt configuration cannot run the required shell under the target environment:

```text
FEASIBILITY_BLOCKED
```

---

# 11. Feasibility review rule

Freeze one exact feasibility head/tree.

Run one bounded Luna Max review with only:

```text
F1 protected-boundary integrity
F2 real PySide6 / Qt Quick implementation
F3 Windows shell proof
F4 Linux/X11 shell proof
F5 Linux/Wayland shell proof
F6 local font proof
F7 local SVG proof
F8 transparent/rounded window proof
F9 no native visual-control leakage
F10 no D2/E/R6O-3 leakage
```

Allowed result:

```text
FEASIBILITY_PASS
P0_P1_BLOCKER
EVIDENCE_INSUFFICIENT
```

## No unnecessary human pause

This prompt constitutes human pre-authorization to continue.

If:

```text
FEASIBILITY_PASS
```

and there is no protected-contract conflict, Sol proceeds immediately into full H2-C implementation.

Do not stop to ask whether to continue.

If Luna identifies a concrete P0/P1 feasibility blocker:

```text
repair only that blocker
run affected qualification
one Luna follow-up
```

If a genuine design/architecture conflict remains after that:

```text
BLOCKED_CONTEXT_CONFLICT
STOP
RETURN TO HUMAN
```

Do not enter an open-ended Luna loop.

---

# 12. Full Qt Quick Sidecar implementation

After feasibility PASS, implement the complete design lock.

Recommended organization:

```text
r6o/views/sidecar/
    model.py
    adapter.py
    qt_app.py

    qml/
        Sidecar.qml
        SidecarChrome.qml
        ArtifactCard.qml
        ReviewOptions.qml
        ReviewAction.qml
        DesignTokens.qml

    assets/
        icons/
        fonts/
```

Exact filenames may differ if a cleaner Qt resource structure is justified.

Do not duplicate semantic logic in QML.

---

# 13. Required design content

Implement the frozen Sidecar reference, including:

```text
PDLt Review
stage badge
ACTIVE state
custom Expand control in STANDARD
custom Close control
Authoritative Prompt title
Open in Editor
external-link icon
artifact content
workspace source
Copy
Review Options
four numbered action rows
Tip
```

Preserve the reference-defined mode compositions:

```text
STANDARD:
    artifact LEFT
    Review Options RIGHT

EXPANDED:
    artifact TOP
    Review Options BELOW
```

No public:

```text
LOCK
MOVE
native title bar
native scrollbar in canonical state
debug projection footer
qualification text
visible expanded Collapse control
```

---

# 14. Fonts

Use deterministic local assets.

Approved H2-C typography lock:

```text
UI:
    Inter

Artifact:
    JetBrains Mono
```

For vendored font assets record:

```text
official upstream
release/version/commit
license
SHA-256
local path
```

Load them through Qt/QML local font resources.

Do not rely on uncontrolled system fallback for canonical qualification.

If this licensing/distribution choice is not acceptable under repository policy:

```text
LICENSING_DECISION_REQUIRED
STOP
RETURN TO HUMAN
```

Do not silently substitute fonts.

---

# 15. Icons

Use the approved local SVG assets for:

```text
Expand
Close
External Link
```

QML must render these assets directly.

Do not reproduce the icons using:

```text
Canvas lines
font glyph substitutes
OS-native icons
theme icons
```

---

# 16. Scrolling and focus

Use Qt Quick/QML native presentation primitives, styled by the Sidecar design.

Artifact overflow must remain scrollable.

Canonical visual state must not expose an unapproved native-looking scrollbar.

The four canonical Review Options must fit without a scrollbar.

Keyboard focus must remain accessible but visually conform to the Sidecar design.

---

# 17. Python/QML bridge

Use a narrow QObject-based presentation bridge.

Conceptual data flow:

```text
Python:
    FocusProjection
        ↓
QObject properties/models
        ↓
QML

QML:
    approved presentation event
        ↓
QObject signal/slot
        ↓
existing Python presentation adapter
```

Do not expose:

```text
arbitrary filesystem APIs
process APIs
workspace root
controller
worker
SessionEngine
ReviewDecision constructors
```

---

# 18. Tests

Preserve existing non-Tk tests wherever they still express valid behavioral contracts.

## Python tests

Test:

```text
projection shaping
property/model mapping
callback routing
action IDs
FREE_RESPONSE_FOCUS
close semantics
terminal dismissal
source/open/copy callbacks
protected-path boundary
```

## QML / Qt tests

Test:

```text
required element presence
forbidden element absence
four actions
mode compositions
keyboard focus
action invocation
scrolling
expand behavior
close
local fonts loaded
SVG assets loaded
canonical dimensions
transparent/frameless window
```

## Visual evidence

Capture the actual production QML window:

```text
H2-C-STANDARD-SIDECAR.png
H2-C-EXPANDED-SIDECAR.png
```

Do not use a synthetic host background as design evidence.

Do not post-process captures.

---

# 19. Qualification evidence

Create a replacement H2-C evidence set for the Qt implementation.

The old PR #9 captures are historical only.

The new evidence must identify:

```text
framework = PySide6 + Qt Quick
exact PySide6 version
Qt version
font asset hashes
icon asset hashes
Windows qualification
Linux/X11 qualification
Linux/Wayland qualification
STANDARD capture
EXPANDED capture
protected-path result
baseline/oracle result
```

Do not claim human approval before it occurs.

---

# 20. Full implementation Luna review

After the complete Sidecar and evidence are frozen, invoke Luna once with fixed scope:

```text
Q1 protected R6O-1 boundary
Q2 projection-only QML authority
Q3 design-contract structural conformance
Q4 Windows Qt Quick qualification
Q5 Linux/X11 qualification
Q6 Linux/Wayland qualification
Q7 fonts/assets provenance
Q8 keyboard/scroll/action behavior
Q9 canonical capture integrity
Q10 no D2/E/R6O-3 leakage
```

If no P0/P1 blockers remain:

```text
do not run another whole-system Luna round
return immediately for human visual approval
```

P2/P3 findings are nonblocking unless they demonstrate:

```text
visible Sidecar mismatch
protected-contract risk
qualification invalidity
```

---

# 21. Human approval boundary

The human directly compares:

```text
REFERENCE_SIDECAR_STANDARD.png
vs
Qt H2-C STANDARD capture
```

and:

```text
REFERENCE_SIDECAR_EXPANDED.png
vs
Qt H2-C EXPANDED capture
```

Approval requires:

```text
KNOWN_SIDECAR_VISUAL_DIVERGENCES = 0
H2-C_VISUAL_CONFORMANCE = HUMAN_PASS
```

Only the human may record that status.

---

# 22. Merge / supersession sequence

After H2-C HUMAN_PASS:

```text
1. approve the replacement Qt H2-C PR;
2. merge it;
3. verify merged main/protected paths;
4. close PR #9 as superseded if not already closed;
5. record PR #9 as historical Tk prototype;
6. begin H2-D2 from merged main.
```

Do not merge PR #9.

---

# 23. D2 invariant

D2 consumes the already-locked Qt Sidecar.

D2 may change:

```text
actual Codex ownership/association
window coordinates
host-relative placement
z-order mechanics
focus mechanics
platform host binding
```

D2 may not change:

```text
QML design
fonts
icons
radii
colors
chrome
artifact card
Review Options styling
STANDARD composition
EXPANDED composition
```

If D2 appears to require a Sidecar redesign:

```text
DESIGN_DECISION_REQUIRED
STOP
```

---

# 24. Resource / packaging policy

PySide6 is a substantial dependency but is accepted for this architecture decision, subject to normal pinned-dependency and licensing records.

Do not optimize packaging prematurely.

First qualify:

```text
correct architecture
correct visual design
correct cross-platform behavior
```

Then establish the smallest supported deployment packaging for the finished Sidecar.

Do not introduce Electron/Node as a fallback during the Qt implementation.

Electron may only be reconsidered if the bounded Qt feasibility slice demonstrates a genuine framework-level failure against the required Sidecar design.

---

# 25. Final continuation instruction

Proceed now as follows:

```text
close implementation work on PR #9
    ↓
create fresh H2-C Qt branch from accepted main base
    ↓
implement bounded Qt Quick shell feasibility slice
    ↓
Windows + X11 + Wayland qualification
    ↓
one Luna feasibility review
    ↓
if PASS, automatically continue
    ↓
implement full QML Sidecar
    ↓
full H2-C qualification
    ↓
one bounded Luna review
    ↓
human visual approval
    ↓
merge replacement H2-C PR
    ↓
close PR #9 as superseded
    ↓
begin H2-D2
```

Do not pause for additional architecture planning unless a genuine blocker under this prompt is encountered.

---

# 26. Required immediate status

Acknowledge this authority with:

```text
QT_QUICK_H2C_ARCHITECTURE_ACCEPTED
PR9_DISPOSITION = SUPERSEDED_DO_NOT_MERGE
NEXT = QT_QUICK_FEASIBILITY_SLICE
```

Then proceed.
