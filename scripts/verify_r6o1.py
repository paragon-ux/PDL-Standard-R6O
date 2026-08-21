from __future__ import annotations

"""Portable R6O-1 verifier over a frozen, externally bound R6S baseline."""

import os
import subprocess
import sys
import tempfile
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(
    os.environ.get("PDL_R6S_BASELINE_REPO")
    or (ROOT.parent / "PDL-Standard-REPL-Harness")
).resolve()


def _run(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _physical_inventory(root: Path) -> dict[str, tuple[int, int, str]]:
    inventory: dict[str, tuple[int, int, str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file() and ".git" not in item.relative_to(root).parts):
        stat = path.stat()
        inventory[path.relative_to(root).as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return inventory


def main() -> int:
    if not (BASELINE / "scripts" / "verify_repl_baseline.py").is_file():
        print(f"R6O-1 VERIFICATION FAIL: baseline not found at {BASELINE}")
        return 1
    ambient_temp = Path(tempfile.gettempdir()).resolve()
    try:
        ambient_temp.relative_to(BASELINE)
    except ValueError:
        pass
    else:
        print("R6O-1 VERIFICATION FAIL: ambient temporary directory is inside the frozen baseline")
        return 1
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PDL_R6S_BASELINE_REPO"] = str(BASELINE)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(BASELINE) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    baseline_before = _physical_inventory(BASELINE)
    with tempfile.TemporaryDirectory(prefix="pdl-r6o1-verifier-") as temporary:
        scratch = Path(temporary)
        isolated_baseline = scratch / "PDL-Standard-REPL-Harness"
        clone = _run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(BASELINE), str(isolated_baseline)],
            scratch,
            environment,
        )
        if clone.returncode != 0:
            print((clone.stdout + clone.stderr).strip())
            print("R6O-1 VERIFICATION FAIL: unable to isolate frozen baseline")
            return 1
        baseline_environment = dict(environment)
        baseline_environment["PYTHONPATH"] = str(isolated_baseline)
        r6o_environment = dict(baseline_environment)
        r6o_environment["PDL_R6S_BASELINE_REPO"] = str(isolated_baseline)
        checks = [
            (
                "baseline_verifier",
                [sys.executable, str(isolated_baseline / "scripts" / "verify_repl_baseline.py")],
                scratch,
                baseline_environment,
            ),
            (
                "baseline_pytest",
                [sys.executable, "-m", "pytest", str(isolated_baseline / "tests"), "-q", "-p", "no:cacheprovider"],
                scratch,
                baseline_environment,
            ),
            (
                "r6o1_pytest",
                [sys.executable, "-m", "pytest", str(ROOT / "r6o" / "tests"), "-q", "-p", "no:cacheprovider"],
                ROOT,
                r6o_environment,
            ),
        ]
        failures: list[str] = []
        for name, cmd, cwd, check_environment in checks:
            print(f"--- {name} ---")
            process = _run(cmd, cwd, check_environment)
            tail = (process.stdout + process.stderr).strip().splitlines()[-12:]
            print("\n".join(tail))
            if process.returncode != 0:
                failures.append(name)
            print(f"exit={process.returncode}")
    if failures:
        print(f"R6O-1 VERIFICATION FAIL: {', '.join(failures)}")
        return 1
    if _physical_inventory(BASELINE) != baseline_before:
        print("R6O-1 VERIFICATION FAIL: frozen baseline physical inventory changed")
        return 1
    print("R6O-1 VERIFICATION PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
