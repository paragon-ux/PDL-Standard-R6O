from __future__ import annotations

"""Fail-closed command dispatch over the ordinary Model message path."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from r6o.contracts_validation import make_validator
from r6o.viewmodel.model_port import ModelPort, StaleProjectionError
from r6o.viewmodel.projection import build_focus_projection_from_port

_CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
_RESULT_SCHEMA = json.loads((_CONTRACTS / "viewmodel_command_result.schema.json").read_text(encoding="utf-8"))
_INPUT_SCHEMA = json.loads((_CONTRACTS / "input_envelope.schema.json").read_text(encoding="utf-8"))


def _result(result_type: str, ok: bool, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "r6o-viewmodel-command-result-1",
        "ok": ok,
        "result_type": result_type,
        "projection": None,
        "focus_role": None,
        "error": None,
    }
    payload.update(extra)
    return payload


def _stale(port: ModelPort, session_id: str, message: str) -> dict[str, Any]:
    try:
        projection = build_focus_projection_from_port(port, session_id)
    except Exception as exc:
        return _result(
            "ERROR",
            False,
            error={"code": "MODEL_ACCESS", "message": f"stale refresh failed: {exc}"},
        )
    return _result(
        "STALE_PROJECTION",
        False,
        projection=projection,
        error={"code": "STALE_PROJECTION", "message": message},
    )


def handle_input(envelope: dict[str, Any], port: ModelPort) -> dict[str, Any]:
    validator = Draft202012Validator(_INPUT_SCHEMA)
    if not validator.is_valid(envelope):
        errors = sorted(validator.iter_errors(envelope), key=lambda error: list(error.path))
        return _result(
            "ERROR",
            False,
            error={"code": "INVALID_ENVELOPE", "message": errors[0].message if errors else "invalid envelope"},
        )

    session_id = envelope["session_id"]
    try:
        projection = build_focus_projection_from_port(port, session_id)
    except Exception as exc:
        return _result("ERROR", False, error={"code": "MODEL_ACCESS", "message": str(exc)})

    if envelope["model_revision"] != projection["model_revision"]:
        return _stale(port, session_id, "command references an obsolete model revision")

    source = envelope["source"]
    if source == "STRUCTURED_ACTION":
        if envelope["projection_id"] != projection["projection_id"]:
            return _stale(port, session_id, "command references an obsolete projection fingerprint")
        action_id = envelope["action_id"]
        action = next((item for item in projection["actions"] if item["action_id"] == action_id), None)
        if action is None:
            return _result("ERROR", False, error={"code": "UNKNOWN_ACTION", "message": f"unknown action: {action_id}"})
        if action["kind"] == "SEMANTIC_MESSAGE":
            return _submit(port, session_id, action["canonical_review_text"], projection["model_revision"])
        text = envelope.get("text")
        if text and str(text).strip():
            return _submit(port, session_id, str(text), projection["model_revision"])
        return _result("FOCUS_REQUIRED", True, focus_role="FREE_RESPONSE")

    text = envelope.get("text")
    if not text or not str(text).strip():
        return _result("ERROR", False, error={"code": "EMPTY_TEXT", "message": "free-response text is required"})
    return _submit(port, session_id, str(text), projection["model_revision"])


def _submit(port: ModelPort, session_id: str, text: str, expected: str) -> dict[str, Any]:
    try:
        submitted = port.submit_user_message(session_id, text, expected)
        projection = build_focus_projection_from_port(port, submitted.session_id)
    except StaleProjectionError as exc:
        return _stale(port, session_id, f"authoritative state advanced before submission: {exc}")
    except Exception as exc:
        return _result("ERROR", False, error={"code": "MODEL_ERROR", "message": str(exc)})
    return _result("REVISION", True, projection=projection)


def validate_command_result(result: dict[str, Any]) -> None:
    errors = list(make_validator(_RESULT_SCHEMA).iter_errors(result))
    if errors:
        raise AssertionError(f"command result invalid: {errors[0].message}")
