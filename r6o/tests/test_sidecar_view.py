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


def test_sidecar_mode_close_and_reopen_are_presentation_only() -> None:
    port = StaticModelPort(state(), {"prompt:P1": artifact()})
    model = SidecarModel(PresentationAdapter(port), "I-1")
    before = model.projection
    assert model.toggle_mode() == "EXPANDED"
    model.close()
    assert not model.visible
    assert model.reopen()
    assert model.visible
    assert model.projection == before


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
