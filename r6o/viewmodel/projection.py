from __future__ import annotations

"""FocusProjection construction (pure; no LLM calls, no domain mutation)."""

import uuid
from typing import Any

from r6o.model_binding.base import ArtifactSnapshot, ModelRevision, ModelPort
from r6o.viewmodel.actions import project_actions

_REVIEW_STAGES = {"PROMPT_REVIEW", "PLAN_REVIEW", "WAITING_INPUT"}
_WORKING_STAGES = {"PROMPT_REQUIRED", "PLAN_REQUIRED", "EXECUTION_READY", "OUTCOME_UNCERTAIN"}
_TERMINAL_STAGES = {"CLOSED_SUCCESS", "CLOSED_CANCELLED"}

_FOCUS_KIND = {
    "PROMPT_REVIEW": "PROMPT_REVIEW",
    "PLAN_REVIEW": "PLAN_REVIEW",
    "WAITING_INPUT": "WAITING_INPUT",
    "EXECUTION_READY": "HANDOFF_READY",
    "CLOSED_SUCCESS": "CLOSED",
    "CLOSED_CANCELLED": "CANCELLED",
}


def _artifact_dict(snapshot: ArtifactSnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "artifact_ref": snapshot.artifact_ref,
        "artifact_revision": snapshot.artifact_revision,
        "artifact_kind": snapshot.artifact_kind,
        "title": snapshot.title,
        "media_type": snapshot.media_type,
        "body": snapshot.body,
        "capabilities": dict(snapshot.capabilities),
    }


def build_focus_projection(revision: ModelRevision, artifact: ArtifactSnapshot | None) -> dict[str, Any]:
    stage = revision.stage
    if stage in _REVIEW_STAGES:
        interaction_state = "REVIEW_REQUIRED"
    elif stage in _WORKING_STAGES:
        interaction_state = "WORKING"
    elif stage in _TERMINAL_STAGES:
        interaction_state = "TERMINAL"
    else:
        interaction_state = "INACTIVE"
    return {
        "schema_version": "r6o-focus-projection-1",
        "session_id": revision.session_id,
        "workspace_id": revision.controller_state.get("instance_id"),
        "model_revision": revision.revision,
        "projection_id": uuid.uuid4().hex,
        "interaction_state": interaction_state,
        "stage": stage,
        "focus_kind": _FOCUS_KIND.get(stage),
        "artifact": _artifact_dict(artifact),
        "actions": project_actions(stage),
        "lifecycle": {
            "review_required": stage in _REVIEW_STAGES,
            "terminal": stage in _TERMINAL_STAGES,
            "close_allowed": stage in _REVIEW_STAGES or stage in _TERMINAL_STAGES,
            "handoff_ready": stage in {"EXECUTION_READY", "CLOSED_SUCCESS"},
        },
    }


def current_artifact_ref(stage: str) -> str | None:
    if stage == "PROMPT_REVIEW":
        return "prompt:current"
    if stage == "PLAN_REVIEW":
        return "plan:current"
    return None


def build_focus_projection_from_port(port: ModelPort, session_id: str) -> dict[str, Any]:
    revision = port.read_state(session_id)
    ref = current_artifact_ref(revision.stage)
    artifact = port.read_artifact(session_id, ref) if ref else None
    return build_focus_projection(revision, artifact)
