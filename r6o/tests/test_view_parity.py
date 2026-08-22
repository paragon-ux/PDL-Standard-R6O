from __future__ import annotations

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.presentation_transport import PresentationAdapter
from r6o.views.sidecar import SidecarModel
from r6o.views.tui import TuiController

G06_ACTIVATION = "Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers."
A02_ACTIVATION = "Use $confirm-with-pseudocode to compare Kafka and RabbitMQ for event delivery."
A02_REVISION = "This is not confirmed. The audience should be data engineers, not backend engineers."


def _binding(tmp_path, baseline_repo, recorded_worker_factory, case_id, name):
    return LocalRuntimeModelBinding(
        baseline_repo,
        worker=recorded_worker_factory([case_id]),
        workspace_root=tmp_path / name,
        run_id=name,
    )


def test_same_session_views_render_identical_projection_semantics(
    tmp_path, baseline_repo, recorded_worker_factory
) -> None:
    binding = _binding(tmp_path, baseline_repo, recorded_worker_factory, "G06", "shared")
    started = binding.start_or_resume(
        ModelSessionRequest(request_id="shared", task_text=G06_ACTIVATION)
    )
    adapter = PresentationAdapter(binding)
    tui = TuiController(adapter, started.session_id)
    sidecar = SidecarModel(adapter, started.session_id)
    assert tui.projection == sidecar.projection
    assert [item["action_id"] for item in tui.state.actions] == [
        item["action_id"] for item in sidecar.actions
    ]
    binding.close()


def test_stale_cross_view_action_refreshes_without_retry(
    tmp_path, baseline_repo, recorded_worker_factory
) -> None:
    binding = _binding(tmp_path, baseline_repo, recorded_worker_factory, "G06", "stale")
    started = binding.start_or_resume(
        ModelSessionRequest(request_id="stale", task_text=G06_ACTIVATION)
    )
    adapter = PresentationAdapter(binding)
    tui = TuiController(adapter, started.session_id)
    sidecar = SidecarModel(adapter, started.session_id)
    assert tui.select_action()["projection"]["stage"] == "PLAN_REVIEW"
    stale = sidecar.select_action("confirm_prompt")
    assert stale["result_type"] == "STALE_PROJECTION"
    assert sidecar.projection["stage"] == "PLAN_REVIEW"
    assert sidecar.notice == "View changed; refreshed to the current projection."
    assert binding.read_state(sidecar.state.session_id).stage == "PLAN_REVIEW"
    binding.close()


def test_g06_tui_and_sidecar_model_structured_outcomes_are_equivalent(
    tmp_path, baseline_repo, recorded_worker_factory
) -> None:
    outcomes = []
    for surface in ("tui", "sidecar"):
        binding = _binding(
            tmp_path, baseline_repo, recorded_worker_factory, "G06", surface
        )
        started = binding.start_or_resume(
            ModelSessionRequest(request_id=surface, task_text=G06_ACTIVATION)
        )
        adapter = PresentationAdapter(binding)
        stages = [started.stage]
        if surface == "tui":
            view = TuiController(adapter, started.session_id)
            view.select_action()
            stages.append(view.projection["stage"])
            view.select_action()
            stages.append(view.projection["stage"])
            session_id = view.state.session_id
        else:
            view = SidecarModel(adapter, started.session_id)
            view.select_action("confirm_prompt")
            stages.append(view.projection["stage"])
            view.select_action("confirm_plan")
            stages.append(view.projection["stage"])
            session_id = view.state.session_id
        outcomes.append(
            (
                stages,
                binding.read_artifact(session_id, "prompt:current").body,
                binding.read_artifact(session_id, "plan:current").body,
            )
        )
        binding.close()
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] == ["PROMPT_REVIEW", "PLAN_REVIEW", "CLOSED_SUCCESS"]


def test_a02_tui_and_host_composer_free_response_outcomes_are_equivalent(
    tmp_path, baseline_repo, recorded_worker_factory
) -> None:
    outcomes = []
    for surface in ("tui", "sidecar"):
        binding = _binding(
            tmp_path, baseline_repo, recorded_worker_factory, "A02", f"a02-{surface}"
        )
        started = binding.start_or_resume(
            ModelSessionRequest(request_id=surface, task_text=A02_ACTIVATION)
        )
        adapter = PresentationAdapter(binding)
        if surface == "tui":
            view = TuiController(adapter, started.session_id)
            view.state.submit_text("TUI_TEXT", A02_REVISION)
            session_id = view.state.session_id
            projection = view.state.projection
        else:
            view = SidecarModel(adapter, started.session_id)
            view.host_composer_text(A02_REVISION)
            session_id = view.state.session_id
            projection = view.projection
        outcomes.append(
            (
                projection["stage"],
                binding.read_artifact(session_id, "prompt:current").body,
            )
        )
        binding.close()
    assert outcomes[0] == outcomes[1]


def test_real_recorded_replay_miss_preserves_projection_and_hides_raw_error(
    tmp_path, baseline_repo, recorded_worker_factory
) -> None:
    binding = _binding(tmp_path, baseline_repo, recorded_worker_factory, "G06", "miss")
    started = binding.start_or_resume(
        ModelSessionRequest(request_id="miss", task_text=G06_ACTIVATION)
    )
    adapter = PresentationAdapter(binding)
    view = SidecarModel(
        adapter,
        started.session_id,
        qualification_case="G06",
    )
    before = view.projection
    result = view.host_composer_text("This input is intentionally not recorded.")
    assert result["result_type"] == "ERROR"
    assert view.projection == before
    assert "Recorded qualification fixture" in view.notice
    assert "ReplayMissError" not in view.notice
    assert "ReplayMissError" in view.state.debug_error["message"]
    binding.close()
