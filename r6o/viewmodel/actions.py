from __future__ import annotations

"""Projection-driven PresentationAction builder.

Actions are derived from current authoritative state; labels/ordinals are not
universal constants beyond the stage mapping below.
"""

import json
from pathlib import Path
from typing import Any

_CANONICAL_PATH = Path(__file__).resolve().parents[1] / "contracts" / "canonical_review_messages.json"
ACTION_MAPPING_VERSION = "r6o-review-msg-1"


def _canonical() -> dict[str, Any]:
    return json.loads(_CANONICAL_PATH.read_text(encoding="utf-8"))


def project_actions(stage: str) -> list[dict[str, Any]]:
    canonical = _canonical()
    if stage == "PROMPT_REVIEW":
        return [
            {
                "action_id": "confirm_prompt",
                "label": "Confirm prompt",
                "ordinal": 1,
                "kind": "SEMANTIC_MESSAGE",
                "canonical_review_text": canonical["prompt_confirm"],
                "emphasis": "PRIMARY",
                "enabled": True,
            },
            {"action_id": "change_task", "label": "Change the task", "ordinal": 2, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True},
            {"action_id": "change_approach", "label": "Change approach", "ordinal": 3, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True},
            {"action_id": "something_else", "label": "Something else...", "ordinal": 4, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True},
        ]
    if stage == "PLAN_REVIEW":
        return [
            {
                "action_id": "confirm_plan",
                "label": "Confirm plan",
                "ordinal": 1,
                "kind": "SEMANTIC_MESSAGE",
                "canonical_review_text": canonical["plan_confirm"],
                "emphasis": "PRIMARY",
                "enabled": True,
            },
            {"action_id": "change_task", "label": "Change the task", "ordinal": 2, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True},
            {"action_id": "change_approach", "label": "Change approach", "ordinal": 3, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True},
            {"action_id": "something_else", "label": "Something else...", "ordinal": 4, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True},
        ]
    return []
