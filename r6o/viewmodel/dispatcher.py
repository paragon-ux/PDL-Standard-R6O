from __future__ import annotations

"""ViewModel command dispatcher: structured actions and free response.

Structured actions NEVER construct controller intents. They resolve to
canonical ordinary review text (or a focus request) and route through the
Model Port's ordinary user-message path. Stale/unknown commands fail closed.
"""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from r6o.model_binding.base import ModelPort, StaleProjectionError
from r6o.viewmodel.projection import build_focus_projection_from_port

_CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
_RESULT_SCHEMA = json.loads((_CONTRACTS / "viewmodel_command_result.schema.json").read_text(encoding="utf-8"))
_INPUT_SCHEMA = json.loads((_CONTRACTS / "input_envelope.schema.json").read_text(encoding="utf-8"))

_FOCUS_PROMPTS = {
    "change_task": "Describe the changed task or request.",
    "change_approach": "Describe the approach change.",
    "something_else": "Type your review input, or continue in the host composer.",
}


def _result(result_type: str, ok: bool, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "r6o-viewmodel-command-result-1",
        "ok": ok,
        "result_type": result_type,
        "projection": None,
        "focus_prompt": None,
        "error": None,
    }
    payload.update(extra)
    return payload


def handle_input(envelope: dict[str, Any], port: ModelPort) -> dict[str, Any]:
    validator = Draft202012Validator(_INPUT_SCHEMA)
    if not validator.is_valid(envelope):
        errors = sorted(validator.iter_errors(envelope), key=lambda e: list(e.path))
        return _result(
            "ERROR",
            False,
            error={"code": "INVALID_ENVELOPE", "message": errors[0].message if errors else "invalid envelope"},
        )

    session_id = envelope["session_id"]
    expected = envelope["model_revision"]
    try:
        current = port.read_state(session_id)
    except Exception as exc:  # fail closed on any model access error
        return _result("ERROR", False, error={"code": "MODEL_ACCESS", "message": str(exc)})

    if expected != current.revision:
        return _result(
            "STALE_PROJECTION",
            False,
            error={"code": "STALE_PROJECTION", "message": "command references an obsolete projection revision"},
        )

    source = envelope["source"]
    if source == "STRUCTURED_ACTION":
        action_id = envelope["action_id"]
        projection = build_focus_projection_from_port(port, session_id)
        action = next((a for a in projection["actions"] if a["action_id"] == action_id), None)
        if action is None:
            return _result("ERROR", False, error={"code": "UNKNOWN_ACTION", "message": f"unknown action: {action_id}"})
        if action["kind"] == "SEMANTIC_MESSAGE":
            text = action["canonical_review_text"]
            return _submit(port, session_id, text, expected)
        focus_prompt = _FOCUS_PROMPTS.get(action_id, action["label"])
        text = envelope.get("text")
        if text:
            return _submit(port, session_id, text, expected)
        return _result("FOCUS_REQUIRED", True, focus_prompt=focus_prompt)

    text = envelope.get("text")
    if not text or not str(text).strip():
        return _result("ERROR", False, error={"code": "EMPTY_TEXT", "message": "free-response text is required"})
    return _submit(port, session_id, str(text), expected)


def _submit(port: ModelPort, session_id: str, text: str, expected: str) -> dict[str, Any]:
    try:
        revision = port.submit_user_message(session_id, text, expected)
    except StaleProjectionError:
        return _result(
            "STALE_PROJECTION",
            False,
            error={"code": "STALE_PROJECTION", "message": "authoritative state advanced before submission"},
        )
    except Exception as exc:  # semantic/worker errors are surfaced, not swallowed
        return _result("ERROR", False, error={"code": "MODEL_ERROR", "message": str(exc)})
    projection = build_focus_projection_from_port(port, session_id)
    return _result("REVISION", True, projection=projection)


def validate_command_result(result: dict[str, Any]) -> None:
    validator = Draft202012Validator(_RESULT_SCHEMA)
    errors = list(validator.iter_errors(result))
    if errors:
        raise AssertionError(f"command result invalid: {errors[0].message}")
