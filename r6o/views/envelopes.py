from __future__ import annotations

"""View-level adaptation of user input into the accepted InputEnvelope contract.

Pure presentation plumbing: revision-bound identity is copied from a
FocusProjection into an ``r6o-input-envelope-1`` payload. No semantic
interpretation and no controller intents.
"""

from typing import Any

INPUT_ENVELOPE_VERSION = "r6o-input-envelope-1"


def structured_action_envelope(projection: dict[str, Any], action_id: str) -> dict[str, Any]:
    return {
        "schema_version": INPUT_ENVELOPE_VERSION,
        "session_id": projection["session_id"],
        "source": "STRUCTURED_ACTION",
        "model_revision": projection["model_revision"],
        "text": None,
        "action_id": action_id,
        "projection_id": projection["projection_id"],
    }


def free_response_envelope(source: str, projection: dict[str, Any], text: str) -> dict[str, Any]:
    if source not in {"TUI_TEXT", "HOST_COMPOSER_TEXT"}:
        raise ValueError(f"unsupported free-response source: {source}")
    return {
        "schema_version": INPUT_ENVELOPE_VERSION,
        "session_id": projection["session_id"],
        "source": source,
        "model_revision": projection["model_revision"],
        "text": text,
        "action_id": None,
        "projection_id": None,
    }
