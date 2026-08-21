from __future__ import annotations

import threading
from pathlib import Path

import pytest

from r6o.model_binding.base import ModelSessionRequest, StaleProjectionError
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.memory_model import RecordingModelPort
from r6o.tests.helpers import artifact, state
from r6o.viewmodel.dispatcher import handle_input, validate_command_result
from r6o.viewmodel.projection import build_focus_projection_from_port

G06 = "Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers."


def _structured(projection: dict, action_id: str) -> dict:
    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": projection["session_id"],
        "source": "STRUCTURED_ACTION",
        "model_revision": projection["model_revision"],
        "text": None,
        "action_id": action_id,
        "projection_id": projection["projection_id"],
    }


def _text(projection: dict, text: str) -> dict:
    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": projection["session_id"],
        "source": "HOST_COMPOSER_TEXT",
        "model_revision": projection["model_revision"],
        "text": text,
        "action_id": None,
        "projection_id": None,
    }


def test_projection_id_is_validated_before_action_resolution() -> None:
    initial = state()
    following = state(revision="model-rev-2", stage="PLAN_REVIEW")
    item = artifact()
    port = RecordingModelPort(initial, following, {item.artifact_ref: item})
    projection = build_focus_projection_from_port(port, "I-1")
    result = handle_input(_structured({**projection, "projection_id": "obsolete"}, "confirm_prompt"), port)
    validate_command_result(result)
    assert result["result_type"] == "STALE_PROJECTION", result
    assert port.submissions == []


def test_stale_free_response_never_reaches_model_mutation() -> None:
    initial = state()
    item = artifact()
    port = RecordingModelPort(initial, state(revision="next"), {item.artifact_ref: item})
    projection = build_focus_projection_from_port(port, "I-1")
    result = handle_input(_text({**projection, "model_revision": "obsolete"}, "change it"), port)
    assert result["result_type"] == "STALE_PROJECTION"
    assert port.submissions == []


@pytest.mark.parametrize(
    ("stage", "relative", "action_id"),
    [
        ("PROMPT_REVIEW", "stages/10_prompt/output/current.md", "confirm_prompt"),
        ("PLAN_REVIEW", "stages/30_plan/output/current.md", "confirm_plan"),
    ],
)
def test_external_current_edit_fails_closed_before_semantic_mutation(
    stage,
    relative,
    action_id,
    tmp_path,
    baseline_repo,
    operation_worker_factory,
) -> None:
    worker = operation_worker_factory("G06")
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "workspaces")
    snapshot = binding.start_or_resume(ModelSessionRequest(request_id="start", task_text=G06))
    if stage == "PLAN_REVIEW":
        prompt_projection = build_focus_projection_from_port(binding, snapshot.session_id)
        result = handle_input(_structured(prompt_projection, "confirm_prompt"), binding)
        assert result["result_type"] == "REVISION"
    projection_a = build_focus_projection_from_port(binding, snapshot.session_id)
    workspace = tmp_path / "workspaces" / projection_a["workspace_id"]
    state_path = workspace / "state" / "controller-state.json"
    controller_before = state_path.read_bytes()
    calls_before = len(worker.calls)
    edited_body = f"EXTERNALLY EDITED {stage} BODY"
    (workspace / Path(relative)).write_text(edited_body + "\n", encoding="utf-8")

    stale = handle_input(_structured(projection_a, action_id), binding)
    validate_command_result(stale)
    assert stale["result_type"] == "STALE_PROJECTION"
    assert len(worker.calls) == calls_before
    assert state_path.read_bytes() == controller_before

    projection_b = build_focus_projection_from_port(binding, snapshot.session_id)
    assert projection_b["artifact"]["body"] == edited_body
    assert projection_b["model_revision"] != projection_a["model_revision"]
    assert projection_b["projection_id"] != projection_a["projection_id"]
    accepted = handle_input(_structured(projection_b, action_id), binding)
    assert accepted["result_type"] == "REVISION", accepted
    binding.close()


def test_unknown_action_and_invalid_envelope_fail_closed() -> None:
    item = artifact()
    port = RecordingModelPort(state(), state(revision="next"), {item.artifact_ref: item})
    projection = build_focus_projection_from_port(port, "I-1")
    unknown = handle_input(_structured(projection, "does_not_exist"), port)
    invalid = handle_input({"source": "STRUCTURED_ACTION"}, port)
    assert unknown["error"]["code"] == "UNKNOWN_ACTION"
    assert invalid["error"]["code"] == "INVALID_ENVELOPE"
    assert port.submissions == []


def test_failed_stale_refresh_returns_schema_valid_model_access_error() -> None:
    item = artifact()

    class RefreshFailingPort(RecordingModelPort):
        failed = False

        def submit_user_message(self, session_id, text, expected_revision):
            self.failed = True
            raise StaleProjectionError("advanced")

        def read_state(self, session_id):
            if self.failed:
                raise OSError("refresh unavailable")
            return super().read_state(session_id)

    port = RefreshFailingPort(state(), state(revision="next"), {item.artifact_ref: item})
    projection = build_focus_projection_from_port(port, "I-1")
    result = handle_input(_structured(projection, "confirm_prompt"), port)
    validate_command_result(result)
    assert result["result_type"] == "ERROR"
    assert result["error"]["code"] == "MODEL_ACCESS"


def test_edit_at_runtime_sync_point_is_stale_before_worker_or_controller_mutation(
    tmp_path, baseline_repo, operation_worker_factory
) -> None:
    worker = operation_worker_factory("G06")
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "workspaces")
    started = binding.start_or_resume(ModelSessionRequest(request_id="start", task_text=G06))
    projection = build_focus_projection_from_port(binding, started.session_id)
    workspace = binding._host.engine.workspace
    state_path = workspace.path / "state" / "controller-state.json"
    state_before = state_path.read_bytes()
    calls_before = len(worker.calls)
    original_sync = workspace.sync_unconfirmed_edit

    def racing_sync(kind, artifact_id, controller_body):
        (workspace.path / "stages/10_prompt/output/current.md").write_text(
            "RACING EDIT\n", encoding="utf-8"
        )
        return original_sync(kind, artifact_id, controller_body)

    workspace.sync_unconfirmed_edit = racing_sync
    result = handle_input(_structured(projection, "confirm_prompt"), binding)
    assert result["result_type"] == "STALE_PROJECTION", result
    assert len(worker.calls) == calls_before
    assert state_path.read_bytes() == state_before
    binding.close()


def test_edit_after_interpretation_is_stale_before_controller_mutation(
    tmp_path, baseline_repo, operation_worker_factory
) -> None:
    worker = operation_worker_factory("G06")
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "workspaces")
    started = binding.start_or_resume(ModelSessionRequest(request_id="start", task_text=G06))
    projection = build_focus_projection_from_port(binding, started.session_id)
    workspace = binding._host.engine.workspace
    state_path = workspace.path / "state" / "controller-state.json"
    state_before = state_path.read_bytes()
    calls_before = len(worker.calls)
    original_call = worker.call

    def racing_call(request):
        result = original_call(request)
        if request.operation == "INTERPRET_PROMPT_REVIEW":
            (workspace.path / "stages/10_prompt/output/current.md").write_text(
                "POST-INTERPRETATION EDIT\n", encoding="utf-8"
            )
        return result

    worker.call = racing_call
    result = handle_input(_structured(projection, "confirm_prompt"), binding)
    assert result["result_type"] == "STALE_PROJECTION", result
    assert len(worker.calls) == calls_before + 1
    assert state_path.read_bytes() == state_before
    binding.close()


def test_concurrent_same_revision_submissions_are_serialized_and_one_is_stale(
    tmp_path, baseline_repo, operation_worker_factory
) -> None:
    worker = operation_worker_factory("G06")
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "workspaces")
    started = binding.start_or_resume(ModelSessionRequest(request_id="start", task_text=G06))
    projection = build_focus_projection_from_port(binding, started.session_id)
    entered = threading.Event()
    release = threading.Event()
    second_done = threading.Event()
    original_call = worker.call

    def blocking_call(request):
        if request.operation == "INTERPRET_PROMPT_REVIEW":
            entered.set()
            assert release.wait(5)
        return original_call(request)

    worker.call = blocking_call
    outcomes = []

    def submit(mark_done=None):
        try:
            outcomes.append(
                binding.submit_user_message(
                    started.session_id,
                    "Yes, that is what I mean.",
                    projection["model_revision"],
                )
            )
        except Exception as exc:
            outcomes.append(exc)
        finally:
            if mark_done is not None:
                mark_done.set()

    first = threading.Thread(target=submit)
    second = threading.Thread(target=submit, args=(second_done,))
    first.start()
    assert entered.wait(5)
    second.start()
    assert not second_done.wait(0.1)
    release.set()
    first.join(5)
    second.join(5)
    assert sum(isinstance(item, StaleProjectionError) for item in outcomes) == 1
    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    binding.close()
