# R6O-2 H2 Follow-up Finding Disposition

Frozen range: `87717ea77975a9b9ac7637850926944e6ab4d48a..b1802d49e33e8a6449c27a2839aa682083d11666`

Frozen tree: `e1b6d58023afde47f836b6674d7a74c5055cf8d7`

The human H2 exercise rejected the previous candidate after the public GUI showed only the fullscreen parent/composer and the recorded A02 case did not expose its accepted deterministic input. The earlier evidence remains unchanged as historical evidence of why geometry-only claims were insufficient.

| Finding | Severity | Independent triage | Disposition |
|---|---:|---|---|
| H2-4-F1 — Standard and Expanded both visibly collapse to the parent/composer because the Sidecar is behind its fullscreen owner | P1 | Valid against the previous freeze; fixed and not reproducible at `b1802d49` | FIXED. The frameless Tk `Toplevel` now receives a real Win32 owner; owner interaction restores owned-window order without global topmost. Geometry exposes `sidecar_native_owner_attached` and `sidecar_above_owner`. Live capture fails closed if either invariant is false, and a pixel regression proves Sidecar pixels are actually present. |
| H2-4-F2 — A02 does not work from the public TUI/Sidecar because the exact recorded input is hidden and replay-miss guidance tells an A02 user to use A02 | P1 | Valid against the previous freeze; fixed and not reproducible at `b1802d49` | FIXED. Both public A02 runners preload and visibly select the exact recorded revision. The UI instructs the reviewer to choose `Something else...` and submit. A02-specific mismatch guidance now says to relaunch A02, and real TUI/Sidecar tests prove the semantic revision result. |

All findings in `r6o_evidence/R6O-2-convergence-2026-08-22/R6O-2-FINDING-DISPOSITION.md`, including P2 findings, remain preserved and closed or explicitly superseded there. No lower-severity finding was discarded in this follow-up.

No architecture ambiguity was introduced. Protected R6O-1 paths are unchanged, no R6O-3 integration was added, and H2 is pending a new human exercise.
