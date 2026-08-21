from __future__ import annotations

import json
from pathlib import Path

from r6o.model_binding.base import SessionInvocation
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.viewmodel.dispatcher import handle_input
from r6o.viewmodel.projection import build_focus_projection_from_port

G06 = {
    "activation": "Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers.",
    "prompt_body": "Explain the difference between optimistic locking and pessimistic locking for an audience of senior developers.",
    "plan_body": (
        "IDENTIFY the target audience as senior developers\n"
        "INTRODUCE the subject of concurrency control\n"
        "DEFINE optimistic locking\n"
        "DEFINE pessimistic locking\n"
        "COMPARE the two approaches\n"
        "SUMMARIZE the differences"
    ),
}
A02 = {
    "activation": "Use $confirm-with-pseudocode to compare Kafka and RabbitMQ for event delivery.",
    "revision": "This is not confirmed. The audience should be data engineers, not backend engineers.",
    "prompt_body": "COMPARE Kafka and RabbitMQ for event delivery, intended for data engineers.",
}


def _structured_action_envelope(port, session_id, action_id):
    projection = build_focus_projection_from_port(port, session_id)
    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": session_id,
        "source": "STRUCTURED_ACTION",
        "model_revision": projection["model_revision"],
        "text": None,
        "action_id": action_id,
        "projection_id": projection["projection_id"],
    }


def _g06_via_viewmodel(binding) -> dict:
    binding.start_or_resume(SessionInvocation(task_text=G06["activation"]))
    session = binding.read_state(binding._session_id).session_id
    binding.submit_user_message(session, G06["activation"], None)
    r = handle_input(_structured_action_envelope(binding, session, "confirm_prompt"), binding)
    assert r["result_type"] == "REVISION", r
    r = handle_input(_structured_action_envelope(binding, session, "confirm_plan"), binding)
    assert r["result_type"] == "REVISION", r
    state = binding.read_state(session).controller_state
    prompt = binding.read_artifact(session, "prompt:current")
    plan = binding.read_artifact(session, "plan:current")
    return {"stage": state["stage"], "prompt_body": prompt.body, "plan_body": plan.body}


def _g06_direct(host) -> dict:
    for turn in ["Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers.", "Yes, that is what I mean.", "Confirm the plan and execute."]:
        host.handle(turn)
    state = host.status()["controller_state"]
    workspace = Path(host.status()["workspace_path"])
    prompt = (workspace / "stages" / "10_prompt" / "output" / "current.md").read_text(encoding="utf-8").rstrip("\n")
    plan = (workspace / "stages" / "30_plan" / "output" / "current.md").read_text(encoding="utf-8").rstrip("\n")
    return {"stage": state["stage"], "prompt_body": prompt, "plan_body": plan}


def test_g06_viewmodel_parity(tmp_path, baseline_repo, recorded_worker_factory):
    from host.app import PDLtHost

    worker = recorded_worker_factory(["G06"])
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "vm", run_id="g06vm")
    via_viewmodel = _g06_via_viewmodel(binding)
    binding.close()

    worker2 = recorded_worker_factory(["G06"])
    host = PDLtHost(baseline_repo, worker=worker2, workspace_root=tmp_path / "direct", run_id="g06direct").start()
    try:
        direct = _g06_direct(host)
    finally:
        host.close()

    assert via_viewmodel == direct == {"stage": "CLOSED_SUCCESS", "prompt_body": G06["prompt_body"], "plan_body": G06["plan_body"]}


def test_a02_viewmodel_free_response_parity(tmp_path, baseline_repo, recorded_worker_factory):
    from host.app import PDLtHost

    worker = recorded_worker_factory(["A02"])
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "vm2", run_id="a02vm")
    binding.start_or_resume(SessionInvocation(task_text=A02["activation"]))
    session = binding.read_state(binding._session_id).session_id
    binding.submit_user_message(session, A02["activation"], None)
    projection = build_focus_projection_from_port(binding, session)
    envelope = {
        "schema_version": "r6o-input-envelope-1",
        "session_id": session,
        "source": "HOST_COMPOSER_TEXT",
        "model_revision": projection["model_revision"],
        "text": A02["revision"],
        "action_id": None,
        "projection_id": None,
    }
    r = handle_input(envelope, binding)
    assert r["result_type"] == "REVISION", r
    state = binding.read_state(session).controller_state
    prompt = binding.read_artifact(session, "prompt:current")
    binding.close()

    worker2 = recorded_worker_factory(["A02"])
    host = PDLtHost(baseline_repo, worker=worker2, workspace_root=tmp_path / "direct2", run_id="a02direct").start()
    try:
        host.handle(A02["activation"])
        host.handle(A02["revision"])
        direct_state = host.status()["controller_state"]
        workspace = Path(host.status()["workspace_path"])
        direct_prompt = (workspace / "stages" / "10_prompt" / "output" / "current.md").read_text(encoding="utf-8").rstrip("\n")
    finally:
        host.close()

    assert state["stage"] == direct_state["stage"] == "PROMPT_REVIEW"
    assert prompt.body == direct_prompt == A02["prompt_body"]
