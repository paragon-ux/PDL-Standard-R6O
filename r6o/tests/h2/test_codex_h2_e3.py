from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from r6o.h2.codex_e3 import (
    CodexH2E3Session,
    H2E3IntegrationError,
)
from r6o.host.codex.windows.input_binding import build_host_composer_envelope
from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from scripts.h2 import run_codex_h2_e3 as e3_runner
from scripts.h2.verify_a02_full_fixture import REVISION_TEXT
from scripts.run_r6o2_tui import (
    A02_ACTIVATION,
    A02_OPERATIONS,
    A02ReplayWorker,
    ObservedWorker,
)


ROOT = Path(__file__).resolve().parents[3]


class FakeInputBinding:
    def __init__(self, *, fail_activation: bool = False) -> None:
        self.fail_activation = fail_activation
        self.activated: list[dict[str, Any]] = []
        self.deactivated = 0
        self.armed = False

    def activate(self, projection: dict[str, Any], *, timeout: float = 5.0) -> None:
        assert timeout == 5.0
        if self.fail_activation:
            raise RuntimeError("focus unavailable")
        self.activated.append(dict(projection))
        self.armed = True

    def deactivate(self) -> None:
        self.deactivated += 1
        self.armed = False


class FakeE3Presentation:
    def __init__(self, input_binding: FakeInputBinding) -> None:
        self.input_binding = input_binding
        self.calls: list[str] = []
        self.projections: list[dict[str, Any]] = []

    def present(self, projection: dict[str, Any], *, initial: bool = False) -> dict[str, Any]:
        self.projections.append(projection)
        if projection["stage"] == "CLOSED_SUCCESS":
            self.calls.extend(["dismiss_sidecar", "focus_actual_composer"])
            return {
                "sidecar_visibility": "DISMISSED",
                "focus_owner": "ACTUAL_CODEX_COMPOSER",
            }
        action_id = projection["actions"][0]["action_id"]
        self.calls.append("attach" if initial else "render_active")
        self.calls.append(f"focus_{action_id}")
        return {
            "sidecar_visibility": "VISIBLE_STANDARD",
            "focus_owner": f"SIDECAR_ACTION_{action_id.upper()}",
        }

    def focus_actual_composer(self, projection: dict[str, Any]) -> dict[str, Any]:
        self.input_binding.activate(projection)
        self.calls.append("focus_actual_composer")
        return {
            "sidecar_visibility": "VISIBLE_STANDARD",
            "focus_owner": "ACTUAL_CODEX_COMPOSER",
        }


@pytest.fixture()
def a02_session(tmp_path: Path, baseline_repo: Path):
    delegate = A02ReplayWorker()
    worker = ObservedWorker(delegate, A02_OPERATIONS, "A02-FULL")
    model = LocalRuntimeModelBinding(
        baseline_repo,
        worker=worker,
        workspace_root=tmp_path / "workspaces",
        run_id="h2-e3-a02-test",
    )
    input_binding = FakeInputBinding()
    presentation = FakeE3Presentation(input_binding)
    events: list[dict[str, Any]] = []
    session = CodexH2E3Session(
        model,
        presentation,
        input_binding,
        ModelSessionRequest(request_id="h2-e3-a02-test", task_text=A02_ACTIVATION),
        on_transition=events.append,
    )
    try:
        yield session, model, worker, input_binding, presentation, events
    finally:
        model.close()


def test_a02_full_composes_focus_capture_and_structured_actions(a02_session) -> None:
    session, _model, worker, input_binding, presentation, events = a02_session

    initial = session.start()
    focused = session.activate_action("something_else")

    assert initial["stage"] == "PROMPT_REVIEW"
    assert focused is initial
    assert worker.calls == [{"operation_id": "A02F:0001", "operation": "DRAFT_PROMPT"}]
    assert input_binding.armed is True
    assert len(input_binding.activated) == 1
    assert events[1]["transition_id"] == "A02-T1-FOCUS-CODEX"
    assert events[1]["envelope"] == session.envelopes[0]
    assert events[1]["envelope"]["action_id"] == "something_else"
    assert events[1]["envelope"]["text"] is None
    assert events[1]["presentation"]["focus_owner"] == "ACTUAL_CODEX_COMPOSER"

    revision_envelope = build_host_composer_envelope(initial, REVISION_TEXT)
    revised = session.submit_composer_text(revision_envelope)
    plan = session.activate_action("confirm_prompt")
    terminal = session.activate_action("confirm_plan")

    assert revised["stage"] == "PROMPT_REVIEW"
    assert revised["artifact"]["body"] != initial["artifact"]["body"]
    assert plan["stage"] == "PLAN_REVIEW"
    assert terminal["stage"] == "CLOSED_SUCCESS"
    assert terminal["artifact"] is None
    assert terminal["actions"] == []
    assert session.terminal is True
    assert input_binding.deactivated == 1
    assert input_binding.armed is False
    assert worker.calls == [
        {"operation_id": operation_id, "operation": operation}
        for operation_id, operation in A02_OPERATIONS
    ]
    assert [item["source"] for item in session.envelopes] == [
        "STRUCTURED_ACTION",
        "HOST_COMPOSER_TEXT",
        "STRUCTURED_ACTION",
        "STRUCTURED_ACTION",
    ]
    assert session.envelopes[1] == revision_envelope
    assert [item["action_id"] for item in session.envelopes[2:]] == [
        "confirm_prompt",
        "confirm_plan",
    ]
    assert [event["transition_id"] for event in events] == [
        "A02-T0-CODEX",
        "A02-T1-FOCUS-CODEX",
        "A02-T2-REVISE-CODEX",
        "A02-T3-CODEX",
        "A02-T4-CODEX",
    ]


def test_start_has_no_input_envelope_and_focus_does_not_call_worker(a02_session) -> None:
    session, _model, worker, input_binding, _presentation, events = a02_session

    session.start()
    assert events[0]["envelope"] is None
    assert worker.calls == [{"operation_id": "A02F:0001", "operation": "DRAFT_PROMPT"}]

    session.activate_action("something_else")
    assert len(worker.calls) == 1
    assert session.projection is events[1]["projection"]
    assert input_binding.armed is True


def test_host_text_is_rejected_until_something_else_arms_the_binding(a02_session) -> None:
    session, _model, worker, _input_binding, _presentation, _events = a02_session
    initial = session.start()
    envelope = build_host_composer_envelope(initial, REVISION_TEXT)

    with pytest.raises(H2E3IntegrationError, match="TEXT_OUTSIDE_FREE_RESPONSE_STATE"):
        session.submit_composer_text(envelope)

    assert len(worker.calls) == 1
    assert session.envelopes == []


def test_wrong_session_or_projection_text_is_fail_closed_without_worker_call(a02_session) -> None:
    session, _model, worker, _input_binding, _presentation, _events = a02_session
    initial = session.start()
    session.activate_action("something_else")
    envelope = build_host_composer_envelope(initial, REVISION_TEXT)
    stale = deepcopy(envelope)
    stale["model_revision"] = "stale-revision"

    with pytest.raises(H2E3IntegrationError, match="INVALID_HOST_COMPOSER_ENVELOPE"):
        session.submit_composer_text(stale)

    assert session.free_response_armed is True
    assert len(worker.calls) == 1


def test_duplicate_action_and_callback_after_terminal_are_rejected(a02_session) -> None:
    session, _model, worker, _input_binding, _presentation, _events = a02_session
    initial = session.start()
    session.activate_action("something_else")

    with pytest.raises(H2E3IntegrationError, match="FREE_RESPONSE_SUBMISSION_PENDING"):
        session.activate_action("something_else")

    session.submit_composer_text(build_host_composer_envelope(initial, REVISION_TEXT))
    session.activate_action("confirm_prompt")
    session.activate_action("confirm_plan")
    calls_before = list(worker.calls)
    callback = build_host_composer_envelope(initial, REVISION_TEXT)

    with pytest.raises(H2E3IntegrationError, match="ACTION_AFTER_TERMINAL"):
        session.submit_composer_text(callback)

    assert worker.calls == calls_before


def test_stale_something_else_after_prompt_revision_is_rejected(a02_session) -> None:
    session, _model, worker, _input_binding, _presentation, _events = a02_session
    initial = session.start()
    session.activate_action("something_else")
    session.submit_composer_text(build_host_composer_envelope(initial, REVISION_TEXT))
    session.activate_action("confirm_prompt")

    with pytest.raises(H2E3IntegrationError, match="INVALID_OR_STALE_ACTION:something_else"):
        session.activate_action("something_else")

    assert len(worker.calls) == 5


def test_focus_viewmodel_failure_does_not_arm_input_binding(a02_session) -> None:
    session, _model, worker, input_binding, _presentation, events = a02_session
    session.start()
    session.input_handler = lambda _envelope, _port: {
        "schema_version": "r6o-viewmodel-command-result-1",
        "ok": False,
        "result_type": "ERROR",
        "projection": None,
        "focus_role": None,
        "error": {"code": "INJECTED", "message": "failure"},
    }

    with pytest.raises(H2E3IntegrationError, match="INVALID_FREE_RESPONSE_FOCUS_RESULT"):
        session.activate_action("something_else")

    assert input_binding.armed is False
    assert session.envelopes == []
    assert len(events) == 1
    assert len(worker.calls) == 1


def test_input_binding_focus_failure_does_not_emit_something_else(a02_session) -> None:
    session, _model, worker, input_binding, _presentation, events = a02_session
    input_binding.fail_activation = True
    session.start()

    with pytest.raises(H2E3IntegrationError, match="ACTUAL_COMPOSER_FOCUS_UNVERIFIED"):
        session.activate_action("something_else")

    assert session.envelopes == []
    assert len(events) == 1
    assert len(worker.calls) == 1
    assert session.free_response_armed is False


def test_text_viewmodel_failure_deactivates_binding_and_preserves_projection(a02_session) -> None:
    session, _model, worker, input_binding, presentation, events = a02_session
    initial = session.start()
    session.activate_action("something_else")
    current = session.projection
    session.input_handler = lambda _envelope, _port: {
        "schema_version": "r6o-viewmodel-command-result-1",
        "ok": False,
        "result_type": "ERROR",
        "projection": None,
        "focus_role": None,
        "error": {"code": "INJECTED", "message": "failure"},
    }

    with pytest.raises(H2E3IntegrationError, match="VIEWMODEL_SUBMISSION_FAILED:INJECTED"):
        session.submit_composer_text(build_host_composer_envelope(initial, REVISION_TEXT))

    assert input_binding.deactivated == 1
    assert input_binding.armed is False
    assert session.projection is current
    assert len(worker.calls) == 1
    assert len(presentation.projections) == 1
    assert len(events) == 2


def test_transition_in_progress_is_rejected_before_dispatch(a02_session) -> None:
    session, _model, worker, _input_binding, _presentation, _events = a02_session
    session.start()
    session._busy = True

    with pytest.raises(H2E3IntegrationError, match="TRANSITION_IN_PROGRESS"):
        session.activate_action("something_else")

    assert len(worker.calls) == 1


def test_e3_runner_has_portable_help() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/h2/run_codex_h2_e3.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--case {A02-FULL}" in completed.stdout
    assert "--record" in completed.stdout


def test_e3_runner_rejects_uncommitted_non_evidence_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    git("init", "-q")
    git("config", "user.name", "H2 E3 Test")
    git("config", "user.email", "h2-e3@example.invalid")
    (repo / "production.py").write_text("VALUE = 1\n", encoding="utf-8")
    git("add", "production.py")
    git("commit", "-q", "-m", "accepted e2")
    accepted_e2 = git("rev-parse", "HEAD")
    git("branch", "-M", e3_runner.EXPECTED_BRANCH)
    (repo / "e3.py").write_text("VALUE = 2\n", encoding="utf-8")
    git("add", "e3.py")
    git("commit", "-q", "-m", "e3 freeze")
    freeze_head = git("rev-parse", "HEAD")
    freeze_tree = git("rev-parse", "HEAD^{tree}")
    manifest = repo / "r6o_evidence" / "H2-E3" / "code-freeze.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "r6o-h2-e3-code-freeze-1",
                "branch": e3_runner.EXPECTED_BRANCH,
                "accepted_e2_head": accepted_e2,
                "code_freeze_head": freeze_head,
                "code_freeze_tree": freeze_tree,
            }
        ),
        encoding="utf-8",
    )
    git("add", "r6o_evidence/H2-E3/code-freeze.json")
    git("commit", "-q", "-m", "record freeze")

    monkeypatch.setattr(e3_runner, "ROOT", repo)
    monkeypatch.setattr(e3_runner, "FREEZE_MANIFEST", manifest)
    monkeypatch.setattr(e3_runner, "ACCEPTED_E2_HEAD", accepted_e2)
    monkeypatch.setattr(e3_runner, "_verify_fixture_identity", lambda: {})
    checkout = e3_runner.verify_checkout()
    assert checkout["code_freeze_head"] == freeze_head
    assert checkout["code_freeze_tree"] == freeze_tree

    (repo / "e3.py").write_text("VALUE = 3\n", encoding="utf-8")
    with pytest.raises(H2E3IntegrationError, match="UNCOMMITTED_NON_E3_EVIDENCE_CHANGES"):
        e3_runner.verify_checkout()
