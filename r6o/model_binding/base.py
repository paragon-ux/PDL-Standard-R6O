from __future__ import annotations

"""Language-neutral R6O Model Port types shared by bindings and the ViewModel.

No concrete runtime, filesystem, or View imports live here.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

MODEL_PORT_VERSION = "r6o-model-port-1"


class StaleProjectionError(RuntimeError):
    """Command referenced an obsolete model revision; no domain mutation occurred."""


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
            "media_type": self.media_type,
            "body": self.body,
            "capabilities": dict(self.capabilities),
        }


@dataclass(frozen=True)
class ModelRevision:
    session_id: str
    revision: str
    stage: str
    controller_state: dict[str, Any]

    @classmethod
    def from_controller_state(cls, session_id: str, state: dict[str, Any]) -> "ModelRevision":
        canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        token = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return cls(
            session_id=session_id,
            revision=token,
            stage=str(state.get("stage", "UNKNOWN")),
            controller_state=state,
        )


@dataclass(frozen=True)
class SessionInvocation:
    schema_version: str = "r6o-session-invocation-1"
    request_id: str = ""
    task_text: str | None = None
    resume_session_id: str | None = None
    presentation: str = "AUTO"
    worker_profile: str | None = None


class ModelPort(Protocol):
    """Versioned MVVM Model Port (r6o-model-port-1)."""

    port_version: str = MODEL_PORT_VERSION

    def start_or_resume(self, invocation: SessionInvocation) -> ModelRevision: ...

    def read_state(self, session_id: str) -> ModelRevision: ...

    def read_artifact(self, session_id: str, artifact_ref: str, expected_revision: str | None = None) -> ArtifactSnapshot: ...

    def submit_user_message(self, session_id: str, text: str, expected_revision: str | None) -> ModelRevision: ...

    def finalize(self, session_id: str) -> dict[str, Any]: ...

    def wait_for_revision(self, session_id: str, after_revision: str | None = None) -> ModelRevision: ...
