from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

sys.dont_write_bytecode = True

BASELINE_REPO = Path(
    os.environ.get("PDL_R6S_BASELINE_REPO")
    or (Path(__file__).resolve().parents[3] / "PDL-Standard-REPL-Harness")
).resolve()
FIXTURE_FILE = BASELINE_REPO / "fixtures" / "r4-recorded-worker" / "recorded-cases.json"


@pytest.fixture(scope="session")
def baseline_repo() -> Path:
    assert BASELINE_REPO.is_dir(), f"frozen baseline not found: {BASELINE_REPO}"
    return BASELINE_REPO


def _recorded_classes():
    old_path = list(sys.path)
    old_setting = sys.dont_write_bytecode
    try:
        sys.path.insert(0, str(BASELINE_REPO))
        sys.dont_write_bytecode = True
        from providers.recorded import RecordedFixtureBuilder
    finally:
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_setting
    return RecordedFixtureBuilder


@pytest.fixture()
def recorded_worker_factory():
    def factory(case_ids: list[str]):
        builder_type = _recorded_classes()
        entries = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))["entries"]
        wanted = set(case_ids)
        builder = builder_type()
        for entry in entries:
            if (entry.get("source") or "").split(":")[0] not in wanted:
                continue
            builder.add(
                entry["operation"],
                entry["prompt_sha256"],
                entry["response"],
                metadata={"source": entry.get("source", "vendored")},
                prompt_text=entry.get("prompt_text"),
            )
        return builder.build()

    return factory


@dataclass
class _WorkerResult:
    text: str
    metadata: dict[str, Any]


class OperationWorker:
    """Test worker replaying qualified responses by operation, with call counts."""

    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def call(self, request: Any) -> _WorkerResult:
        self.calls.append(request.operation)
        try:
            response = self.responses[request.operation]
        except KeyError:
            raise AssertionError(f"unexpected worker operation: {request.operation}") from None
        return _WorkerResult(response, {"source": "operation-worker"})


@pytest.fixture()
def operation_worker_factory():
    def factory(case_id: str) -> OperationWorker:
        entries = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))["entries"]
        responses = {
            entry["operation"]: entry["response"]
            for entry in entries
            if (entry.get("source") or "").split(":")[0] == case_id
        }
        return OperationWorker(responses)

    return factory
