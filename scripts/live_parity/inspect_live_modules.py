from __future__ import annotations

"""Bounded inspection of only the production modules loaded by a live child."""

import re
import sys
from pathlib import Path
from typing import Any


_EXCLUDED_PARTS = {"tests", "docs", "fixtures", "r6o_evidence", "evidence"}
_REPLAY_FILES = {"providers/recorded.py", "providers/fixtures.py"}
_RULES = {
    "g06_matches": re.compile(r"\bG06\b", re.IGNORECASE),
    "a02_matches": re.compile(r"\bA02\b", re.IGNORECASE),
    "rdx_case_matches": re.compile(r"\bRDX(?:[-_][A-Z0-9_-]+)?\b", re.IGNORECASE),
    "recorded_fixture_path_matches": re.compile(
        r"recorded-cases\.json|recorded[-_]worker|fixtures[/\\].*recorded",
        re.IGNORECASE,
    ),
    "historical_evidence_path_matches": re.compile(
        r"r6o_evidence|historical[-_]?evidence|fixed[-_]?evidence", re.IGNORECASE
    ),
    "expected_output_routing_matches": re.compile(
        r"expected[-_]?output|fixture[-_]?output", re.IGNORECASE
    ),
    "recorded_provider_live_import_matches": re.compile(
        r"providers\.recorded|(?:from|import)\s+providers\s+import\s+recorded",
        re.IGNORECASE,
    ),
}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def should_scan(relative: str) -> bool:
    normalized = relative.replace("\\", "/").lower()
    parts = set(Path(normalized).parts)
    if parts & _EXCLUDED_PARTS:
        return False
    return normalized not in _REPLAY_FILES


def imported_module_paths(roots: dict[str, str | Path]) -> dict[str, list[str]]:
    resolved = {label: Path(root).resolve() for label, root in roots.items()}
    paths: set[str] = set()
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename or not str(filename).endswith(".py"):
            continue
        candidate = Path(filename).resolve()
        for label, root in resolved.items():
            if _inside(candidate, root):
                relative = candidate.relative_to(root).as_posix()
                if should_scan(relative):
                    paths.add(f"{label}/{relative}")
    result = {label: [] for label in resolved}
    for value in sorted(paths):
        label, _, _ = value.partition("/")
        result.setdefault(label, []).append(value)
    return result


def scan_imported_modules(roots: dict[str, str | Path]) -> dict[str, Any]:
    paths_by_root = imported_module_paths(roots)
    counts = {name: 0 for name in _RULES}
    matched: list[str] = []
    for label, paths in paths_by_root.items():
        root = Path(roots[label]).resolve()
        for qualified in paths:
            relative = qualified.split("/", 1)[1]
            source = root / relative
            try:
                lines = source.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for line_number, line in enumerate(lines, 1):
                for rule, pattern in _RULES.items():
                    if pattern.search(line):
                        counts[rule] += 1
                        matched.append(f"{qualified}:{line_number}:{rule}")
    return {
        "scanned_module_count": sum(len(paths) for paths in paths_by_root.values()),
        "scanned_paths": sorted(path for paths in paths_by_root.values() for path in paths),
        **counts,
        "matched_locations": sorted(matched),
    }


def import_containment(
    side: str,
    *,
    r6o_root: str | Path,
    r6s_root: str | Path,
    gate_root: str | Path,
) -> list[str]:
    control = Path(r6o_root).resolve()
    frozen = Path(r6s_root).resolve()
    gate = Path(gate_root).resolve()
    violations: list[str] = []
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        candidate = Path(filename).resolve()
        if _inside(candidate, gate) and not _inside(candidate, gate / "scripts" / "live_parity"):
            violations.append(f"{name}={candidate}:gate-worktree")
        if side == "r6o" and (name == "r6o" or name.startswith("r6o.")):
            if not _inside(candidate, control):
                violations.append(f"{name}={candidate}:not-r6o-control")
        if name == "host" or any(name.startswith(prefix + ".") for prefix in ("host", "runtime", "controller", "observation", "providers")):
            if not _inside(candidate, frozen):
                violations.append(f"{name}={candidate}:not-r6s-frozen")
    return sorted(set(violations))
