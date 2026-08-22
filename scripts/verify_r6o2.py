from __future__ import annotations

"""R6O-2 qualification: protected R6O-1 regression plus real View gates."""

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(
    os.environ.get("PDL_R6S_BASELINE_REPO")
    or (ROOT.parent / "PDL-Standard-REPL-Harness")
).resolve()
ACCEPTED_R6O1_MERGE = "87717ea77975a9b9ac7637850926944e6ab4d48a"
PROTECTED_PATHS = (
    "r6o/model_binding",
    "r6o/viewmodel",
    "r6o/contracts",
    "r6o_evidence/R6O-1",
)
R6O1_TESTS = (
    "test_actions.py",
    "test_artifact_providers.py",
    "test_boundaries.py",
    "test_contracts.py",
    "test_lifecycle.py",
    "test_parity_g06_a02.py",
    "test_projection.py",
    "test_stale.py",
)
R6O2_TESTS = (
    "test_presentation_transport.py",
    "test_public_runners.py",
    "test_sidecar_view.py",
    "test_tui_view.py",
    "test_view_boundaries.py",
    "test_view_parity.py",
)


def _inventory(root: Path) -> dict[str, tuple[int, int, str]]:
    values: dict[str, tuple[int, int, str]] = {}
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and ".git" not in item.relative_to(root).parts
    ):
        stat = path.stat()
        values[path.relative_to(root).as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return values


def _run(
    command: list[str], cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _check(
    name: str,
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    failures: list[str],
) -> None:
    print(f"--- {name} ---")
    result = _run(command, cwd, environment)
    output = (result.stdout + result.stderr).strip().splitlines()
    print("\n".join(output[-16:]))
    print(f"exit={result.returncode}")
    if result.returncode:
        failures.append(name)


def _protected_paths_unchanged() -> bool:
    command = [
        "git",
        "diff",
        "--quiet",
        ACCEPTED_R6O1_MERGE,
        "--",
        *PROTECTED_PATHS,
    ]
    return subprocess.run(command, cwd=ROOT).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="R6O-2 stage verifier")
    parser.add_argument(
        "--display", action="store_true", help="run the local Tk geometry/interaction gate"
    )
    args = parser.parse_args()
    if not (BASELINE / "scripts" / "verify_repl_baseline.py").is_file():
        print(f"R6O-2 VERIFICATION FAIL: baseline not found at {BASELINE}")
        return 1
    if not _protected_paths_unchanged():
        print("R6O-2 VERIFICATION FAIL: accepted R6O-1 protected paths changed")
        return 1
    ambient_temp = Path(tempfile.gettempdir()).resolve()
    if ambient_temp == BASELINE or ambient_temp.is_relative_to(BASELINE):
        print("R6O-2 VERIFICATION FAIL: ambient temporary directory is inside the frozen baseline")
        return 1

    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PDL_R6S_BASELINE_REPO"] = str(BASELINE)
    baseline_before = _inventory(BASELINE)
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pdl-r6o2-verifier-") as temporary:
        scratch = Path(temporary)
        isolated = scratch / "PDL-Standard-REPL-Harness"
        clone = _run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(BASELINE), str(isolated)],
            scratch,
            environment,
        )
        if clone.returncode:
            print((clone.stdout + clone.stderr).strip())
            print("R6O-2 VERIFICATION FAIL: unable to isolate frozen baseline")
            return 1
        baseline_environment = dict(environment)
        baseline_environment["PYTHONPATH"] = str(isolated)
        r6o_environment = dict(environment)
        r6o_environment["PDL_R6S_BASELINE_REPO"] = str(isolated)
        r6o_environment.pop("PYTHONPATH", None)

        tests = ROOT / "r6o" / "tests"
        _check(
            "baseline_verifier",
            [sys.executable, str(isolated / "scripts" / "verify_repl_baseline.py")],
            scratch,
            baseline_environment,
            failures,
        )
        _check(
            "baseline_pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                str(isolated / "tests"),
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            scratch,
            baseline_environment,
            failures,
        )
        _check(
            "r6o1_regression",
            [
                sys.executable,
                "-m",
                "pytest",
                *(str(tests / name) for name in R6O1_TESTS),
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            ROOT,
            r6o_environment,
            failures,
        )
        _check(
            "r6o2_views",
            [
                sys.executable,
                "-m",
                "pytest",
                *(str(tests / name) for name in R6O2_TESTS),
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            ROOT,
            r6o_environment,
            failures,
        )
        _check(
            "full_suite",
            [
                sys.executable,
                "-m",
                "pytest",
                str(tests),
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            ROOT,
            r6o_environment,
            failures,
        )
        if args.display:
            display_environment = dict(r6o_environment)
            display_environment["R6O2_RUN_DISPLAY_TESTS"] = "1"
            _check(
                "local_display_gate",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(tests / "test_sidecar_display.py"),
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ],
                ROOT,
                display_environment,
                failures,
            )
        else:
            print("--- local_display_gate ---")
            print("LOCAL_DISPLAY_GATE_REQUIRED (run: python scripts/verify_r6o2.py --display)")

    if _inventory(BASELINE) != baseline_before:
        print("R6O-2 VERIFICATION FAIL: frozen baseline physical inventory changed")
        return 1
    if not _protected_paths_unchanged():
        print("R6O-2 VERIFICATION FAIL: accepted R6O-1 protected paths changed")
        return 1
    if failures:
        print("R6O-2 VERIFICATION FAIL: " + ", ".join(failures))
        return 1
    print("R6O-2 VERIFICATION PASS")
    print("VISUAL_MECHANICAL_CONFORMANCE = " + ("PASS" if args.display else "LOCAL_DISPLAY_GATE_REQUIRED"))
    print("H2_HUMAN_VISUAL_DISPOSITION = PENDING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
