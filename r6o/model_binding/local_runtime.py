from __future__ import annotations

"""Current Model binding over the qualified, frozen R6S runtime."""

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from r6o.model_binding.base import (
    ArtifactSnapshot,
    LifecycleSnapshot,
    ModelSessionRequest,
    ModelStateSnapshot,
    ReviewSubject,
    StaleProjectionError,
)
from r6o.model_binding.runtime_loader import FrozenRuntimeLoader

_ARTIFACT_STAGE = {"prompt": "10_prompt", "plan": "30_plan"}
_ARTIFACT_TITLE = {
    "prompt": "Authoritative Prompt (PDL.md)",
    "plan": "Authoritative Response Plan (PDL.md)",
}
_REVIEW_STAGES = {"PROMPT_REVIEW", "PLAN_REVIEW", "WAITING_INPUT"}
_TERMINAL_STAGES = {"CLOSED_SUCCESS", "CLOSED_CANCELLED"}


def _canonical_hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _outside_baseline(path: str | Path, baseline_repo: Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if resolved == baseline_repo or _is_within(resolved, baseline_repo):
        raise ValueError(f"{label} must be outside the frozen baseline: {resolved}")
    return resolved


def _parse_ref(artifact_ref: str) -> tuple[str, str]:
    parts = artifact_ref.split(":", 1)
    if len(parts) != 2 or parts[0] not in _ARTIFACT_STAGE or not parts[1]:
        raise ValueError(f"invalid opaque artifact_ref: {artifact_ref!r}")
    return parts[0], parts[1]


class _SessionLocator:
    """Small local session-to-workspace registry below the Model Port."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.registry_path = workspace_root / ".r6o-session-locator.json"

    def _read(self) -> dict[str, str]:
        if not self.registry_path.exists():
            return {}
        value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise RuntimeError("invalid local session locator")
        return value

    def register(self, session_id: str, workspace: Path) -> None:
        entries = self._read()
        entries[session_id] = str(workspace.resolve())
        temporary = self.registry_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(entries, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.registry_path)

    def resolve(self, session_id: str) -> Path:
        try:
            return Path(self._read()[session_id]).resolve()
        except KeyError:
            raise KeyError(f"unknown session: {session_id}") from None


class LocalRuntimeModelBinding:
    """Translate R6S host/controller/workspace state into normalized snapshots."""

    port_version = "r6o-model-port-1"

    def __init__(
        self,
        baseline_repo: str | Path,
        *,
        worker: Any,
        workspace_root: str | Path | None = None,
        run_id: str = "r6o1",
    ) -> None:
        self.baseline_repo = Path(baseline_repo).resolve()
        if workspace_root is None:
            workspace_root = tempfile.mkdtemp(prefix="pdl-r6o1-workspaces-")
        self.workspace_root = _outside_baseline(workspace_root, self.baseline_repo, "workspace_root")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.worker = worker
        self.run_id = run_id
        self._loader = FrozenRuntimeLoader(self.baseline_repo)
        self._locator = _SessionLocator(self.workspace_root)
        self._host: Any = None
        self._session_id: str | None = None

    def _start_host(self, *, restore_path: Path | None = None) -> Any:
        if self._host is not None:
            raise RuntimeError("a Model session is already active in this binding")
        if restore_path is not None:
            restore_path = _outside_baseline(restore_path, self.baseline_repo, "restore_path")
        host_type = self._loader.load_host_class()
        self._host = host_type(
            self.baseline_repo,
            worker=self.worker,
            workspace_root=self.workspace_root,
            restore_path=restore_path,
            run_id=self.run_id,
        ).start()
        return self._host

    def start_or_resume(self, request: ModelSessionRequest) -> ModelStateSnapshot:
        if request.mode == "NEW":
            host = self._start_host()
            host.handle(request.task_text)
            snapshot = self._snapshot()
            self._session_id = snapshot.session_id
            workspace = _outside_baseline(host.status()["workspace_path"], self.baseline_repo, "workspace_path")
            self._locator.register(snapshot.session_id, workspace)
            return snapshot

        requested = request.resume_session_id
        if requested is None:
            raise ValueError("resume session identity missing")
        restore_path = _outside_baseline(self._locator.resolve(requested), self.baseline_repo, "restore_path")
        self._start_host(restore_path=restore_path)
        snapshot = self._snapshot()
        if snapshot.session_id != requested:
            self.close()
            raise RuntimeError(
                f"restored session identity mismatch: {snapshot.session_id} != {requested}"
            )
        self._session_id = requested
        return snapshot

    def _require_session(self, session_id: str) -> Any:
        if self._host is None or self._session_id is None:
            raise RuntimeError("start_or_resume must be called first")
        if session_id != self._session_id:
            raise KeyError(f"unknown session: {session_id}")
        return self._host

    def _artifact_material(
        self,
        kind: str,
        controller_artifact: dict[str, Any] | None,
    ) -> tuple[str, str, str]:
        if self._host is None:
            raise RuntimeError("Model session is not active")
        workspace = _outside_baseline(
            self._host.status()["workspace_path"], self.baseline_repo, "workspace_path"
        )
        output = workspace / "stages" / _ARTIFACT_STAGE[kind] / "output"
        metadata = json.loads((output / "current.json").read_text(encoding="utf-8"))
        body = (output / "current.md").read_text(encoding="utf-8").rstrip("\n")
        artifact_id = str(metadata["artifact_id"])
        revision = _canonical_hash(
            {
                "artifact_id": artifact_id,
                "metadata": metadata,
                "controller_metadata": controller_artifact or {},
                "body": body,
            }
        )
        return artifact_id, revision, body

    @staticmethod
    def _review_kind(stage: str, state: dict[str, Any]) -> str | None:
        if stage == "PROMPT_REVIEW":
            return "prompt"
        if stage in {"PLAN_REVIEW", "WAITING_INPUT"} and state.get("current_plan"):
            return "plan"
        return None

    def _snapshot(self) -> ModelStateSnapshot:
        if self._host is None:
            raise RuntimeError("Model session is not active")
        status = self._host.status()
        state = status.get("controller_state")
        if not isinstance(state, dict):
            raise RuntimeError("authoritative controller state is unavailable")
        session_id = str(state.get("instance_id") or "")
        if not session_id:
            raise RuntimeError("authoritative session identity is unavailable")
        stage = str(state.get("stage") or "UNKNOWN")
        kind = self._review_kind(stage, state)
        subject: ReviewSubject | None = None
        artifact_revision: str | None = None
        if kind:
            controller_artifact = state.get(f"current_{kind}")
            artifact_id, artifact_revision, _ = self._artifact_material(kind, controller_artifact)
            subject = ReviewSubject(
                artifact_ref=f"{kind}:{artifact_id}",
                artifact_revision=artifact_revision,
                artifact_kind=kind,
                title=_ARTIFACT_TITLE[kind],
            )
        if stage in _REVIEW_STAGES:
            interaction = "REVIEW_REQUIRED"
        elif stage in _TERMINAL_STAGES:
            interaction = "TERMINAL"
        elif stage == "UNKNOWN":
            interaction = "INACTIVE"
        else:
            interaction = "WORKING"
        terminal_disposition = None
        if stage == "CLOSED_SUCCESS":
            terminal_disposition = "HOST_HANDOFF"
        elif stage == "CLOSED_CANCELLED":
            terminal_disposition = "CANCELLED"
        lifecycle = LifecycleSnapshot(
            review_required=stage in _REVIEW_STAGES,
            terminal=stage in _TERMINAL_STAGES,
            close_allowed=stage in _REVIEW_STAGES or stage in _TERMINAL_STAGES,
            handoff_ready=stage == "CLOSED_SUCCESS",
            terminal_disposition=terminal_disposition,
            result_body=state.get("result") or state.get("execution_result"),
        )
        model_revision = _canonical_hash(
            {
                "controller_state": state,
                "workspace_id": status.get("workspace_id"),
                "review_artifact_revision": artifact_revision,
            }
        )
        return ModelStateSnapshot(
            session_id=session_id,
            workspace_id=str(status["workspace_id"]) if status.get("workspace_id") else None,
            model_revision=model_revision,
            stage=stage,
            interaction_state=interaction,
            review_subject=subject,
            lifecycle=lifecycle,
        )

    def read_state(self, session_id: str) -> ModelStateSnapshot:
        self._require_session(session_id)
        return self._snapshot()

    def read_artifact(
        self,
        session_id: str,
        artifact_ref: str,
        expected_revision: str | None = None,
    ) -> ArtifactSnapshot:
        self._require_session(session_id)
        kind, requested_id = _parse_ref(artifact_ref)
        status = self._host.status()
        state = status.get("controller_state") or {}
        controller_artifact = state.get(f"current_{kind}")
        artifact_id, revision, body = self._artifact_material(kind, controller_artifact)
        if requested_id not in {"current", artifact_id}:
            raise ValueError(
                f"artifact identity mismatch: {artifact_ref!r} vs {artifact_id!r}"
            )
        if expected_revision is not None and expected_revision != revision:
            raise StaleProjectionError(
                f"artifact revision {expected_revision} != {revision}"
            )
        return ArtifactSnapshot(
            artifact_ref=f"{kind}:{artifact_id}",
            artifact_revision=revision,
            artifact_kind=kind,
            title=_ARTIFACT_TITLE[kind],
            body=body,
            capabilities={"copy": True, "open_external": True},
        )

    def submit_user_message(
        self,
        session_id: str,
        text: str,
        expected_revision: str | None,
    ) -> ModelStateSnapshot:
        host = self._require_session(session_id)
        current = self._snapshot()
        if expected_revision is not None and expected_revision != current.model_revision:
            raise StaleProjectionError(
                f"revision {expected_revision} != {current.model_revision}"
            )
        immediately_before_mutation = self._snapshot()
        if expected_revision is not None and expected_revision != immediately_before_mutation.model_revision:
            raise StaleProjectionError("authoritative state changed before mutation")
        host.handle(text)
        return self._snapshot()

    def finalize(self, session_id: str) -> ModelStateSnapshot:
        snapshot = self.read_state(session_id)
        self.close()
        return snapshot

    def close(self) -> None:
        if self._host is not None:
            self._host.close()
            self._host = None
        self._session_id = None
