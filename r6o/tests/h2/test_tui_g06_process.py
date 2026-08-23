from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import r6o.views.tui.app as tui_module
from r6o.views.tui.app import TerminalInput, TerminalReviewApp, TerminalViewClosed
import scripts.h2.verify_tui_g06 as verifier_module
from scripts.h2.verify_tui_g06 import (
    PLAN_SHA256,
    PROMPT_SHA256,
    RESULT_SHA256,
    normalized_text_sha256,
    run_qualification,
)


def test_public_tui_g06_process_reaches_closed_success(
    tmp_path: Path,
    baseline_repo: Path,
) -> None:
    evidence = tmp_path / "evidence"
    report = run_qualification(baseline_repo, evidence_dir=evidence)
    assert report["status"] == "MECHANICAL_PASS_PENDING_HUMAN"
    assert report["driver"] == "PUBLIC_PROCESS_STDIN_KEYBOARD_BOUNDARY"
    assert report["observed_screens"] == ["PROMPT REVIEW", "PLAN REVIEW"]
    assert report["terminal_behavior"] == "RESTORE_AND_RETURN_WITHOUT_TERMINAL_REVIEW_SCREEN"
    assert report["presentation_reference"] == {
        "path": "docs/h2/TUI-REFERENCE-v4-2026-08-22.md",
        "normalized_text_sha256": "af74ce9fa9b09b8f7e4e555e9213c9e6a0574897718749c872f015da51c331b5",
    }
    assert report["observed_operation_ids"] == [f"G06:000{index}" for index in range(1, 6)]
    assert report["final_stage"] == "CLOSED_SUCCESS"
    assert report["prompt_body_sha256"] == PROMPT_SHA256
    assert report["plan_body_sha256"] == PLAN_SHA256
    assert report["result_body_sha256"] == RESULT_SHA256
    assert report["oracle_inventory_unchanged"] is True

    transitions = [
        json.loads(line)
        for line in (evidence / "state-transitions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["transition_id"] for item in transitions] == [
        "G06-T0-TUI",
        "G06-T1-TUI",
        "G06-T2-TUI",
    ]
    assert [item["stage"] for item in transitions] == [
        "PROMPT_REVIEW",
        "PLAN_REVIEW",
        "CLOSED_SUCCESS",
    ]


def test_terminal_recording_contains_real_input_and_ordered_screens(
    tmp_path: Path,
    baseline_repo: Path,
) -> None:
    evidence = tmp_path / "evidence"
    run_qualification(baseline_repo, evidence_dir=evidence)
    lines = (evidence / "tui-g06.cast").read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    events = [json.loads(line) for line in lines[1:]]
    assert header["version"] == 2
    assert [event[2] for event in events if event[1] == "i"] == ["\r", "\r"]
    rendered = "".join(event[2] for event in events if event[1] == "o")
    positions = [rendered.index(marker) for marker in ("PDLt · PROMPT REVIEW", "PDLt · PLAN REVIEW")]
    assert positions == sorted(positions)
    assert "PDLt REVIEW" not in rendered
    assert "\nACTIONS\n" not in rendered
    assert "[Enter]" not in rendered
    assert "PDLt · REVIEW COMPLETE" not in rendered
    assert "Review Options" in rendered
    assert "ACTIVE" in rendered
    assert "Enter  Select" in rendered


def test_tui_view_does_not_import_protected_runtime_or_controller_authority() -> None:
    view_source = (Path(__file__).resolve().parents[2] / "views" / "tui" / "app.py").read_text(
        encoding="utf-8"
    ).lower()
    for forbidden in (
        "mechanicalcontroller",
        "mechanical_controller",
        "sessionengine",
        "session_engine",
        "workeradapter",
        "worker_adapter",
        "reviewdecision",
        "review_decision",
        "localruntimemodelbinding",
        "workspace_root",
    ):
        assert forbidden not in view_source


def test_qualification_rejects_evidence_directory_inside_frozen_oracle(
    baseline_repo: Path,
) -> None:
    forbidden = baseline_repo / "h2-b1-evidence-forbidden"
    with pytest.raises(ValueError, match="outside the frozen R6S baseline"):
        run_qualification(baseline_repo, evidence_dir=forbidden)
    assert not forbidden.exists()


def projection(stage: str = "PROMPT_REVIEW") -> dict[str, object]:
    actions = [
        {"action_id": "confirm_prompt", "ordinal": 1, "label": "Confirm prompt", "enabled": True},
        {"action_id": "change_task", "ordinal": 2, "label": "Change the task", "enabled": True},
        {"action_id": "change_approach", "ordinal": 3, "label": "Change approach", "enabled": True},
        {"action_id": "something_else", "ordinal": 4, "label": "Something else...", "enabled": True},
    ]
    return {
        "stage": stage,
        "session_id": "I-test",
        "model_revision": "rev-1",
        "projection_id": "projection-1",
        "artifact": {
            "title": "Authoritative Prompt (PDL.md)",
            "body": "A projection-driven artifact body.",
        }
        if stage not in {"CLOSED_SUCCESS", "CLOSED_CANCELLED"}
        else None,
        "actions": actions if stage not in {"CLOSED_SUCCESS", "CLOSED_CANCELLED"} else [],
    }


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        ("\x1b[A", "UP"),
        ("\x1b[B", "DOWN"),
        ("\x1b[Z", "PREVIOUS"),
        ("\x1b[5~", "PAGE_UP"),
        ("\x1b[6~", "PAGE_DOWN"),
        ("\x1b[15~", "REFRESH"),
        ("\x1b[", "UNKNOWN"),
        ("\x1b[1", "UNKNOWN"),
        ("\x11", "CLOSE"),
        ("\x7f", "BACKSPACE"),
    ],
)
def test_keyboard_contract(sequence: str, expected: str) -> None:
    assert TerminalInput(io.StringIO(sequence)).read().name == expected


def test_stream_input_preserves_non_ascii_review_text() -> None:
    input_stream = io.StringIO("é")
    event = TerminalInput(input_stream).read()
    assert event.name == "TEXT"
    assert event.text == "é"


def test_reference_identity_is_stable_across_git_line_endings(tmp_path: Path) -> None:
    lf = tmp_path / "lf.md"
    crlf = tmp_path / "crlf.md"
    lf.write_bytes(b"one\ntwo\n")
    crlf.write_bytes(b"one\r\ntwo\r\n")
    assert normalized_text_sha256(lf) == normalized_text_sha256(crlf)


def test_reference_v4_normal_frame_has_single_hierarchy_and_fixed_footer() -> None:
    output = io.StringIO()
    app = TerminalReviewApp(object(), "I-test", stdin=io.StringIO(), stdout=output)
    app._render(projection())
    rendered = output.getvalue()
    assert rendered.count("PDLt · PROMPT REVIEW") == 1
    assert "ACTIVE" in rendered
    assert "Authoritative Prompt (PDL.md)" in rendered
    assert "Review Options" in rendered
    assert "> 1  Confirm prompt" in rendered
    assert "Enter  Select" in rendered and "F5  Refresh" in rendered and "Ctrl+Q  Close" in rendered
    assert "PDLt REVIEW" not in rendered
    assert "\nACTIONS\n" not in rendered
    assert "[Enter]" not in rendered


def test_narrow_ascii_fallback_keeps_every_projected_action_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    class AsciiOutput(io.StringIO):
        encoding = "ascii"

        def write(self, value: str) -> int:
            value.encode("ascii", errors="strict")
            return super().write(value)

    output = AsciiOutput()
    app = TerminalReviewApp(object(), "I-test", stdin=io.StringIO(), stdout=output)
    monkeypatch.setattr(app, "_terminal_size", lambda: (40, 20))
    app._render(projection())
    rendered = output.getvalue()
    assert "+- PDLt" in rendered
    assert "Up/Down" in rendered
    for label in ("Confirm prompt", "Change the task", "Change approach", "Something else..."):
        assert label in rendered

    long_projection = projection()
    long_projection["actions"][3]["label"] = "Something else with a deliberately long projection-driven action label"
    output.seek(0)
    output.truncate(0)
    app._render(long_projection)
    wrapped = output.getvalue()
    assert "   4  Something else with a" in wrapped
    assert "      deliberately long projection-" in wrapped
    assert "      driven action label" in wrapped


def test_dirty_frozen_oracle_is_rejected_before_qualification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier_module, "git_status", lambda _repo: "?? injected.py")
    with pytest.raises(RuntimeError, match="frozen oracle working tree is not clean"):
        verifier_module.require_clean_oracle(Path("oracle"))


def test_terminal_projection_returns_without_rendering_completion_screen() -> None:
    output = io.StringIO()
    closed = projection("CLOSED_SUCCESS")
    result = TerminalReviewApp(object(), "I-test", stdin=io.StringIO(), stdout=output).run(closed)
    assert result is closed
    assert output.getvalue() == ""


def test_something_else_focus_then_enter_submits_exactly_one_tui_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelopes: list[dict[str, object]] = []
    closed = projection("CLOSED_SUCCESS")

    def handle(envelope: dict[str, object], _port: object) -> dict[str, object]:
        envelopes.append(envelope)
        if envelope["source"] == "STRUCTURED_ACTION":
            return {"result_type": "FOCUS_REQUIRED", "ok": True, "projection": None}
        return {"result_type": "REVISION", "ok": True, "projection": closed}

    monkeypatch.setattr(tui_module, "handle_input", handle)
    monkeypatch.setattr(tui_module, "validate_command_result", lambda result: None)
    keys = io.StringIO("\t\t\t\rUse data engineers.\r")
    result = TerminalReviewApp(object(), "I-test", stdin=keys, stdout=io.StringIO()).run(projection())
    assert result is closed
    assert len(envelopes) == 2
    assert envelopes[0]["source"] == "STRUCTURED_ACTION"
    assert envelopes[0]["action_id"] == "something_else"
    assert envelopes[0]["text"] is None
    assert envelopes[1]["source"] == "TUI_TEXT"
    assert envelopes[1]["text"] == "Use data engineers."
    assert envelopes[1]["action_id"] is None
    assert envelopes[1]["projection_id"] is None


@pytest.mark.parametrize("after_focus", ["\x1b\x11", "\r\x11"])
def test_free_response_escape_or_empty_enter_never_submits_text(
    monkeypatch: pytest.MonkeyPatch,
    after_focus: str,
) -> None:
    envelopes: list[dict[str, object]] = []

    def handle(envelope: dict[str, object], _port: object) -> dict[str, object]:
        envelopes.append(envelope)
        return {"result_type": "FOCUS_REQUIRED", "ok": True, "projection": None}

    monkeypatch.setattr(tui_module, "handle_input", handle)
    monkeypatch.setattr(tui_module, "validate_command_result", lambda result: None)
    keys = io.StringIO("\t\t\t\r" + after_focus)
    with pytest.raises(TerminalViewClosed):
        TerminalReviewApp(object(), "I-test", stdin=keys, stdout=io.StringIO()).run(projection())
    assert len(envelopes) == 1
    assert envelopes[0]["source"] == "STRUCTURED_ACTION"
