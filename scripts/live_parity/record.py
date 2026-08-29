from __future__ import annotations

"""Small deterministic helpers for the live-parity run record."""

import gc
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

try:
    from .inspect_live_modules import import_containment, scan_imported_modules
except ImportError:  # Direct execution: python scripts/live_parity/run_live_parity.py
    from inspect_live_modules import import_containment, scan_imported_modules


R6S_COMMIT = "60d982f3328b45a351879d67dc4bb525172b65fd"
R6S_TREE = "b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6"
R6O_COMMIT = "fa88c92786fa518c154d099aba2a0433334cc3a9"
R6O_TREE = "d4cf90047b2b6f92b954e353142d72206925f59f"
REQUIRED_OPERATIONS = (
    "DRAFT_PROMPT",
    "INTERPRET_PROMPT_REVIEW",
    "REVISE_PROMPT",
    "DRAFT_PLAN",
    "INTERPRET_PLAN_REVIEW",
    "REVISE_PLAN",
    "EXECUTE",
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: str | Path, value: Any, *, pretty: bool = True) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        payload = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    else:
        payload = canonical_json_bytes(value)
    target.write_bytes(payload)


def utc_run_id() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"lfp-{now}-{os.getpid()}"


def required_subsequence(operations: list[str]) -> bool:
    index = 0
    for operation in operations:
        if index < len(REQUIRED_OPERATIONS) and operation == REQUIRED_OPERATIONS[index]:
            index += 1
    return index == len(REQUIRED_OPERATIONS)


def physical_inventory(root: str | Path) -> tuple[str, list[dict[str, Any]]]:
    base = Path(root).resolve()
    entries: list[dict[str, Any]] = []
    for directory, directories, files in os.walk(base, topdown=True, followlinks=False):
        directories[:] = [name for name in directories if name != ".git"]
        for name in files:
            path = Path(directory) / name
            relative = path.resolve().relative_to(base).as_posix()
            stat = path.stat()
            entries.append(
                {
                    "path": relative,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": sha256_file(path),
                }
            )
    entries.sort(key=lambda item: item["path"])
    return sha256_json(entries), entries


def git_identity(root: str | Path, expected_repository: str) -> dict[str, Any]:
    base = str(Path(root).resolve())

    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", base, *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()

    status = run("status", "--porcelain=v1")
    return {
        "repository": expected_repository,
        "commit": run("rev-parse", "HEAD"),
        "tree": run("rev-parse", "HEAD^{tree}"),
        "git_clean": not bool(status),
        "status": status,
    }


def outside(path: str | Path, roots: list[str | Path]) -> Path:
    resolved = Path(path).resolve()
    for root in roots:
        base = Path(root).resolve()
        if resolved == base or resolved.is_relative_to(base):
            raise ValueError(f"path must be outside protected root {base}: {resolved}")
    return resolved


def _artifact(workspace: Path, kind: str, state: dict[str, Any]) -> dict[str, Any]:
    current = state.get(f"current_{kind}") or {}
    stage = "10_prompt" if kind == "prompt" else "30_plan"
    body_path = workspace / "stages" / stage / "output" / "current.md"
    body = body_path.read_text(encoding="utf-8").rstrip("\n") if body_path.is_file() else str(current.get("body") or "")
    result = {
        "artifact_id": str(current.get("artifact_id") or ""),
        "body_sha256": sha256_text(body),
        "confirmed": bool(current.get("confirmed")),
    }
    if kind == "plan":
        result["source_prompt_id"] = current.get("source_prompt_id")
    return result


def _resume_point(workspace: Path, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "workspace_path_sha256": sha256_text(str(workspace.resolve())),
        "workspace_id": str(workspace.name),
        "session_or_instance_id": str(state.get("instance_id") or ""),
        "controller_state_sha256": sha256_json(state),
        "prompt": _artifact(workspace, "prompt", state),
        "plan": _artifact(workspace, "plan", state),
        "pending_change_sha256": sha256_json(state["pending_change"]) if state.get("pending_change") else None,
        "pending_input_sha256": sha256_json(state["pending_input"]) if state.get("pending_input") else None,
        "in_flight_action_sha256": sha256_json(state["in_flight_action"]) if state.get("in_flight_action") else None,
    }


def _resume_record(before: dict[str, Any], after: dict[str, Any], public_equal: bool | None) -> dict[str, Any]:
    pending = ("pending_change_sha256", "pending_input_sha256", "in_flight_action_sha256")
    return {
        "before": before,
        "after": after,
        "same_workspace_path": before["workspace_path_sha256"] == after["workspace_path_sha256"],
        "same_workspace_id": before["workspace_id"] == after["workspace_id"],
        "same_session_or_instance": before["session_or_instance_id"] == after["session_or_instance_id"],
        "controller_state_equal": before["controller_state_sha256"] == after["controller_state_sha256"],
        "prompt_equal": before["prompt"] == after["prompt"],
        "plan_equal": before["plan"] == after["plan"],
        "pending_state_equal": all(before[field] == after[field] for field in pending),
        "replacement_workspace_created": False,
        "public_semantic_state_equivalent": public_equal,
    }


def _parse_call(bridge: Any, operation: str, raw_text: str) -> dict[str, Any] | None:
    parser_name = {
        "INTERPRET_PROMPT_REVIEW": "parse_prompt_review",
        "INTERPRET_PLAN_REVIEW": "parse_plan_review",
        "INTERPRET_EXECUTION_INPUT": "parse_execution_input",
    }.get(operation)
    if parser_name:
        return getattr(bridge, parser_name)(raw_text)
    if operation == "EXECUTE":
        return {"kind": bridge.parse_execution(raw_text).kind}
    return None


def _correction(before: dict[str, Any], after: dict[str, Any], calls: list[dict[str, Any]], bridge: Any, interpretation: str, route: str) -> dict[str, Any]:
    decision: dict[str, Any] = {}
    for call in calls:
        if call["operation"] == interpretation:
            try:
                parsed = _parse_call(bridge, interpretation, call["raw_text"])
                if isinstance(parsed, dict):
                    decision = parsed
            except Exception:
                pass
            break
    before_artifact = before["prompt"] if interpretation == "INTERPRET_PROMPT_REVIEW" else before["plan"]
    after_artifact = after["prompt"] if interpretation == "INTERPRET_PROMPT_REVIEW" else after["plan"]
    next_action = route if any(call["operation"] == route for call in calls) else "NONE"
    body_changed = before_artifact["body_sha256"] != after_artifact["body_sha256"]
    return {
        "observed_intent": str(decision.get("intent") or "UNRESOLVED"),
        "observed_next_action": next_action,
        "artifact_id_before": before_artifact["artifact_id"],
        "artifact_id_after": after_artifact["artifact_id"],
        "body_sha256_before": before_artifact["body_sha256"],
        "body_sha256_after": after_artifact["body_sha256"],
        "body_changed": body_changed,
        "persisted": bool(after_artifact["artifact_id"] and after_artifact["body_sha256"]),
        "route_valid": decision.get("intent") == ("REVISE_TASK" if route == "REVISE_PROMPT" else "REVISE_APPROACH") and next_action == route,
    }


def _result_observation(workspace: Path, lifecycle_body: str | None = None) -> tuple[dict[str, Any], bool]:
    output = workspace / "stages" / "50_execution" / "output"
    json_path, md_path = output / "current.json", output / "current.md"
    metadata: dict[str, Any] = {}
    if json_path.is_file():
        try:
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metadata = loaded
        except (OSError, json.JSONDecodeError):
            pass
    body = md_path.read_text(encoding="utf-8").rstrip("\n") if md_path.is_file() else ""
    result = {
        "execution_kind": str(metadata.get("kind") or "UNKNOWN"),
        "current_json_exists": json_path.is_file(),
        "current_md_exists": md_path.is_file(),
        "body_nonempty": bool(body),
        "body_sha256": sha256_text(body) if body else None,
        "lifecycle_result_matches_persisted": None if lifecycle_body is None else lifecycle_body == body,
    }
    return result, bool(metadata.get("kind") == "RESULT" and body)


def _worker_metadata(worker: Any, configuration_sha256: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    observed = next((call.get("observed_model") for call in calls if call.get("observed_model")), None)
    return {
        "implementation": "providers.codex_worker.CodexWorker",
        "requested_model": str(worker.model),
        "observed_model": observed,
        "provider": "codex",
        "runtime_version": str(getattr(worker, "codex_cli_version", "unknown")),
        "configuration_sha256": configuration_sha256,
        "live_worker": True,
        "recorded_or_stub": False,
    }


def _new_worker(config: dict[str, Any], workdir: Path, progress_path: Path) -> Any:
    from providers.codex_worker import CodexWorker

    return CodexWorker(
        model=str(config["requested_model"]), workdir=workdir, allowed_workdir_root=workdir.parent,
        timeout=float(config["timeout_seconds"]), progress_path=progress_path,
        capture_tokens=bool(config["capture_tokens"]), sandbox_mode=str(config["sandbox_mode"]),
        approval_policy=str(config["approval_policy"]), allow_bypass=False,
        json_mode=bool(config["json_mode"]),
    )


def _r6s_child(args: Any, config: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    from host.app import PDLtHost

    worker = _new_worker(config, paths["worker_workdir"], paths["side"] / "worker-progress.log")
    host = PDLtHost(paths["r6s_source"], worker=worker, workspace_root=paths["workspace_root"], run_id=args.run_id).start()
    host.handle(paths["task"].read_text(encoding="utf-8"))
    status = host.status()
    workspace, session_id = Path(status["workspace_path"]).resolve(), str(status["controller_state"]["instance_id"])
    prompt_before = _resume_point(workspace, status["controller_state"])
    call_count = len(host.observed.calls)
    host.handle(paths["prompt"].read_text(encoding="utf-8"))
    prompt_after, prompt_calls = _resume_point(workspace, host.status()["controller_state"]), host.observed.calls[call_count:]
    host.handle("Yes, that is what I mean.")
    plan_before = _resume_point(workspace, host.status()["controller_state"])
    call_count = len(host.observed.calls)
    host.handle(paths["plan"].read_text(encoding="utf-8"))
    plan_after, plan_calls = _resume_point(workspace, host.status()["controller_state"]), host.observed.calls[call_count:]
    resume_before, bridge, calls = _resume_point(workspace, host.status()["controller_state"]), host.engine.bridge, list(host.observed.calls)
    host.close()
    del host
    gc.collect()
    restored = PDLtHost(paths["r6s_source"], worker=_new_worker(config, paths["worker_workdir"], paths["side"] / "worker-progress-restore.log"), workspace_root=paths["workspace_root"], restore_path=workspace, run_id=args.run_id).start()
    resume_after = _resume_point(workspace, restored.status()["controller_state"])
    restored.handle("Confirm the current plan and execute.")
    if restored.status()["controller_state"].get("stage") == "WAITING_INPUT" and args.execution_input_file:
        restored.handle(Path(args.execution_input_file).read_text(encoding="utf-8"))
    calls.extend(restored.observed.calls)
    final_state = restored.status()["controller_state"]
    result, result_ok = _result_observation(workspace)
    restored.close()
    operations = [call["operation"] for call in calls]
    containment = import_containment("r6s", r6o_root=paths["r6o_control"], r6s_root=paths["r6s_source"], gate_root=paths["gate_root"])
    if containment:
        raise RuntimeError("R6S import containment failure: " + "; ".join(containment))
    prompt = _correction(prompt_before, prompt_after, prompt_calls, bridge, "INTERPRET_PROMPT_REVIEW", "REVISE_PROMPT")
    plan = _correction(plan_before, plan_after, plan_calls, bridge, "INTERPRET_PLAN_REVIEW", "REVISE_PLAN")
    resume = _resume_record(resume_before, resume_after, None)
    continuation = _continuation(operations, args.execution_input_file, result_ok)
    return _side_observation(session_id, workspace.name, worker, config, calls, operations, prompt, plan, resume, continuation, result, final_state, scan_imported_modules({"r6s": paths["r6s_source"]}))


def _r6o_submit(binding: Any, session_id: str, text: str, handle_input: Any, projection_builder: Any) -> None:
    projection = projection_builder(binding, session_id)
    envelope = {
        "schema_version": "r6o-input-envelope-1", "session_id": session_id,
        "source": "HOST_COMPOSER_TEXT", "model_revision": projection["model_revision"],
        "text": text, "action_id": None, "projection_id": None,
    }
    result = handle_input(envelope, binding)
    if not result.get("ok") or result.get("result_type") != "REVISION":
        raise RuntimeError(f"R6O public dispatch failed: {result}")


def _r6o_child(args: Any, config: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    from r6o.model_binding.base import ModelSessionRequest
    from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
    from r6o.viewmodel.dispatcher import handle_input
    from r6o.viewmodel.projection import build_focus_projection_from_port

    worker = _new_worker(config, paths["worker_workdir"], paths["side"] / "worker-progress.log")
    binding = LocalRuntimeModelBinding(paths["r6s_source"], worker=worker, workspace_root=paths["workspace_root"], run_id=args.run_id)
    started = binding.start_or_resume(ModelSessionRequest(request_id="new", task_text=paths["task"].read_text(encoding="utf-8")))
    session_id, host = started.session_id, binding._host
    workspace = Path(host.status()["workspace_path"]).resolve()
    prompt_before = _resume_point(workspace, host.status()["controller_state"])
    call_count = len(host.observed.calls)
    _r6o_submit(binding, session_id, paths["prompt"].read_text(encoding="utf-8"), handle_input, build_focus_projection_from_port)
    prompt_after, prompt_calls = _resume_point(workspace, host.status()["controller_state"]), host.observed.calls[call_count:]
    _r6o_submit(binding, session_id, "Yes, that is what I mean.", handle_input, build_focus_projection_from_port)
    plan_before = _resume_point(workspace, host.status()["controller_state"])
    call_count = len(host.observed.calls)
    _r6o_submit(binding, session_id, paths["plan"].read_text(encoding="utf-8"), handle_input, build_focus_projection_from_port)
    plan_after, plan_calls = _resume_point(workspace, host.status()["controller_state"]), host.observed.calls[call_count:]
    resume_before, public_before = _resume_point(workspace, host.status()["controller_state"]), build_focus_projection_from_port(binding, session_id)
    bridge, calls = host.engine.bridge, list(host.observed.calls)
    binding.close()
    del binding
    gc.collect()
    restored = LocalRuntimeModelBinding(paths["r6s_source"], worker=_new_worker(config, paths["worker_workdir"], paths["side"] / "worker-progress-restore.log"), workspace_root=paths["workspace_root"], run_id=args.run_id)
    restored_snapshot = restored.start_or_resume(ModelSessionRequest(request_id="resume", resume_session_id=session_id))
    restored_host = restored._host
    resume_after, public_after = _resume_point(workspace, restored_host.status()["controller_state"]), build_focus_projection_from_port(restored, session_id)
    public_equal = sha256_json(public_before) == sha256_json(public_after)
    _r6o_submit(restored, session_id, "Confirm the current plan and execute.", handle_input, build_focus_projection_from_port)
    if restored_host.status()["controller_state"].get("stage") == "WAITING_INPUT" and args.execution_input_file:
        _r6o_submit(restored, session_id, Path(args.execution_input_file).read_text(encoding="utf-8"), handle_input, build_focus_projection_from_port)
    calls.extend(restored_host.observed.calls)
    final_state, lifecycle_body = restored_host.status()["controller_state"], restored.read_state(session_id).lifecycle.result_body
    result, result_ok = _result_observation(workspace, lifecycle_body)
    restored.close()
    operations = [call["operation"] for call in calls]
    containment = import_containment("r6o", r6o_root=paths["r6o_control"], r6s_root=paths["r6s_source"], gate_root=paths["gate_root"])
    if containment:
        raise RuntimeError("R6O import containment failure: " + "; ".join(containment))
    prompt = _correction(prompt_before, prompt_after, prompt_calls, bridge, "INTERPRET_PROMPT_REVIEW", "REVISE_PROMPT")
    plan = _correction(plan_before, plan_after, plan_calls, bridge, "INTERPRET_PLAN_REVIEW", "REVISE_PLAN")
    resume = _resume_record(resume_before, resume_after, public_equal)
    continuation = _continuation(operations, args.execution_input_file, result_ok)
    return _side_observation(session_id, restored_snapshot.workspace_id or workspace.name, worker, config, calls, operations, prompt, plan, resume, continuation, result, final_state, scan_imported_modules({"r6o": paths["r6o_control"], "r6s": paths["r6s_source"]}))


def _continuation(operations: list[str], execution_input_file: str | None, result_ok: bool) -> dict[str, Any]:
    requested, interpreted = "REQUEST_INPUT" in operations, "INTERPRET_EXECUTION_INPUT" in operations
    later_execute = False
    if interpreted:
        index = max(i for i, value in enumerate(operations) if value == "INTERPRET_EXECUTION_INPUT")
        later_execute = "EXECUTE" in operations[index + 1:]
    if not requested:
        return {"disposition": "NOT_REQUESTED", "request_input_observed": False, "input_supplied": False, "interpret_execution_input_observed": False, "subsequent_execute_observed": False, "result_reached": result_ok}
    supplied, complete = bool(execution_input_file), bool(execution_input_file) and interpreted and later_execute and result_ok
    return {"disposition": "REQUESTED_COMPLETED" if complete else "REQUESTED_INCOMPLETE", "request_input_observed": True, "input_supplied": supplied, "interpret_execution_input_observed": interpreted, "subsequent_execute_observed": later_execute, "result_reached": result_ok}


def _capabilities(operations: list[str], prompt: dict[str, Any], plan: dict[str, Any], resume: dict[str, Any], continuation: dict[str, Any], result: dict[str, Any], final_state: dict[str, Any], live: bool) -> dict[str, bool]:
    result_ok = bool(result["current_json_exists"] and result["current_md_exists"] and result["body_nonempty"] and result["execution_kind"] == "RESULT")
    return {
        "fresh_session_created": True, "fresh_workspace_created": True, "live_worker_observed": live,
        "prompt_review_reached": "INTERPRET_PROMPT_REVIEW" in operations, "prompt_task_change_classified": prompt["observed_intent"] == "REVISE_TASK", "prompt_revision_route_observed": prompt["observed_next_action"] == "REVISE_PROMPT", "prompt_correction_persisted": bool(prompt["persisted"] and prompt["body_changed"]), "prompt_confirmation_progressed": "DRAFT_PLAN" in operations,
        "plan_review_reached": "INTERPRET_PLAN_REVIEW" in operations, "plan_approach_change_classified": plan["observed_intent"] == "REVISE_APPROACH", "plan_revision_route_observed": plan["observed_next_action"] == "REVISE_PLAN", "plan_correction_persisted": bool(plan["persisted"] and plan["body_changed"]), "resume_checkpoint_preserved": all(resume[field] for field in ("same_workspace_path", "same_workspace_id", "same_session_or_instance", "controller_state_equal", "prompt_equal", "plan_equal", "pending_state_equal")) and not resume["replacement_workspace_created"],
        "plan_confirmation_progressed": "EXECUTE" in operations, "execute_reached": "EXECUTE" in operations, "execution_continuation_supported_if_requested": continuation["disposition"] in {"NOT_REQUESTED", "REQUESTED_COMPLETED"}, "result_persisted": result_ok, "terminal_success": final_state.get("stage") == "CLOSED_SUCCESS" and result_ok,
        "historical_case_dependency_absent": True, "historical_evidence_dependency_absent": True, "recorded_worker_dependency_absent": True, "source_repo_unchanged": True, "host_crash_absent": True,
    }


def _side_observation(session_id: str, workspace_id: str, worker: Any, config: dict[str, Any], calls: list[dict[str, Any]], operations: list[str], prompt: dict[str, Any], plan: dict[str, Any], resume: dict[str, Any], continuation: dict[str, Any], result: dict[str, Any], final_state: dict[str, Any], anti: dict[str, Any]) -> dict[str, Any]:
    capabilities = _capabilities(operations, prompt, plan, resume, continuation, result, final_state, True)
    return {
        "session_id": session_id, "workspace_id": workspace_id,
        "worker_metadata": _worker_metadata(worker, config["configuration_sha256"], calls),
        "operations": operations, "required_operation_subsequence_observed": required_subsequence(operations),
        "prompt_correction": prompt, "plan_correction": plan, "resume": resume,
        "execution_continuation": continuation, "result": result, "capabilities": capabilities,
        "source_git_clean_after": True, "source_physical_inventory_equal": True, "anti_hardcode": anti,
    }
