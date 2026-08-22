from __future__ import annotations

from r6o.model_binding.memory_model import RecordingModelPort, StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.tests.helpers import artifact, state
from r6o.views.sidecar import SidecarModel


def test_sidecar_actions_are_projection_driven_and_focus_uses_host_composer() -> None:
    model = SidecarModel(
        PresentationAdapter(StaticModelPort(state(), {"prompt:P1": artifact()})),
        "I-1",
    )
    assert [item["action_id"] for item in model.actions] == [
        "confirm_prompt",
        "change_task",
        "change_approach",
        "something_else",
    ]
    result = model.select_action("something_else")
    assert result["result_type"] == "FOCUS_REQUIRED"
    assert result["focus_role"] == "FREE_RESPONSE"


def test_sidecar_mode_close_and_fresh_reattach_are_presentation_only() -> None:
    port = StaticModelPort(state(), {"prompt:P1": artifact()})
    adapter = PresentationAdapter(port)
    model = SidecarModel(adapter, "I-1")
    before = model.projection
    assert model.toggle_mode() == "EXPANDED"
    model.close()
    assert not model.visible
    attached = SidecarModel(adapter, "I-1")
    assert attached.visible
    assert attached.projection == before


def test_sidecar_host_composer_uses_host_source_and_updates_projection() -> None:
    current = state()
    next_state = state(revision="model-rev-2", artifact_revision="artifact-rev-1")
    port = RecordingModelPort(
        current,
        next_state,
        {
            "prompt:P1": artifact("artifact-rev-1"),
        },
    )
    model = SidecarModel(PresentationAdapter(port), "I-1")
    result = model.host_composer_text("Revise the prompt")
    assert result["result_type"] == "REVISION"
    assert port.submissions == ["Revise the prompt"]


def test_recorded_replay_miss_is_a_qualification_notice_without_raw_exception() -> None:
    projection = PresentationAdapter(
        StaticModelPort(state(), {"prompt:P1": artifact()})
    ).current_projection("I-1")

    class ReplayMissAdapter:
        def current_projection(self, _session_id):
            return projection

        def submit_input(self, _envelope):
            return {
                "result_type": "ERROR",
                "projection": None,
                "error": {
                    "code": "MODEL_ERROR",
                    "message": "ReplayMissError: no deterministic response",
                },
            }

    model = SidecarModel(
        ReplayMissAdapter(),
        "I-1",
        qualification_case="G06",
    )
    before = model.projection
    result = model.host_composer_text("arbitrary feedback")
    assert result["result_type"] == "ERROR"
    assert "Recorded qualification fixture" in model.notice
    assert "ReplayMissError" not in model.notice
    assert model.projection == before
    assert model.state.debug_error["message"].startswith("ReplayMissError")
