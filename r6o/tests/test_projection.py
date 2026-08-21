from __future__ import annotations

import json

from r6o.contracts_validation import make_validator
from r6o.model_binding.memory_model import StaticModelPort
from r6o.tests.helpers import artifact, state
from r6o.viewmodel.projection import build_focus_projection, build_focus_projection_from_port

SCHEMA = json.loads(
    (__import__("pathlib").Path(__file__).resolve().parents[1] / "contracts" / "focus_projection.schema.json").read_text(encoding="utf-8")
)


def test_projection_fingerprint_is_deterministic() -> None:
    first = build_focus_projection(state(), artifact())
    second = build_focus_projection(state(), artifact())
    make_validator(SCHEMA).validate(first)
    assert first == second
    assert first["projection_id"].startswith("projection-")


def test_projection_fingerprint_changes_with_authoritative_revision() -> None:
    first = build_focus_projection(state(), artifact())
    changed_model = build_focus_projection(state(revision="model-rev-2"), artifact())
    changed_artifact = build_focus_projection(
        state(revision="model-rev-2", artifact_revision="artifact-rev-2"),
        artifact("artifact-rev-2", "EDITED BODY"),
    )
    assert first["projection_id"] != changed_model["projection_id"]
    assert changed_model["projection_id"] != changed_artifact["projection_id"]


def test_projection_fingerprint_is_bound_to_session_and_workspace() -> None:
    first = build_focus_projection(state(), artifact())
    other_session = build_focus_projection(state(session_id="I-2"), artifact())
    other_workspace = build_focus_projection(state(workspace_id="W-2"), artifact())
    assert len({first["projection_id"], other_session["projection_id"], other_workspace["projection_id"]}) == 3


def test_projection_fingerprint_covers_response_and_lifecycle_content() -> None:
    first = build_focus_projection(state(model_response="first"), artifact())
    changed_response = build_focus_projection(state(model_response="second"), artifact())
    changed_lifecycle = build_focus_projection(
        state(stage="CLOSED_SUCCESS", result_body="result", model_response="result"), None
    )
    other_lifecycle = build_focus_projection(
        state(stage="CLOSED_SUCCESS", result_body="other", model_response="result"), None
    )
    assert first["projection_id"] != changed_response["projection_id"]
    assert changed_lifecycle["projection_id"] != other_lifecycle["projection_id"]


def test_projection_uses_actual_workspace_id_and_has_no_paths() -> None:
    snapshot = state()
    item = artifact()
    port = StaticModelPort(snapshot, {item.artifact_ref: item})
    projection = build_focus_projection_from_port(port, snapshot.session_id)
    assert projection["workspace_id"] == "W-1"
    assert projection["session_id"] == "I-1"
    serialized = json.dumps(projection)
    assert "C:\\" not in serialized
    assert "/workspace" not in serialized
