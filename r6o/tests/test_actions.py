from __future__ import annotations

import json
from pathlib import Path

from r6o.viewmodel.actions import project_actions
from r6o.model_binding.memory_model import RecordingModelPort
from r6o.tests.helpers import artifact, state
from r6o.viewmodel.dispatcher import handle_input, validate_command_result
from r6o.viewmodel.projection import build_focus_projection_from_port

CANONICAL = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "canonical_review_messages.json").read_text(encoding="utf-8"))


def test_prompt_review_actions_are_dynamic_and_canonical() -> None:
    actions = project_actions("PROMPT_REVIEW")
    assert [a["ordinal"] for a in actions] == [1, 2, 3, 4]
    confirm = next(a for a in actions if a["action_id"] == "confirm_prompt")
    assert confirm["kind"] == "SEMANTIC_MESSAGE"
    assert confirm["canonical_review_text"] == CANONICAL["prompt_confirm"]
    for a in actions[1:]:
        assert a["kind"] == "FREE_RESPONSE_FOCUS"
        assert a.get("canonical_review_text") is None


def test_plan_review_actions() -> None:
    actions = project_actions("PLAN_REVIEW")
    confirm = next(a for a in actions if a["action_id"] == "confirm_plan")
    assert confirm["canonical_review_text"] == CANONICAL["plan_confirm"]
    assert confirm["emphasis"] == "PRIMARY"


def test_no_actions_outside_review() -> None:
    assert project_actions("CLOSED_SUCCESS") == []
    assert project_actions("EXECUTION_READY") == []


def test_free_response_action_returns_semantic_focus_role_without_ui_copy() -> None:
    item = artifact()
    port = RecordingModelPort(state(), state(revision="next"), {item.artifact_ref: item})
    projection = build_focus_projection_from_port(port, "I-1")
    envelope = {
        "schema_version": "r6o-input-envelope-1",
        "session_id": "I-1",
        "source": "STRUCTURED_ACTION",
        "model_revision": projection["model_revision"],
        "text": None,
        "action_id": "change_task",
        "projection_id": projection["projection_id"],
    }
    result = handle_input(envelope, port)
    validate_command_result(result)
    assert result["result_type"] == "FOCUS_REQUIRED"
    assert result["focus_role"] == "FREE_RESPONSE"
    assert "focus_prompt" not in result
    assert port.submissions == []
