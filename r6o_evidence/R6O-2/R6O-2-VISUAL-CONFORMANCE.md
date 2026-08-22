# R6O-2 Visual Conformance

Locked references: `PDLt-R6O-Vertical-Presentation-Implementation-v2.0/references/REFERENCE_UI.png` (sha256 95bcaae7...) and `REFERENCE_UI-HARNESS.png` (sha256 73115928...); normative text in `03-VIEW-CONTRACT.md` and `references/TUI-REFERENCE.md`; derived reference in `PDL-Archival/R6O-2-VISUAL-GUIDE-REFERENCE.md`.

## Component reviews (Sol Medium + DeepSeek Vision, after each component)

### Component 1 — presentation adapter + envelopes
- Sol Medium: NO P0/P1 FINDINGS IN COMPONENT 1 SCOPE; overall CONFORMS.
- DeepSeek Vision: CONFIRMS no-chatbox/host-composer contract; layout geometry correctly belongs to the Sidecar component.

### Component 2 — TUI View
- Sol Medium first review: 7 findings (F1 dynamic actions truncated/ordinal, F2 disabled action executable, F3 focused input parsed as commands, F4 scroll unreachable, F5 stale refresh failure escapes, F6 notice below input line, F7 header glyph). All fixed.
- DeepSeek Vision after fix: CONFIRMS header `PDLt · PROMPT REVIEW`, artifact left, actions right (1–4), help line, `Review >` final line.

### Component 3 — Sidecar View
- Sol Medium first review: 5 findings (F1 toggle geometry not applied, F2 harness composer not rendered, F3 expanded actions absent, F4 focus not wired, F5 close hides harness). All fixed (embeddable panel, harness composer, pack order, focus callback, close-only-panel).
- Sol Medium second re-review (pre-final screenshots): F1 actions absent in expanded screenshot, F2 tests missing, F3 stale notice masked. F2 closed by the R6O-2 suite; F3 fixed in both Views; F1 resolved by re-capture after pack-order fix.
- DeepSeek Vision final: Standard CONFIRMS; Expanded CONFIRMS (right-anchored half-screen, artifact dominant, compact actions, composer visible at bottom, no sidecar input).

## Screenshots (evidence)
- `PDL-Archival/r6o2-tui-render.png` (TUI render)
- `PDL-Archival/r6o2-harness-standard.png` (Sidecar standard in harness)
- `PDL-Archival/r6o2-harness-expanded.png` (Sidecar expanded in harness)

## Geometry checklist
- [x] Standard: compact fixed-height panel immediately above host composer
- [x] Standard: artifact left / compact numbered actions right
- [x] Standard: no sidecar chatbox
- [x] Expanded: ~half-screen, right anchored
- [x] Expanded: artifact dominant, action panel intrinsic height
- [x] Expanded: composer remains harness-owned; no sidecar input
- [x] Expand/collapse and Close distinct; presentation-only
- [x] Reopen refetches current projection
