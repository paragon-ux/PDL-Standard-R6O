from __future__ import annotations

"""Provenance-safe composition root for deterministic R6O-2 sessions."""

import importlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.runtime_loader import FrozenRuntimeLoader
from r6o.presentation_transport import PresentationAdapter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT.parent / "PDL-Standard-REPL-Harness"

G06_ACTIVATION = (
    "Use $confirm-with-pseudocode to explain the difference between optimistic "
    "and pessimistic locking for senior developers."
)
A02_ACTIVATION = (
    "Use $confirm-with-pseudocode to compare Kafka and RabbitMQ for event delivery."
)
A02_REVISION = (
    "This is not confirmed. The audience should be data engineers, not backend engineers."
)


def resolve_baseline() -> Path:
    baseline = Path(
        os.environ.get("PDL_R6S_BASELINE_REPO") or DEFAULT_BASELINE
    ).resolve()
    FrozenRuntimeLoader(baseline).validate_identity()
    return baseline


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _module_inside(module: ModuleType, root: Path) -> bool:
    filename = getattr(module, "__file__", None)
    return bool(filename and _inside(Path(filename), root))


def build_recorded_worker(baseline: Path, case_id: str) -> Any:
    """Build a worker from the frozen vendored fixture without ambient imports."""

    FrozenRuntimeLoader(baseline).validate_identity()
    for name, module in tuple(sys.modules.items()):
        if name == "providers" or name.startswith("providers."):
            if not _module_inside(module, baseline):
                raise RuntimeError(f"module provenance collision for {name!r}")

    old_path = list(sys.path)
    old_dont_write = sys.dont_write_bytecode
    old_prefix = sys.pycache_prefix
    with tempfile.TemporaryDirectory(prefix="pdl-r6o2-provider-cache-") as cache:
        try:
            baseline_text = str(baseline)
            sys.path[:] = [
                baseline_text,
                *(entry for entry in sys.path if entry != baseline_text),
            ]
            sys.dont_write_bytecode = True
            sys.pycache_prefix = cache
            importlib.invalidate_caches()
            module = importlib.import_module("providers.recorded")
            if not _module_inside(module, baseline):
                raise RuntimeError(
                    "providers.recorded did not resolve inside the frozen baseline"
                )
            builder_type = module.RecordedFixtureBuilder
        finally:
            sys.path[:] = old_path
            sys.dont_write_bytecode = old_dont_write
            sys.pycache_prefix = old_prefix

    fixture = baseline / "fixtures" / "r4-recorded-worker" / "recorded-cases.json"
    entries = json.loads(fixture.read_text(encoding="utf-8"))["entries"]
    builder = builder_type()
    matched = 0
    for entry in entries:
        if (entry.get("source") or "").split(":", 1)[0] != case_id:
            continue
        matched += 1
        builder.add(
            entry["operation"],
            entry["prompt_sha256"],
            entry["response"],
            metadata={"source": entry.get("source", "vendored")},
            prompt_text=entry.get("prompt_text"),
        )
    if not matched:
        raise RuntimeError(f"recorded fixture case not found: {case_id}")
    return builder.build()


@dataclass
class RecordedSession:
    binding: LocalRuntimeModelBinding
    adapter: PresentationAdapter
    session_id: str
    workspace_root: Path
    _temporary: tempfile.TemporaryDirectory[str]

    def close(self) -> None:
        try:
            self.binding.close()
        finally:
            self._temporary.cleanup()


def start_recorded_session(
    case_id: str = "G06",
    activation: str | None = None,
    *,
    surface: str = "r6o2",
) -> RecordedSession:
    baseline = resolve_baseline()
    temporary = tempfile.TemporaryDirectory(prefix=f"pdl-{surface}-")
    workspace_root = Path(temporary.name) / "workspaces"
    worker = build_recorded_worker(baseline, case_id)
    binding = LocalRuntimeModelBinding(
        baseline,
        worker=worker,
        workspace_root=workspace_root,
        run_id=surface,
    )
    task = activation or (G06_ACTIVATION if case_id == "G06" else A02_ACTIVATION)
    snapshot = binding.start_or_resume(
        ModelSessionRequest(request_id=f"{surface}-new", task_text=task)
    )
    return RecordedSession(
        binding=binding,
        adapter=PresentationAdapter(binding),
        session_id=snapshot.session_id,
        workspace_root=workspace_root,
        _temporary=temporary,
    )
