from __future__ import annotations

import json
from pathlib import Path

from r6o.viewmodel.actions import project_actions

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
