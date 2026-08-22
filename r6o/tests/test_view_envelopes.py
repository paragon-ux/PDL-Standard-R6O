from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from r6o.views.envelopes import free_response_envelope, structured_action_envelope

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "input_envelope.schema.json").read_text(encoding="utf-8"))
PROJECTION = {"session_id": "s1", "model_revision": "rev-1", "projection_id": "p-1"}


def test_structured_envelope_schema_valid() -> None:
    envelope = structured_action_envelope(PROJECTION, "confirm_prompt")
    Draft202012Validator(SCHEMA).validate(envelope)
    assert envelope["source"] == "STRUCTURED_ACTION"
    assert envelope["text"] is None
    assert envelope["action_id"] == "confirm_prompt"
    assert envelope["projection_id"] == "p-1"


def test_free_response_envelopes_schema_valid() -> None:
    for source in ("TUI_TEXT", "HOST_COMPOSER_TEXT"):
        envelope = free_response_envelope(source, PROJECTION, "feedback")
        Draft202012Validator(SCHEMA).validate(envelope)
        assert envelope["source"] == source
        assert envelope["text"] == "feedback"


def test_unsupported_source_rejected() -> None:
    try:
        free_response_envelope("SOMETHING_ELSE", PROJECTION, "x")
    except ValueError:
        return
    raise AssertionError("unsupported free-response source must raise")
