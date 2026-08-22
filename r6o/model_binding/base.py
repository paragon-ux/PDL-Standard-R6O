from __future__ import annotations

"""Language-neutral R6O Model Port types.

Concrete runtime, controller, filesystem, and View types do not cross this
boundary.  Bindings translate their authoritative state into these snapshots.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

MODEL_PORT_VERSION = "r6o-model-port-1"


class StaleProjectionError(RuntimeError):
    """A command referenced obsolete authoritative state; nothing was mutated."""


@dataclass(frozen=True)
class ArtifactSnapshot:
    artifact_ref: str
    artifact_revision: str
    artifact_kind: str
    title: str
    body: str
    media_type: str = "text/plain"
    capabilities: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_ref": self.artifact_ref,
            "artifact_revision": self.artifact_revision,
            "artifact_kind": self.artifact_kind,
            "title": self.title,
            "body": self.body,
            "media_type": self.media_type,
            "capabilities": dict(self.capabilities),
        }


@dataclass(frozen=True)
class ReviewSubject:
    artifact_ref: str
    artifact_revision: str
    artifact_kind: str
    title: str

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact_ref": self.artifact_ref,
            "artifact_revision": self.artifact_revision,
            "artifact_kind": self.artifact_kind,
            "title": self.title,
        }


@dataclass(frozen=True)
class LifecycleSnapshot:
    review_required: bool
    terminal: bool
    close_allowed: bool
    handoff_ready: bool
    terminal_disposition: str | None = None
    result_body: str | None = None
    authorized_handoff_artifacts: tuple[ArtifactSnapshot, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_required": self.review_required,
            "terminal": self.terminal,
            "close_allowed": self.close_allowed,
            "handoff_ready": self.handoff_ready,
            "terminal_disposition": self.terminal_disposition,
            "result_body": self.result_body,
            "authorized_handoff_artifacts": [item.to_dict() for item in self.authorized_handoff_artifacts],
        }


@dataclass(frozen=True)
class ModelStateSnapshot:
    session_id: str
    workspace_id: str | None
    model_revision: str
    stage: str
    interaction_state: str
    review_subject: ReviewSubject | None
    lifecycle: LifecycleSnapshot
    model_response: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
            "model_revision": self.model_revision,
            "stage": self.stage,
            "interaction_state": self.interaction_state,
            "review_subject": self.review_subject.to_dict() if self.review_subject else None,
            "lifecycle": self.lifecycle.to_dict(),
            "model_response": self.model_response,
        }


@dataclass(frozen=True)
class HostInvocation:
    """Host-owned presentation choice; never sent through the Model Port."""

    request_id: str
    presentation: str = "AUTO"
    schema_version: str = "r6o-host-invocation-1"

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id must be non-empty")
        if self.presentation not in {"AUTO", "TUI", "SIDECAR"}:
            raise ValueError(f"unsupported presentation: {self.presentation}")


@dataclass(frozen=True)
class ModelSessionRequest:
    """Exactly one NEW or RESUME request for an authoritative Model session."""

    request_id: str
    task_text: str | None = None
    resume_session_id: str | None = None
    worker_profile: str | None = None
    schema_version: str = "r6o-model-session-request-1"

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id must be non-empty")
        task = self.task_text.strip() if isinstance(self.task_text, str) else ""
        resume = self.resume_session_id.strip() if isinstance(self.resume_session_id, str) else ""
        if bool(task) == bool(resume):
            raise ValueError("exactly one of task_text or resume_session_id is required")
        if self.task_text is not None and not task:
            raise ValueError("task_text must be non-empty")
        if self.resume_session_id is not None and not resume:
            raise ValueError("resume_session_id must be non-empty")

    @property
    def mode(self) -> str:
        return "NEW" if self.task_text is not None else "RESUME"


@dataclass(frozen=True)
class HandoffReceipt:
    handoff_ref: str
    handoff_id: str
    digest: str
    durable: bool


class HandoffStore(Protocol):
    def persist(self, envelope: dict[str, Any]) -> HandoffReceipt: ...


class ModelPort(Protocol):
    """Versioned MVVM Model Port (r6o-model-port-1)."""

    port_version: str = MODEL_PORT_VERSION

    def start_or_resume(self, request: ModelSessionRequest) -> ModelStateSnapshot: ...

    def read_state(self, session_id: str) -> ModelStateSnapshot: ...

    def read_artifact(
        self,
        session_id: str,
        artifact_ref: str,
        expected_revision: str | None = None,
    ) -> ArtifactSnapshot: ...

    def submit_user_message(
        self,
        session_id: str,
        text: str,
        expected_revision: str | None,
    ) -> ModelStateSnapshot: ...

    def finalize(self, session_id: str) -> ModelStateSnapshot: ...
