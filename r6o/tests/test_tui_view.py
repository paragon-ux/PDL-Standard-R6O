from __future__ import annotations

from r6o.model_binding.memory_model import RecordingModelPort, StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.tests.helpers import artifact, plan, state
from r6o.views.tui.controller import TuiController


def _controller(port) -> TuiController:
    return TuiController(PresentationAdapter(port), "I-1")


def test_render_matches_reference_layout() -> None:
    c = _controller(StaticModelPort(state(), {"prompt:P1": artifact(body="COMPARE Kafka and RabbitMQ.")}))
    out = c.render()
    assert "PDLt · PROMPT REVIEW" in out
    assert "COMPARE Kafka and RabbitMQ." in out
    assert "1 Confirm prompt" in out
    assert "4 Something else..." in out
    assert out.rstrip().endswith("Review >")


def test_structured_action_submits_canonical_text() -> None:
    port = RecordingModelPort(state(), state(stage="PLAN_REVIEW"), {"prompt:P1": artifact(), "plan:R1": plan()})
    c = _controller(port)
    result = c.select_action(1)
    assert result["result_type"] == "REVISION"
    assert port.submissions == ["Yes, that is what I mean."]
    assert c.projection["stage"] == "PLAN_REVIEW"


def test_focus_action_does_not_submit() -> None:
    port = RecordingModelPort(state(), state(stage="PLAN_REVIEW"), {"prompt:P1": artifact(), "plan:R1": plan()})
    c = _controller(port)
    c.select_action(4)
    assert c.focus_mode is True
    assert port.submissions == []


def test_disabled_action_is_guarded() -> None:
    snap = state()
    actions = [
        {"action_id": "x", "label": "Disabled", "ordinal": 1, "kind": "SEMANTIC_MESSAGE", "canonical_review_text": "hidden", "emphasis": "NORMAL", "enabled": False}
    ]
    # inject a projection with a disabled action
    adapter = _FakeAdapter(actions)
    c = TuiController(adapter, "I-1")
    c.select_action(1)
    assert c.notice == "action 1 is disabled"


class _FakeAdapter:
    def __init__(self, actions):
        self.actions = actions
        self.submits = []

    def current_projection(self, session_id):
        return {"session_id": session_id, "model_revision": "r", "projection_id": "p", "stage": "PROMPT_REVIEW", "artifact": None, "actions": self.actions, "lifecycle": {}}

    def submit_input(self, envelope):
        self.submits.append(envelope)
        return {"result_type": "REVISION", "projection": self.current_projection(session_id="I-1")}


def test_free_text_routes_tui_text() -> None:
    port = RecordingModelPort(state(), state(), {"prompt:P1": artifact(), "plan:R1": plan()})
    c = _controller(port)
    c.submit_text("This is feedback.")
    assert port.submissions == ["This is feedback."]


def test_stale_refresh_uses_returned_projection_without_retry() -> None:
    port = RecordingModelPort(state(), state(), {"prompt:P1": artifact(), "plan:R1": plan()})
    c = _controller(port)
    fresh = c.render
    stale_result = {"result_type": "STALE_PROJECTION", "projection": {"session_id": "I-1", "model_revision": "r2", "projection_id": "p2", "stage": "PROMPT_REVIEW", "artifact": None, "actions": [], "lifecycle": {}}}
    class _StaleAdapter:
        def current_projection(self, s): return {"session_id": s, "model_revision": "r1", "projection_id": "p1", "stage": "PROMPT_REVIEW", "artifact": None, "actions": [], "lifecycle": {}}
        def submit_input(self, e): return stale_result
    c2 = TuiController(_StaleAdapter(), "I-1")
    result = c2.submit_text("x")
    assert result["result_type"] == "STALE_PROJECTION"
    assert c2.projection["model_revision"] == "r2"


def test_scroll_changes_window() -> None:
    body = "\n".join(f"line {i}" for i in range(20))
    c = _controller(StaticModelPort(state(), {"prompt:P1": artifact(body=body)}))
    first = c.render()
    c.scroll_artifact(3)
    second = c.render()
    assert first != second

