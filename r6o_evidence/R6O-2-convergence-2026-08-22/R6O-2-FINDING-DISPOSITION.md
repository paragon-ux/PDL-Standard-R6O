# R6O-2 PR #3 Finding Disposition

Code range: `87717ea77975a9b9ac7637850926944e6ab4d48a..f9d3a569c066486d6f621901097c75d477197a79`

The later v3 review supersedes the first review only where placement/composition guidance conflicts. Human decision `DR-R6O-2R-1` freezes Expanded as artifact TOP / Review Options BELOW because the horizontal alternative caused visible compression.

| Finding | Severity | Triage | Disposition |
|---|---:|---|---|
| Luna F1 — TUI top border exceeds width | P2 | Valid | FIXED; display-width invariant at 42/56/76/100/120. |
| Luna F2 — actions omitted at 42x14 | P2 | Valid | FIXED; focus-driven viewport and continuation cues retain all actions. |
| H2-3-F1 — horizontal Expanded plus collapsed transition | P1 | Partially superseded | Horizontal prescription superseded by V3-05 and human decision; stale-layout/transition defect FIXED. |
| H2-3-F2 — terminal third artifact | P1 | Valid | FIXED in both Views. |
| H2-3-F3 — Close injects reopen UI | P1 | Valid | FIXED; fresh external View reconstruction tested. |
| H2-3-F4 — fake host/editor | P1 | Valid | FIXED; neutral fullscreen parent/composer fixture. |
| H2-3-F5 — TUI revision focus | P1 | Valid | FIXED using real A02 flow. |
| H2-3-F6 — incomplete mechanical PASS | P1 | Valid | FIXED with live transitions, lifecycle tests, public smokes, and new post-freeze evidence. |
| H2-3-F7 — raw replay exception | P2 | Valid | FIXED; public case selector and deterministic friendly notice, no mutation/fallback. |
| H2-3-F8 — revision footer | P2 | Valid | FIXED in default UI; explicit debug-only option retained. |
| V3-01 | P1 | Valid | FIXED; separate owned/transient frameless floating Sidecar. |
| V3-02 | P1 | Valid | FIXED; selected usable work area, monitor, and DPI recorded. |
| V3-03 | P1 | Valid | FIXED; Standard composer equations pass exactly at measured DPI. |
| V3-04 | P1 | Valid | FIXED; 30% right overlay and frozen insets pass exactly. |
| V3-05 | P1 | Valid | FIXED; approved vertical composition and live controls tested. |
| V3-06 | P1 | Valid | FIXED; custom-only chrome properties and screenshots. |
| V3-07 | P1 | Valid | FIXED; neutral fixture, no reopen control, state-preserving Close. |
| V3-08 | P1 | Valid | FIXED; terminal dismissal/yield, no third artifact. |
| V3-09 | P2 | Valid | FIXED; default footer absent. |
| Luna convergence C1 — stale TUI text projection bypasses terminal/clamp lifecycle | P1 | Valid | FIXED in `f9d3a56`; real stale-to-terminal exit and stale action-index clamp regressions pass. |

No lower-severity finding was discarded. Every prior finding is either fixed or explicitly superseded by the later authoritative review plus the human freeze decision.
