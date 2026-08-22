from __future__ import annotations

from r6o.model_binding.memory_model import RecordingModelPort, StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.tests.helpers import artifact, plan, state
from r6o.views.sidecar.model import SidecarModel


def _model(port, focus=None) -> SidecarModel:
    return SidecarModel(PresentationAdapter(port), "I-1", focus_host_callback=focus)


def test_structured_action_submits_canonical_text() -> None:
    port = RecordingModelPort(state(), state(stage="PLAN_REVIEW"), {"prompt:P1": artifact(), "plan:R1": plan()})
    m = _model(port)
    result = m.select_action("confirm_prompt")
    assert result["result_type"] == "REVISION"
    assert port.submissions == ["Yes, that is what I mean."]


def test_focus_action_requests_composer_without_submit() -> None:
    port = RecordingModelPort(state(), state(stage="PLAN_REVIEW"), {"prompt:P1": artifact(), "plan:R1": plan()})
    focused = []
    m = _model(port, focused.append)
    m.select_action("something_else")
    assert focused == ["Something else..."]
    assert port.submissions == []


def test_disabled_action_guarded() -> None:
    snap = state()
    actions = [{"action_id": "x", "label": "Disabled", "ordinal": 1, "kind": "SEMANTIC_MESSAGE", "canonical_review_text": "hidden", "emphasis": "NORMAL", "enabled": False}]
    class _FakeAdapter:
        def current_projection(self, s): return {"session_id": s, "model_revision": "r", "projection_id": "p", "stage": "PROMPT_REVIEW", "artifact": None, "actions": actions, "lifecycle": {}}
        def submit_input(self, e): raise AssertionError("must not submit")
    m = SidecarModel(_FakeAdapter(), "I-1")
    m.select_action("x")
    assert m.notice == "action disabled: Disabled"


def test_host_composer_text_routes_host_source() -> None:
    port = RecordingModelPort(state(), state(), {"prompt:P1": artifact(), "plan:R1": plan()})
    m = _model(port)
    m.host_composer_text("feedback")
    assert port.submissions == ["feedback"]


def test_close_and_reopen_are_presentation_only() -> None:
    port = StaticModelPort(state(), {"prompt:P1": artifact(), "plan:R1": plan()})
    m = _model(port)
    before = m.projection["model_revision"]
    m.close()
    assert m.closed is True
    assert m.projection["model_revision"] == before
    m.open_()
    assert m.closed is False
    assert m.projection["model_revision"] == before


def test_toggle_mode_is_presentation_only() -> None:
    port = StaticModelPort(state(), {"prompt:P1": artifact(), "plan:R1": plan()})
    m = _model(port)
    before = m.projection["model_revision"]
    m.toggle_mode()
    assert m.mode == "EXPANDED"
    assert m.projection["model_revision"] == before


def test_stale_refresh_failure_shows_model_access() -> None:
    class _FailingAdapter:
        def __init__(self): self.calls = 0
        def current_projection(self, s):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("down")
            return {"session_id": s, "model_revision": "r1", "projection_id": "p1", "stage": "PROMPT_REVIEW", "artifact": None, "actions": [], "lifecycle": {}}
        def submit_input(self, e): return {"result_type": "STALE_PROJECTION", "projection": None}
    m = SidecarModel(_FailingAdapter(), "I-1")
    m.select_action = None  # not used
    m.host_composer_text("x")
    assert "MODEL_ACCESS" in m.notice

