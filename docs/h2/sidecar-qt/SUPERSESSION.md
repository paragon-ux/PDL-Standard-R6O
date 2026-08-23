# Supersession

This package supersedes `R6O-SIDECAR-FIDELITY-MINI-SPEC-v1-2026-08-23`
for all framework/rendering-pipeline instructions.

Retained from v1:

- measured icon optical sizes;
- SVG icon assets;
- Inter / JetBrains Mono typography decision;
- corrected border/color tokens;
- canonical Sidecar dimensions;
- zero-known-divergence approval rule;
- Sidecar-only visual evidence principle.

Revoked from v1:

- Pillow production raster renderer;
- ImageTk/PhotoImage rendering pipeline;
- Tk Canvas as window presentation surface;
- Windows-authoritative visual qualification;
- Win32 rounded-region prescription as the canonical implementation;
- 4x Pillow supersampling requirement;
- cross-platform skip of rounded-window behavior.

Current authority:

`PySide6 + Qt Quick/QML`, using one shared QML implementation on Windows,
Linux/X11, and Linux/Wayland.
