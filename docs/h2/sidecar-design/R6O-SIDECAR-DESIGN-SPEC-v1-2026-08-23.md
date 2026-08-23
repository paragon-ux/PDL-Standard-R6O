# R6O Sidecar Design Specification v1
## H2-C Sidecar Visual Approval Boundary

**Date:** 2026-08-23  
**Status:** PROPOSED HUMAN DESIGN LOCK  
**Scope:** Sidecar GUI only  
**TUI:** explicitly out of scope; existing TUI design remains unchanged  
**Primary reference:** `REFERENCE_UI-HARNESS.png`  
**Approval rule:** **100% Sidecar conformance / zero known Sidecar-owned visual deviations**

---

# 1. Purpose

This specification replaces divergence/convergence notes as the visual authority for the R6O Sidecar.

H2-C is the point at which the Sidecar's presentation is frozen.

The acceptance question is no longer:

```text
"Is the current implementation close enough?"
```

It is:

```text
"Does the Sidecar match the approved reference?"
```

The synthetic host scene is not part of this design approval.

The TUI is not governed by this specification.

---

# 2. Normative visual source

The controlling image is:

```text
REFERENCE_UI-HARNESS.png
dimensions: 1672 × 941
SHA-256: a4defa180dbcebbcc443cd486474a1e6869cbeeb1a58359abb00c07b22facb2e
```

For H2-C visual approval, only the Sidecar-owned regions are normative.

Two canonical Sidecar-only images have been extracted directly from the controlling reference.

## STANDARD canonical crop

```text
source bounds:
    left   = 28
    top    = 479
    right  = 703
    bottom = 779

canonical dimensions:
    675 × 300

SHA-256:
    f78361a61734848a47c26feca1be31c1f01e8a2ee21f4bd650e436053c5b140c
```

File:

```text
REFERENCE_SIDECAR_STANDARD.png
```

## EXPANDED canonical crop

```text
source bounds:
    left   = 1241
    top    = 98
    right  = 1653
    bottom = 904

canonical dimensions:
    412 × 806

SHA-256:
    3939a378d12cf45c25aa5aa32bc0fb429ab044ca510aeb428049938ee3c61313
```

File:

```text
REFERENCE_SIDECAR_EXPANDED.png
```

These two crops are the direct H2-C visual approval references.

---

# 3. Precedence

For Sidecar visual design:

```text
1. REFERENCE_SIDECAR_STANDARD.png
2. REFERENCE_SIDECAR_EXPANDED.png
3. this design specification
4. functional H2 contracts
5. implementation details
```

Where prose and the image appear to disagree, the image wins for visible Sidecar-owned presentation.

A functional requirement may not be expressed by adding an unapproved visible control.

If a functional requirement cannot be implemented without changing visible reference appearance:

```text
STOP
DESIGN_DECISION_REQUEST
```

Do not silently deviate.

---

# 4. Meaning of "100% conformance"

For H2-C:

> **100% conformance means there are zero known visible differences in Sidecar-owned composition, controls, hierarchy, chrome, spacing intent, or canonical-state content treatment.**

The following phrases are not valid approval standards:

```text
substantially similar
close enough
within the spirit of the reference
roughly equivalent
acceptable divergence
we can revisit it in D2
```

Any known Sidecar-owned mismatch is H2-C `FAIL` until:

```text
a) implementation is corrected, or
b) the human explicitly revises the reference/specification.
```

There is no deferred visual-debt list after H2-C approval.

---

# 5. What is and is not compared

## Included in H2-C visual conformance

Everything visually owned by the Sidecar:

```text
outer window shape
custom chrome
header hierarchy
stage badge
status indicator
window controls
artifact panel
artifact title
Open in Editor control
artifact content surface
source line
Copy control
Review Options section
number badges
action rows
action emphasis
Tip copy
spacing
borders
corner treatment
text hierarchy
canonical scroll presentation
STANDARD composition
EXPANDED composition
```

## Excluded from H2-C visual conformance

The surrounding host application:

```text
Codex editor content
Codex title bar
Codex tabs
Codex composer
host navigation
host toolbar
desktop wallpaper
synthetic qualification background
```

Those are not Sidecar pixels.

Actual Codex placement/ownership remains a D2 concern.

---

# 6. No synthetic background in visual approval evidence

A synthetic Tk parent may remain as an internal unit/geometry test fixture if useful.

It MUST NOT be used as the H2-C visual approval surface.

H2-C visual evidence captures:

```text
Sidecar window only
```

at the canonical reference dimensions.

The approval set consists of:

```text
REFERENCE_SIDECAR_STANDARD.png
vs
implementation STANDARD Sidecar capture

REFERENCE_SIDECAR_EXPANDED.png
vs
implementation EXPANDED Sidecar capture
```

No artificial editor, artificial composer, or fullscreen synthetic background is required for visual approval.

---

# 7. Canonical STANDARD design

Canonical size:

```text
675 × 300 px
```

Canonical composition:

```text
┌───────────────────────────────────────────────────────────────────────┐
│ PDLt Review   PROMPT REVIEW                     ● ACTIVE   [expand] [×]│
├─────────────────────────────────────────┬─────────────────────────────┤
│ Authoritative Prompt (PDL.md)           │ Review Options              │
│                         Open in Editor ↗ │                             │
│ ┌─────────────────────────────────────┐ │ [1] Confirm this prompt     │
│ │ # Prompt                            │ │ [2] Change the task         │
│ │                                     │ │ [3] Change the approach     │
│ │ Build a task manager with:          │ │ [4] Something else...      │
│ │ ...                                 │ │                             │
│ └─────────────────────────────────────┘ │ Tip: Type directly in the   │
│ Source: Workspace File ...       Copy   │ chat below to provide other │
│                                         │ feedback.                    │
└─────────────────────────────────────────┴─────────────────────────────┘
```

## 7.1 Structural rules

STANDARD is horizontally composed:

```text
artifact region LEFT
Review Options RIGHT
```

Reference-derived body split is approximately:

```text
artifact region ≈ 61%
Review Options ≈ 39%
```

Do not reintroduce the older 70/30 implementation assumption.

The canonical image itself is the final authority for the split.

## 7.2 Header

Required visible elements, left to right:

```text
PDLt Review
PROMPT REVIEW badge
green status dot
ACTIVE
expand control
close control
```

There is no:

```text
LOCK
MOVE
drag mode
native Windows title bar
native minimize
native maximize
native Windows close button
```

## 7.3 STANDARD expand control

The reference visibly shows a custom expand/fullscreen-style icon in STANDARD.

It is part of the design lock.

The control uses the Sidecar's custom chrome.

## 7.4 Close

The reference visibly shows a custom `×` control.

It closes/dismisses the presentation View only.

Its functional semantics must not change its visual form.

---

# 8. Canonical EXPANDED design

Canonical size:

```text
412 × 806 px
```

Canonical composition:

```text
┌──────────────────────────────────────────┐
│ PDLt Review   PROMPT REVIEW   ● ACTIVE × │
├──────────────────────────────────────────┤
│ Authoritative Prompt (PDL.md)            │
│                         Open in Editor ↗  │
│ ┌──────────────────────────────────────┐ │
│ │ # Prompt                             │ │
│ │                                      │ │
│ │ Build a task manager with:           │ │
│ │ ...                                  │ │
│ └──────────────────────────────────────┘ │
│ Source: Workspace File             Copy  │
│ /workspace/pdlt/PDL.md                  │
├──────────────────────────────────────────┤
│ Review Options                           │
│                                          │
│ [1] Confirm this prompt                  │
│ [2] Change the task                      │
│ [3] Change the approach                  │
│ [4] Something else...                    │
│                                          │
│ Tip: Type directly in the chat below     │
│ to provide other feedback.               │
│                                          │
│                                          │
└──────────────────────────────────────────┘
```

EXPANDED is vertically composed:

```text
artifact TOP
Review Options BELOW
```

It is not STANDARD merely made taller.

## 8.1 Review Options sizing

The reference does not show Review Options stretched into a large bordered scroll container.

The action rows and Tip occupy their natural content region.

Unused lower vertical space belongs to the Sidecar surface, not to an artificially stretched action list.

## 8.2 Visible controls

The EXPANDED reference visibly contains:

```text
PDLt Review
stage badge
green status dot
ACTIVE
close
```

It does **not visibly contain a Collapse button**.

Therefore:

> A visible Collapse control is nonconformant to the current reference.

If reverse transition from EXPANDED to STANDARD must remain available for qualification/functionality, it must be provided without adding a visible control that is absent from the reference, or the reference must be explicitly revised by the human.

Do not silently add `Collapse`, `LOCK`, or `MOVE`.

---

# 9. Artifact card

Both modes contain the same artifact-card vocabulary.

Required:

```text
Authoritative Prompt (PDL.md)
Open in Editor
external-link icon
artifact content surface
Source: Workspace File
/workspace/pdlt/PDL.md
Copy
```

The exact artifact content in the canonical visual fixture is the reference content.

H2-C visual qualification MUST use reference-sized canonical content rather than a 45-line stress artifact.

Stress/overflow behavior is tested separately.

## 9.1 Open in Editor

`Open in Editor` is visible in the reference and therefore required.

It may be implemented through a presentation callback.

It must not introduce controller/runtime authority into the View.

## 9.2 Copy

`Copy` is visible in the reference and therefore required.

It copies the projected artifact representation exposed to the View.

It must not mutate protocol state.

---

# 10. Review Options

Canonical visible heading:

```text
Review Options
```

Canonical canonical-fixture rows:

```text
1  Confirm this prompt
2  Change the task
3  Change the approach
4  Something else...
```

Each action consists of:

```text
small numbered badge
+
larger label row
```

The badge is visually distinct from the action body.

Canonical badge accents:

```text
1 — green
2 — blue
3 — amber/orange
4 — neutral gray
```

The first action carries primary emphasis.

Do not replace this presentation with:

```text
plain Tk buttons
native focus rectangles
one large button with number embedded in text
```

---

# 11. Tip

Required canonical copy:

```text
Tip: Type directly in the chat below
to provide other feedback.
```

`Tip:` receives stronger emphasis than the rest of the sentence.

The Tip belongs below the action list.

It is visible in both STANDARD and EXPANDED.

---

# 12. Scroll behavior

The canonical reference contains **no visible native scrollbar**.

Therefore canonical H2-C visual evidence MUST contain no visible:

```text
Tk scrollbar
Windows scrollbar
bright scrollbar track
scrollbar arrows
permanent review-options scrollbar
```

## 12.1 Canonical visual state

The exact reference content fits the canonical artifact surface.

No scrollbar is shown.

## 12.2 Overflow behavior

The reference image does not specify a visible overflow treatment.

Therefore overflow behavior is functional rather than part of the canonical visual lock.

Requirements:

```text
artifact remains scrollable
canonical reference state remains scrollbar-free
overflow must not force a permanent native scrollbar into normal presentation
```

Any new visible overflow affordance requires human design approval before becoming part of the Sidecar lock.

For the normal four action rows:

```text
Review Options must not show a scrollbar.
```

---

# 13. Focus presentation

The reference does not contain a native Tk dotted focus rectangle.

Therefore H2-C canonical screenshots must not show one.

Keyboard accessibility remains required.

Focus must be expressed with Sidecar-owned styling consistent with the reference, for example through the existing row/badge emphasis.

Do not expose toolkit-default focus chrome when it visibly diverges from the reference.

---

# 14. Debug and qualification text

The following are forbidden in the production/reference Sidecar:

```text
Projection snapshot · ...
artifact://...
revision hashes
SYNTHETIC ...
qualification requirement ...
debug coordinates
LOCK
MOVE
test fixture labels
```

Qualification-only data belongs in logs/evidence, not inside the Sidecar.

The synthetic parent may identify itself in nonvisual component tests, but no such text belongs in Sidecar-only visual evidence.

---

# 15. Window chrome and behavior

The Sidecar is custom-decorated.

Required:

```text
frameless
no native OS title bar
no native OS minimize/maximize
no native OS close control
no native resize border
no user-visible drag mode
no user-visible lock mode
```

The reference's rounded frame and custom controls define the visible window.

Window placement/ownership is tested later against Codex, but D2 may not restyle the already-approved Sidecar.

---

# 16. Typography

The reference visibly uses two text roles:

```text
UI/chrome/action text:
    proportional sans-serif

artifact body:
    monospaced
```

The exact font-family names are not encoded in the PNG and cannot be recovered reliably from the source image alone.

Therefore the design lock is on:

```text
visual text metrics
weight hierarchy
relative size
line spacing
monospaced vs proportional role
```

not on an unsupported claim about a specific font family.

If implementation chooses a font family, it must visually reproduce the reference.

Do not alter the reference to match the toolkit's default font.

---

# 17. Color and surface treatment

The reference defines a dark, low-contrast layered surface.

Reference-sampled dark surface pixels cluster around:

```text
#081018
#101018
#101818
#081010
```

These values are measurements from the raster reference, not source-design tokens.

The implementation must visually match the reference's:

```text
dark outer surface
slightly separated card surfaces
subtle cool-gray borders
white primary text
muted gray secondary text
purple stage badge
green ACTIVE status
green / blue / amber / neutral action badges
```

Do not use default Tk widget palette/chrome.

Because the original design-token source is not available, the PNG remains the color authority.

---

# 18. Spacing and density

The Sidecar is compact.

Required visual characteristics:

```text
tight header
small consistent outer inset
small card-to-card gap
compact action rows
minimal empty padding in STANDARD
intentional open vertical space only in EXPANDED
```

Do not increase padding simply to make native widgets easier to fit.

Do not compress text until it wraps differently from the reference canonical state.

---

# 19. Rounded corners and borders

The reference visibly uses:

```text
rounded outer Sidecar corners
rounded artifact card
rounded action rows
rounded compact controls
thin low-contrast borders
```

Default square/native Tk control borders are nonconformant.

Exact source radius values are not available from the PNG.

The implementation must match the raster appearance of the reference.

---

# 20. Canonical H2-C visual fixture

The visual fixture must reproduce the reference content, not stress content.

Canonical fixture:

```text
stage:
    PROMPT REVIEW

status:
    ACTIVE

artifact title:
    Authoritative Prompt (PDL.md)

artifact body:
    # Prompt

    Build a task manager with:
      - User authentication
      - Project management
      - Task tracking
      - Due dates and reminders

    Target tech stack: React + FastAPI + SQLite

source:
    Source: Workspace File
    /workspace/pdlt/PDL.md

actions:
    1 Confirm this prompt
    2 Change the task
    3 Change the approach
    4 Something else...

tip:
    Tip: Type directly in the chat below
    to provide other feedback.
```

The purpose is to compare presentation with like-for-like content.

Separate functional tests may use long artifacts and other projected action sets.

---

# 21. H2-C visual qualification procedure

## 21.1 STANDARD

Launch/render the Sidecar component alone at:

```text
675 × 300
```

with the canonical fixture.

Capture only the Sidecar top-level/window.

Compare directly to:

```text
REFERENCE_SIDECAR_STANDARD.png
```

## 21.2 EXPANDED

Launch/render the Sidecar component alone at:

```text
412 × 806
```

with the same canonical fixture.

Capture only the Sidecar top-level/window.

Compare directly to:

```text
REFERENCE_SIDECAR_EXPANDED.png
```

## 21.3 No synthetic-scene visual evidence

Do not use a fullscreen synthetic-owner screenshot as H2-C visual approval evidence.

Synthetic geometry tests may continue separately.

---

# 22. Automated conformance assertions

Automation must assert objective Sidecar-owned properties.

At minimum:

```text
STANDARD outer size = 675 × 300
EXPANDED outer size = 412 × 806

STANDARD:
    horizontal artifact/options composition
    Open in Editor visible
    Copy visible
    Tip visible
    Expand visible
    Close visible

EXPANDED:
    vertical artifact/options composition
    Open in Editor visible
    Copy visible
    Tip visible
    Close visible
    no visible Collapse control

both:
    stage badge visible
    ACTIVE visible
    exactly four canonical action rows
    no LOCK
    no MOVE
    no debug footer
    no native scrollbar in canonical state
    no native title bar
    no native dotted focus rectangle
```

Do not replace these assertions with a single fuzzy screenshot-similarity percentage.

---

# 23. Raster comparison policy

Raster comparison may be used as a diagnostic tool.

It is NOT the definition of conformance.

Forbidden approval logic:

```text
SSIM > X therefore PASS
pixel similarity > Y therefore PASS
looks mostly similar therefore PASS
```

The design approval boundary is:

```text
canonical reference
+
explicit required-element inventory
+
explicit forbidden-element inventory
+
human direct comparison
+
zero known deviations
```

A difference image may be produced to help find deviations.

It may not authorize a known deviation.

---

# 24. Human approval checklist

H2-C may be approved only when the human can answer **YES** to every item.

## STANDARD

- [ ] outer Sidecar shape matches reference;
- [ ] header matches reference;
- [ ] stage badge matches reference;
- [ ] ACTIVE treatment matches reference;
- [ ] Expand and Close match reference;
- [ ] artifact/options horizontal composition matches;
- [ ] Open in Editor is present and visually correct;
- [ ] Copy is present and visually correct;
- [ ] artifact surface matches;
- [ ] source treatment matches;
- [ ] all four action rows match;
- [ ] number badges match;
- [ ] Tip matches;
- [ ] no visible native scrollbars;
- [ ] no toolkit-native focus artifact;
- [ ] no debug/qualification UI.

## EXPANDED

- [ ] outer Sidecar shape matches reference;
- [ ] header matches reference;
- [ ] no extra visible Collapse/Lock/Move control;
- [ ] artifact is above Review Options;
- [ ] artifact card matches;
- [ ] Open in Editor matches;
- [ ] Copy matches;
- [ ] Review Options rows match;
- [ ] Tip matches;
- [ ] lower open space matches the reference intent;
- [ ] no stretched action scroll container;
- [ ] no visible native scrollbars;
- [ ] no debug/qualification UI.

If one item is NO:

```text
H2-C VISUAL LOCK = FAIL
```

---

# 25. Functional requirements that must not alter the lock

The following may be tested separately:

```text
artifact overflow scrolling
keyboard traversal
close
terminal dismissal
projection refresh
window lock
geometry calculation
```

They do not authorize additional visible UI in the canonical states.

A test-only control must remain test-only.

---

# 26. D2 boundary after H2-C approval

After H2-C is approved, D2 may change:

```text
window owner
window coordinates
host-relative placement
z-order mechanics
focus transfer
```

D2 may NOT change:

```text
Sidecar chrome
cards
action styling
typography system
visible controls
scrollbar treatment
STANDARD composition
EXPANDED composition
Tip
source treatment
Open in Editor treatment
Copy treatment
```

If D2 requires a visual Sidecar change:

```text
return to human design decision
do not silently revise H2-C
```

---

# 27. TUI exclusion

This specification does not apply to the TUI.

The current TUI remains independently governed by its accepted H2-B gates/reference.

No attempt should be made to make the TUI visually imitate this Sidecar.

---

# 28. Approval record

When accepted, record:

```text
SIDECAR_DESIGN_SPEC = R6O-SIDECAR-DESIGN-SPEC-v1
REFERENCE_STANDARD_SHA256 = f78361a61734848a47c26feca1be31c1f01e8a2ee21f4bd650e436053c5b140c
REFERENCE_EXPANDED_SHA256 = 3939a378d12cf45c25aa5aa32bc0fb429ab044ca510aeb428049938ee3c61313
H2-C_VISUAL_CONFORMANCE = HUMAN_PASS
KNOWN_SIDECAR_VISUAL_DIVERGENCES = 0
```

That is the design lock.

Thereafter, "100% conformance" means exactly what this specification defines: **no knowingly different Sidecar-owned presentation.**
