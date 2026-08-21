from __future__ import annotations

"""Pure lifecycle compilation and persistence-before-observation coordination."""

import hashlib
import json
from typing import Any

from r6o.viewmodel.model_port import (
    ArtifactSnapshot,
    HandoffReceipt,
    HandoffStore,
    ModelStateSnapshot,
)

_RESUMABLE_CLOSE_STAGES = {"PROMPT_REVIEW", "PLAN_REVIEW", "WAITING_INPUT"}


def _hash_identity(prefix: str, value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_disposition(state: ModelStateSnapshot) -> str:
    if state.stage == "CLOSED_SUCCESS":
        return "HOST_HANDOFF"
    if state.stage == "CLOSED_CANCELLED":
        return "CANCELLED"
    if state.stage in _RESUMABLE_CLOSE_STAGES:
        return "PDLT_RESUME"
    raise ValueError(f"stage {state.stage!r} is not an authorized close synchronization point")


def build_handoff_envelope(
    state: ModelStateSnapshot,
    artifacts: list[ArtifactSnapshot],
) -> dict[str, Any]:
    if derive_disposition(state) != "HOST_HANDOFF" or not state.lifecycle.handoff_ready:
        raise ValueError("handoff requires authorized CLOSED_SUCCESS state")
    semantics = {
        "session_id": state.session_id,
        "workspace_id": state.workspace_id,
        "source_model_revision": state.model_revision,
        "disposition": "HOST_HANDOFF",
        "artifacts": [
            {
                "artifact_ref": item.artifact_ref,
                "artifact_revision": item.artifact_revision,
                "artifact_kind": item.artifact_kind,
                "body": item.body,
            }
            for item in artifacts
        ],
        "execution_request": (
            {"result_body": state.lifecycle.result_body}
            if state.lifecycle.result_body is not None
            else None
        ),
        "created_at": None,
    }
    return {
        "schema_version": "r6o-handoff-envelope-1",
        "handoff_id": _hash_identity("handoff", semantics),
        **semantics,
    }


def build_close_result(
    state: ModelStateSnapshot,
    *,
    receipt: HandoffReceipt | None = None,
) -> dict[str, Any]:
    disposition = derive_disposition(state)
    if disposition == "HOST_HANDOFF":
        try:
            digest_is_valid = len(receipt.digest) == 64 and int(receipt.digest, 16) >= 0 if receipt else False
        except ValueError:
            digest_is_valid = False
        if (
            receipt is None
            or not receipt.durable
            or not receipt.handoff_ref
            or not receipt.handoff_id
            or not digest_is_valid
        ):
            raise ValueError("HOST_HANDOFF requires a valid durable HandoffReceipt")
        handoff_ref: str | None = receipt.handoff_ref
        handoff_identity: str | None = receipt.handoff_id
    else:
        if receipt is not None:
            raise ValueError(f"{disposition} must not include a handoff receipt")
        handoff_ref = None
        handoff_identity = None
    identity = {
        "disposition": disposition,
        "model_revision": state.model_revision,
        "handoff_id": handoff_identity,
    }
    return {
        "schema_version": "r6o-close-result-1",
        "session_id": state.session_id,
        "result_id": _hash_identity("close", identity),
        "disposition": disposition,
        "model_revision": state.model_revision,
        "handoff_ref": handoff_ref,
        "reason_code": None,
    }


def coordinate_close(
    state: ModelStateSnapshot,
    artifacts: list[ArtifactSnapshot],
    store: HandoffStore,
) -> dict[str, Any]:
    disposition = derive_disposition(state)
    if disposition != "HOST_HANDOFF":
        return build_close_result(state)
    envelope = build_handoff_envelope(state, artifacts)
    receipt = store.persist(envelope)
    if receipt.handoff_id != envelope["handoff_id"]:
        raise ValueError("HandoffStore receipt identity does not match persisted envelope")
    return build_close_result(state, receipt=receipt)
