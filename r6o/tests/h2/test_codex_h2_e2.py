from __future__ import annotations

import inspect
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.h2.codex_e2 import (
    AttachedCodexSidecarPresentation,
    CodexH2E2Session,
    H2E2IntegrationError,
    build_structured_action_envelope,
)
from scripts.run_r6o2_tui import G06_ACTIVATION


ROOT = Path(__file__).resolve().parents[3]


class FakePresentation:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.projections: list[dict[str, Any]] = []

    def present(self, projection: dict[str, Any], *, initial: bool = False) -> dict[str, Any]:
        stage = projection["stage"]
        self.projections.append(projection)
        if stage == "CLOSED_SUCCESS":
            self.calls.extend(["render_terminal", "dismiss_sidecar", "focus_actual_composer"])
            return {
                "sidecar_visibility": "DISMISSED",
                "focus_owner": "ACTUAL_CODEX_COMPOSER",
            }
        action_id = projection["actions"][0]["action_id"]
        self.calls.extend(
            [
                "attach" if initial else "render_active",
                f"focus_{action_id}",
            ]
        )
        return {
            "sidecar_visibility": "VISIBLE_STANDARD",
            "focus_owner": f"SIDECAR_ACTION_{action_id.upper()}",
        }


@pytest.fixture()
def g06_session(tmp_path, baseline_repo, operation_worker_factory):
    worker = operation_worker_factory("G06")
    model = LocalRuntimeModelBinding(
        baseline_repo,
        worker=worker,
        workspace_root=tmp_path / "workspaces",
        run_id="h2-e2-test",
    )
    presentation = FakePresentation()
    events: list[dict[str, Any]] = []
    session = CodexH2E2Session(
        model,
        presentation,
        ModelSessionRequest(request_id="h2-e2-test", task_text=G06_ACTIVATION),
        on_transition=events.append,
    )
    try:
        yield session, model, worker, presentation, events
    finally:
        model.close()


def test_g06_start_projects_authoritative_prompt_and_primary_action(g06_session) -> None:
    session, _model, worker, presentation, events = g06_session

    prompt = session.start()

    assert prompt["stage"] == "PROMPT_REVIEW"
    assert prompt["artifact"]["artifact_kind"] == "prompt"
    assert prompt["artifact"]["body"].strip()
    assert prompt["actions"][0]["action_id"] == "confirm_prompt"
    assert worker.calls == ["DRAFT_PROMPT"]
    assert presentation.calls == ["attach", "focus_confirm_prompt"]
    assert events[0]["transition_id"] == "G06-T0-CODEX"
    assert events[0]["envelope"] is None


def test_g06_two_clicks_are_exact_structured_actions_and_close_success(g06_session) -> None:
    session, _model, worker, presentation, events = g06_session
    prompt = session.start()

    plan = session.activate_action("confirm_prompt")
    terminal = session.activate_action("confirm_plan")

    assert plan["stage"] == "PLAN_REVIEW"
    assert plan["artifact"]["artifact_kind"] == "plan"
    assert plan["artifact"]["body"].strip()
    assert (
        plan["artifact"]["artifact_ref"],
        plan["artifact"]["artifact_revision"],
    ) != (
        prompt["artifact"]["artifact_ref"],
        prompt["artifact"]["artifact_revision"],
    )
    assert plan["actions"][0]["action_id"] == "confirm_plan"
    assert terminal["stage"] == "CLOSED_SUCCESS"
    assert terminal["artifact"] is None
    assert terminal["actions"] == []
    assert session.terminal is True
    assert worker.calls == [
        "DRAFT_PROMPT",
        "INTERPRET_PROMPT_REVIEW",
        "DRAFT_PLAN",
        "INTERPRET_PLAN_REVIEW",
        "EXECUTE",
    ]
    assert [item["source"] for item in session.envelopes] == [
        "STRUCTURED_ACTION",
        "STRUCTURED_ACTION",
    ]
    assert [item["action_id"] for item in session.envelopes] == [
        "confirm_prompt",
        "confirm_plan",
    ]
    assert all(item["text"] is None for item in session.envelopes)
    assert presentation.calls == [
        "attach",
        "focus_confirm_prompt",
        "render_active",
        "focus_confirm_plan",
        "render_terminal",
        "dismiss_sidecar",
        "focus_actual_composer",
    ]
    assert [event["transition_id"] for event in events] == [
        "G06-T0-CODEX",
        "G06-T1-CODEX",
        "G06-T2-CODEX",
    ]


def test_real_qt_sidecar_clicks_drive_exact_g06_path(
    tmp_path, baseline_repo, operation_worker_factory
) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    from r6o.views.sidecar.qt_app import QtSidecarWindow

    worker = operation_worker_factory("G06")
    model = LocalRuntimeModelBinding(
        baseline_repo,
        worker=worker,
        workspace_root=tmp_path / "qt-workspaces",
        run_id="h2-e2-qt-test",
    )
    holder: dict[str, CodexH2E2Session] = {}
    callback_errors: list[Exception] = []

    def on_action(action_id: str) -> None:
        try:
            holder["session"].activate_action(action_id)
        except Exception as exc:
            callback_errors.append(exc)

    sidecar = QtSidecarWindow(on_action=on_action)

    class LocalQtBinding:
        def __init__(self) -> None:
            self.sidecar = sidecar
            self.focus_return_count = 0

        def attach(self, projection: dict[str, Any]) -> dict[str, Any]:
            assert self.sidecar.render(projection) is True
            return {"visible": self.sidecar.window.isVisible()}

        def observe(self) -> dict[str, Any]:
            return {"visible": self.sidecar.window.isVisible()}

        def close_view_and_verify_focus(self) -> dict[str, Any]:
            self.focus_return_count += 1
            self.sidecar.close_view()
            return {
                "sidecar_visible": self.sidecar.window.isVisible(),
                "composer_keyboard_focus": True,
            }

    binding = LocalQtBinding()
    session = CodexH2E2Session(
        model,
        AttachedCodexSidecarPresentation(binding),
        ModelSessionRequest(request_id="h2-e2-qt-test", task_text=G06_ACTIVATION),
    )
    holder["session"] = session

    def action_item(action_id: str) -> Any:
        pending = [sidecar.window.contentItem()]
        object_name = f"reviewAction_{action_id}"
        while pending:
            item = pending.pop()
            if str(item.objectName()) == object_name:
                return item
            pending.extend(item.childItems())
        raise LookupError(object_name)

    def click(action_id: str) -> None:
        item = action_item(action_id)
        center = item.mapToScene(QPointF(item.property("width") / 2, item.property("height") / 2))
        QTest.mouseClick(
            sidecar.window,
            Qt.LeftButton,
            Qt.NoModifier,
            center.toPoint(),
        )
        QTest.qWait(20)

    try:
        session.start()
        click("confirm_prompt")
        assert session.projection["stage"] == "PLAN_REVIEW"
        assert action_item("confirm_plan").property("activeFocus") is True
        click("confirm_plan")
        assert session.terminal is True
        assert sidecar.window.isVisible() is False
        assert binding.focus_return_count == 1
        assert callback_errors == []
        assert worker.calls == [
            "DRAFT_PROMPT",
            "INTERPRET_PROMPT_REVIEW",
            "DRAFT_PLAN",
            "INTERPRET_PLAN_REVIEW",
            "EXECUTE",
        ]
    finally:
        sidecar.close()
        model.close()


def test_invalid_or_duplicate_activation_never_submits_again(g06_session) -> None:
    session, _model, worker, presentation, _events = g06_session
    session.start()
    session.activate_action("confirm_prompt")
    calls_before = list(worker.calls)
    envelopes_before = list(session.envelopes)
    presentations_before = list(presentation.calls)

    with pytest.raises(H2E2IntegrationError, match="INVALID_OR_STALE_ACTION"):
        session.activate_action("confirm_prompt")

    assert worker.calls == calls_before
    assert session.envelopes == envelopes_before
    assert presentation.calls == presentations_before


@pytest.mark.parametrize("result_type", ["ERROR", "STALE_PROJECTION"])
def test_viewmodel_submission_failure_keeps_current_sidecar_projection(
    g06_session, result_type: str
) -> None:
    session, _model, worker, presentation, events = g06_session
    current = session.start()
    error = {
        "schema_version": "r6o-viewmodel-command-result-1",
        "ok": False,
        "result_type": result_type,
        "projection": current if result_type == "STALE_PROJECTION" else None,
        "focus_role": None,
        "error": {
            "code": result_type,
            "message": "injected deterministic failure",
        },
    }
    session.input_handler = lambda _envelope, _port: error

    with pytest.raises(H2E2IntegrationError, match="VIEWMODEL_SUBMISSION_FAILED"):
        session.activate_action("confirm_prompt")

    assert worker.calls == ["DRAFT_PROMPT"]
    assert session.envelopes == []
    assert session.projection is current
    assert presentation.calls == ["attach", "focus_confirm_prompt"]
    assert len(events) == 1


def test_invalid_returned_projection_is_not_rendered(g06_session) -> None:
    session, _model, worker, presentation, events = g06_session
    current = session.start()
    invalid = deepcopy(current)
    invalid["stage"] = "WAITING_INPUT"
    result = {
        "schema_version": "r6o-viewmodel-command-result-1",
        "ok": True,
        "result_type": "REVISION",
        "projection": invalid,
        "focus_role": None,
        "error": None,
    }
    session.input_handler = lambda _envelope, _port: result

    with pytest.raises(H2E2IntegrationError, match="UNEXPECTED_G06_STAGE"):
        session.activate_action("confirm_prompt")

    assert worker.calls == ["DRAFT_PROMPT"]
    assert session.envelopes == []
    assert presentation.projections == [current]
    assert len(events) == 1


def test_reentrant_duplicate_is_rejected_before_dispatch(g06_session) -> None:
    session, _model, worker, _presentation, _events = g06_session
    session.start()
    session._busy = True
    with pytest.raises(H2E2IntegrationError, match="DUPLICATE_ACTION_ACTIVATION"):
        session.activate_action("confirm_prompt")
    assert worker.calls == ["DRAFT_PROMPT"]
    assert session.envelopes == []


class FakeAction:
    def __init__(self, action_id: str, focused: bool = True) -> None:
        self.action_id = action_id
        self.focused = focused

    def objectName(self) -> str:
        return f"reviewAction_{self.action_id}"

    def childItems(self) -> list[Any]:
        return []

    def property(self, name: str) -> bool:
        assert name == "activeFocus"
        return self.focused


class FakeSidecar:
    def __init__(self) -> None:
        self.rendered: list[str] = []
        self.primary_action = "confirm_prompt"
        self.window = self

    def render(self, projection: dict[str, Any]) -> bool:
        self.rendered.append(projection["stage"])
        if projection["stage"] == "PLAN_REVIEW":
            self.primary_action = "confirm_plan"
        return projection["stage"] != "CLOSED_SUCCESS"

    def contentItem(self) -> "FakeSidecar":
        return self

    def objectName(self) -> str:
        return "fakeRoot"

    def childItems(self) -> list[FakeAction]:
        return [FakeAction(self.primary_action)]


class FakeBinding:
    def __init__(self, *, sidecar_visible_after_close: bool = False) -> None:
        self.sidecar = FakeSidecar()
        self.sidecar_visible_after_close = sidecar_visible_after_close
        self.calls: list[str] = []

    def attach(self, projection: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("attach")
        self.sidecar.render(projection)
        return {"visible": True}

    def observe(self) -> dict[str, Any]:
        self.calls.append("observe")
        return {"visible": True}

    def close_view_and_verify_focus(self) -> dict[str, Any]:
        self.calls.append("close_view_and_verify_focus")
        return {
            "sidecar_visible": self.sidecar_visible_after_close,
            "composer_keyboard_focus": True,
        }


def _projection(stage: str, action_id: str | None = None) -> dict[str, Any]:
    if stage == "CLOSED_SUCCESS":
        return {"stage": stage}
    return {
        "stage": stage,
        "actions": [{"action_id": action_id, "enabled": True}],
    }


def test_actual_presentation_dismisses_then_returns_focus_exactly_once() -> None:
    binding = FakeBinding()
    presentation = AttachedCodexSidecarPresentation(binding)

    presentation.present(_projection("PROMPT_REVIEW", "confirm_prompt"), initial=True)
    presentation.present(_projection("PLAN_REVIEW", "confirm_plan"))
    terminal = presentation.present(_projection("CLOSED_SUCCESS"))

    assert terminal["sidecar_visibility"] == "DISMISSED"
    assert terminal["focus_owner"] == "ACTUAL_CODEX_COMPOSER"
    assert binding.sidecar.rendered == [
        "PROMPT_REVIEW",
        "PLAN_REVIEW",
        "CLOSED_SUCCESS",
    ]
    assert binding.calls == ["attach", "observe", "close_view_and_verify_focus"]
    with pytest.raises(H2E2IntegrationError, match="TERMINAL_CLOSE_NOT_EXACTLY_ONCE"):
        presentation.present(_projection("CLOSED_SUCCESS"))
    assert binding.calls.count("close_view_and_verify_focus") == 1


def test_terminal_focus_return_fails_closed_if_sidecar_remains_visible() -> None:
    presentation = AttachedCodexSidecarPresentation(
        FakeBinding(sidecar_visible_after_close=True)
    )
    with pytest.raises(H2E2IntegrationError, match="TERMINAL_SIDECAR_NOT_DISMISSED"):
        presentation.present(_projection("CLOSED_SUCCESS"))


def test_structured_action_builder_contains_no_composer_text() -> None:
    projection = {
        "session_id": "I-1",
        "model_revision": "model-1",
        "projection_id": "projection-1",
    }
    envelope = build_structured_action_envelope(projection, "confirm_prompt")
    assert envelope == {
        "schema_version": "r6o-input-envelope-1",
        "session_id": "I-1",
        "source": "STRUCTURED_ACTION",
        "model_revision": "model-1",
        "text": None,
        "action_id": "confirm_prompt",
        "projection_id": "projection-1",
    }
    source = inspect.getsource(CodexH2E2Session)
    assert "HOST_COMPOSER_TEXT" not in source
    assert "CodexComposerInputBinding" not in source


def test_e2_runner_has_portable_help() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/h2/run_codex_h2_e2.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--case {G06}" in completed.stdout
    assert "--record" in completed.stdout


def test_readme_e2_command_is_branch_bound_and_excludes_composer_submission() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## H2-E2 actual Codex G06 structured-action checkout", 1)[1]
    section = section.split("\n## ", 1)[0]
    assert "codex/h2-e2-g06-integration" in section
    assert "8a85ac4214e7b3386c3c8079b0d45fb79a97e9ff" in section
    assert "python scripts\\h2\\run_codex_h2_e2.py --case G06 --record" in section
    assert "E1 composer input binding is not armed" in section
    assert "H2_E2_G06_PASS" in section
