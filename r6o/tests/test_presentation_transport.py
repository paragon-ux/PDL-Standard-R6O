from __future__ import annotations

from r6o.model_binding.memory_model import RecordingModelPort, StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.tests.helpers import artifact, state
from r6o.views.envelopes import structured_action_envelope, text_envelope


def test_adapter_exposes_only_projection_and_input_submission() -> None:
    current = state()
    next_state = state(revision="model-rev-2", stage="PLAN_REVIEW")
    port = RecordingModelPort(
        current,
        next_state,
        {
            "prompt:P1": artifact(),
            "plan:R1": artifact("artifact-rev-1", "PLAN BODY"),
        },
    )
    adapter = PresentationAdapter(port)
    projection = adapter.current_projection("I-1")
    result = adapter.submit_input(
        structured_action_envelope(projection, "confirm_prompt")
    )
    assert result["result_type"] == "REVISION"
    assert result["projection"]["stage"] == "PLAN_REVIEW"
    assert port.submissions == ["Yes, that is what I mean."]
    assert set(vars(adapter)) == {"_port"}


def test_envelope_builders_preserve_projection_revision_identity() -> None:
    projection = PresentationAdapter(
        StaticModelPort(state(), {"prompt:P1": artifact()})
    ).current_projection("I-1")
    action = structured_action_envelope(projection, "confirm_prompt")
    assert action["source"] == "STRUCTURED_ACTION"
    assert action["projection_id"] == projection["projection_id"]
    assert action["model_revision"] == projection["model_revision"]
    free = text_envelope("TUI_TEXT", projection, "Revise it")
    assert free["source"] == "TUI_TEXT"
    assert free["text"] == "Revise it"
    assert free["action_id"] is None and free["projection_id"] is None
