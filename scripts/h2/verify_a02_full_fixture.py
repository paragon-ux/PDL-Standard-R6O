from __future__ import annotations

"""Record and verify the H2-A2 deterministic A02-FULL fixture."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIXTURE_DIR = ROOT / "fixtures" / "r6o2" / "a02-full"
RECORDED_CASE_PATH = FIXTURE_DIR / "recorded-case.json"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
CANONICAL_MESSAGES_PATH = ROOT / "r6o" / "contracts" / "canonical_review_messages.json"

FROZEN_ORACLE_COMMIT = "60d982f3328b45a351879d67dc4bb525172b65fd"
FROZEN_ORACLE_TREE = "b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6"
APPROVED_RECORDING_MODEL = "gpt-5.6-sol"

ACTIVATION_TEXT = "Use $confirm-with-pseudocode to compare Kafka and RabbitMQ for event delivery."
REVISION_TEXT = "This is not confirmed. The audience should be data engineers, not backend engineers."

EXPECTED_OPERATIONS = (
    ("A02F:0001", "DRAFT_PROMPT"),
    ("A02F:0002", "INTERPRET_PROMPT_REVIEW"),
    ("A02F:0003", "REVISE_PROMPT"),
    ("A02F:0004", "INTERPRET_PROMPT_REVIEW"),
    ("A02F:0005", "DRAFT_PLAN"),
    ("A02F:0006", "INTERPRET_PLAN_REVIEW"),
    ("A02F:0007", "EXECUTE"),
)

EXPECTED_MILESTONES = (
    ("A02-S1", "PROMPT_REVIEW_INITIAL", "PROMPT_REVIEW", ("A02F:0001",)),
    ("A02-S2", "PROMPT_REVIEW_REVISED", "PROMPT_REVIEW", ("A02F:0002", "A02F:0003")),
    ("A02-S3", "PLAN_REVIEW", "PLAN_REVIEW", ("A02F:0004", "A02F:0005")),
    ("A02-S4", "CLOSED_SUCCESS", "CLOSED_SUCCESS", ("A02F:0006", "A02F:0007")),
)

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
RECORDED_CASE_KEYS = {"schema_version", "case_id", "entries"}
RECORDED_ENTRY_KEYS = {
    "operation_id",
    "operation",
    "prompt_sha256",
    "response",
    "response_sha256",
    "recording_metadata",
}
MANIFEST_KEYS = {
    "schema_version",
    "case_id",
    "status",
    "recording_process",
    "frozen_r6s_oracle",
    "semantic_inputs",
    "expected_milestones",
    "expected_artifact_hashes",
    "worker_operations",
    "recorded_case_sha256",
}
RECORDING_PROCESS_KEYS = {
    "process_version",
    "recorded_at_utc",
    "worker",
    "requested_model",
    "observed_model",
    "codex_cli_version",
    "sandbox_mode",
    "approval_mode",
    "dangerous_bypass",
    "ambient_llm_fallback",
}
MILESTONE_KEYS = {
    "state_id",
    "state_name",
    "stage",
    "after_operation_ids",
    "artifact_kind",
    "artifact_ref",
    "artifact_revision_relation",
    "artifact_body_sha256",
}
ARTIFACT_HASH_KEYS = {
    "initial_prompt_body_sha256",
    "revised_prompt_body_sha256",
    "plan_body_sha256",
    "final_result_body_sha256",
}
WORKER_OPERATION_KEYS = {
    "operation_id",
    "operation",
    "prompt_sha256",
    "response_sha256",
}
RECORDING_METADATA_KEYS = {
    "worker",
    "model",
    "mode",
    "sandbox_mode",
    "approval_mode",
    "codex_cli_version",
    "json_mode",
    "usage_source",
    "usage_exact",
    "usage",
}
USAGE_KEYS = {
    "codex_cli_input_tokens",
    "codex_cli_cached_input_tokens",
    "codex_cli_output_tokens",
}


class ReplayMissError(RuntimeError):
    """The deterministic replay did not match the next frozen operation."""


@dataclass(frozen=True)
class WorkerResult:
    text: str
    metadata: dict[str, Any]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError(f"{label} must be a JSON object")
    return value


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise AssertionError(f"{label} fields differ: expected {sorted(expected)}, got {sorted(value)}")


def require_sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise AssertionError(f"{label} must be a lowercase SHA-256 hex digest")


def resolve_baseline_repo(value: str | Path | None = None) -> Path:
    candidate = value or os.environ.get("PDL_R6S_BASELINE_REPO") or (ROOT.parent / "PDL-Standard-REPL-Harness")
    resolved = Path(candidate).resolve()
    if not resolved.is_dir():
        raise RuntimeError(f"frozen baseline not found: {resolved}")
    return resolved


def git_value(repo: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        raise RuntimeError((process.stdout + process.stderr).strip())
    return process.stdout.strip()


def verify_oracle_identity(baseline_repo: Path) -> None:
    commit = git_value(baseline_repo, "rev-parse", "HEAD")
    tree = git_value(baseline_repo, "rev-parse", "HEAD^{tree}")
    if commit != FROZEN_ORACLE_COMMIT or tree != FROZEN_ORACLE_TREE:
        raise RuntimeError(
            "frozen oracle identity mismatch: "
            f"expected {FROZEN_ORACLE_COMMIT}/{FROZEN_ORACLE_TREE}, got {commit}/{tree}"
        )


def physical_inventory(root: Path) -> dict[str, tuple[int, int, str]]:
    inventory: dict[str, tuple[int, int, str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        stat = path.stat()
        inventory[relative.as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return inventory


def canonical_inputs() -> dict[str, str]:
    messages = load_json(CANONICAL_MESSAGES_PATH)
    return {
        "activation_text": ACTIVATION_TEXT,
        "free_response_revision_text": REVISION_TEXT,
        "revised_prompt_confirmation_text": messages["prompt_confirm"],
        "plan_confirmation_text": messages["plan_confirm"],
    }


def action_envelope(binding: Any, session_id: str, action_id: str) -> dict[str, Any]:
    from r6o.viewmodel.projection import build_focus_projection_from_port

    projection = build_focus_projection_from_port(binding, session_id)
    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": session_id,
        "source": "STRUCTURED_ACTION",
        "model_revision": projection["model_revision"],
        "text": None,
        "action_id": action_id,
        "projection_id": projection["projection_id"],
    }


def text_envelope(binding: Any, session_id: str, text: str) -> dict[str, Any]:
    from r6o.viewmodel.projection import build_focus_projection_from_port

    projection = build_focus_projection_from_port(binding, session_id)
    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": session_id,
        "source": "HOST_COMPOSER_TEXT",
        "model_revision": projection["model_revision"],
        "text": text,
        "action_id": None,
        "projection_id": None,
    }


class StrictReplayWorker:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.entries = entries
        self.index = 0
        self.consumed_operation_ids: list[str] = []

    def call(self, request: Any) -> WorkerResult:
        if self.index >= len(self.entries):
            raise ReplayMissError(f"replay exhausted at operation {request.operation}")
        entry = self.entries[self.index]
        prompt_hash = sha256_text(request.prompt)
        if request.operation != entry["operation"] or prompt_hash != entry["prompt_sha256"]:
            raise ReplayMissError(
                "replay mismatch at "
                f"{entry['operation_id']}: expected {entry['operation']} prompt={entry['prompt_sha256']}, "
                f"got {request.operation} prompt={prompt_hash}"
            )
        self.index += 1
        self.consumed_operation_ids.append(entry["operation_id"])
        return WorkerResult(
            entry["response"],
            {"source": entry["operation_id"], "fixture": "A02-FULL"},
        )

    def assert_fully_consumed(self) -> None:
        if self.index != len(self.entries):
            remaining = [entry["operation_id"] for entry in self.entries[self.index :]]
            raise ReplayMissError(f"unconsumed fixture operations: {remaining}")


class RecordingWorker:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.entries: list[dict[str, Any]] = []

    def call(self, request: Any) -> WorkerResult:
        index = len(self.entries)
        if index >= len(EXPECTED_OPERATIONS):
            raise RuntimeError(f"unexpected extra recording operation: {request.operation}")
        operation_id, expected_operation = EXPECTED_OPERATIONS[index]
        if request.operation != expected_operation:
            raise RuntimeError(
                f"recording order mismatch at {operation_id}: expected {expected_operation}, got {request.operation}"
            )
        result = self.delegate.call(request)
        metadata = {
            key: result.metadata.get(key)
            for key in (
                "worker",
                "model",
                "observed_model",
                "mode",
                "sandbox_mode",
                "approval_mode",
                "codex_cli_version",
                "json_mode",
                "response_id",
                "usage_source",
                "usage_exact",
                "usage",
            )
            if result.metadata.get(key) is not None
        }
        self.entries.append(
            {
                "operation_id": operation_id,
                "operation": request.operation,
                "prompt_sha256": sha256_text(request.prompt),
                "response": result.text,
                "response_sha256": sha256_text(result.text),
                "recording_metadata": metadata,
            }
        )
        return WorkerResult(result.text, dict(result.metadata))


def current_artifact(binding: Any, session_id: str) -> Any:
    state = binding.read_state(session_id)
    if state.review_subject is None:
        raise AssertionError(f"state {state.stage} has no review subject")
    return binding.read_artifact(
        session_id,
        state.review_subject.artifact_ref,
        state.review_subject.artifact_revision,
    )


def worker_call_count(worker: Any) -> int:
    if isinstance(worker, StrictReplayWorker):
        return worker.index
    if isinstance(worker, RecordingWorker):
        return len(worker.entries)
    raise TypeError(f"unsupported A02-FULL worker type: {type(worker).__name__}")


def milestone(
    state_id: str,
    state_name: str,
    stage: str,
    operation_ids: tuple[str, ...],
    artifact: Any | None,
) -> dict[str, Any]:
    artifact_ref_tokens = {
        "A02-S1": "PROMPT_PROJECTION_REF",
        "A02-S2": "PROMPT_PROJECTION_REF",
        "A02-S3": "PLAN_PROJECTION_REF",
        "A02-S4": None,
    }
    revision_relations = {
        "A02-S1": "NEW_NON_EMPTY_REVISION",
        "A02-S2": "CHANGED_FROM_A02_S1",
        "A02-S3": "NEW_NON_EMPTY_REVISION",
        "A02-S4": "NO_ACTIVE_REVIEW_ARTIFACT",
    }
    return {
        "state_id": state_id,
        "state_name": state_name,
        "stage": stage,
        "after_operation_ids": list(operation_ids),
        "artifact_kind": artifact.artifact_kind if artifact is not None else None,
        "artifact_ref": artifact_ref_tokens[state_id],
        "artifact_revision_relation": revision_relations[state_id],
        "artifact_body_sha256": sha256_text(artifact.body) if artifact is not None else None,
    }


def run_human_equivalent_flow(
    baseline_repo: Path,
    worker: Any,
    workspace_root: Path,
) -> dict[str, Any]:
    from r6o.model_binding.base import ModelSessionRequest
    from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
    from r6o.viewmodel.dispatcher import handle_input

    inputs = canonical_inputs()
    binding = LocalRuntimeModelBinding(
        baseline_repo,
        worker=worker,
        workspace_root=workspace_root,
        run_id="h2-a2-a02-full",
    )
    try:
        started = binding.start_or_resume(
            ModelSessionRequest(request_id="h2-a2-a02-full", task_text=inputs["activation_text"])
        )
        session_id = started.session_id
        initial_state = binding.read_state(session_id)
        if initial_state.stage != "PROMPT_REVIEW":
            raise AssertionError(f"expected initial PROMPT_REVIEW, got {initial_state.stage}")
        initial_prompt = current_artifact(binding, session_id)

        calls_before_focus = worker_call_count(worker)
        focus_result = handle_input(action_envelope(binding, session_id, "something_else"), binding)
        calls_after_focus = worker_call_count(worker)
        if (
            not focus_result["ok"]
            or focus_result["result_type"] != "FOCUS_REQUIRED"
            or focus_result["focus_role"] != "FREE_RESPONSE"
        ):
            raise AssertionError(f"Something else focus transition failed: {focus_result}")
        if calls_after_focus != calls_before_focus:
            raise AssertionError("Something else focus transition invoked the worker")
        focused_state = binding.read_state(session_id)
        focused_prompt = current_artifact(binding, session_id)
        if focused_state.stage != initial_state.stage:
            raise AssertionError("Something else focus transition changed the workflow stage")
        if (
            focused_prompt.artifact_ref != initial_prompt.artifact_ref
            or focused_prompt.artifact_revision != initial_prompt.artifact_revision
            or focused_prompt.body != initial_prompt.body
        ):
            raise AssertionError("Something else focus transition changed the Prompt artifact")

        revised_result = handle_input(
            text_envelope(binding, session_id, inputs["free_response_revision_text"]),
            binding,
        )
        if not revised_result["ok"] or revised_result["result_type"] != "REVISION":
            raise AssertionError(f"A02 revision failed: {revised_result}")
        revised_state = binding.read_state(session_id)
        if revised_state.stage != "PROMPT_REVIEW":
            raise AssertionError(f"expected revised PROMPT_REVIEW, got {revised_state.stage}")
        revised_prompt = current_artifact(binding, session_id)
        if revised_prompt.artifact_revision == initial_prompt.artifact_revision:
            raise AssertionError("revised Prompt did not advance artifact revision")

        prompt_result = handle_input(action_envelope(binding, session_id, "confirm_prompt"), binding)
        if not prompt_result["ok"] or prompt_result["result_type"] != "REVISION":
            raise AssertionError(f"revised Prompt confirmation failed: {prompt_result}")
        plan_state = binding.read_state(session_id)
        if plan_state.stage != "PLAN_REVIEW":
            raise AssertionError(f"expected PLAN_REVIEW, got {plan_state.stage}")
        plan = current_artifact(binding, session_id)

        plan_result = handle_input(action_envelope(binding, session_id, "confirm_plan"), binding)
        if not plan_result["ok"] or plan_result["result_type"] != "REVISION":
            raise AssertionError(f"Plan confirmation failed: {plan_result}")
        final_state = binding.read_state(session_id)
        if final_state.stage != "CLOSED_SUCCESS":
            raise AssertionError(f"expected CLOSED_SUCCESS, got {final_state.stage}")
        if not final_state.lifecycle.result_body:
            raise AssertionError("terminal result body is empty")
        final_prompt = binding.read_artifact(session_id, "prompt:current")
        final_plan = binding.read_artifact(session_id, "plan:current")
        if final_prompt.body != revised_prompt.body or final_plan.body != plan.body:
            raise AssertionError("terminal artifacts differ from confirmed review artifacts")

        return {
            "session_id": session_id,
            "milestones": [
                milestone(*EXPECTED_MILESTONES[0], initial_prompt),
                milestone(*EXPECTED_MILESTONES[1], revised_prompt),
                milestone(*EXPECTED_MILESTONES[2], plan),
                milestone(*EXPECTED_MILESTONES[3], None),
            ],
            "initial_prompt_body": initial_prompt.body,
            "revised_prompt_body": revised_prompt.body,
            "plan_body": plan.body,
            "result_body": final_state.lifecycle.result_body,
            "terminal_disposition": final_state.lifecycle.terminal_disposition,
            "authorized_handoff_artifact_kinds": sorted(
                item.artifact_kind for item in final_state.lifecycle.authorized_handoff_artifacts
            ),
            "focus_transition": {
                "action_id": "something_else",
                "result_type": focus_result["result_type"],
                "focus_role": focus_result["focus_role"],
                "worker_call_delta": calls_after_focus - calls_before_focus,
                "artifact_unchanged": True,
            },
        }
    finally:
        binding.close()


def validate_fixture_documents(
    recorded: dict[str, Any],
    manifest: dict[str, Any],
    *,
    recorded_case_bytes: bytes | None = None,
) -> None:
    recorded = require_object(recorded, "recorded case root")
    manifest = require_object(manifest, "manifest root")
    require_exact_keys(recorded, RECORDED_CASE_KEYS, "recorded case")
    require_exact_keys(manifest, MANIFEST_KEYS, "manifest")
    if recorded.get("schema_version") != "r6o-h2-a02-full-recorded-case-1":
        raise AssertionError("wrong recorded-case schema_version")
    if recorded.get("case_id") != "A02-FULL":
        raise AssertionError("wrong recorded case_id")
    entries = recorded.get("entries")
    if not isinstance(entries, list) or len(entries) != len(EXPECTED_OPERATIONS):
        raise AssertionError("recorded case must contain exactly seven entries")
    for entry, (operation_id, operation) in zip(entries, EXPECTED_OPERATIONS, strict=True):
        entry = require_object(entry, f"recorded entry {operation_id}")
        require_exact_keys(entry, RECORDED_ENTRY_KEYS, f"recorded entry {operation_id}")
        if entry["operation_id"] != operation_id or entry["operation"] != operation:
            raise AssertionError(f"wrong operation order at {operation_id}")
        require_sha256(entry["prompt_sha256"], f"prompt hash at {operation_id}")
        require_sha256(entry["response_sha256"], f"response hash at {operation_id}")
        if not isinstance(entry["response"], str) or not entry["response"]:
            raise AssertionError(f"response at {operation_id} must be a non-empty string")
        if entry["response_sha256"] != sha256_text(entry["response"]):
            raise AssertionError(f"response hash mismatch at {operation_id}")
        try:
            response_document = json.loads(entry["response"])
        except json.JSONDecodeError as exc:
            raise AssertionError(f"response at {operation_id} is not JSON") from exc
        require_object(response_document, f"response at {operation_id}")
        recording_metadata = require_object(
            entry["recording_metadata"], f"recording metadata at {operation_id}"
        )
        require_exact_keys(recording_metadata, RECORDING_METADATA_KEYS, f"recording metadata at {operation_id}")
        expected_metadata = {
            "worker": "codex",
            "model": APPROVED_RECORDING_MODEL,
            "mode": "live-demonstration",
            "sandbox_mode": "read-only",
            "approval_mode": "never",
            "json_mode": True,
            "usage_source": "codex_cli_json",
            "usage_exact": True,
        }
        for key, expected in expected_metadata.items():
            if recording_metadata[key] != expected:
                raise AssertionError(f"recording metadata {operation_id}.{key} must be {expected!r}")
        if not isinstance(recording_metadata["codex_cli_version"], str) or not recording_metadata[
            "codex_cli_version"
        ]:
            raise AssertionError(f"recording metadata {operation_id}.codex_cli_version must be non-empty")
        usage = require_object(recording_metadata["usage"], f"recording usage at {operation_id}")
        require_exact_keys(usage, USAGE_KEYS, f"recording usage at {operation_id}")
        if any(type(value) is not int or value < 0 for value in usage.values()):
            raise AssertionError(f"recording usage at {operation_id} must contain non-negative integers")

    if manifest.get("schema_version") != "r6o-h2-a02-full-manifest-1":
        raise AssertionError("wrong manifest schema_version")
    if manifest.get("case_id") != "A02-FULL" or manifest.get("status") != "FROZEN_FOR_INDEPENDENT_REVIEW":
        raise AssertionError("wrong manifest case/status")
    recording_process = require_object(manifest.get("recording_process"), "recording_process")
    require_exact_keys(recording_process, RECORDING_PROCESS_KEYS, "recording_process")
    expected_recording_values = {
        "process_version": "h2-a2-codex-recording-1",
        "worker": "CodexWorker",
        "requested_model": APPROVED_RECORDING_MODEL,
        "sandbox_mode": "read-only",
        "approval_mode": "never",
        "dangerous_bypass": False,
        "ambient_llm_fallback": False,
    }
    for key, expected in expected_recording_values.items():
        if recording_process[key] != expected:
            raise AssertionError(f"recording_process.{key} must be {expected!r}")
    if recording_process["observed_model"] is not None:
        raise AssertionError("recording_process.observed_model must match the recorded null observation")
    if not isinstance(recording_process["codex_cli_version"], str) or not recording_process[
        "codex_cli_version"
    ]:
        raise AssertionError("recording_process.codex_cli_version must be non-empty")
    try:
        recorded_at = datetime.fromisoformat(recording_process["recorded_at_utc"])
    except (TypeError, ValueError) as exc:
        raise AssertionError("recording_process.recorded_at_utc must be ISO-8601") from exc
    if recorded_at.tzinfo is None or recorded_at.utcoffset() != timezone.utc.utcoffset(recorded_at):
        raise AssertionError("recording_process.recorded_at_utc must be UTC")
    for entry in entries:
        if entry["recording_metadata"]["model"] != recording_process["requested_model"]:
            raise AssertionError(f"recording model mismatch at {entry['operation_id']}")
        if entry["recording_metadata"]["codex_cli_version"] != recording_process["codex_cli_version"]:
            raise AssertionError(f"recording CLI version mismatch at {entry['operation_id']}")

    oracle = require_object(manifest.get("frozen_r6s_oracle"), "frozen_r6s_oracle")
    require_exact_keys(oracle, {"commit", "tree", "mutation_policy"}, "frozen_r6s_oracle")
    if oracle != {
        "commit": FROZEN_ORACLE_COMMIT,
        "tree": FROZEN_ORACLE_TREE,
        "mutation_policy": "READ_ONLY",
    }:
        raise AssertionError("manifest frozen R6S oracle identity/policy differs")
    semantic_inputs = require_object(manifest.get("semantic_inputs"), "semantic_inputs")
    if manifest.get("semantic_inputs") != canonical_inputs():
        raise AssertionError("semantic inputs differ from the A2 freeze")
    require_exact_keys(semantic_inputs, set(canonical_inputs()), "semantic_inputs")
    milestones = manifest.get("expected_milestones")
    if not isinstance(milestones, list) or len(milestones) != len(EXPECTED_MILESTONES):
        raise AssertionError("expected_milestones must contain exactly four entries")
    expected_milestone_static = (
        ("A02-S1", "PROMPT_REVIEW_INITIAL", "PROMPT_REVIEW", ["A02F:0001"], "prompt", "PROMPT_PROJECTION_REF", "NEW_NON_EMPTY_REVISION"),
        ("A02-S2", "PROMPT_REVIEW_REVISED", "PROMPT_REVIEW", ["A02F:0002", "A02F:0003"], "prompt", "PROMPT_PROJECTION_REF", "CHANGED_FROM_A02_S1"),
        ("A02-S3", "PLAN_REVIEW", "PLAN_REVIEW", ["A02F:0004", "A02F:0005"], "plan", "PLAN_PROJECTION_REF", "NEW_NON_EMPTY_REVISION"),
        ("A02-S4", "CLOSED_SUCCESS", "CLOSED_SUCCESS", ["A02F:0006", "A02F:0007"], None, None, "NO_ACTIVE_REVIEW_ARTIFACT"),
    )
    for milestone_document, expected in zip(milestones, expected_milestone_static, strict=True):
        milestone_document = require_object(milestone_document, f"milestone {expected[0]}")
        require_exact_keys(milestone_document, MILESTONE_KEYS, f"milestone {expected[0]}")
        actual_static = (
            milestone_document["state_id"],
            milestone_document["state_name"],
            milestone_document["stage"],
            milestone_document["after_operation_ids"],
            milestone_document["artifact_kind"],
            milestone_document["artifact_ref"],
            milestone_document["artifact_revision_relation"],
        )
        if actual_static != expected:
            raise AssertionError(f"milestone {expected[0]} static contract differs")
        if expected[0] == "A02-S4":
            if milestone_document["artifact_body_sha256"] is not None:
                raise AssertionError("terminal milestone artifact hash must be null")
        else:
            require_sha256(milestone_document["artifact_body_sha256"], f"milestone {expected[0]} hash")

    artifact_hashes = require_object(manifest.get("expected_artifact_hashes"), "expected_artifact_hashes")
    require_exact_keys(artifact_hashes, ARTIFACT_HASH_KEYS, "expected_artifact_hashes")
    for key, value in artifact_hashes.items():
        require_sha256(value, f"expected_artifact_hashes.{key}")
    worker_operations = manifest.get("worker_operations")
    if not isinstance(worker_operations, list) or len(worker_operations) != len(EXPECTED_OPERATIONS):
        raise AssertionError("worker_operations must contain exactly seven entries")
    for worker_operation, (operation_id, _) in zip(worker_operations, EXPECTED_OPERATIONS, strict=True):
        worker_operation = require_object(worker_operation, f"worker operation {operation_id}")
        require_exact_keys(worker_operation, WORKER_OPERATION_KEYS, f"worker operation {operation_id}")
        require_sha256(worker_operation["prompt_sha256"], f"worker operation {operation_id} prompt hash")
        require_sha256(worker_operation["response_sha256"], f"worker operation {operation_id} response hash")
    require_sha256(manifest.get("recorded_case_sha256"), "recorded_case_sha256")
    frozen_recorded_case_bytes = (
        RECORDED_CASE_PATH.read_bytes() if recorded_case_bytes is None else recorded_case_bytes
    )
    if manifest.get("recorded_case_sha256") != sha256_bytes(frozen_recorded_case_bytes):
        raise AssertionError("recorded-case file hash mismatch")
    expected_operation_manifest = [
        {
            "operation_id": entry["operation_id"],
            "operation": entry["operation"],
            "prompt_sha256": entry["prompt_sha256"],
            "response_sha256": entry["response_sha256"],
        }
        for entry in entries
    ]
    if manifest.get("worker_operations") != expected_operation_manifest:
        raise AssertionError("manifest worker operation hashes differ from recorded case")


def expected_artifact_hashes(flow: dict[str, Any]) -> dict[str, str]:
    return {
        "initial_prompt_body_sha256": sha256_text(flow["initial_prompt_body"]),
        "revised_prompt_body_sha256": sha256_text(flow["revised_prompt_body"]),
        "plan_body_sha256": sha256_text(flow["plan_body"]),
        "final_result_body_sha256": sha256_text(flow["result_body"]),
    }


def verify_fixture(
    baseline_repo: str | Path | None = None,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    baseline = resolve_baseline_repo(baseline_repo)
    verify_oracle_identity(baseline)
    before = physical_inventory(baseline)
    recorded = load_json(RECORDED_CASE_PATH)
    manifest = load_json(MANIFEST_PATH)
    validate_fixture_documents(recorded, manifest)
    worker = StrictReplayWorker(recorded["entries"])
    if workspace_root is None:
        context = tempfile.TemporaryDirectory(prefix="pdl-h2-a2-verify-")
        workspace = Path(context.name) / "workspaces"
    else:
        context = None
        workspace = Path(workspace_root).resolve()
    try:
        flow = run_human_equivalent_flow(baseline, worker, workspace)
    finally:
        if context is not None:
            context.cleanup()
    worker.assert_fully_consumed()
    expected_ids = [operation_id for operation_id, _ in EXPECTED_OPERATIONS]
    if worker.consumed_operation_ids != expected_ids:
        raise AssertionError("fixture operation IDs were not consumed exactly once in order")
    if flow["milestones"] != manifest.get("expected_milestones"):
        raise AssertionError("observed state milestones differ from manifest")
    hashes = expected_artifact_hashes(flow)
    if hashes != manifest.get("expected_artifact_hashes"):
        raise AssertionError("observed artifact/result hashes differ from manifest")
    if flow["terminal_disposition"] != "HOST_HANDOFF":
        raise AssertionError("terminal disposition is not HOST_HANDOFF")
    if flow["authorized_handoff_artifact_kinds"] != ["plan", "prompt"]:
        raise AssertionError("terminal authorized artifacts are incomplete")
    after = physical_inventory(baseline)
    if after != before:
        raise AssertionError("frozen R6S oracle physical inventory changed")
    return {
        "case_id": "A02-FULL",
        "final_stage": "CLOSED_SUCCESS",
        "consumed_operation_ids": worker.consumed_operation_ids,
        "artifact_hashes": hashes,
        "oracle_commit": FROZEN_ORACLE_COMMIT,
        "oracle_tree": FROZEN_ORACLE_TREE,
        "oracle_inventory_unchanged": True,
        "focus_transition": flow["focus_transition"],
    }


def record_fixture(
    baseline_repo: str | Path | None,
    *,
    model: str,
) -> dict[str, Any]:
    if model != APPROVED_RECORDING_MODEL:
        raise ValueError(
            f"H2-A2 recording model must be {APPROVED_RECORDING_MODEL!r}, got {model!r}"
        )
    baseline = resolve_baseline_repo(baseline_repo)
    verify_oracle_identity(baseline)
    before = physical_inventory(baseline)
    old_path = list(sys.path)
    sys.path.insert(0, str(baseline))
    try:
        from providers.codex_worker import CodexWorker
    finally:
        sys.path[:] = old_path

    with tempfile.TemporaryDirectory(prefix="pdl-h2-a2-record-") as temporary:
        scratch = Path(temporary)
        delegate = CodexWorker(
            model=model,
            workdir=scratch / "codex-worker",
            allowed_workdir_root=scratch,
            timeout=600.0,
            on_progress=lambda line: print(f"CODEX_WORKER {line}", flush=True),
            sandbox_mode="read-only",
            approval_policy="never",
            allow_bypass=False,
            json_mode=True,
        )
        worker = RecordingWorker(delegate)
        flow = run_human_equivalent_flow(baseline, worker, scratch / "workspaces")
    if len(worker.entries) != len(EXPECTED_OPERATIONS):
        raise AssertionError(f"recording produced {len(worker.entries)} operations, expected seven")
    if physical_inventory(baseline) != before:
        raise AssertionError("frozen R6S oracle physical inventory changed during recording")

    recorded = {
        "schema_version": "r6o-h2-a02-full-recorded-case-1",
        "case_id": "A02-FULL",
        "entries": worker.entries,
    }
    recorded_bytes = json_bytes(recorded)
    first_metadata = worker.entries[0]["recording_metadata"]
    manifest = {
        "schema_version": "r6o-h2-a02-full-manifest-1",
        "case_id": "A02-FULL",
        "status": "FROZEN_FOR_INDEPENDENT_REVIEW",
        "recording_process": {
            "process_version": "h2-a2-codex-recording-1",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "worker": "CodexWorker",
            "requested_model": model,
            "observed_model": first_metadata.get("observed_model"),
            "codex_cli_version": first_metadata.get("codex_cli_version"),
            "sandbox_mode": "read-only",
            "approval_mode": "never",
            "dangerous_bypass": False,
            "ambient_llm_fallback": False,
        },
        "frozen_r6s_oracle": {
            "commit": FROZEN_ORACLE_COMMIT,
            "tree": FROZEN_ORACLE_TREE,
            "mutation_policy": "READ_ONLY",
        },
        "semantic_inputs": canonical_inputs(),
        "expected_milestones": flow["milestones"],
        "expected_artifact_hashes": expected_artifact_hashes(flow),
        "worker_operations": [
            {
                "operation_id": entry["operation_id"],
                "operation": entry["operation"],
                "prompt_sha256": entry["prompt_sha256"],
                "response_sha256": entry["response_sha256"],
            }
            for entry in worker.entries
        ],
        "recorded_case_sha256": sha256_bytes(recorded_bytes),
    }
    validate_fixture_documents(recorded, manifest, recorded_case_bytes=recorded_bytes)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    RECORDED_CASE_PATH.write_bytes(recorded_bytes)
    MANIFEST_PATH.write_bytes(json_bytes(manifest))
    return {
        "recorded_case": str(RECORDED_CASE_PATH.relative_to(ROOT)),
        "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
        "operation_ids": [entry["operation_id"] for entry in worker.entries],
        "artifact_hashes": manifest["expected_artifact_hashes"],
        "requested_model": model,
        "observed_model": first_metadata.get("observed_model"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--record", action="store_true", help="generate a new live Codex recording")
    parser.add_argument(
        "--approve-live-recording",
        action="store_true",
        help="required acknowledgement that --record invokes the live Codex worker",
    )
    parser.add_argument("--model", choices=(APPROVED_RECORDING_MODEL,), default=APPROVED_RECORDING_MODEL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.record:
        if not args.approve_live_recording:
            print("A02-FULL RECORDING FAIL: --approve-live-recording is required", file=sys.stderr)
            return 2
        report = record_fixture(args.baseline_repo, model=args.model)
        print(json.dumps({"status": "A02_FULL_RECORDED", **report}, indent=2))
        return 0
    report = verify_fixture(args.baseline_repo)
    print(json.dumps({"status": "A02_FULL_FIXTURE_PASS", **report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
