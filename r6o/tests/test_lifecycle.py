from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import hashlib
from dataclasses import replace

from r6o.contracts_validation import make_validator
from r6o.model_binding.base import HandoffReceipt
from r6o.model_binding.handoff_store import FileHandoffStore, canonical_envelope_bytes
from r6o.tests.helpers import artifact, state
from r6o.viewmodel.lifecycle import (
    build_close_result,
    build_handoff_envelope,
    coordinate_close,
    derive_disposition,
)

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


def _schema(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _terminal():
    return state(revision="rev-final", stage="CLOSED_SUCCESS", result_body="Final deterministic result.")


class RecordingDurableStore:
    def __init__(self) -> None:
        self.envelopes = {}

    def persist(self, envelope):
        payload = canonical_envelope_bytes(envelope)
        self.envelopes[envelope["handoff_id"]] = envelope
        return HandoffReceipt(
            handoff_ref=f"test-durable:{envelope['handoff_id']}",
            handoff_id=envelope["handoff_id"],
            digest=hashlib.sha256(payload).hexdigest(),
            durable=True,
        )


def test_handoff_envelope_and_retry_ids_are_deterministic() -> None:
    first = build_handoff_envelope(_terminal(), [artifact()])
    second = build_handoff_envelope(_terminal(), [artifact()])
    assert first == second
    make_validator(_schema("handoff_envelope.schema.json")).validate(first)
    store = RecordingDurableStore()
    close_a = coordinate_close(_terminal(), [artifact()], store)
    close_b = coordinate_close(_terminal(), [artifact()], store)
    assert close_a == close_b
    make_validator(_schema("close_result.schema.json")).validate(close_a)


def test_host_handoff_without_durable_receipt_is_impossible() -> None:
    with pytest.raises(ValueError):
        build_close_result(_terminal())
    with pytest.raises(TypeError):
        build_close_result(
            _terminal(),
            receipt=HandoffReceipt("forged:h", "h", "0" * 64, True),
        )


def test_persist_failure_produces_no_host_handoff_result() -> None:
    class FailingStore:
        def persist(self, envelope):
            raise OSError("disk unavailable")

    with pytest.raises(OSError, match="disk unavailable"):
        coordinate_close(_terminal(), [artifact()], FailingStore())


def test_unverified_or_mismatched_store_receipt_is_rejected() -> None:
    class LyingStore:
        def persist(self, envelope):
            return HandoffReceipt("remote:h", envelope["handoff_id"], "0" * 64, True)

    with pytest.raises(ValueError, match="verify durable persistence"):
        coordinate_close(_terminal(), [artifact()], LyingStore())


def test_handoff_rejects_stale_extra_and_unauthorized_artifacts() -> None:
    with pytest.raises(ValueError, match="Model-authorized"):
        build_handoff_envelope(_terminal(), [artifact("stale")])
    with pytest.raises(ValueError, match="Model-authorized"):
        build_handoff_envelope(_terminal(), [artifact(), artifact(body="extra")])


def test_file_store_flushes_fsyncs_replaces_and_returns_receipt(tmp_path, monkeypatch) -> None:
    calls = {"fsync": 0, "replace": 0}
    real_fsync = os.fsync
    real_replace = os.replace

    def recording_fsync(descriptor):
        calls["fsync"] += 1
        return real_fsync(descriptor)

    def recording_replace(source, destination):
        calls["replace"] += 1
        return real_replace(source, destination)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "replace", recording_replace)
    envelope = build_handoff_envelope(_terminal(), [artifact()])
    receipt = FileHandoffStore(tmp_path).persist(envelope)
    assert receipt.durable is True
    assert receipt.handoff_id == envelope["handoff_id"]
    assert len(receipt.digest) == 64
    assert calls["fsync"] >= 1
    if os.name != "nt":
        assert calls["replace"] == 1
    assert json.loads(Path(receipt.handoff_ref).read_text(encoding="utf-8")) == envelope
    assert not list(tmp_path.glob("*.tmp"))


def test_in_memory_and_file_stores_share_lifecycle_contract(tmp_path) -> None:
    memory = coordinate_close(_terminal(), [artifact()], RecordingDurableStore())
    filesystem = coordinate_close(_terminal(), [artifact()], FileHandoffStore(tmp_path))
    assert memory["result_id"] == filesystem["result_id"]
    assert memory["disposition"] == filesystem["disposition"] == "HOST_HANDOFF"


def test_result_identity_is_bound_to_session() -> None:
    first = build_close_result(state(stage="CLOSED_CANCELLED", artifact_revision=None, session_id="I-1"))
    second = build_close_result(state(stage="CLOSED_CANCELLED", artifact_revision=None, session_id="I-2"))
    assert first["result_id"] != second["result_id"]


def test_model_lifecycle_is_disposition_authority() -> None:
    terminal = _terminal()
    contradictory = replace(
        terminal,
        lifecycle=replace(terminal.lifecycle, terminal_disposition="CANCELLED", handoff_ready=True),
    )
    with pytest.raises(ValueError, match="contradicts"):
        derive_disposition(contradictory)


def test_close_stage_rules_are_explicit() -> None:
    assert derive_disposition(state(stage="PROMPT_REVIEW")) == "PDLT_RESUME"
    assert derive_disposition(state(stage="CLOSED_CANCELLED", artifact_revision=None)) == "CANCELLED"
    with pytest.raises(ValueError):
        derive_disposition(state(stage="EXECUTION_READY", artifact_revision=None))
    cancelled = build_close_result(state(stage="CLOSED_CANCELLED", artifact_revision=None))
    assert cancelled["handoff_ref"] is None
    with pytest.raises(ValueError):
        build_handoff_envelope(state(stage="EXECUTION_READY", artifact_revision=None), [artifact()])


def test_file_store_rejects_path_traversal_identifier(tmp_path) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        FileHandoffStore(tmp_path).persist({"handoff_id": "../../escape"})
