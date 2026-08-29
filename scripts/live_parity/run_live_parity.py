from __future__ import annotations

"""Parent/child runner for the qualification-only live parity gate."""

import argparse
import json
import os
import queue
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any

try:
    from . import record as rec
    from .inspect_live_modules import detach_provider_stdin
    from .validate import validate_record
except ImportError:  # Direct execution: python scripts/live_parity/run_live_parity.py
    import record as rec
    from inspect_live_modules import detach_provider_stdin
    from validate import validate_record


IMPLEMENTATION = "providers.codex_worker.CodexWorker"
PHASE_STATUS = {"PASS", "FAIL_SEMANTIC", "FAIL_INTEGRITY", "INCONCLUSIVE_ENVIRONMENT", "STOP_DEPENDENCY", "STOP_SCOPE"}
_INTEGRITY_MARKERS = ("integrity", "contradict", "hash", "inventory", "anti_hardcode", "worker_configuration", "baseline", "attestation", "retained", "evidence", "source_repo")


class RunFailure(RuntimeError):
    def __init__(self, disposition: str, stage: str, message: str, *, error_type: str | None = None) -> None:
        super().__init__(message)
        if disposition not in PHASE_STATUS or disposition == "PASS":
            raise ValueError(f"invalid failure disposition: {disposition}")
        self.disposition = disposition
        self.stage = stage
        self.error_type = error_type or type(self).__name__


def _read_input(path: Path) -> bytes:
    return rec.read_utf8_bytes(path)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _preimage(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "implementation": IMPLEMENTATION,
        "requested_model": args.model,
        # The user config defines DeepSeek as a separate provider while the
        # active desktop default remains OpenAI.  Retain the explicit route
        # in the worker preimage so a model name cannot silently select the
        # ChatGPT provider.
        "model_provider": "deepseek" if args.model == "deepseek-v4-flash" else None,
        "model_reasoning_effort": "max" if args.model == "deepseek-v4-flash" else None,
        "sandbox_mode": args.sandbox_mode,
        "approval_policy": "never",
        "dangerous_bypass": False,
        "timeout_seconds": float(args.worker_timeout),
        "capture_tokens": not args.no_token_telemetry,
        "json_mode": not args.no_token_telemetry,
        "worker_workdir_policy": "separate external per-side workdir",
    }


def _child_paths(args: argparse.Namespace) -> dict[str, Path]:
    run_dir = Path(args.run_dir).resolve()
    side = run_dir / args.side
    return {
        "run_dir": run_dir,
        "side": side,
        "private_inputs": run_dir / "private-inputs",
        "workspace_root": side / "workspace",
        "worker_workdir": side / "worker-workdir",
        "task": Path(args.task_file),
        "prompt": Path(args.prompt_correction_file),
        "plan": Path(args.plan_correction_file),
        "r6s_source": Path(args.r6s_source).resolve(),
        "r6o_control": Path(args.r6o_control).resolve(),
        "gate_root": Path(args.gate_root).resolve(),
    }


def _child_main(args: argparse.Namespace) -> int:
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    paths = _child_paths(args)
    paths["side"].mkdir(parents=True, exist_ok=True)
    paths["workspace_root"].mkdir(parents=True, exist_ok=True)
    paths["worker_workdir"].mkdir(parents=True, exist_ok=True)
    config = json.loads(Path(args.config_file).read_bytes().decode("utf-8"))
    config["configuration_sha256"] = rec.sha256_json(config)
    roots = [paths["r6s_source"]] if args.side == "r6s" else [paths["r6o_control"], paths["r6s_source"]]
    gate = paths["gate_root"]
    sys.path[:] = [str(root) for root in roots] + [entry for entry in sys.path if not entry or not _inside(Path(entry), gate)]
    detach_provider_stdin()
    try:
        runner = rec._r6s_child if args.side == "r6s" else rec._r6o_child
        rec.write_json(paths["side"] / "child-result.json", {"ok": True, "observation": runner(args, config, paths)})
        return 0
    except Exception as exc:
        name = type(exc).__name__
        module = type(exc).__module__
        environment = name in {"TransportError", "FileNotFoundError", "TimeoutExpired", "TimeoutError", "ConnectionError", "AuthenticationError", "AuthError", "ProviderError", "ServiceUnavailableError", "ExecutableNotFoundError"} or module == "subprocess" or any(token in str(exc).lower() for token in ("transporterror", "invalid_request_error", "model is not supported", "authentication", "unauthorized", "timed out", "connection refused", "service unavailable", "executable not found"))
        disposition = "STOP_DEPENDENCY" if isinstance(exc, ImportError) else ("INCONCLUSIVE_ENVIRONMENT" if environment else "FAIL_INTEGRITY")
        rec.write_canonical_json(paths["side"] / "child-result.json", {
            "ok": False,
            "failure_status": disposition,
            "failure_stage": f"{args.side}_child",
            "error_type": name,
            "error": f"{name}: {exc}",
        })
        return 1


def _child_output_queue(stream: Any) -> queue.Queue[str | None]:
    output: queue.Queue[str | None] = queue.Queue()
    def read() -> None:
        try:
            for line in stream:
                output.put(line)
        finally:
            output.put(None)
    threading.Thread(target=read, daemon=True).start()
    return output


def _spawn_child(args: argparse.Namespace, side: str, run_dir: Path, config_path: Path, r6o: Path, r6s: Path, gate: Path, inputs: dict[str, Path]) -> dict[str, Any]:
    side_dir = run_dir / side
    workdir = side_dir / "worker-workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-u", str(Path(__file__).resolve()), "_child",
        "--side", side, "--run-id", args.run_id, "--run-dir", str(run_dir),
        "--config-file", str(config_path), "--r6o-control", str(r6o), "--r6s-source", str(r6s),
        "--gate-root", str(gate), "--task-file", str(inputs["task"]),
        "--prompt-correction-file", str(inputs["prompt"]), "--plan-correction-file", str(inputs["plan"]),
        "--model", args.model, "--worker-timeout", str(args.worker_timeout), "--sandbox-mode", args.sandbox_mode,
    ]
    if args.no_token_telemetry:
        command.append("--no-token-telemetry")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(str(root) for root in ([r6s] if side == "r6s" else [r6o, r6s]))
    log_path = side_dir / "child-process.log"
    try:
        completed = subprocess.Popen(
            command, cwd=workdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1,
        )
        with log_path.open("w", encoding="utf-8", newline="\n") as log:
            assert completed.stdout is not None
            lines = _child_output_queue(completed.stdout)
            deadline = time.monotonic() + max(300.0, float(args.worker_timeout) * 10.0 + 120.0)
            while True:
                try:
                    line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty as exc:
                    completed.kill()
                    raise RunFailure("INCONCLUSIVE_ENVIRONMENT", f"{side}_child", f"{side} child timed out", error_type="TimeoutError") from exc
                if line is None:
                    break
                log.write(line)
                log.flush()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") != "REQUEST_INPUT":
                    continue
                request_path = Path(str(event.get("request_path", ""))).resolve()
                request_display = ""
                if request_path.is_file() and _inside(request_path, side_dir):
                    try:
                        request_display = request_path.read_bytes().decode("utf-8")
                    except UnicodeError:
                        request_display = ""
                side_specific = getattr(args, f"{side}_execution_input_file", None)
                source = Path(side_specific or args.execution_input_file).resolve() if (side_specific or args.execution_input_file) else None
                if source is None:
                    try:
                        print(f"{side} requested execution input: {request_display}", file=sys.stderr)
                        entered = input(f"Path to UTF-8 execution input for {side} (blank = incomplete): ").strip()
                    except EOFError:
                        entered = ""
                    source = Path(entered).resolve() if entered else None
                response: dict[str, Any] = {"retained_path": None}
                if source is not None:
                    try:
                        data = _read_input(source)
                        target = run_dir / "private-inputs" / f"execution-input-{side}.txt"
                        target.write_bytes(data)
                        response = {"retained_path": str(target), "sha256": rec.sha256_file(target)}
                    except (OSError, UnicodeError, ValueError) as exc:
                        response = {"retained_path": None, "error": f"{type(exc).__name__}: {exc}"}
                if completed.stdin is not None:
                    completed.stdin.write(json.dumps(response, ensure_ascii=False) + "\n")
                    completed.stdin.flush()
            if completed.stdin is not None:
                completed.stdin.close()
        try:
            return_code = completed.wait(timeout=max(1.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            completed.kill()
            raise RunFailure("INCONCLUSIVE_ENVIRONMENT", f"{side}_child", f"{side} child timed out", error_type=type(exc).__name__) from exc
    except RunFailure:
        raise
    except OSError as exc:
        raise RunFailure("INCONCLUSIVE_ENVIRONMENT", f"{side}_child", f"unable to launch {side} child: {exc}", error_type=type(exc).__name__) from exc
    result_path = side_dir / "child-result.json"
    if not result_path.is_file():
        raise RunFailure("FAIL_INTEGRITY", f"{side}_child", f"{side} child produced no result; rc={return_code}")
    result = json.loads(result_path.read_bytes().decode("utf-8"))
    if return_code != 0 or result.get("ok") is not True:
        disposition = result.get("failure_status", "FAIL_INTEGRITY")
        if disposition not in PHASE_STATUS or disposition == "PASS":
            disposition = "FAIL_INTEGRITY"
        raise RunFailure(disposition, result.get("failure_stage", f"{side}_child"), result.get("error", "unknown child failure"), error_type=result.get("error_type"))
    return result["observation"]


def _baseline_record(before: dict[str, Any], after: dict[str, Any], before_hash: str, after_hash: str) -> dict[str, Any]:
    return {
        "repository": before["repository"], "commit": before["commit"], "tree": before["tree"],
        "git_clean_before": before["git_clean"], "git_clean_after": after["git_clean"],
        "physical_inventory_before_sha256": before_hash, "physical_inventory_after_sha256": after_hash,
        "physical_inventory_equal": before_hash == after_hash,
    }


def _require_gate_state(gate: Path, expected_head: str, expected_tree: str, *, stage: str) -> dict[str, Any]:
    try:
        state = rec.gate_identity(gate)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunFailure("FAIL_INTEGRITY", stage, f"cannot inspect gate worktree: {exc}", error_type=type(exc).__name__) from exc
    if state["branch"] != rec.GATE_BRANCH or state["head"] != expected_head or state["tree"] != expected_tree:
        raise RunFailure("FAIL_INTEGRITY", stage, "gate branch/head/tree does not match E5 freeze")
    if not state["git_clean"] or state["untracked_files"] != 0 or not state["diff_check_pass"]:
        raise RunFailure("FAIL_INTEGRITY", stage, "gate worktree is not clean or diff-check failed")
    return state


def _write_inventory_artifact(run_dir: Path, label: str, phase: str, root: Path, digest: str, entries: list[dict[str, Any]]) -> Path:
    target = run_dir / label / f"source-inventory-{phase}.json"
    rec.write_canonical_json(target, {
        "schema_version": "pdl-live-functional-parity-source-inventory-1",
        "side": label,
        "root": str(root.resolve()),
        "digest_sha256": digest,
        "entries": entries,
    })
    return target


def _evidence_manifest(run_dir: Path) -> list[dict[str, str]]:
    paths = [
        Path("run-record.json"), Path("private-inputs/task.txt"), Path("private-inputs/prompt-correction.txt"),
        Path("private-inputs/plan-correction.txt"), Path("private-inputs/worker-config.json"),
        Path("r6s/semantic-evidence.json"), Path("r6s/imported-modules.json"),
        Path("r6s/source-inventory-before.json"), Path("r6s/source-inventory-after.json"),
        Path("r6s/execution-request.json"),
        Path("r6o/semantic-evidence.json"), Path("r6o/imported-modules.json"),
        Path("r6o/source-inventory-before.json"), Path("r6o/source-inventory-after.json"),
        Path("r6o/execution-request.json"),
    ]
    paths.extend(path for path in (run_dir / "private-inputs").glob("execution-input-*.txt"))
    result: list[dict[str, str]] = []
    for relative in paths:
        target = relative if relative.is_absolute() else run_dir / relative
        if target.is_file():
            result.append({"path": target.relative_to(run_dir).as_posix(), "sha256": rec.sha256_file(target)})
    return sorted(result, key=lambda item: item["path"])


def _write_failure_status(args: argparse.Namespace, disposition: str, stage: str, exc: BaseException) -> None:
    if not getattr(args, "run_id", None):
        return
    try:
        run_root = Path(args.run_root).resolve()
        run_dir = run_root / "current" / args.run_id
        if not run_dir.is_dir():
            return
        status_path = run_dir / "run-status.json"
        if status_path.exists():
            return
        safe_message = " ".join(str(exc).split())[:500]
        rec.write_canonical_json(status_path, {
            "schema_version": "pdl-live-functional-parity-run-status-1",
            "run_id": args.run_id,
            "disposition": disposition,
            "failure_stage": stage,
            "stage": stage,
            "error_type": getattr(exc, "error_type", type(exc).__name__),
            "message": safe_message,
            "run_record_sha256": rec.sha256_file(run_dir / "run-record.json") if (run_dir / "run-record.json").is_file() else None,
            "execution_metadata_sha256": rec.sha256_file(run_dir / "execution-metadata.json") if (run_dir / "execution-metadata.json").is_file() else None,
            "structural_validation_sha256": rec.sha256_file(run_dir / "validation" / "structural.json") if (run_dir / "validation" / "structural.json").is_file() else None,
            "semantic_validation_sha256": rec.sha256_file(run_dir / "validation" / "semantic.json") if (run_dir / "validation" / "semantic.json").is_file() else None,
            "pass_markers_authorized": False,
        })
    except (OSError, ValueError):
        return


def _run_main(args: argparse.Namespace) -> int:
    gate = Path(args.gate_root).resolve()
    expected_gate = Path(__file__).resolve().parents[2]
    try:
        r6o = rec.outside(args.r6o_control, [gate, args.r6s])
        r6s = rec.outside(args.r6s, [gate, args.r6o_control])
        run_base = rec.outside(args.run_root, [gate, r6o, r6s])
    except ValueError as exc:
        raise RunFailure("STOP_SCOPE", "path_preflight", str(exc), error_type=type(exc).__name__) from exc
    inputs = {name: Path(value).resolve() for name, value in {
        "task": args.task_file, "prompt": args.prompt_correction_file, "plan": args.plan_correction_file,
    }.items()}
    if Path(args.run_id).name != args.run_id or args.run_id in {".", ".."}:
        raise RunFailure("STOP_SCOPE", "run_preflight", "run-id must be a single path-safe name")
    run_dir = run_base / "current" / args.run_id
    if run_dir.exists():
        raise RunFailure("FAIL_INTEGRITY", "run_preflight", f"run directory already exists; current output must be fresh: {run_dir}")
    run_dir.mkdir(parents=True)
    if args.model != "deepseek-v4-flash" or args.sandbox_mode != "read-only" or args.no_token_telemetry or float(args.worker_timeout) != 600.0:
        raise RunFailure("FAIL_INTEGRITY", "configuration_preflight", "E6 workers require deepseek-v4-flash, read-only, telemetry, and a 600 second timeout")
    if gate != expected_gate:
        raise RunFailure("FAIL_INTEGRITY", "gate_preflight", f"--gate-root must equal runner root {expected_gate}")
    private = run_dir / "private-inputs"
    private.mkdir(parents=True)
    input_bytes = {name: _read_input(path) for name, path in inputs.items()}
    retained = {}
    for name, source in inputs.items():
        target = private / {"task": "task.txt", "prompt": "prompt-correction.txt", "plan": "plan-correction.txt"}[name]
        target.write_bytes(input_bytes[name])
        retained[name] = target
    config = _preimage(args)
    config["configuration_sha256"] = rec.sha256_json(config)
    config_path = private / "worker-config.json"
    rec.write_canonical_json(config_path, {key: value for key, value in config.items() if key != "configuration_sha256"})
    if rec.sha256_file(config_path) != config["configuration_sha256"]:
        raise RunFailure("FAIL_INTEGRITY", "configuration_preflight", "worker configuration preimage hash was not retained canonically")
    gate_before = _require_gate_state(gate, args.code_freeze_head, args.code_freeze_tree, stage="gate_preflight")
    try:
        identity = {"r6s": rec.git_identity(r6s, "paragon-ux/PDL-Standard-REPL-Harness"), "r6o": rec.git_identity(r6o, "paragon-ux/PDL-Standard-R6O")}
    except (FileNotFoundError, TimeoutError, ConnectionError) as exc:
        raise RunFailure("INCONCLUSIVE_ENVIRONMENT", "source_preflight", str(exc), error_type=type(exc).__name__) from exc
    except subprocess.CalledProcessError as exc:
        raise RunFailure("STOP_DEPENDENCY", "source_preflight", "pinned source Git identity is unavailable", error_type=type(exc).__name__) from exc
    if (identity["r6s"]["commit"], identity["r6s"]["tree"], identity["r6s"]["git_clean"]) != (rec.R6S_COMMIT, rec.R6S_TREE, True):
        raise RunFailure("STOP_DEPENDENCY", "r6s_preflight", "R6S baseline identity or cleanliness preflight failed")
    if (identity["r6o"]["commit"], identity["r6o"]["tree"], identity["r6o"]["git_clean"]) != (rec.R6O_COMMIT, rec.R6O_TREE, True):
        raise RunFailure("STOP_DEPENDENCY", "r6o_preflight", "R6O control baseline identity or cleanliness preflight failed")
    before = {}
    for label, root in (("r6s", r6s), ("r6o", r6o)):
        digest, entries = rec.physical_inventory(root)
        before[label] = (digest, entries)
        _write_inventory_artifact(run_dir, label, "before", root, digest, entries)
    observations: dict[str, dict[str, Any]] = {}
    for label in ("r6s", "r6o"):
        observations[label] = _spawn_child(args, label, run_dir, config_path, r6o, r6s, gate, retained)
    try:
        after_identity = {"r6s": rec.git_identity(r6s, "paragon-ux/PDL-Standard-REPL-Harness"), "r6o": rec.git_identity(r6o, "paragon-ux/PDL-Standard-R6O")}
    except (FileNotFoundError, TimeoutError, ConnectionError) as exc:
        raise RunFailure("INCONCLUSIVE_ENVIRONMENT", "source_after_children", str(exc), error_type=type(exc).__name__) from exc
    except subprocess.CalledProcessError as exc:
        raise RunFailure("FAIL_INTEGRITY", "source_after_children", "source Git identity could not be recomputed", error_type=type(exc).__name__) from exc
    after = {}
    for label, root in (("r6s", r6s), ("r6o", r6o)):
        digest, entries = rec.physical_inventory(root)
        after[label] = (digest, entries)
        _write_inventory_artifact(run_dir, label, "after", root, digest, entries)
        observations[label]["source_git_clean_after"] = after_identity[label]["git_clean"]
        observations[label]["source_physical_inventory_equal"] = before[label][0] == after[label][0]
        observations[label]["capabilities"]["source_repo_unchanged"] = observations[label]["source_git_clean_after"] and observations[label]["source_physical_inventory_equal"]
    gate_after = _require_gate_state(gate, args.code_freeze_head, args.code_freeze_tree, stage="gate_after_children")
    attestation = {
        "task_sha256": rec.sha256_file(retained["task"]), "prompt_correction_sha256": rec.sha256_file(retained["prompt"]), "plan_correction_sha256": rec.sha256_file(retained["plan"]),
        "task_evidence_path": "private-inputs/task.txt", "prompt_correction_evidence_path": "private-inputs/prompt-correction.txt", "plan_correction_evidence_path": "private-inputs/plan-correction.txt",
        "private_input_evidence_retained": True, "prompt_correction_class": "TASK_CHANGE", "plan_correction_class": "APPROACH_ONLY", "runtime_supplied": True, "same_inputs_both_sides": True,
        "historical_case_id_supplied": False, "historical_evidence_supplied": False, "expected_output_supplied": False, "recorded_worker_supplied": False,
    }
    worker_config = {key: config[key] for key in ("implementation", "requested_model", "configuration_sha256")}
    worker_config.update({"same_configuration_both_sides": True, "real_live_worker": True, "recorded_or_stub_worker": False, "bypass_state": "disabled", "bypass_exception_rationale": None})
    anti = {label: observations[label].pop("anti_hardcode") for label in ("r6s", "r6o")}
    execution_inputs = {label: observations[label].pop("_execution_input", {}) for label in ("r6s", "r6o")}
    if observations["r6s"]["session_id"] == observations["r6o"]["session_id"] or observations["r6s"]["workspace_id"] == observations["r6o"]["workspace_id"]:
        raise RunFailure("FAIL_INTEGRITY", "worker_independence", "R6S and R6O reused a session or workspace identity")
    parity = {
        "required_capabilities_pass_both": all(all(value is True for value in observations[label]["capabilities"].values()) for label in ("r6s", "r6o")),
        "same_input_hashes": attestation["same_inputs_both_sides"], "same_worker_configuration": True,
        "anti_hardcode_pass_both": all(side["scanned_module_count"] > 0 and not side["matched_locations"] for side in anti.values()),
        "source_read_only_pass_both": all(observations[label]["source_git_clean_after"] and observations[label]["source_physical_inventory_equal"] for label in ("r6s", "r6o")),
        "generated_text_equality_required": False,
    }
    record = {
        "schema_version": "pdl-live-functional-parity-record-2", "run_id": args.run_id,
        "baselines": {label: _baseline_record(identity[label], after_identity[label], before[label][0], after[label][0]) for label in ("r6s", "r6o")},
        "input_attestation": attestation, "worker_configuration": worker_config, "anti_hardcode": anti,
        "r6s": observations["r6s"], "r6o": observations["r6o"], "parity": parity,
        "status": "PASS" if all(value is True for key, value in parity.items() if key != "generated_text_equality_required") else "FAIL",
    }
    record_path = run_dir / "run-record.json"
    rec.write_canonical_json(record_path, record)
    record_hash = rec.sha256_file(record_path)
    metadata = {
        "schema_version": "pdl-live-functional-parity-execution-metadata-1", "run_id": args.run_id,
        "gate_root": str(gate), "r6o_control_root": str(r6o), "r6s_root": str(r6s),
        "code_freeze": {"branch": rec.GATE_BRANCH, "head": args.code_freeze_head, "tree": args.code_freeze_tree},
        "gate_before": gate_before, "gate_after": gate_after, "gate_final": gate_after,
        "run_record": {"path": "run-record.json", "sha256": record_hash},
        "conditional_inputs": execution_inputs,
        "evidence_files": _evidence_manifest(run_dir),
    }
    metadata_path = run_dir / "execution-metadata.json"
    rec.write_canonical_json(metadata_path, metadata)
    metadata_hash = rec.sha256_file(metadata_path)
    structural, semantic = validate_record(
        record, run_dir,
        r6o_control=r6o, r6s_source=r6s, gate_root=gate,
        code_freeze_head=args.code_freeze_head, code_freeze_tree=args.code_freeze_tree,
        execution_metadata=metadata,
    )
    validation_dir = run_dir / "validation"
    rec.write_canonical_json(validation_dir / "structural.json", {"passed": not structural, "findings": structural})
    rec.write_canonical_json(validation_dir / "semantic.json", {"passed": not semantic, "findings": semantic})
    after_hash = rec.sha256_file(record_path)
    rec.write_canonical_json(validation_dir / "record-integrity.json", {"sha256_before": record_hash, "sha256_after": after_hash, "unchanged": record_hash == after_hash})
    gate_final = _require_gate_state(gate, args.code_freeze_head, args.code_freeze_tree, stage="gate_after_validation")
    for label, root in (("r6s", r6s), ("r6o", r6o)):
        current_identity = rec.git_identity(root, identity[label]["repository"])
        current_digest, _ = rec.physical_inventory(root)
        if current_identity["commit"] != identity[label]["commit"] or current_identity["tree"] != identity[label]["tree"] or not current_identity["git_clean"] or current_digest != after[label][0]:
            raise RunFailure("FAIL_INTEGRITY", "final_integrity", f"{label} source changed after validation")
    if gate_final != gate_after or record_hash != after_hash or metadata_hash != rec.sha256_file(metadata_path):
        raise RunFailure("FAIL_INTEGRITY", "final_integrity", "gate or run record changed after validation")
    status_path = run_dir / "run-status.json"
    dependency_failure = any("environment dependency missing" in str(item) or "schema load/validation error" in str(item) for item in structural)
    integrity_failure = any(any(marker in str(item).lower() for marker in _INTEGRITY_MARKERS) for item in semantic)
    disposition = "PASS" if not structural and not semantic and record["status"] == "PASS" else ("STOP_DEPENDENCY" if dependency_failure else ("FAIL_INTEGRITY" if structural or integrity_failure else "FAIL_SEMANTIC"))
    if disposition == "PASS" and _require_gate_state(gate, args.code_freeze_head, args.code_freeze_tree, stage="gate_before_markers") != gate_final:
        raise RunFailure("FAIL_INTEGRITY", "final_integrity", "gate changed immediately before PASS markers")
    rec.write_canonical_json(status_path, {
        "schema_version": "pdl-live-functional-parity-run-status-1", "run_id": args.run_id,
        "disposition": disposition, "failure_stage": "validation", "stage": "validation", "error_type": None,
        "message": "current run passed" if disposition == "PASS" else "current run did not satisfy the gate",
        "run_record_sha256": record_hash, "execution_metadata_sha256": rec.sha256_file(metadata_path),
        "structural_validation_sha256": rec.sha256_file(validation_dir / "structural.json"),
        "semantic_validation_sha256": rec.sha256_file(validation_dir / "semantic.json"),
        "pass_markers_authorized": disposition == "PASS",
    })
    if disposition != "PASS":
        print("RUN_RECORD_INVALID" if structural else "RUN_RECORD_SEMANTIC_INVALID")
        return 1
    print("R6S_ARBITRARY_LIVE_CAPABILITY_PASS")
    print("R6O_ARBITRARY_LIVE_CAPABILITY_PASS")
    print("PDLT_R6O_LIVE_FUNCTIONAL_PARITY_PASS")
    print(f"RUN_ID={args.run_id}")
    print(f"RUN_RECORD={record_path}")
    print(f"RUN_RECORD_SHA256={record_hash}")
    print(f"EXECUTION_METADATA={metadata_path}")
    print(f"EXECUTION_METADATA_SHA256={rec.sha256_file(metadata_path)}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qualification-only live R6S/R6O functional parity runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--gate-root", type=Path, required=True)
    run.add_argument("--code-freeze-head", required=True)
    run.add_argument("--code-freeze-tree", required=True)
    run.add_argument("--r6o-control", type=Path, required=True)
    run.add_argument("--r6s", type=Path, required=True)
    run.add_argument("--run-root", type=Path, required=True)
    run.add_argument("--task-file", type=Path, required=True)
    run.add_argument("--prompt-correction-file", type=Path, required=True)
    run.add_argument("--plan-correction-file", type=Path, required=True)
    run.add_argument("--model", default="deepseek-v4-flash")
    run.add_argument("--worker-timeout", type=float, default=600.0)
    run.add_argument("--sandbox-mode", choices=("read-only", "workspace-write"), default="read-only")
    run.add_argument("--no-token-telemetry", action="store_true")
    run.add_argument("--execution-input-file", type=Path, default=None)
    run.add_argument("--r6s-execution-input-file", type=Path, default=None)
    run.add_argument("--r6o-execution-input-file", type=Path, default=None)
    run.add_argument("--run-id", default=None)
    child = sub.add_parser("_child", help=argparse.SUPPRESS)
    child.add_argument("--side", choices=("r6s", "r6o"), required=True)
    child.add_argument("--run-id", required=True)
    child.add_argument("--run-dir", type=Path, required=True)
    child.add_argument("--config-file", type=Path, required=True)
    child.add_argument("--r6o-control", type=Path, required=True)
    child.add_argument("--r6s-source", type=Path, required=True)
    child.add_argument("--gate-root", type=Path, required=True)
    child.add_argument("--task-file", type=Path, required=True)
    child.add_argument("--prompt-correction-file", type=Path, required=True)
    child.add_argument("--plan-correction-file", type=Path, required=True)
    child.add_argument("--model", required=True)
    child.add_argument("--worker-timeout", type=float, required=True)
    child.add_argument("--sandbox-mode", choices=("read-only", "workspace-write"), required=True)
    child.add_argument("--no-token-telemetry", action="store_true")
    child.add_argument("--execution-input-file", type=Path, default=None)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "_child":
        return _child_main(args)
    args.run_id = args.run_id or rec.utc_run_id()
    try:
        return _run_main(args)
    except RunFailure as exc:
        _write_failure_status(args, exc.disposition, exc.stage, exc)
        print(f"{exc.disposition}: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        _write_failure_status(args, "STOP_DEPENDENCY", "import", exc)
        print(f"STOP_DEPENDENCY: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        _write_failure_status(args, "FAIL_INTEGRITY", "parent", exc)
        print(f"FAIL_INTEGRITY: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
