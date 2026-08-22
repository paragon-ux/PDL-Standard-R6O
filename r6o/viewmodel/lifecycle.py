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

def _hash_identity(prefix: str, value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_disposition(state: ModelStateSnapshot) -> str:
    lifecycle = state.lifecycle
    if not lifecycle.close_allowed:
        raise ValueError("Model lifecycle does not authorize close")
    if lifecycle.terminal:
        disposition = lifecycle.terminal_disposition
        if disposition not in {"HOST_HANDOFF", "CANCELLED", "FAILED"}:
            raise ValueError("terminal Model lifecycle has no valid disposition")
        if (disposition == "HOST_HANDOFF") != lifecycle.handoff_ready:
            raise ValueError("Model lifecycle handoff readiness contradicts disposition")
        return disposition
    if lifecycle.review_required and lifecycle.terminal_disposition is None:
        return "PDLT_RESUME"
    raise ValueError("Model lifecycle is not an authorized close synchronization point")


def build_handoff_envelope(
    state: ModelStateSnapshot,
    artifacts: list[ArtifactSnapshot],
) -> dict[str, Any]:
    if derive_disposition(state) != "HOST_HANDOFF":
        raise ValueError("handoff requires Model-authorized HOST_HANDOFF state")
    authorized = [item.to_dict() for item in state.lifecycle.authorized_handoff_artifacts]
    supplied = [item.to_dict() for item in artifacts]
    if supplied != authorized:
        raise ValueError("handoff artifacts do not match the Model-authorized terminal set")
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


def _compile_close_result(
    state: ModelStateSnapshot,
    *,
    receipt: HandoffReceipt | None = None,
    handoff_verified: bool = False,
) -> dict[str, Any]:
    disposition = derive_disposition(state)
    if disposition == "HOST_HANDOFF":
        try:
            digest_is_valid = len(receipt.digest) == 64 and int(receipt.digest, 16) >= 0 if receipt else False
        except ValueError:
            digest_is_valid = False
        if (
            receipt is None
            or not handoff_verified
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
        "session_id": state.session_id,
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


def build_close_result(state: ModelStateSnapshot) -> dict[str, Any]:
    """Compile non-handoff close results; HOST_HANDOFF requires coordination."""

    if derive_disposition(state) == "HOST_HANDOFF":
        raise ValueError("HOST_HANDOFF must be produced by coordinate_close after persistence")
    return _compile_close_result(state)


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
    expected_digest = hashlib.sha256(
        (json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    ).hexdigest()
    if receipt.digest != expected_digest or not receipt.durable:
        raise ValueError("HandoffStore did not verify durable persistence of the canonical envelope")
    return _compile_close_result(state, receipt=receipt, handoff_verified=True)
