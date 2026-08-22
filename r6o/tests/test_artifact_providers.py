from __future__ import annotations

import json
from pathlib import Path

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.memory_model import RecordingModelPort, StaticModelPort
from r6o.tests.helpers import artifact, state
from r6o.viewmodel.projection import build_focus_projection_from_port

G06_ACTIVATION = "Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers."


def test_local_binding_reads_opaque_content_revision(tmp_path, baseline_repo, recorded_worker_factory) -> None:
    binding = LocalRuntimeModelBinding(
        baseline_repo,
        worker=recorded_worker_factory(["G06"]),
        workspace_root=tmp_path / "workspaces",
    )
    started = binding.start_or_resume(ModelSessionRequest(request_id="start", task_text=G06_ACTIVATION))
    snapshot = binding.read_artifact(started.session_id, started.review_subject.artifact_ref)
    assert snapshot.artifact_kind == "prompt"
    assert snapshot.artifact_revision != snapshot.artifact_ref.split(":", 1)[1]
    assert len(snapshot.artifact_revision) == 64
    binding.close()


def test_viewmodel_non_path_contract_independence() -> None:
    item = artifact()
    port = StaticModelPort(state(), {item.artifact_ref: item})
    projection = build_focus_projection_from_port(port, "I-1")
    assert projection["artifact"]["body"] == item.body
    serialized = json.dumps(projection)
    assert "Path" not in serialized
    assert "C:\\" not in serialized


def test_test_doubles_have_no_protocol_state_machine() -> None:
    source = (Path(__file__).resolve().parents[1] / "model_binding" / "memory_model.py").read_text(encoding="utf-8")
    for forbidden in ("PROMPT_CONFIRM", "PLAN_CONFIRM", "PROMPT_REVIEW -> PLAN_REVIEW", "current_prompt", "current_plan"):
        assert forbidden not in source
    initial = state()
    following = state(revision="model-rev-2", stage="PLAN_REVIEW")
    port = RecordingModelPort(initial, following, {artifact().artifact_ref: artifact()})
    returned = port.submit_user_message("I-1", "opaque ordinary text", initial.model_revision)
    assert returned is following
    assert port.submissions == ["opaque ordinary text"]
