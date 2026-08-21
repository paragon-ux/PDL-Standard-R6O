from __future__ import annotations

import json

from r6o.contracts_validation import make_validator

from r6o.model_binding.base import ArtifactSnapshot, ModelRevision
from r6o.model_binding.memory_model import InMemoryModel
from r6o.viewmodel.projection import build_focus_projection, build_focus_projection_from_port

SCHEMA = json.loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "contracts" / "focus_projection.schema.json").read_text(encoding="utf-8"))


def _revision() -> ModelRevision:
    return ModelRevision.from_controller_state(
        "s1",
        {"stage": "PROMPT_REVIEW", "instance_id": "I-1", "current_prompt": {"artifact_id": "P1", "body": "b"}},
    )


def test_projection_is_schema_valid_and_reconstructable() -> None:
    artifact = ArtifactSnapshot("prompt:P1", "P1", "prompt", "Authoritative Prompt (PDL.md)", "COMPARE Kafka and RabbitMQ.")
    first = build_focus_projection(_revision(), artifact)
    second = build_focus_projection(_revision(), artifact)
    make_validator(SCHEMA).validate(first)
    assert first["session_id"] == second["session_id"]
    assert first["model_revision"] == second["model_revision"]
    assert first["artifact"] == second["artifact"]
    assert first["actions"] == second["actions"]
    assert first["lifecycle"] == second["lifecycle"]
    assert first["projection_id"] != second["projection_id"]  # projection instance identity


def test_projection_from_in_memory_port_has_no_paths() -> None:
    port = InMemoryModel()
    rev = port.read_state(port._session_id)
    projection = build_focus_projection_from_port(port, rev.session_id)
    make_validator(SCHEMA).validate(projection)
    assert projection["interaction_state"] == "REVIEW_REQUIRED"
    assert projection["artifact"]["artifact_ref"].startswith("prompt:")
    serialized = json.dumps(projection)
    assert "C:\\" not in serialized
    assert "/workspace" not in serialized


