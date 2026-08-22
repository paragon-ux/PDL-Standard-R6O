from __future__ import annotations

"""Narrow non-path Model Port test doubles with no protocol semantics."""

from collections.abc import Mapping

from r6o.model_binding.base import (
    ArtifactSnapshot,
    ModelSessionRequest,
    ModelStateSnapshot,
    StaleProjectionError,
)


class StaticModelPort:
    """Return caller-supplied snapshots without interpreting protocol state."""

    port_version = "r6o-model-port-1"

    def __init__(
        self,
        snapshot: ModelStateSnapshot,
        artifacts: Mapping[str, ArtifactSnapshot] | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._artifacts = dict(artifacts or {})

    def start_or_resume(self, request: ModelSessionRequest) -> ModelStateSnapshot:
        if request.resume_session_id and request.resume_session_id != self._snapshot.session_id:
            raise KeyError(f"unknown session: {request.resume_session_id}")
        return self._snapshot

    def read_state(self, session_id: str) -> ModelStateSnapshot:
        if session_id != self._snapshot.session_id:
            raise KeyError(f"unknown session: {session_id}")
        return self._snapshot

    def read_artifact(
        self,
        session_id: str,
        artifact_ref: str,
        expected_revision: str | None = None,
    ) -> ArtifactSnapshot:
        self.read_state(session_id)
        if artifact_ref.endswith(":current") and self._snapshot.review_subject:
            artifact_ref = self._snapshot.review_subject.artifact_ref
        try:
            snapshot = self._artifacts[artifact_ref]
        except KeyError:
            raise KeyError(f"unknown artifact ref: {artifact_ref}") from None
        if expected_revision is not None and expected_revision != snapshot.artifact_revision:
            raise StaleProjectionError(
                f"artifact revision {expected_revision} != {snapshot.artifact_revision}"
            )
        return snapshot

    def submit_user_message(
        self,
        session_id: str,
        text: str,
        expected_revision: str | None,
    ) -> ModelStateSnapshot:
        raise RuntimeError("StaticModelPort does not accept mutations")

    def finalize(self, session_id: str) -> ModelStateSnapshot:
        return self.read_state(session_id)


class RecordingModelPort(StaticModelPort):
    """Record ordinary text and return a caller-supplied next snapshot."""

    def __init__(
        self,
        snapshot: ModelStateSnapshot,
        next_snapshot: ModelStateSnapshot,
        artifacts: Mapping[str, ArtifactSnapshot] | None = None,
    ) -> None:
        super().__init__(snapshot, artifacts)
        self.next_snapshot = next_snapshot
        self.submissions: list[str] = []

    def submit_user_message(
        self,
        session_id: str,
        text: str,
        expected_revision: str | None,
    ) -> ModelStateSnapshot:
        current = self.read_state(session_id)
        if expected_revision is not None and expected_revision != current.model_revision:
            raise StaleProjectionError(
                f"revision {expected_revision} != {current.model_revision}"
            )
        self.submissions.append(text)
        self._snapshot = self.next_snapshot
        return self._snapshot
