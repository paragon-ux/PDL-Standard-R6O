from __future__ import annotations

import json
from pathlib import Path

import pytest

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.runtime_loader import FrozenRuntimeLoader
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


def _action(binding, session_id: str, action_id: str) -> dict:
    projection = build_focus_projection_from_port(binding, session_id)
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
    started = binding.start_or_resume(ModelSessionRequest(request_id="g06", task_text=G06["activation"]))
    session_id = started.session_id
    assert handle_input(_action(binding, session_id, "confirm_prompt"), binding)["result_type"] == "REVISION"
    final_result = handle_input(_action(binding, session_id, "confirm_plan"), binding)
    assert final_result["result_type"] == "REVISION"
    state = binding.read_state(session_id)
    prompt = binding.read_artifact(session_id, "prompt:current")
    plan = binding.read_artifact(session_id, "plan:current")
    assert state.lifecycle.result_body == final_result["projection"]["model_response"]
    assert {item.artifact_kind for item in state.lifecycle.authorized_handoff_artifacts} == {"prompt", "plan"}
    return {"stage": state.stage, "prompt_body": prompt.body, "plan_body": plan.body, "model_response": state.model_response}


def _g06_direct(host) -> dict:
    turn = None
    for text in [G06["activation"], "Yes, that is what I mean.", "Confirm the plan and execute."]:
        turn = host.handle(text)
    status = host.status()
    workspace = Path(status["workspace_path"])
    return {
        "stage": status["controller_state"]["stage"],
        "prompt_body": (workspace / "stages/10_prompt/output/current.md").read_text(encoding="utf-8").rstrip("\n"),
        "plan_body": (workspace / "stages/30_plan/output/current.md").read_text(encoding="utf-8").rstrip("\n"),
        "model_response": turn.text,
    }


def test_g06_structured_actions_match_direct_r6s(tmp_path, baseline_repo, recorded_worker_factory) -> None:
    binding = LocalRuntimeModelBinding(baseline_repo, worker=recorded_worker_factory(["G06"]), workspace_root=tmp_path / "vm")
    via_viewmodel = _g06_via_viewmodel(binding)
    binding.close()

    host_type = FrozenRuntimeLoader(baseline_repo).load_host_class()
    host = host_type(baseline_repo, worker=recorded_worker_factory(["G06"]), workspace_root=tmp_path / "direct").start()
    try:
        direct = _g06_direct(host)
    finally:
        host.close()
    assert via_viewmodel == direct
    assert via_viewmodel["stage"] == "CLOSED_SUCCESS"
    assert via_viewmodel["prompt_body"] == G06["prompt_body"]
    assert via_viewmodel["plan_body"] == G06["plan_body"]
    assert via_viewmodel["model_response"]


def test_a02_free_response_matches_direct_r6s(tmp_path, baseline_repo, recorded_worker_factory) -> None:
    binding = LocalRuntimeModelBinding(baseline_repo, worker=recorded_worker_factory(["A02"]), workspace_root=tmp_path / "vm")
    started = binding.start_or_resume(ModelSessionRequest(request_id="a02", task_text=A02["activation"]))
    projection = build_focus_projection_from_port(binding, started.session_id)
    envelope = {
        "schema_version": "r6o-input-envelope-1",
        "session_id": started.session_id,
        "source": "HOST_COMPOSER_TEXT",
        "model_revision": projection["model_revision"],
        "text": A02["revision"],
        "action_id": None,
        "projection_id": None,
    }
    assert handle_input(envelope, binding)["result_type"] == "REVISION"
    vm_state = binding.read_state(started.session_id)
    vm_prompt = binding.read_artifact(started.session_id, "prompt:current").body
    binding.close()

    host_type = FrozenRuntimeLoader(baseline_repo).load_host_class()
    host = host_type(baseline_repo, worker=recorded_worker_factory(["A02"]), workspace_root=tmp_path / "direct").start()
    try:
        host.handle(A02["activation"])
        host.handle(A02["revision"])
        status = host.status()
        direct_prompt = (Path(status["workspace_path"]) / "stages/10_prompt/output/current.md").read_text(encoding="utf-8").rstrip("\n")
    finally:
        host.close()
    assert vm_state.stage == status["controller_state"]["stage"] == "PROMPT_REVIEW"
    assert vm_prompt == direct_prompt == A02["prompt_body"]


def test_resume_preserves_authoritative_r6s_state(tmp_path, baseline_repo, recorded_worker_factory) -> None:
    root = tmp_path / "resume"
    first = LocalRuntimeModelBinding(baseline_repo, worker=recorded_worker_factory(["G06"]), workspace_root=root)
    started = first.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06["activation"]))
    before = build_focus_projection_from_port(first, started.session_id)
    first.close()
    second = LocalRuntimeModelBinding(baseline_repo, worker=recorded_worker_factory(["G06"]), workspace_root=root)
    resumed = second.start_or_resume(ModelSessionRequest(request_id="resume", resume_session_id=started.session_id))
    after = build_focus_projection_from_port(second, resumed.session_id)
    second.close()
    assert before == after


def test_resume_preserves_non_state_changing_protocol_response(
    tmp_path, baseline_repo, operation_worker_factory
) -> None:
    root = tmp_path / "resume-protocol-response"
    worker = operation_worker_factory("G06")
    first = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=root)
    started = first.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06["activation"]))
    workspace = first._host.engine.workspace.path
    (workspace / "stages/10_prompt/output/current.md").write_text(
        "Externally refined prompt before protocol discussion.\n", encoding="utf-8"
    )
    current = build_focus_projection_from_port(first, started.session_id)
    worker.responses["INTERPRET_PROMPT_REVIEW"] = '{"kind":"PROTOCOL_DISCUSSION"}'
    worker.responses["ANSWER_PROTOCOL_DISCUSSION"] = '{"body":"The current stage reviews the prompt."}'
    result = handle_input(
        {
            "schema_version": "r6o-input-envelope-1",
            "session_id": started.session_id,
            "source": "HOST_COMPOSER_TEXT",
            "model_revision": current["model_revision"],
            "text": "What does this stage do?",
            "action_id": None,
            "projection_id": None,
        },
        first,
    )
    assert result["result_type"] == "REVISION", result
    before = result["projection"]
    assert before["model_response"] == "The current stage reviews the prompt."
    first.close()
    second = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=root)
    resumed = second.start_or_resume(ModelSessionRequest(request_id="resume", resume_session_id=started.session_id))
    after = build_focus_projection_from_port(second, resumed.session_id)
    second.close()
    assert before == after


def test_resume_preserves_waiting_and_blocked_execution_responses(
    tmp_path, baseline_repo, operation_worker_factory
) -> None:
    cases = [
        ({"kind": "REQUEST_INPUT", "body": "Supply the deployment region.", "expected_type": "string", "description": "Cloud region"}, "WAITING_INPUT"),
        ({"kind": "BLOCKED_BY_HIGHER_PRIORITY", "body": "Execution is blocked by policy."}, "CLOSED_CANCELLED"),
    ]
    for index, (outcome, expected_stage) in enumerate(cases):
        root = tmp_path / f"resume-output-{index}"
        worker = operation_worker_factory("G06")
        worker.responses["EXECUTE"] = json.dumps(outcome)
        first = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=root)
        started = first.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06["activation"]))
        assert handle_input(_action(first, started.session_id, "confirm_prompt"), first)["result_type"] == "REVISION"
        assert handle_input(_action(first, started.session_id, "confirm_plan"), first)["result_type"] == "REVISION"
        before = build_focus_projection_from_port(first, started.session_id)
        first.close()

        second = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=root)
        resumed = second.start_or_resume(ModelSessionRequest(request_id="resume", resume_session_id=started.session_id))
        after = build_focus_projection_from_port(second, resumed.session_id)
        second.close()
        assert before == after
        assert after["stage"] == expected_stage
        assert after["model_response"] == outcome["body"]


@pytest.mark.parametrize("missing_name", ["current.md", "current.json"])
def test_missing_persisted_terminal_output_fails_closed(
    missing_name, tmp_path, baseline_repo, operation_worker_factory
) -> None:
    binding = LocalRuntimeModelBinding(
        baseline_repo,
        worker=operation_worker_factory("G06"),
        workspace_root=tmp_path / "workspaces",
    )
    started = binding.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06["activation"]))
    assert handle_input(_action(binding, started.session_id, "confirm_prompt"), binding)["result_type"] == "REVISION"
    final = handle_input(_action(binding, started.session_id, "confirm_plan"), binding)
    assert final["result_type"] == "REVISION"
    execution = binding._host.engine.workspace.path / "stages/50_execution/output" / missing_name
    execution.unlink()
    with pytest.raises(RuntimeError, match="persisted execution output is incomplete"):
        binding.read_state(started.session_id)
    binding.close()


def test_cancel_after_waiting_resumes_cancel_response_not_stale_input_request(
    tmp_path, baseline_repo, operation_worker_factory
) -> None:
    root = tmp_path / "cancel-after-waiting"
    worker = operation_worker_factory("G06")
    worker.responses["EXECUTE"] = json.dumps(
        {"kind": "REQUEST_INPUT", "body": "Supply a region.", "expected_type": "string", "description": "Region"}
    )
    worker.responses["INTERPRET_EXECUTION_INPUT"] = '{"kind":"CANCEL"}'
    first = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=root)
    started = first.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06["activation"]))
    assert handle_input(_action(first, started.session_id, "confirm_prompt"), first)["result_type"] == "REVISION"
    assert handle_input(_action(first, started.session_id, "confirm_plan"), first)["result_type"] == "REVISION"
    waiting = build_focus_projection_from_port(first, started.session_id)
    cancelled = handle_input(
        {
            "schema_version": "r6o-input-envelope-1",
            "session_id": started.session_id,
            "source": "HOST_COMPOSER_TEXT",
            "model_revision": waiting["model_revision"],
            "text": "Cancel.",
            "action_id": None,
            "projection_id": None,
        },
        first,
    )
    assert cancelled["projection"]["model_response"] == "Cancelled."
    first.close()
    second = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=root)
    resumed = second.start_or_resume(ModelSessionRequest(request_id="resume", resume_session_id=started.session_id))
    assert resumed.model_response == "Cancelled."
    second.close()
