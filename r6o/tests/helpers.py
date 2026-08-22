from __future__ import annotations

from r6o.model_binding.base import (
    ArtifactSnapshot,
    LifecycleSnapshot,
    ModelStateSnapshot,
    ReviewSubject,
)


def artifact(revision: str = "artifact-rev-1", body: str = "PROMPT BODY") -> ArtifactSnapshot:
    return ArtifactSnapshot(
        artifact_ref="prompt:P1",
        artifact_revision=revision,
        artifact_kind="prompt",
        title="Authoritative Prompt (PDL.md)",
        body=body,
        capabilities={"copy": True, "open_external": False},
    )


def state(
    *,
    revision: str = "model-rev-1",
    stage: str = "PROMPT_REVIEW",
    artifact_revision: str | None = "artifact-rev-1",
    result_body: str | None = None,
    session_id: str = "I-1",
    workspace_id: str = "W-1",
    model_response: str | None = None,
) -> ModelStateSnapshot:
    review = stage in {"PROMPT_REVIEW", "PLAN_REVIEW", "WAITING_INPUT"}
    terminal = stage in {"CLOSED_SUCCESS", "CLOSED_CANCELLED"}
    kind = "prompt" if stage == "PROMPT_REVIEW" else "plan"
    subject = None
    if review and artifact_revision:
        subject = ReviewSubject(
            artifact_ref=f"{kind}:{'P1' if kind == 'prompt' else 'R1'}",
            artifact_revision=artifact_revision,
            artifact_kind=kind,
            title="Authoritative Prompt (PDL.md)" if kind == "prompt" else "Authoritative Response Plan (PDL.md)",
        )
    disposition = "HOST_HANDOFF" if stage == "CLOSED_SUCCESS" else "CANCELLED" if stage == "CLOSED_CANCELLED" else None
    authorized = ()
    if stage == "CLOSED_SUCCESS" and artifact_revision:
        authorized = (artifact(artifact_revision),)
    return ModelStateSnapshot(
        session_id=session_id,
        workspace_id=workspace_id,
        model_revision=revision,
        stage=stage,
        interaction_state="TERMINAL" if terminal else "REVIEW_REQUIRED" if review else "WORKING",
        review_subject=subject,
        lifecycle=LifecycleSnapshot(
            review_required=review,
            terminal=terminal,
            close_allowed=review or terminal,
            handoff_ready=stage == "CLOSED_SUCCESS",
            terminal_disposition=disposition,
            result_body=result_body,
            authorized_handoff_artifacts=authorized,
        ),
        model_response=model_response,
    )
