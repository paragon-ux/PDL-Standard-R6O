from __future__ import annotations

"""R6O-2 stage verifier: baseline + R6O-1 regression + R6O-2 view gates.

Runs against an isolated clone of the frozen oracle so the live checkout is
never written. Physical inventory of the live oracle is verified before/after.
"""

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(os.environ.get("PDL_R6S_BASELINE_REPO") or (ROOT.parent / "PDL-Standard-REPL-Harness"))

R6O1_TEST_FILES = [
    "test_contracts.py", "test_projection.py", "test_actions.py", "test_stale.py",
    "test_artifact_providers.py", "test_parity_g06_a02.py", "test_lifecycle.py",
]
R6O2_TEST_FILES = [
    "test_view_envelopes.py", "test_presentation_transport.py", "test_tui_view.py",
    "test_sidecar_view.py", "test_view_parity.py", "test_view_boundaries.py",
]


def _physical_inventory(root: Path) -> dict[str, tuple[int, str]]:
    inventory: dict[str, tuple[int, str]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        inventory[rel] = (path.stat().st_size, digest)
    return inventory


def _run(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _run_check(name: str, cmd: list[str], cwd: Path, env: dict[str, str], failures: list[str]) -> None:
    print(f"--- {name} ---")
    proc = _run(cmd, cwd, env)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
    print("\n".join(tail))
    if proc.returncode != 0:
        failures.append(name)
    print(f"exit={proc.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="R6O-2 verifier")
    parser.add_argument("--display", action="store_true", help="run opt-in display-dependent Tk checks")
    args = parser.parse_args()

    if not (BASELINE / "scripts" / "verify_repl_baseline.py").is_file():
        print(f"R6O-2 VERIFICATION FAIL: baseline not found at {BASELINE}")
        return 1
    ambient_temp = Path(tempfile.gettempdir()).resolve()
    try:
        ambient_temp.relative_to(BASELINE)
    except ValueError:
        pass
    else:
        print("R6O-2 VERIFICATION FAIL: ambient temporary directory is inside the frozen baseline")
        return 1

    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PDL_R6S_BASELINE_REPO"] = str(BASELINE)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(BASELINE) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")

    baseline_before = _physical_inventory(BASELINE)
    failures: list[str] = []
    skipped_display: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pdl-r6o2-verifier-") as temporary:
        scratch = Path(temporary)
        isolated_baseline = scratch / "PDL-Standard-REPL-Harness"
        clone = _run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(BASELINE), str(isolated_baseline)],
            scratch,
            environment,
        )
        if clone.returncode != 0:
            print((clone.stdout + clone.stderr).strip())
            print("R6O-2 VERIFICATION FAIL: unable to isolate frozen baseline")
            return 1
        baseline_environment = dict(environment)
        baseline_environment["PYTHONPATH"] = str(isolated_baseline)
        r6o_environment = dict(baseline_environment)
        r6o_environment["PDL_R6S_BASELINE_REPO"] = str(isolated_baseline)

        checks = [
            ("baseline_verifier", [sys.executable, str(isolated_baseline / "scripts" / "verify_repl_baseline.py")], scratch, baseline_environment),
            ("baseline_pytest", [sys.executable, "-m", "pytest", str(isolated_baseline / "tests"), "-q", "-p", "no:cacheprovider"], scratch, baseline_environment),
            ("r6o1_regression", [sys.executable, "-m", "pytest", *[str(ROOT / "r6o" / "tests" / n) for n in R6O1_TEST_FILES], "-q", "-p", "no:cacheprovider"], ROOT, r6o_environment),
            ("r6o2_tests", [sys.executable, "-m", "pytest", *[str(ROOT / "r6o" / "tests" / n) for n in R6O2_TEST_FILES], "-q", "-p", "no:cacheprovider"], ROOT, r6o_environment),
            ("full_suite", [sys.executable, "-m", "pytest", str(ROOT / "r6o" / "tests"), "-q", "-p", "no:cacheprovider"], ROOT, r6o_environment),
        ]
        for name, cmd, cwd, env in checks:
            _run_check(name, cmd, cwd, env, failures)

        if args.display:
            display_environment = dict(r6o_environment)
            display_environment["R6O2_RUN_DISPLAY_TESTS"] = "1"
            _run_check(
                "r6o2_display_tests",
                [sys.executable, "-m", "pytest", str(ROOT / "r6o" / "tests" / "test_sidecar_display.py"), "-q", "-p", "no:cacheprovider"],
                ROOT,
                display_environment,
                failures,
            )
        else:
            print("--- r6o2_display_tests ---")
            print("SKIPPED: opt-in display-dependent checks (run locally: python scripts/verify_r6o2.py --display)")
            skipped_display.append("--display not requested")

    if _physical_inventory(BASELINE) != baseline_before:
        print("R6O-2 VERIFICATION FAIL: frozen baseline physical inventory changed")
        return 1

    print()
    print("R6O-2 mechanical gate summary")
    for name, _, _, _ in checks:
        print(f"  {name}: {'PASS' if name not in failures else 'FAIL'}")
    print(f"  frozen_oracle_inventory: UNCHANGED ({len(baseline_before)} files)")
    if skipped_display:
        print(f"  display_dependent_checks: NOT RUN ({'; '.join(skipped_display)})")
    if failures:
        print(f"R6O-2 VERIFICATION FAIL: {', '.join(failures)}")
        return 1
    print("R6O-2 VERIFICATION PASS (mechanical H2 gates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
