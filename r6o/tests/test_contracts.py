from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from r6o.contracts_validation import make_validator
from r6o.model_binding.base import HostInvocation, ModelSessionRequest
from r6o.tests.helpers import artifact, state
from r6o.viewmodel.projection import build_focus_projection

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
SCHEMAS = sorted(CONTRACTS.glob("*.schema.json"))


def _load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _validates(name: str, instance: dict) -> bool:
    return make_validator(_load(name)).is_valid(instance)


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda path: path.name)
def test_all_schemas_are_valid_json_schemas(path: Path) -> None:
    Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_normalized_model_port_outputs_are_machine_validated() -> None:
    snapshot = state()
    assert _validates("model_state_snapshot.schema.json", snapshot.to_dict())
    assert _validates("artifact_snapshot.schema.json", artifact().to_dict())
    schema = _load("model_port.schema.json")
    refs = json.dumps(schema["$defs"], sort_keys=True)
    assert "model_state_snapshot.schema.json" in refs
    assert "artifact_snapshot.schema.json" in refs
    assert "model_port_error.schema.json" in refs
    assert "wait_for_revision" not in json.dumps(schema)


def test_host_and_model_invocations_are_separate() -> None:
    HostInvocation(request_id="host-1", presentation="AUTO")
    new = ModelSessionRequest(request_id="new-1", task_text="Do the task")
    resume = ModelSessionRequest(request_id="resume-1", resume_session_id="I-1")
    assert new.mode == "NEW"
    assert resume.mode == "RESUME"
    assert "presentation" not in _load("model_session_request.schema.json")["properties"]
    assert "task_text" not in _load("host_invocation.schema.json")["properties"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"task_text": "task", "resume_session_id": "I-1"},
        {"task_text": ""},
        {"resume_session_id": ""},
    ],
)
def test_new_and_resume_are_mutually_exclusive(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ModelSessionRequest(request_id="request", **kwargs)


def test_model_session_request_schema_oneof() -> None:
    base = {
        "schema_version": "r6o-model-session-request-1",
        "request_id": "r1",
        "worker_profile": None,
    }
    assert _validates("model_session_request.schema.json", {**base, "task_text": "task", "resume_session_id": None})
    assert _validates("model_session_request.schema.json", {**base, "task_text": None, "resume_session_id": "I-1"})
    assert not _validates("model_session_request.schema.json", {**base, "task_text": "task", "resume_session_id": "I-1"})
    assert not _validates("model_session_request.schema.json", {**base, "task_text": None, "resume_session_id": None})


def test_command_result_conditional_shapes() -> None:
    projection = build_focus_projection(state(), artifact())
    samples = [
        {"schema_version": "r6o-viewmodel-command-result-1", "ok": True, "result_type": "REVISION", "projection": projection, "focus_role": None, "error": None},
        {"schema_version": "r6o-viewmodel-command-result-1", "ok": True, "result_type": "FOCUS_REQUIRED", "projection": None, "focus_role": "FREE_RESPONSE", "error": None},
        {"schema_version": "r6o-viewmodel-command-result-1", "ok": False, "result_type": "STALE_PROJECTION", "projection": projection, "focus_role": None, "error": {"code": "STALE_PROJECTION", "message": "stale"}},
        {"schema_version": "r6o-viewmodel-command-result-1", "ok": False, "result_type": "ERROR", "projection": None, "focus_role": None, "error": {"code": "MODEL_ERROR", "message": "failure"}},
    ]
    for sample in samples:
        assert _validates("viewmodel_command_result.schema.json", sample), sample
    contradictory = dict(samples[1], ok=False)
    assert not _validates("viewmodel_command_result.schema.json", contradictory)
    leaked_copy = dict(samples[1], focus_prompt="Describe the task")
    assert not _validates("viewmodel_command_result.schema.json", leaked_copy)


def test_close_result_requires_handoff_reference_conditionally() -> None:
    host = {
        "schema_version": "r6o-close-result-1",
        "session_id": "I-1",
        "result_id": "close-1",
        "disposition": "HOST_HANDOFF",
        "model_revision": "rev-1",
        "handoff_ref": "memory:handoff-1",
        "reason_code": None,
    }
    assert _validates("close_result.schema.json", host)
    assert not _validates("close_result.schema.json", {**host, "handoff_ref": None})
    assert _validates("close_result.schema.json", {**host, "disposition": "CANCELLED", "handoff_ref": None})
    assert not _validates("close_result.schema.json", {**host, "disposition": "CANCELLED"})


def test_nested_objects_reject_extra_properties() -> None:
    value = state().to_dict()
    value["lifecycle"]["filesystem_path"] = "forbidden"
    assert not _validates("model_state_snapshot.schema.json", value)


def test_canonical_review_messages() -> None:
    canonical = _load("canonical_review_messages.json")
    assert canonical["mapping_version"] == "r6o-review-msg-1"
    assert canonical["prompt_confirm"] == "Yes, that is what I mean."
    assert canonical["plan_confirm"] == "Confirm the plan and execute."
