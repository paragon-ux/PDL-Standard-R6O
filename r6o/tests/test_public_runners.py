from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_exact(arguments: list[str], baseline_repo: Path) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "PDL_R6S_BASELINE_REPO": str(baseline_repo),
            "PYTHONDONTWRITEBYTECODE": "1",
            "R6O2_SMOKE_MODE": "1",
        }
    )
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )


def test_exact_public_tui_command_reaches_real_ready_state(baseline_repo) -> None:
    process = _run_exact(["scripts/run_r6o2_tui.py", "--recorded"], baseline_repo)
    assert process.returncode == 0, process.stdout + process.stderr
    assert "R6O2_TUI_READY" in process.stdout
    assert "stage=PROMPT_REVIEW" in process.stdout

    a02 = _run_exact(
        ["scripts/run_r6o2_tui.py", "--recorded", "--case", "A02"],
        baseline_repo,
    )
    assert a02.returncode == 0, a02.stdout + a02.stderr
    assert "case=A02" in a02.stdout


def test_exact_public_sidecar_commands_reach_real_ready_state(baseline_repo) -> None:
    for mode in ("STANDARD", "EXPANDED"):
        process = _run_exact(
            [
                "scripts/run_r6o2_sidecar.py",
                "--recorded",
                "--harness",
                "--mode",
                mode,
            ],
            baseline_repo,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        assert "R6O2_SIDECAR_READY" in process.stdout
        assert f"mode={mode}" in process.stdout
        assert "stage=PROMPT_REVIEW" in process.stdout

    a02 = _run_exact(
        [
            "scripts/run_r6o2_sidecar.py",
            "--recorded",
            "--case",
            "A02",
            "--harness",
            "--mode",
            "STANDARD",
        ],
        baseline_repo,
    )
    assert a02.returncode == 0, a02.stdout + a02.stderr
    assert "case=A02" in a02.stdout
