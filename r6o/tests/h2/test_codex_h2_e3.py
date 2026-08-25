from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from r6o.h2.codex_e3 import (
    AttachedCodexE3Presentation,
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


def test_t1_recorder_failure_rolls_back_semantic_capture_eligibility(a02_session) -> None:
    session, _model, worker, input_binding, _presentation, _events = a02_session
    session.start()
    session.on_transition = lambda event: (_ for _ in ()).throw(
        H2E3IntegrationError("INJECTED_T1_RECORDER_FAILURE")
    )

    with pytest.raises(H2E3IntegrationError, match="INJECTED_T1_RECORDER_FAILURE"):
        session.activate_action("something_else")

    assert session.free_response_armed is False
    assert session.envelopes == []
    assert input_binding.armed is True
    assert len(worker.calls) == 1


def test_e3_terminal_focus_waits_for_observable_ready_state() -> None:
    focus_states = iter([False, True])
    foreground_states = iter([0, 101])
    calls: list[str] = []

    class Composer:
        def set_focus(self) -> None:
            calls.append("focus")

        def has_keyboard_focus(self) -> bool:
            return next(focus_states)

    sidecar = SimpleNamespace(
        render=lambda projection: False,
        dismiss_terminal=lambda: calls.append("dismiss"),
    )
    binding = SimpleNamespace(
        sidecar=sidecar,
        sidecar_hwnd=303,
        host_hwnd=101,
        refresh_controls=lambda: SimpleNamespace(composer=Composer()),
        native=SimpleNamespace(
            foreground=lambda: next(foreground_states),
            is_visible=lambda _hwnd: False,
        ),
    )
    presentation = AttachedCodexE3Presentation(binding, SimpleNamespace())

    result = presentation.present({"stage": "CLOSED_SUCCESS"})

    assert calls == ["dismiss", "focus"]
    assert result["focus_return"] == {
        "sidecar_visible": False,
        "composer_keyboard_focus": True,
        "foreground_hwnd": 101,
        "expected_foreground_hwnd": 101,
    }
    with pytest.raises(H2E3IntegrationError, match="TERMINAL_CLOSE_NOT_EXACTLY_ONCE"):
        presentation.present({"stage": "CLOSED_SUCCESS"})
    with pytest.raises(H2E3IntegrationError, match="ACTIVE_PROJECTION_AFTER_TERMINAL"):
        presentation.present({"stage": "PROMPT_REVIEW"})


def test_t1_evidence_uses_pre_handoff_empty_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    safe = {
        "composer": {"empty": True},
        "conversation": {"fresh": True, "visible_turn_group_count": 0},
    }
    worker = SimpleNamespace(calls=[])

    def capture(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"capture")

    binding = SimpleNamespace(sidecar=SimpleNamespace(capture=capture))
    monkeypatch.setattr(e3_runner, "ROOT", tmp_path)
    recorder = e3_runner.EvidenceRecorder(tmp_path, worker, binding)
    monkeypatch.setattr(e3_runner, "_host_session_observation", lambda _binding: safe)
    recorder.prepare_free_response_handoff()
    monkeypatch.setattr(
        e3_runner,
        "_host_session_observation",
        lambda _binding: (_ for _ in ()).throw(AssertionError("post-handoff reread raced typing")),
    )
    event = {
        "transition_id": "A02-T1-FOCUS-CODEX",
        "state_id": "A02-S1",
        "projection": {
            "stage": "PROMPT_REVIEW",
            "projection_id": "projection-1",
            "artifact": {"artifact_kind": "prompt", "artifact_ref": "prompt-1", "body": "body"},
            "lifecycle": {},
        },
        "presentation": {"focus_owner": "ACTUAL_CODEX_COMPOSER"},
        "envelope": {
            "source": "STRUCTURED_ACTION",
            "action_id": "something_else",
            "text": None,
        },
    }

    recorder(event)

    assert recorder.transitions[0]["host_session_observation"] == safe


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


def test_initial_host_preflight_failure_is_actionable() -> None:
    observation = {
        "composer": {"empty": False},
        "conversation": {"fresh": False},
    }
    with pytest.raises(
        H2E3IntegrationError,
        match="INITIAL_HOST_NOT_READY:OPEN_FRESH_NEW_CHAT_AND_VERIFY_EMPTY_COMPOSER",
    ):
        e3_runner._require_safe_host_session(observation, phase="INITIAL")


def test_attempt_ledger_appends_new_freeze_without_mutating_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = tmp_path / "r6o_evidence" / "H2-E3" / "actual-host"
    evidence.mkdir(parents=True)
    historical = [
        {
            "attempt": 1,
            "status": "FAIL",
            "failure": "OLD_FAILURE",
            "code_freeze_head": "old-head",
            "code_freeze_tree": "old-tree",
        }
    ]
    (evidence / "live-attempts.json").write_text(json.dumps(historical), encoding="utf-8")
    monkeypatch.setattr(e3_runner, "ROOT", tmp_path)
    checkout = {
        "head": "new-evidence-head",
        "tree": "new-evidence-tree",
        "code_freeze_head": "repair-head",
        "code_freeze_tree": "repair-tree",
    }

    path, attempts, count, attempt_dir = e3_runner._start_attempt(evidence, checkout)

    assert attempts[0] == historical[0]
    assert count == 2
    assert attempt_dir == evidence / "attempt-0002"
    assert attempts[1]["code_freeze_head"] == "repair-head"
    assert attempts[1]["code_freeze_tree"] == "repair-tree"
    assert attempts[1]["evidence_path"].endswith("actual-host/attempt-0002")
    e3_runner._finish_attempt(
        path,
        attempts,
        status="FAIL",
        failure="PRIMARY_FAILURE",
        cleanup_failures=["INPUT_BINDING_STOP:HOST_INPUT_HOOK_STOP_TIMEOUT"],
    )
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted[0] == historical[0]
    assert persisted[1]["cleanup_failures"] == [
        "INPUT_BINDING_STOP:HOST_INPUT_HOOK_STOP_TIMEOUT"
    ]


def test_old_freeze_attempts_and_pass_are_preserved_only_as_historical() -> None:
    evidence = ROOT / "r6o_evidence" / "H2-E3" / "actual-host"
    attempts = json.loads((evidence / "live-attempts.json").read_text(encoding="utf-8"))
    assert len(attempts) == 9
    assert [item["attempt"] for item in attempts] == list(range(1, 10))
    assert [item["status"] for item in attempts] == [
        "RUNNING",
        "RUNNING",
        "FAIL",
        "FAIL",
        "FAIL",
        "FAIL",
        "FAIL",
        "FAIL",
        "H2_E3_A02_FULL_PASS",
    ]
    assert all(
        item["code_freeze_head"] == "858b0b52844761314456c64cd065549a23627073"
        and item["code_freeze_tree"] == "0c78427a66f90e363df808be8d32b10aaf7b74e2"
        for item in attempts
    )
    index = json.loads(
        (evidence / "historical-evidence-index.json").read_text(encoding="utf-8")
    )
    assert index["attempt"] == 9
    assert index["status"] == "HISTORICAL_OLD_FREEZE_PASS"
    assert index["qualifies_current_freeze"] is False
    for key in ("qualification", "transitions"):
        path = ROOT / index[key]["path"]
        assert path.is_file()
        canonical_bytes = path.read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(canonical_bytes).hexdigest() == index[key]["sha256"]


def test_cleanup_attempts_every_resource_after_each_prior_failure() -> None:
    calls: list[str] = []

    def fail(label: str):
        def callback() -> None:
            calls.append(label)
            raise RuntimeError(label)

        return callback

    failures = e3_runner._close_run_resources(
        input_binding=SimpleNamespace(
            abort_handoff=fail("abort"),
            stop=fail("stop"),
        ),
        host=SimpleNamespace(close=fail("host")),
        model=SimpleNamespace(close=fail("model")),
        temporary=SimpleNamespace(cleanup=fail("temporary")),
        handoff_started=True,
    )

    assert calls == ["abort", "stop", "host", "model", "temporary"]
    assert [item.split(":", 1)[0] for item in failures] == [
        "INPUT_HANDOFF_ABORT",
        "INPUT_BINDING_STOP",
        "HOST_CLOSE",
        "MODEL_CLOSE",
        "TEMPORARY_CLEANUP",
    ]


def test_e3_cleanup_force_removes_stalled_accepted_d2_router_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    router = SimpleNamespace(_hook=456)
    host = SimpleNamespace(focus_router=router)
    fake_user32 = SimpleNamespace(
        UnhookWindowsHookEx=lambda handle: calls.append(int(handle.value)) or True
    )
    monkeypatch.setattr(e3_runner.ctypes, "windll", SimpleNamespace(user32=fake_user32))

    e3_runner._force_remove_host_router_hook(host)

    assert calls == [456]
    assert router._hook == 0


def test_readme_has_fresh_chat_preflight_and_complete_rerun_procedure() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    assert "--output r6o_evidence\\H2-E3\\actual-host\\preflight-reset.json" in readme
    assert "INITIAL_HOST_NOT_READY:OPEN_FRESH_NEW_CHAT_AND_VERIFY_EMPTY_COMPOSER" in readme
    assert "If an attempt fails" in readme
    assert "never resume a prior failed host session" in readme
    assert "No fixed delay or undocumented pause" in normalized
