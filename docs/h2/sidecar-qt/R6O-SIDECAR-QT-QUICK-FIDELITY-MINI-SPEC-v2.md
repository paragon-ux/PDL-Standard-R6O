# R6O Sidecar Qt Quick Fidelity Mini-Spec v2

**Date:** 2026-08-23  
**Scope:** replacement H2-C Sidecar GUI visual lock  
**Architecture:** PySide6 + Qt Quick/QML  
**Status:** HUMAN-AUTHORIZED FIDELITY AUTHORITY  
**Supersedes:** `R6O Sidecar Rendering Fidelity Mini-Spec v1`  
**Does not modify:** Model, ViewModel, TUI, D1, D2, E-series, or R6O-3.

---

## 1. Purpose

This specification defines the rendering-fidelity requirements for the replacement H2-C Sidecar.

It supersedes the prior Tk/Pillow rendering prescription.

The Sidecar is now implemented directly in Qt Quick/QML:

```text
Authoritative PDLt runtime
        ↓
accepted R6O-1 ViewModel / FocusProjection
        ↓
Python Sidecar presentation adapter
        ↓
QObject properties + narrow signals/slots
        ↓
PySide6 Qt Quick Window
        ↓
QML production presentation
```

There is only one production visual implementation.

Do not create:

```text
Tk presentation
Pillow production raster renderer
Electron renderer
platform-specific visual renderer
parallel screenshot-only renderer
```

The QML shown to the user is the QML used for qualification.

---

## 2. Visual authority

The controlling Sidecar references remain:

```text
REFERENCE_SIDECAR_STANDARD.png
REFERENCE_SIDECAR_EXPANDED.png
```

Canonical logical dimensions:

```text
STANDARD:
    675 × 300

EXPANDED:
    412 × 806
```

The comprehensive Sidecar design specification remains authoritative for:

```text
component inventory
composition
visible labels
required controls
forbidden controls
mode-specific behavior
human approval boundary
```

This mini-spec adds the exact Qt Quick rendering discipline needed to implement that design faithfully.

---

## 3. Meaning of fidelity

H2-C requires:

> **100% implementation of the approved Sidecar design with zero known Sidecar-owned visual deviations.**

Cross-platform fidelity means:

```text
same QML source
same design tokens
same local font assets
same SVG assets
same logical geometry
same wrapping constraints
same component hierarchy
same visible controls
same design intent and perceptual presentation
```

It does **not** require byte-identical screenshots across Windows, X11, and Wayland.

Unavoidable graphics-stack differences may exist in:

```text
subpixel antialiasing
font edge rasterization
GPU sampling
compositor sampling
```

Those differences may not alter:

```text
component bounds
text wrapping
text placement materially
font family/weight choice
icon geometry
border/radius geometry
control inventory
layout
source design colors
```

Human visual approval remains authoritative.

---

## 4. Production rendering pipeline

The QML scene graph is the canonical production renderer.

Required pipeline:

```text
FocusProjection + presentation state
        ↓
QObject property/model bridge
        ↓
QML component tree
        ↓
Qt Quick scene graph
        ↓
actual production Window
```

For canonical H2-C output, do not introduce an intermediate bitmap-authority layer.

Forbidden production rendering approaches:

```text
Tk Canvas
Pillow-generated Sidecar bitmap
Canvas line-drawn reference icons
font glyph used as icon substitute
OS-native button chrome
OS-native scrollbar chrome
platform-specific alternative layouts
```

`QQuickWindow.grabWindow()` or an equivalent Qt capture API may capture the actual production window for evidence.

It must not be used as a separate renderer.

---

## 5. Window shell

Use a Qt Quick top-level `Window`.

Required properties/behavior:

```text
frameless
transparent outside the approved Sidecar silhouette
no native title bar
no native minimize/maximize controls
no native close control
fixed canonical size during H2-C capture
custom Sidecar chrome only
```

Conceptual QML:

```qml
Window {
    flags: Qt.FramelessWindowHint
    color: "transparent"

    Rectangle {
        anchors.fill: parent
        radius: DesignTokens.outerRadius
        color: DesignTokens.outerSurface
        border.color: DesignTokens.outerBorder
        border.width: 1
        clip: true
    }
}
```

Exact production code may differ, but the visible result must match the reference.

### 5.1 Rounded top-level silhouette

Outside the rounded outer surface, pixels must remain transparent.

Do not simulate rounded corners with an opaque dark rectangular matte.

Where Qt/platform behavior permits an input/containment mask, use Qt's window/input-region facilities rather than creating a new platform-specific visual renderer.

H2-C qualifies the visual silhouette and Sidecar-local input behavior.

Actual host-relative placement remains D2.

---

## 6. Rounded surfaces

Use Qt Quick rounded rectangles directly.

Locked logical radii:

```text
outer Sidecar            12 px
artifact card             9 px
artifact body             6 px
compact chrome control    6 px
action row                5 px
number badge              5 px
stage badge               4 px
```

Do not reproduce rounded geometry with:

```text
Canvas path approximations
spline polygons
pre-rendered rounded-card bitmaps
platform-native widgets
```

The same radius tokens apply on all platforms.

---

## 7. Borders and surfaces

Reference-aligned locked tokens:

```text
outer border             #22282F
card/control border      #242A30
standard outer surface   #12181E
artifact body            #0B1117

primary text             #EEF2F5
muted text               #A8AFB6

stage fill               #2A2145
stage border             #40325F

ACTIVE                   #4BD477
action blue              #48A7E8
action amber             #E58B25
action neutral           #9AA4AD
```

These are the starting locked tokens derived from the approved reference and previous review.

If direct human comparison demonstrates that a token is visibly wrong, revise the token through an explicit design-spec amendment rather than a hidden platform override.

Forbidden:

```text
Windows-only color adjustment
Linux-only color adjustment
theme-derived colors
system palette inheritance
```

---

## 8. Typography

The H2-C typography decision is now frozen:

```text
UI family:
    Inter

Artifact family:
    JetBrains Mono
```

Use exact locally bundled font assets.

For every font file record:

```text
family
style / weight
official upstream
release/version/commit
license
SHA-256
local repository path
```

Load fonts through Qt/QML local resources, e.g. `FontLoader`.

Canonical qualification must not depend on the operating system's installed fonts.

If a required glyph is missing:

```text
FAIL
```

Do not silently fall back.

### 8.1 Typography roles

At minimum define explicit tokens for:

```text
Sidecar title
stage badge
ACTIVE label
section heading
artifact title
artifact body
action label
number badge
source text
Tip label
Tip body
compact control label
```

Each token must define:

```text
family
pixel size
weight
line height / spacing where applicable
```

Do not use implicit toolkit defaults.

---

## 9. Icons

Use the supplied local SVG assets:

```text
assets/svg/expand.svg
assets/svg/close.svg
assets/svg/external-link.svg
```

Canonical optical sizes:

```text
Expand:
    17 × 15 px
    inside 32 × 30 px control

Close:
    14 × 14 px
    inside 32 × 30 px control

External Link:
    12 × 12 px
```

QML should load the SVGs directly or through a Qt resource bundle.

Do not replace them with:

```text
Canvas drawings
font glyphs
Unicode ×
OS-native icons
desktop-theme icons
different platform assets
```

The PNG copies are convenience/reference fallbacks only; SVG is the preferred source asset.

---

## 10. Geometry that must remain locked

Do not reopen macro layout.

Canonical window sizes:

```text
STANDARD:
    675 × 300

EXPANDED:
    412 × 806
```

STANDARD:

```text
artifact LEFT
Review Options RIGHT
```

EXPANDED:

```text
artifact TOP
Review Options BELOW
```

Retain:

```text
Open in Editor
Copy
Tip
four canonical actions
no public LOCK
no public MOVE
no debug footer
no qualification text
no visible expanded Collapse control
no native scrollbar in canonical state
```

A framework migration is not permission to redesign the component.

---

## 11. Recommended QML component decomposition

The presentation should remain small and explicit.

Recommended structure:

```text
qml/
    Sidecar.qml
    SidecarChrome.qml
    ArtifactCard.qml
    ReviewOptions.qml
    ReviewAction.qml
    DesignTokens.qml
```

This is guidance, not a mandatory filename contract.

The important architectural rule is:

```text
visual hierarchy in QML
semantic authority outside QML
```

Do not duplicate ViewModel state machines in QML.

---

## 12. QML state ownership

QML may own only disposable presentation state:

```text
hover
visual focus
scroll offset
STANDARD / EXPANDED presentation mode
transient animations
pressed state
```

QML may not own:

```text
protocol stage authority
Prompt / Plan authority
ReviewDecision
worker state
workspace state
filesystem authority
controller state
session-engine state
```

Projection changes flow from Python to QML.

Approved presentation actions flow from QML back through narrow QObject signals/slots.

---

## 13. STANDARD fidelity lock

STANDARD must reproduce the approved 675×300 composition.

Required visible structure:

```text
PDLt Review
PROMPT REVIEW badge
green ACTIVE state
custom Expand control
custom Close control

Authoritative Prompt (PDL.md)
Open in Editor + External-Link icon
artifact content surface
Source: Workspace File
/workspace/pdlt/PDL.md
Copy

Review Options
1 Confirm this prompt
2 Change the task
3 Change the approach
4 Something else...
Tip
```

The horizontal artifact/options split remains governed by the approved reference.

Do not substitute standard Qt Quick Controls styling for the custom Sidecar cards/rows.

---

## 14. EXPANDED fidelity lock

EXPANDED must reproduce the approved 412×806 vertical composition.

Required:

```text
header
artifact region
Review Options below
Tip below actions
open lower surface consistent with reference
```

Review Options are content-driven rather than a stretched native scroll pane.

No visible:

```text
Collapse
LOCK
MOVE
native title bar
native scrollbar
```

The reverse transition to STANDARD may remain keyboard/programmatic presentation behavior without inventing a visible control absent from the reference.

---

## 15. Artifact scrolling

Use QML scrolling primitives such as `Flickable` / `ScrollView` only if their visible presentation is explicitly Sidecar-styled.

Canonical fixture:

```text
no visible native-looking scrollbar
```

Overflow must remain functional.

Acceptable:

```text
wheel
trackpad
keyboard
touch/flick where applicable
```

If an overflow indicator is introduced later, it requires explicit visual approval unless it is absent from canonical states.

The four canonical Review Options must fit without scrolling.

---

## 16. Focus and keyboard treatment

Keyboard accessibility remains required.

Use Qt focus semantics but custom Sidecar visual focus styling.

Canonical captures must not show:

```text
native dotted focus rectangles
desktop-theme focus rings
platform-specific button chrome
```

Focus styling must not change between Windows/X11/Wayland except for unavoidable rasterization details.

---

## 17. Platform qualification

The same production QML must qualify on:

```text
Windows
Linux/X11
Linux/Wayland
```

There are no platform-specific visual implementations.

Allowed platform differences are limited to Qt's underlying window-system integration.

Forbidden:

```text
if Windows -> different QML layout
if Linux -> different fonts
if Wayland -> different icons
platform-specific design-token overrides
```

---

## 18. Windows qualification

Prove:

```text
real Qt Quick Window
frameless
transparent outer corners
correct STANDARD dimensions
correct EXPANDED dimensions
local fonts loaded
SVG assets loaded
keyboard/mouse behavior
Sidecar-only captures
```

Do not add Win32-specific rendering unless Qt itself demonstrably cannot meet a requirement.

Native window-handle access for later D2 is permitted but is not part of H2-C visual design.

---

## 19. Linux/X11 qualification

Run display-capable tests under a real X11 environment, such as:

```text
Xvfb
+
explicit compositor if transparency requires one
```

Prove the same:

```text
frameless Qt Quick Window
transparent rounded silhouette
canonical dimensions
fonts
SVG assets
input/focus
Sidecar-only captures
```

Display-dependent qualification may not be silently skipped.

---

## 20. Linux/Wayland qualification

Run under a nested/headless Wayland compositor, such as Weston.

Force Qt to use the Wayland platform path.

Prove:

```text
Qt Quick Wayland surface
transparent rounded silhouette
canonical dimensions
fonts
SVG assets
input/focus
Sidecar-only captures
```

Do not silently fall back to X11.

Wayland restrictions on arbitrary global top-level placement are explicitly a D2 concern and do not invalidate H2-C.

---

## 21. Screenshot and visual evidence policy

Capture the actual production Qt Quick Sidecar.

Preferred mechanism:

```text
QQuickWindow.grabWindow()
```

or another capture path that demonstrably captures the actual running production window without restyling.

Canonical evidence:

```text
H2-C-STANDARD-SIDECAR.png
H2-C-EXPANDED-SIDECAR.png
```

No synthetic host background.

No manual post-processing.

No screenshot-only alternate renderer.

Cross-platform screenshots may differ slightly in antialiasing. Do not require cross-platform byte equality.

---

## 22. Automated fidelity requirements

Replace the old Tk/Pillow-oriented rendering requirements with:

```text
Q01 actual PySide6 + Qt Quick production View
Q02 frameless transparent Qt Quick top-level window
Q03 675×300 STANDARD logical geometry
Q04 412×806 EXPANDED logical geometry
Q05 QML circular/rounded outer surface using 12px token
Q06 QML artifact/card/control radii use locked tokens
Q07 Expand uses approved SVG at locked optical size
Q08 Close uses approved SVG at locked optical size
Q09 External-Link uses approved SVG at locked optical size
Q10 Inter loaded from approved local asset
Q11 JetBrains Mono loaded from approved local asset
Q12 explicit typography tokens; no toolkit-default text styling
Q13 locked colors/borders sourced from DesignTokens
Q14 no native title bar or native window controls
Q15 no native-looking scrollbar in canonical state
Q16 no LOCK/MOVE/debug/qualification UI
Q17 STANDARD horizontal composition
Q18 EXPANDED vertical composition
Q19 keyboard focus/action behavior preserved
Q20 artifact overflow behavior preserved
Q21 same QML/assets/tokens used on Windows/X11/Wayland
Q22 Windows display qualification
Q23 Linux/X11 display qualification
Q24 Linux/Wayland display qualification
Q25 canonical STANDARD human comparison
Q26 canonical EXPANDED human comparison
```

`Q01–Q24` are mechanically/independently qualifiable.

`Q25–Q26` remain human-only approval gates.

Structural presence alone cannot close the final visual approval.

---

## 23. Test layers

### Python boundary tests

Retain/test:

```text
FocusProjection shaping
QObject property mapping
approved callback routing
projected action IDs
FREE_RESPONSE_FOCUS
close View-only semantics
Open in Editor callback
Copy callback
terminal dismissal
protected authority boundary
```

### QML / Qt Quick tests

Test:

```text
required components
forbidden components
action count/order
STANDARD/EXPANDED states
focus traversal
keyboard activation
scrolling
local fonts
SVG assets
window flags
window transparency
canonical dimensions
```

### Cross-platform display tests

Required CI paths:

```text
Windows Qt Quick H2-C
Linux/X11 Qt Quick H2-C
Linux/Wayland Qt Quick H2-C
```

A platform may not silently skip its display proof.

---

## 24. Evidence record

The replacement Qt H2-C evidence should record:

```text
PySide6 version
Qt version
QML resource identities
font versions/hashes/licenses
SVG hashes
design-token contract hash
Windows qualification
Linux/X11 qualification
Linux/Wayland qualification
STANDARD capture
EXPANDED capture
protected-path result
oracle/baseline result
```

Evidence must not claim:

```text
H2-C HUMAN_PASS
D2 PASS
E-series PASS
overall H2 PASS
```

before the respective gates occur.

---

## 25. Luna scope

After implementation is frozen, Luna checks:

```text
L01 protected R6O-1 boundary
L02 QML remains presentation-only
L03 Q01–Q24 evidence
L04 font/icon provenance
L05 Windows Qt Quick qualification
L06 X11 qualification
L07 Wayland qualification
L08 canonical capture integrity
L09 no D2/E/R6O-3 leakage
L10 no visual-conformance overclaim
```

Do not ask Luna to rediscover the GUI architecture.

If no P0/P1 blocker remains, return directly to human visual approval.

---

## 26. Human approval

The human compares:

```text
REFERENCE_SIDECAR_STANDARD.png
vs
Qt production STANDARD capture
```

and:

```text
REFERENCE_SIDECAR_EXPANDED.png
vs
Qt production EXPANDED capture
```

Approval means:

```text
H2-C_VISUAL_CONFORMANCE = HUMAN_PASS
KNOWN_SIDECAR_VISUAL_DIVERGENCES = 0
```

There is no fuzzy “close enough” approval category.

Platform antialiasing differences are not design divergences unless they materially alter the visible reference-defined presentation.

---

## 27. PR #9 and replacement implementation

PR #9 is historical negative evidence only:

```text
PR #9 = SUPERSEDED_TK_PROTOTYPE
DO_NOT_MERGE
```

The Qt Quick replacement starts from the accepted base and generates a completely new H2-C visual evidence set.

Do not inherit old Tk screenshots as passing evidence.

Reusable concepts from PR #9 include:

```text
projection callback semantics
pure geometry concepts
action ordering
functional acceptance cases
design references
qualification fail-closed principles
```

Tk-specific rendering code is not reusable production authority.

---

## 28. D2 boundary after H2-C

After human approval, D2 may work on:

```text
actual Codex window association
host-relative placement
z-order
focus transfer
non-interference
platform host mechanics
```

D2 may not alter:

```text
QML component design
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

If D2 exposes a genuine platform limitation requiring visible redesign:

```text
DESIGN_DECISION_REQUIRED
STOP
```

Do not silently fork the UI per platform.

---

## 29. Acceptance summary

Before final human review:

```text
Qt feasibility PASS on Windows/X11/Wayland
full Qt H2-C tests green
R6O suite green
R6O-1 verification green
protected-path diff empty
oracle/baseline intact
Q01–Q24 closed
bounded Luna review green
Q25–Q26 pending human
implementer-known visual divergences = 0
```

Only the human closes:

```text
Q25
Q26
H2-C_VISUAL_CONFORMANCE
```

---

## 30. Final invariant

```text
One QML Sidecar.
One set of design tokens.
One set of fonts.
One set of SVG assets.
One presentation contract.
Windows / X11 / Wayland all qualify that same implementation.
```

H2-C locks the Sidecar presentation.

D2 attaches that already-locked presentation to Codex.

No framework-specific visual redesign is deferred downstream.
