from __future__ import annotations

"""Mechanical InputEnvelope builders for public Views."""

from typing import Any


def structured_action_envelope(
    projection: dict[str, Any], action_id: str
) -> dict[str, Any]:
    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": projection["session_id"],
        "source": "STRUCTURED_ACTION",
        "model_revision": projection["model_revision"],
        "text": None,
        "action_id": action_id,
        "projection_id": projection["projection_id"],
    }


def text_envelope(
    source: str, projection: dict[str, Any], text: str
) -> dict[str, Any]:
    if source not in {"TUI_TEXT", "HOST_COMPOSER_TEXT"}:
        raise ValueError(f"unsupported free-response source: {source}")
    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": projection["session_id"],
        "source": source,
        "model_revision": projection["model_revision"],
        "text": text,
        "action_id": None,
        "projection_id": None,
    }
