from __future__ import annotations

"""Parent/child runner for the qualification-only live parity gate."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

try:
    from . import record as rec
    from .validate import validate_record
except ImportError:  # Direct execution: python scripts/live_parity/run_live_parity.py
    import record as rec
    from validate import validate_record


IMPLEMENTATION = "providers.codex_worker.CodexWorker"


def _read_input(path: Path) -> bytes:
    data = path.read_bytes()
    data.decode("utf-8")
    if not data.strip():
        raise ValueError(f"input is empty or whitespace-only: {path}")
    return data


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
        "side": side,
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
    config = json.loads(Path(args.config_file).read_text(encoding="utf-8"))
    config["configuration_sha256"] = rec.sha256_json(config)
    roots = [paths["r6s_source"]] if args.side == "r6s" else [paths["r6o_control"], paths["r6s_source"]]
    gate = paths["gate_root"]
    sys.path[:] = [str(root) for root in roots] + [entry for entry in sys.path if not entry or not _inside(Path(entry), gate)]
    try:
        runner = rec._r6s_child if args.side == "r6s" else rec._r6o_child
        rec.write_json(paths["side"] / "child-result.json", {"ok": True, "observation": runner(args, config, paths)})
        return 0
    except Exception as exc:
        rec.write_json(paths["side"] / "child-result.json", {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1


def _spawn_child(args: argparse.Namespace, side: str, run_dir: Path, config_path: Path, r6o: Path, r6s: Path, gate: Path, inputs: dict[str, Path]) -> dict[str, Any]:
    side_dir = run_dir / side
    workdir = side_dir / "worker-workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(Path(__file__).resolve()), "_child",
        "--side", side, "--run-id", args.run_id, "--run-dir", str(run_dir),
        "--config-file", str(config_path), "--r6o-control", str(r6o), "--r6s-source", str(r6s),
        "--gate-root", str(gate), "--task-file", str(inputs["task"]),
        "--prompt-correction-file", str(inputs["prompt"]), "--plan-correction-file", str(inputs["plan"]),
        "--model", args.model, "--worker-timeout", str(args.worker_timeout), "--sandbox-mode", args.sandbox_mode,
    ]
    if args.no_token_telemetry:
        command.append("--no-token-telemetry")
    if args.execution_input_file:
        command += ["--execution-input-file", str(Path(args.execution_input_file).resolve())]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(str(root) for root in ([r6s] if side == "r6s" else [r6o, r6s]))
    log_path = side_dir / "child-process.log"
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        completed = subprocess.run(command, cwd=workdir, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=max(300.0, float(args.worker_timeout) * 10.0 + 120.0))
    result_path = side_dir / "child-result.json"
    if not result_path.is_file():
        raise RuntimeError(f"{side} child produced no result; rc={completed.returncode}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if completed.returncode != 0 or result.get("ok") is not True:
        raise RuntimeError(f"{side} child failed: {result.get('error', 'unknown child failure')}")
    return result["observation"]


def _baseline_record(before: dict[str, Any], after: dict[str, Any], before_hash: str, after_hash: str) -> dict[str, Any]:
    return {
        "repository": before["repository"], "commit": before["commit"], "tree": before["tree"],
        "git_clean_before": before["git_clean"], "git_clean_after": after["git_clean"],
        "physical_inventory_before_sha256": before_hash, "physical_inventory_after_sha256": after_hash,
        "physical_inventory_equal": before_hash == after_hash,
    }


def _run_main(args: argparse.Namespace) -> int:
    gate = Path(__file__).resolve().parents[2]
    r6o, r6s = rec.outside(args.r6o_control, [gate, args.r6s]), rec.outside(args.r6s, [gate, args.r6o_control])
    inputs = {name: Path(value).resolve() for name, value in {
        "task": args.task_file, "prompt": args.prompt_correction_file, "plan": args.plan_correction_file,
    }.items()}
    for path in inputs.values():
        _read_input(path)
    if args.execution_input_file:
        _read_input(Path(args.execution_input_file).resolve())
    run_base = rec.outside(args.run_root, [gate, r6o, r6s])
    if Path(args.run_id).name != args.run_id or args.run_id in {".", ".."}:
        raise ValueError("run-id must be a single path-safe name")
    run_dir = run_base / "current" / args.run_id
    if run_dir.exists():
        raise RuntimeError(f"run directory already exists; current output must be fresh: {run_dir}")
    private = run_dir / "private-inputs"
    private.mkdir(parents=True)
    retained = {}
    for name, source in inputs.items():
        target = private / {"task": "task.txt", "prompt": "prompt-correction.txt", "plan": "plan-correction.txt"}[name]
        target.write_bytes(_read_input(source))
        retained[name] = target
    config = _preimage(args)
    config["configuration_sha256"] = rec.sha256_json(config)
    config_path = private / "worker-config.json"
    rec.write_json(config_path, {key: value for key, value in config.items() if key != "configuration_sha256"}, pretty=False)
    if rec.sha256_file(config_path) != config["configuration_sha256"]:
        raise RuntimeError("worker configuration preimage hash was not retained canonically")
    identity = {"r6s": rec.git_identity(r6s, "paragon-ux/PDL-Standard-REPL-Harness"), "r6o": rec.git_identity(r6o, "paragon-ux/PDL-Standard-R6O")}
    if (identity["r6s"]["commit"], identity["r6s"]["tree"], identity["r6s"]["git_clean"]) != (rec.R6S_COMMIT, rec.R6S_TREE, True):
        raise RuntimeError("R6S baseline identity or cleanliness preflight failed")
    if (identity["r6o"]["commit"], identity["r6o"]["tree"], identity["r6o"]["git_clean"]) != (rec.R6O_COMMIT, rec.R6O_TREE, True):
        raise RuntimeError("R6O control baseline identity or cleanliness preflight failed")
    before = {label: rec.physical_inventory(root)[0] for label, root in (("r6s", r6s), ("r6o", r6o))}
    observations = {label: _spawn_child(args, label, run_dir, config_path, r6o, r6s, gate, retained) for label in ("r6s", "r6o")}
    after_identity = {"r6s": rec.git_identity(r6s, "paragon-ux/PDL-Standard-REPL-Harness"), "r6o": rec.git_identity(r6o, "paragon-ux/PDL-Standard-R6O")}
    after = {label: rec.physical_inventory(root)[0] for label, root in (("r6s", r6s), ("r6o", r6o))}
    for label in ("r6s", "r6o"):
        observations[label]["source_git_clean_after"] = after_identity[label]["git_clean"]
        observations[label]["source_physical_inventory_equal"] = before[label] == after[label]
        observations[label]["capabilities"]["source_repo_unchanged"] = observations[label]["source_git_clean_after"] and observations[label]["source_physical_inventory_equal"]
    attestation = {
        "task_sha256": rec.sha256_file(retained["task"]), "prompt_correction_sha256": rec.sha256_file(retained["prompt"]), "plan_correction_sha256": rec.sha256_file(retained["plan"]),
        "task_evidence_path": "private-inputs/task.txt", "prompt_correction_evidence_path": "private-inputs/prompt-correction.txt", "plan_correction_evidence_path": "private-inputs/plan-correction.txt",
        "private_input_evidence_retained": True, "prompt_correction_class": "TASK_CHANGE", "plan_correction_class": "APPROACH_ONLY", "runtime_supplied": True, "same_inputs_both_sides": True,
        "historical_case_id_supplied": False, "historical_evidence_supplied": False, "expected_output_supplied": False, "recorded_worker_supplied": False,
    }
    worker_config = {key: config[key] for key in ("implementation", "requested_model", "configuration_sha256")}
    worker_config.update({"same_configuration_both_sides": True, "real_live_worker": True, "recorded_or_stub_worker": False, "bypass_state": "disabled", "bypass_exception_rationale": None})
    anti = {label: observations[label].pop("anti_hardcode") for label in ("r6s", "r6o")}
    parity = {
        "required_capabilities_pass_both": all(all(value is True for value in observations[label]["capabilities"].values()) for label in ("r6s", "r6o")),
        "same_input_hashes": attestation["same_inputs_both_sides"], "same_worker_configuration": True,
        "anti_hardcode_pass_both": all(side["scanned_module_count"] > 0 and not side["matched_locations"] for side in anti.values()),
        "source_read_only_pass_both": all(observations[label]["source_git_clean_after"] and observations[label]["source_physical_inventory_equal"] for label in ("r6s", "r6o")),
        "generated_text_equality_required": False,
    }
    record = {
        "schema_version": "pdl-live-functional-parity-record-2", "run_id": args.run_id,
        "baselines": {label: _baseline_record(identity[label], after_identity[label], before[label], after[label]) for label in ("r6s", "r6o")},
        "input_attestation": attestation, "worker_configuration": worker_config, "anti_hardcode": anti,
        "r6s": observations["r6s"], "r6o": observations["r6o"], "parity": parity,
        "status": "PASS" if all(value is True for key, value in parity.items() if key != "generated_text_equality_required") else "FAIL",
    }
    record_path = run_dir / "run-record.json"
    rec.write_json(record_path, record)
    record_hash = rec.sha256_file(record_path)
    structural, semantic = validate_record(record, run_dir)
    validation_dir = run_dir / "validation"
    rec.write_json(validation_dir / "structural.json", {"passed": not structural, "findings": structural})
    rec.write_json(validation_dir / "semantic.json", {"passed": not semantic, "findings": semantic})
    after_hash = rec.sha256_file(record_path)
    rec.write_json(validation_dir / "record-integrity.json", {"sha256_before": record_hash, "sha256_after": after_hash, "unchanged": record_hash == after_hash})
    if record_hash != after_hash:
        print("RUN_RECORD_SEMANTIC_INVALID")
        return 1
    if structural:
        print("RUN_RECORD_INVALID")
        return 1
    if semantic or record["status"] != "PASS":
        print("RUN_RECORD_SEMANTIC_INVALID")
        return 1
    print("R6S_ARBITRARY_LIVE_CAPABILITY_PASS")
    print("R6O_ARBITRARY_LIVE_CAPABILITY_PASS")
    print("PDLT_R6O_LIVE_FUNCTIONAL_PARITY_PASS")
    print(f"RUN_ID={args.run_id}")
    print(f"RUN_RECORD={record_path}")
    print(f"RUN_RECORD_SHA256={record_hash}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qualification-only live R6S/R6O functional parity runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
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
    return _run_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
