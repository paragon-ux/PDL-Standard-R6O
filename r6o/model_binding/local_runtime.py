from __future__ import annotations

"""Current MVVM Model binding: adapter over the frozen R6S runtime via PDLtHost.

This module is the only place that imports the current runtime. It treats the
frozen baseline repository as read-only and never writes into it.
"""

import json
from pathlib import Path
from typing import Any

from r6o.model_binding.base import (
    ArtifactSnapshot,
    ModelRevision,
    SessionInvocation,
    StaleProjectionError,
)

_ARTIFACT_STAGE = {"prompt": "10_prompt", "plan": "30_plan"}
_ARTIFACT_TITLE = {
    "prompt": "Authoritative Prompt (PDL.md)",
    "plan": "Authoritative Response Plan (PDL.md)",
}


def _parse_ref(artifact_ref: str) -> tuple[str, str]:
    parts = artifact_ref.split(":", 1)
    if len(parts) != 2 or parts[0] not in _ARTIFACT_STAGE:
        raise ValueError(f"invalid opaque artifact_ref: {artifact_ref!r}")
    return parts[0], parts[1]


class LocalRuntimeModelBinding:
    """Model Port bound to the qualified R6S Python runtime."""

    port_version = "r6o-model-port-1"

    def __init__(
        self,
        baseline_repo: str | Path,
        *,
        worker: Any,
        workspace_root: str | Path | None = None,
        restore_path: str | Path | None = None,
        run_id: str = "r6o1",
    ):
        self.baseline_repo = Path(baseline_repo).resolve()
        self.worker = worker
        self.workspace_root = Path(workspace_root) if workspace_root else None
        self.restore_path = Path(restore_path) if restore_path else None
        self.run_id = run_id
        self._host: Any = None
        self._session_id: str | None = None

    def _ensure_host(self) -> Any:
        if self._host is not None:
            return self._host
        from host.app import PDLtHost  # lazy import from the frozen repo

        self._host = PDLtHost(
            self.baseline_repo,
            worker=self.worker,
            workspace_root=self.workspace_root,
            restore_path=self.restore_path,
            run_id=self.run_id,
        ).start()
        status = self._host.status()
        self._session_id = str(status.get("workspace_id") or self.run_id)
        return self._host

    def start_or_resume(self, invocation: SessionInvocation) -> ModelRevision:
        self._ensure_host()
        if self._session_id is None:
            raise RuntimeError("session identity missing")
        return self.read_state(self._session_id)

    def read_state(self, session_id: str) -> ModelRevision:
        host = self._ensure_host()
        if self._session_id is not None and session_id != self._session_id:
            raise KeyError(f"unknown session: {session_id}")
        status = host.status()
        state = status.get("controller_state") or {}
        return ModelRevision.from_controller_state(self._session_id or session_id, state)

    def read_artifact(self, session_id: str, artifact_ref: str, expected_revision: str | None = None) -> ArtifactSnapshot:
        kind, artifact_id = _parse_ref(artifact_ref)
        current = self.read_state(session_id)
        status = self._host.status()
        workspace = Path(status["workspace_path"])
        output = workspace / "stages" / _ARTIFACT_STAGE[kind] / "output"
        meta = json.loads((output / "current.json").read_text(encoding="utf-8"))
        body = (output / "current.md").read_text(encoding="utf-8").rstrip("\n")
        actual_id = str(meta["artifact_id"])
        if artifact_id not in ("current", actual_id):
            raise ValueError(f"artifact identity mismatch: {artifact_ref!r} vs {actual_id!r}")
        if expected_revision is not None and expected_revision != actual_id:
            raise StaleProjectionError(f"artifact revision {expected_revision} != {actual_id}")
        return ArtifactSnapshot(
            artifact_ref=f"{kind}:{actual_id}",
            artifact_revision=actual_id,
            artifact_kind=kind,
            title=_ARTIFACT_TITLE[kind],
            body=body,
            capabilities={"copy": True, "open_external": True},
        )

    def submit_user_message(self, session_id: str, text: str, expected_revision: str | None) -> ModelRevision:
        current = self.read_state(session_id)
        if expected_revision is not None and expected_revision != current.revision:
            raise StaleProjectionError(f"revision {expected_revision} != {current.revision}")
        self._host.handle(text)
        return self.read_state(session_id)

    def finalize(self, session_id: str) -> dict[str, Any]:
        state = self.read_state(session_id).controller_state
        if self._host is not None:
            self._host.close()
            self._host = None
        return state

    def wait_for_revision(self, session_id: str, after_revision: str | None = None) -> ModelRevision:
        return self.read_state(session_id)

    def close(self) -> None:
        if self._host is not None:
            self._host.close()
            self._host = None
