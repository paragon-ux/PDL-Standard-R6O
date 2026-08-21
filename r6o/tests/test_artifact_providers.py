from __future__ import annotations

import json

from r6o.model_binding.base import SessionInvocation
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.memory_model import InMemoryModel
from r6o.viewmodel.projection import build_focus_projection_from_port

G06_ACTIVATION = "Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers."


def test_local_binding_reads_opaque_artifact(tmp_path, baseline_repo, recorded_worker_factory):
    worker = recorded_worker_factory(["G06"])
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "ws", run_id="prov")
    binding.start_or_resume(SessionInvocation(task_text=G06_ACTIVATION))
    session = binding.read_state(binding._session_id).session_id
    binding.submit_user_message(session, G06_ACTIVATION, None)
    snapshot = binding.read_artifact(session, "prompt:current")
    assert snapshot.artifact_kind == "prompt"
    assert snapshot.artifact_revision == snapshot.artifact_ref.split(":", 1)[1]
    assert "optimistic locking" in snapshot.body
    binding.close()


def test_memory_provider_is_non_path_and_projection_equivalent(tmp_path, baseline_repo, recorded_worker_factory):
    worker = recorded_worker_factory(["G06"])
    local = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "ws2", run_id="prov2")
    local.start_or_resume(SessionInvocation(task_text=G06_ACTIVATION))
    local_session = local.read_state(local._session_id).session_id
    local.submit_user_message(local_session, G06_ACTIVATION, None)
    local_projection = build_focus_projection_from_port(local, local_session)

    memory = InMemoryModel()
    memory_projection = build_focus_projection_from_port(memory, memory._session_id)

    serialized_memory = json.dumps(memory_projection)
    assert "C:\\" not in serialized_memory
    assert "Path" not in serialized_memory

    # Semantically equivalent projection shape: artifact body present in both.
    assert local_projection["artifact"]["body"]
    assert memory_projection["artifact"]["body"]
    assert local_projection["interaction_state"] == memory_projection["interaction_state"] == "REVIEW_REQUIRED"
    local.close()
