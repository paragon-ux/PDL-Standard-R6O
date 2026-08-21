from __future__ import annotations

"""R6O-1 verifier: frozen baseline gates + work-repo conformance suite."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT.parent / "PDL-Standard-REPL-Harness"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    checks = [
        ("baseline_verifier", ["python", "scripts\\verify_repl_baseline.py"], BASELINE),
        ("baseline_pytest", ["python", "-m", "pytest", "tests", "-q"], BASELINE),
        ("r6o1_pytest", ["python", "-m", "pytest", "r6o\\tests", "-q"], ROOT),
    ]
    failures: list[str] = []
    for name, cmd, cwd in checks:
        print(f"--- {name} ---")
        proc = _run(cmd, cwd)
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
        print("\n".join(tail))
        if proc.returncode != 0:
            failures.append(name)
        print(f"exit={proc.returncode}")
    if failures:
        print(f"R6O-1 VERIFICATION FAIL: {', '.join(failures)}")
        return 1
    print("R6O-1 VERIFICATION PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
