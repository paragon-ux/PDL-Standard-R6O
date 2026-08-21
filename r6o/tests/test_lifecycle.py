from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from r6o.model_binding.base import ArtifactSnapshot
from r6o.viewmodel.lifecycle import build_close_result, build_handoff_envelope, write_handoff

HANDOFF_SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "handoff_envelope.schema.json").read_text(encoding="utf-8"))
CLOSE_SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "close_result.schema.json").read_text(encoding="utf-8"))


def _terminal_state(stage: str = "CLOSED_SUCCESS") -> dict:
    return {
        "stage": stage,
        "instance_id": "I-1",
        "workspace_id": "W-1",
        "revision": "rev-final",
        "result": "Final deterministic result." if stage == "CLOSED_SUCCESS" else None,
    }


def _artifacts() -> list[ArtifactSnapshot]:
    return [
        ArtifactSnapshot("prompt:P1", "P1", "prompt", "Authoritative Prompt (PDL.md)", "PROMPT BODY"),
        ArtifactSnapshot("plan:R1", "R1", "plan", "Authoritative Response Plan (PDL.md)", "PLAN BODY"),
    ]


def test_handoff_envelope_is_mechanical_and_deterministic() -> None:
    a = build_handoff_envelope(_terminal_state(), _artifacts())
    b = build_handoff_envelope(_terminal_state(), _artifacts())
    Draft202012Validator(HANDOFF_SCHEMA).validate(a)
    assert a["disposition"] == "HOST_HANDOFF"
    assert a["execution_request"] == {"result_body": "Final deterministic result."}
    assert [x["artifact_kind"] for x in a["artifacts"]] == ["prompt", "plan"]
    stripped = lambda env: {k: v for k, v in env.items() if k != "handoff_id"}
    assert stripped(a) == stripped(b)


def test_handoff_persisted_before_close_result(tmp_path: Path) -> None:
    envelope = build_handoff_envelope(_terminal_state(), _artifacts())
    handoff_path = tmp_path / "handoff.json"
    ref = write_handoff(handoff_path, envelope)
    close = build_close_result(_terminal_state(), handoff_ref=ref)
    Draft202012Validator(CLOSE_SCHEMA).validate(close)
    assert close["disposition"] == "HOST_HANDOFF"
    assert handoff_path.is_file(), "handoff must be durable before CloseResult is observable"
    persisted = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert persisted["handoff_id"] == envelope["handoff_id"]


def test_cancelled_has_no_handoff() -> None:
    close = build_close_result(_terminal_state("CLOSED_CANCELLED"))
    Draft202012Validator(CLOSE_SCHEMA).validate(close)
    assert close["disposition"] == "CANCELLED"
    try:
        build_handoff_envelope(_terminal_state("CLOSED_CANCELLED"), _artifacts())
    except ValueError:
        return
    raise AssertionError("handoff must not be produced for CANCELLED disposition")
