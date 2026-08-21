from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BASELINE_REPO = Path(os.environ.get("PDL_R6S_BASELINE_REPO") or (Path(__file__).resolve().parents[3] / "PDL-Standard-REPL-Harness"))
if str(BASELINE_REPO) not in sys.path:
    sys.path.insert(0, str(BASELINE_REPO))

FIXTURE_FILE = BASELINE_REPO / "fixtures" / "r4-recorded-worker" / "recorded-cases.json"


@pytest.fixture(scope="session")
def baseline_repo() -> Path:
    assert BASELINE_REPO.is_dir(), f"frozen baseline not found: {BASELINE_REPO}"
    return BASELINE_REPO


@pytest.fixture(scope="session")
def fixture_file(baseline_repo: Path) -> Path:
    return baseline_repo / "fixtures" / "r4-recorded-worker" / "recorded-cases.json"


@pytest.fixture()
def recorded_worker_factory():
    from providers.fixtures import build_recorded_fixture_from_vendored

    def factory(case_ids: list[str]):
        return build_recorded_fixture_from_vendored(BASELINE_REPO, FIXTURE_FILE, case_ids=case_ids)

    return factory
