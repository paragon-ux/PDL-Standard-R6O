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


def test_stale_structured_action_uses_returned_projection() -> None:
    stale_actions = [{"action_id": "confirm_plan", "label": "Confirm plan", "ordinal": 1, "kind": "SEMANTIC_MESSAGE", "canonical_review_text": "Confirm the plan and execute.", "emphasis": "PRIMARY", "enabled": True}]
    stale_projection = {"session_id": "I-1", "model_revision": "r2", "projection_id": "p2", "stage": "PLAN_REVIEW", "artifact": None, "actions": stale_actions, "lifecycle": {}}
    class _StaleAdapter:
        def __init__(self): self.submits = []
        def current_projection(self, s): return {"session_id": s, "model_revision": "r1", "projection_id": "p1", "stage": "PROMPT_REVIEW", "artifact": None, "actions": [{"action_id": "confirm_prompt", "label": "Confirm prompt", "ordinal": 1, "kind": "SEMANTIC_MESSAGE", "canonical_review_text": "Yes, that is what I mean.", "emphasis": "PRIMARY", "enabled": True}], "lifecycle": {}}
        def submit_input(self, e):
            self.submits.append(e)
            return {"result_type": "STALE_PROJECTION", "projection": stale_projection}
    m = SidecarModel(_StaleAdapter(), "I-1")
    result = m.select_action("confirm_prompt")
    assert result["result_type"] == "STALE_PROJECTION"
    assert len(m.adapter.submits) == 1
    assert m.projection["model_revision"] == "r2"
    assert [a["action_id"] for a in m.projection["actions"]] == ["confirm_plan"]



def test_reopen_refetches_authoritative_revision_change() -> None:
    rev1 = {"session_id": "I-1", "model_revision": "r1", "projection_id": "p1", "stage": "PROMPT_REVIEW", "artifact": {"artifact_ref": "prompt:P1", "artifact_revision": "P1", "artifact_kind": "prompt", "title": "Authoritative Prompt (PDL.md)", "media_type": "text/plain", "body": "BODY V1", "capabilities": {}}, "actions": [], "lifecycle": {}}
    rev2 = {"session_id": "I-1", "model_revision": "r2", "projection_id": "p2", "stage": "PROMPT_REVIEW", "artifact": {"artifact_ref": "prompt:P1", "artifact_revision": "P2", "artifact_kind": "prompt", "title": "Authoritative Prompt (PDL.md)", "media_type": "text/plain", "body": "BODY V2", "capabilities": {}}, "actions": [{"action_id": "change_task", "label": "Change the task", "ordinal": 2, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True}], "lifecycle": {}}

    class _RevAdapter:
        def __init__(self): self.calls = 0
        def current_projection(self, s):
            self.calls += 1
            return rev1 if self.calls == 1 else rev2
        def submit_input(self, e): return {"result_type": "REVISION", "projection": rev2}

    m = SidecarModel(_RevAdapter(), "I-1")
    assert m.projection["model_revision"] == "r1"
    m.close()
    m.open_()
    assert m.projection["model_revision"] == "r2"
    assert m.projection["artifact"]["body"] == "BODY V2"
    assert m.projection["actions"][0]["action_id"] == "change_task"
