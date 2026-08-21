from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from r6o.contracts_validation import make_validator

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
SCHEMAS = sorted(CONTRACTS.glob("*.schema.json"))


def _load(name: str):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _validates(name: str, instance: dict) -> bool:
    validator = make_validator(_load(name))
    return validator.is_valid(instance)


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: p.name)
def test_all_schemas_are_valid_json_schemas(path: Path) -> None:
    Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_focus_projection_sample() -> None:
    sample = {
        "schema_version": "r6o-focus-projection-1",
        "session_id": "s1",
        "workspace_id": "W-1",
        "model_revision": "rev-1",
        "projection_id": "p-1",
        "interaction_state": "REVIEW_REQUIRED",
        "stage": "PROMPT_REVIEW",
        "focus_kind": "PROMPT_REVIEW",
        "artifact": {
            "artifact_ref": "prompt:P1",
            "artifact_revision": "P1",
            "artifact_kind": "prompt",
            "title": "Authoritative Prompt (PDL.md)",
            "media_type": "text/plain",
            "body": "COMPARE Kafka and RabbitMQ.",
            "capabilities": {"copy": True, "open_external": False},
        },
        "actions": [],
        "lifecycle": {"review_required": True, "terminal": False, "close_allowed": True, "handoff_ready": False},
    }
    assert _validates("focus_projection.schema.json", sample)
    bad = dict(sample)
    del bad["model_revision"]
    assert not _validates("focus_projection.schema.json", bad)


def test_input_envelope_structured_action_requires_identity() -> None:
    valid = {
        "schema_version": "r6o-input-envelope-1",
        "session_id": "s1",
        "source": "STRUCTURED_ACTION",
        "model_revision": "rev-1",
        "text": None,
        "action_id": "confirm_prompt",
        "projection_id": "p-1",
    }
    assert _validates("input_envelope.schema.json", valid)
    bad = dict(valid)
    del bad["action_id"]
    assert not _validates("input_envelope.schema.json", bad)
    bad2 = dict(valid)
    bad2["source"] = "HOST_COMPOSER_TEXT"
    assert not _validates("input_envelope.schema.json", bad2)


def test_input_envelope_text_requires_text() -> None:
    valid = {
        "schema_version": "r6o-input-envelope-1",
        "session_id": "s1",
        "source": "TUI_TEXT",
        "model_revision": "rev-1",
        "text": "This is a correction.",
        "action_id": None,
        "projection_id": None,
    }
    assert _validates("input_envelope.schema.json", valid)
    bad = dict(valid)
    bad["text"] = ""
    assert not _validates("input_envelope.schema.json", bad)


def test_command_result_samples() -> None:
    for result_type, ok in [("REVISION", True), ("FOCUS_REQUIRED", True), ("STALE_PROJECTION", False), ("ERROR", False)]:
        sample = {
            "schema_version": "r6o-viewmodel-command-result-1",
            "ok": ok,
            "result_type": result_type,
            "projection": None,
            "focus_prompt": None,
            "error": None if ok else {"code": result_type, "message": "reason"},
        }
        assert _validates("viewmodel_command_result.schema.json", sample), result_type


def test_handoff_and_close_samples() -> None:
    handoff = {
        "schema_version": "r6o-handoff-envelope-1",
        "handoff_id": "h-1",
        "session_id": "s1",
        "workspace_id": "W-1",
        "source_model_revision": "rev-1",
        "disposition": "HOST_HANDOFF",
        "artifacts": [{"artifact_ref": "prompt:P1", "artifact_revision": "P1", "artifact_kind": "prompt", "body": "..."}],
        "execution_request": {"result_body": "out"},
        "created_at": None,
    }
    assert _validates("handoff_envelope.schema.json", handoff)
    close = {
        "schema_version": "r6o-close-result-1",
        "session_id": "s1",
        "result_id": "c-1",
        "disposition": "HOST_HANDOFF",
        "model_revision": "rev-1",
        "handoff_ref": "C:/tmp/h.json",
        "reason_code": None,
    }
    assert _validates("close_result.schema.json", close)


def test_canonical_review_messages() -> None:
    canonical = _load("canonical_review_messages.json")
    assert canonical["mapping_version"] == "r6o-review-msg-1"
    assert canonical["prompt_confirm"] == "Yes, that is what I mean."
    assert canonical["plan_confirm"] == "Confirm the plan and execute."

