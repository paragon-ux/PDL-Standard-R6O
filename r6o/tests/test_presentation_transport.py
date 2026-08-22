from __future__ import annotations

import json
from pathlib import Path

from r6o.model_binding.base import ArtifactSnapshot, ModelStateSnapshot
from r6o.model_binding.memory_model import RecordingModelPort, StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.tests.helpers import artifact, plan, state
from r6o.views.envelopes import structured_action_envelope

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "focus_projection.schema.json").read_text(encoding="utf-8"))
RESULT_SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "viewmodel_command_result.schema.json").read_text(encoding="utf-8"))
from jsonschema import Draft202012Validator

from r6o.contracts_validation import make_validator


def test_adapter_public_surface_mechanical_only() -> None:
    adapter = PresentationAdapter(StaticModelPort(state()))
    assert {n for n in dir(adapter) if not n.startswith("_")} == {"current_projection", "submit_input"}


def test_current_projection_is_schema_valid_and_revision_bound() -> None:
    snap: ModelStateSnapshot = state()
    adapter = PresentationAdapter(StaticModelPort(snap, {"prompt:P1": artifact(), "plan:R1": plan()}))
    projection = adapter.current_projection("I-1")
    make_validator(SCHEMA).validate(projection)
    assert projection["model_revision"] == snap.model_revision
    assert projection["artifact"]["artifact_revision"] == "artifact-rev-1"


def test_submit_structured_action_routes_canonical_text() -> None:
    next_snap = state(stage="PLAN_REVIEW", artifact_revision="artifact-rev-1")
    port = RecordingModelPort(state(), next_snap, {"prompt:P1": artifact(), "plan:R1": plan()})
    adapter = PresentationAdapter(port)
    projection = adapter.current_projection("I-1")
    result = adapter.submit_input(structured_action_envelope(projection, "confirm_prompt"))
    make_validator(RESULT_SCHEMA).validate(result)
    assert result["result_type"] == "REVISION"
    assert port.submissions == ["Yes, that is what I mean."]


def test_submit_invalid_envelope_returns_error() -> None:
    adapter = PresentationAdapter(StaticModelPort(state(), {"prompt:P1": artifact(), "plan:R1": plan()}))
    result = adapter.submit_input({"source": "STRUCTURED_ACTION"})
    assert result["result_type"] == "ERROR"
    assert result["error"]["code"] == "INVALID_ENVELOPE"



