from __future__ import annotations

"""Bounded production-module inspection and external evidence validation."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _read_utf8_bytes(path: str | Path) -> bytes:
    data = Path(path).read_bytes(); data.decode("utf-8")
    if not data.strip():
        raise ValueError(f"input is empty or whitespace-only: {path}")
    return data


def child_inputs(paths: dict[str, Path]) -> tuple[dict[str, str], dict[str, str]]:
    texts: dict[str, str] = {}; hashes: dict[str, str] = {}
    for name, key in (("task", "task"), ("prompt_correction", "prompt"), ("plan_correction", "plan")):
        data = _read_utf8_bytes(paths[key]); texts[name] = data.decode("utf-8"); hashes[name] = hashlib.sha256(data).hexdigest()
    return texts, hashes


def request_execution_input(args: Any, paths: dict[str, Path], pending_input: Any) -> tuple[str | None, dict[str, Any]]:
    request_path = paths["side"] / "execution-request.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_bytes(_canonical_json({"schema_version": "pdl-live-functional-parity-execution-request-1", "side": args.side, "pending_input": pending_input}))
    print(json.dumps({"event": "REQUEST_INPUT", "side": args.side, "request_path": str(request_path)}, ensure_ascii=False), flush=True)
    try:
        response = json.loads(sys.stdin.readline() or "{}")
    except json.JSONDecodeError:
        response = {}
    retained = response.get("retained_path") if isinstance(response, dict) else None
    evidence: dict[str, Any] = {"request_observed": True, "request_evidence_path": request_path.relative_to(paths["run_dir"]).as_posix(), "request_evidence_sha256": _sha256_file(request_path), "input_supplied": False, "input_path": None, "input_sha256": None, "child_decoded_sha256": None}
    if not isinstance(retained, str) or not retained:
        return None, evidence
    candidate = Path(retained).resolve(); private_root = paths["private_inputs"].resolve()
    try:
        candidate.relative_to(private_root); data = _read_utf8_bytes(candidate)
    except (OSError, UnicodeError, ValueError):
        return None, evidence
    digest = hashlib.sha256(data).hexdigest(); evidence.update({"input_supplied": True, "input_path": candidate.relative_to(paths["run_dir"]).as_posix(), "input_sha256": digest, "child_decoded_sha256": digest})
    return data.decode("utf-8"), evidence


def write_child_evidence(args: Any, paths: dict[str, Path], input_hashes: dict[str, str], config: dict[str, Any], operations: list[str], snapshots: dict[str, Any], execution_input: dict[str, Any], lifecycle_result_body_sha256: str | None, imported: dict[str, Any]) -> None:
    payload = {"schema_version": "pdl-live-functional-parity-semantic-evidence-1", "side": args.side, "input_hashes": input_hashes, "worker": {"implementation": "providers.codex_worker.CodexWorker", "requested_model": config["requested_model"], "configuration_sha256": config["configuration_sha256"], "workdir": str(paths["worker_workdir"].resolve()), "workdir_sha256": hashlib.sha256(str(paths["worker_workdir"].resolve()).encode("utf-8")).hexdigest()}, "operations": operations, "snapshots": snapshots, "execution_input": execution_input, "lifecycle_result_body_sha256": lifecycle_result_body_sha256}
    paths["side"].mkdir(parents=True, exist_ok=True)
    (paths["side"] / "semantic-evidence.json").write_bytes(_canonical_json(payload)); (paths["side"] / "imported-modules.json").write_bytes(_canonical_json(imported))


_EXCLUDED_PARTS = {"tests", "docs", "fixtures", "r6o_evidence", "evidence"}
_REPLAY_FILES = {"providers/recorded.py", "providers/fixtures.py"}
_RULES = {
    "g06_matches": re.compile(r"\bG06\b", re.IGNORECASE), "a02_matches": re.compile(r"\bA02\b", re.IGNORECASE),
    "rdx_case_matches": re.compile(r"\bRDX(?:[-_][A-Z0-9_-]+)?\b", re.IGNORECASE),
    "recorded_fixture_path_matches": re.compile(r"recorded-cases\.json|recorded[-_]worker|fixtures[/\\].*recorded", re.IGNORECASE),
    "historical_evidence_path_matches": re.compile(r"r6o_evidence|historical[-_]?evidence|fixed[-_]?evidence", re.IGNORECASE),
    "expected_output_routing_matches": re.compile(r"expected[-_]?output|fixture[-_]?output", re.IGNORECASE),
    "recorded_provider_live_import_matches": re.compile(r"providers\.recorded|(?:from|import)\s+providers\s+import\s+recorded", re.IGNORECASE),
}


def _inside(path: Path, root: Path) -> bool:
    try: path.resolve().relative_to(root.resolve()); return True
    except ValueError: return False


def should_scan(relative: str) -> bool:
    normalized = relative.replace("\\", "/").lower()
    return not (set(Path(normalized).parts) & _EXCLUDED_PARTS) and normalized not in _REPLAY_FILES


def imported_module_paths(roots: dict[str, str | Path]) -> dict[str, list[str]]:
    resolved = {label: Path(root).resolve() for label, root in roots.items()}; paths: set[str] = set()
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename or not str(filename).endswith(".py"): continue
        candidate = Path(filename).resolve()
        for label, root in resolved.items():
            if _inside(candidate, root):
                relative = candidate.relative_to(root).as_posix()
                if should_scan(relative): paths.add(f"{label}/{relative}")
    result = {label: [] for label in resolved}
    for value in sorted(paths):
        label, _, _ = value.partition("/"); result.setdefault(label, []).append(value)
    return result


def _scan_paths(roots: dict[str, str | Path], paths_by_root: dict[str, list[str]]) -> dict[str, Any]:
    counts = {name: 0 for name in _RULES}; matched: list[str] = []
    for label, paths in paths_by_root.items():
        root = Path(roots[label]).resolve()
        for qualified in paths:
            source = root / qualified.split("/", 1)[1]
            try: lines = source.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError): continue
            for line_number, line in enumerate(lines, 1):
                for rule, pattern in _RULES.items():
                    if pattern.search(line): counts[rule] += 1; matched.append(f"{qualified}:{line_number}:{rule}")
    return {"scanned_module_count": sum(map(len, paths_by_root.values())), "scanned_paths": sorted(path for paths in paths_by_root.values() for path in paths), **counts, "matched_locations": sorted(matched)}


def scan_imported_modules(roots: dict[str, str | Path]) -> dict[str, Any]:
    return _scan_paths(roots, imported_module_paths(roots))


def imported_module_evidence(roots: dict[str, str | Path]) -> dict[str, Any]:
    modules: list[dict[str, str]] = []
    for label, paths in imported_module_paths(roots).items():
        root = Path(roots[label]).resolve()
        for qualified in paths:
            relative = qualified.split("/", 1)[1]; modules.append({"root": label, "relative_path": relative, "qualified_path": qualified, "sha256": _sha256_file(root / relative)})
    return {"modules": modules, "containment_violations": []}


def scan_recorded_paths(roots: dict[str, str | Path], qualified_paths: list[str]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []; paths_by_root = {label: [] for label in roots}; seen: set[str] = set()
    for qualified in qualified_paths:
        if not isinstance(qualified, str) or "/" not in qualified: errors.append(f"invalid imported module path: {qualified!r}"); continue
        label, relative = qualified.split("/", 1)
        if label not in roots: errors.append(f"imported module root is not declared: {qualified!r}"); continue
        if qualified in seen: errors.append(f"duplicate imported module path: {qualified!r}"); continue
        seen.add(qualified)
        if "\\" in relative or not relative or Path(relative).is_absolute() or any(part in {"", ".", ".."} for part in Path(relative).parts) or not relative.endswith(".py"):
            errors.append(f"imported module path is not canonical: {qualified!r}"); continue
        if not should_scan(relative): errors.append(f"imported module path is excluded from production scan: {qualified!r}"); continue
        root = Path(roots[label]).resolve(); source = (root / relative).resolve()
        if not _inside(source, root) or not source.is_file(): errors.append(f"imported module path is missing or escapes root: {qualified!r}"); continue
        paths_by_root[label].append(qualified)
    return _scan_paths(roots, paths_by_root), errors


def verify_imported_module_evidence(roots: dict[str, str | Path], evidence: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    modules = evidence.get("modules") if isinstance(evidence, dict) else None
    if not isinstance(modules, list): return _scan_paths(roots, {label: [] for label in roots}), ["imported module evidence has no modules list"]
    paths: list[str] = []; errors: list[str] = []
    for item in modules:
        if not isinstance(item, dict) or not isinstance(item.get("qualified_path"), str): errors.append("imported module evidence item is invalid"); continue
        qualified = item["qualified_path"]; paths.append(qualified); label, _, relative = qualified.partition("/")
        if item.get("root") != label or item.get("relative_path") != relative: errors.append(f"imported module path fields disagree: {qualified!r}"); continue
        if label in roots:
            source = (Path(roots[label]).resolve() / relative).resolve()
            if source.is_file() and item.get("sha256") != _sha256_file(source): errors.append(f"imported module bytes changed: {qualified!r}")
    scan, path_errors = scan_recorded_paths(roots, paths); return scan, errors + path_errors


def import_containment(side: str, *, r6o_root: str | Path, r6s_root: str | Path, gate_root: str | Path) -> list[str]:
    control, frozen, gate = Path(r6o_root).resolve(), Path(r6s_root).resolve(), Path(gate_root).resolve(); violations: list[str] = []
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not filename: continue
        candidate = Path(filename).resolve()
        if _inside(candidate, gate) and not _inside(candidate, gate / "scripts" / "live_parity"): violations.append(f"{name}={candidate}:gate-worktree")
        if side == "r6o" and (name == "r6o" or name.startswith("r6o.")) and not _inside(candidate, control): violations.append(f"{name}={candidate}:not-r6o-control")
        if (name == "host" or any(name.startswith(prefix + ".") for prefix in ("host", "runtime", "controller", "observation", "providers"))) and not _inside(candidate, frozen): violations.append(f"{name}={candidate}:not-r6s-frozen")
    return sorted(set(violations))


def validate_external_artifacts(record: dict[str, Any], run_root: str | Path, metadata: dict[str, Any], *, r6o_control: str | Path, r6s_source: str | Path, gate_root: str | Path, code_freeze_head: str, code_freeze_tree: str) -> list[str]:
    try:
        from .record import R6O_COMMIT, R6O_TREE, R6S_COMMIT, R6S_TREE, gate_identity, git_identity, physical_inventory, sha256_json, sha256_text
    except ImportError:
        from record import R6O_COMMIT, R6O_TREE, R6S_COMMIT, R6S_TREE, gate_identity, git_identity, physical_inventory, sha256_json, sha256_text
    root, control, source, gate = Path(run_root).resolve(), Path(r6o_control).resolve(), Path(r6s_source).resolve(), Path(gate_root).resolve(); findings: list[str] = []
    bad = lambda message: findings.append(f"INTEGRITY: {message}")

    def load(path: Path, label: str) -> Any:
        try:
            raw = path.read_bytes(); value = json.loads(raw.decode("utf-8"))
            if raw != _canonical_json(value): bad(f"{label} is not canonical UTF-8 JSON")
            return value
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            bad(f"{label} is unreadable or invalid JSON: {exc}"); return None

    def safe(value: Any, label: str) -> Path | None:
        if not isinstance(value, str) or not value or "\\" in value: bad(f"{label} is not a canonical relative POSIX path"); return None
        posix = PurePosixPath(value)
        if posix.is_absolute() or re.match(r"^[A-Za-z]:", value) or "//" in value or any(part in {"", ".", ".."} for part in posix.parts): bad(f"{label} contains absolute or traversal components"); return None
        candidate = (root / Path(*posix.parts)).resolve()
        if candidate == root or not _inside(candidate, root): bad(f"{label} escapes run root"); return None
        return candidate

    if not isinstance(metadata, dict): bad("execution metadata is not an object"); return findings
    if metadata.get("schema_version") != "pdl-live-functional-parity-execution-metadata-1": bad("execution metadata schema_version is not accepted")
    if metadata.get("run_id") != record.get("run_id"): bad("execution metadata run_id does not match the record")
    for field, expected in (("gate_root", str(gate)), ("r6o_control_root", str(control)), ("r6s_root", str(source))):
        if metadata.get(field) != expected: bad(f"execution metadata {field} is not the explicit validated root")
    freeze = metadata.get("code_freeze")
    if not isinstance(freeze, dict) or (freeze.get("branch"), freeze.get("head"), freeze.get("tree")) != ("codex/live-functional-parity-v1", code_freeze_head, code_freeze_tree): bad("execution metadata code_freeze does not match the supplied E5 identity")
    try:
        current_gate = gate_identity(gate); fields = ("root", "branch", "head", "tree", "git_clean", "untracked_files", "diff_check_pass", "status", "diff_check_output")
        for stage in ("gate_before", "gate_after", "gate_final"):
            observed = metadata.get(stage)
            if observed is not None and (not isinstance(observed, dict) or any(observed.get(field) != current_gate.get(field) for field in fields)): bad(f"execution metadata {stage} does not match the recomputed gate")
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc: bad(f"gate identity cannot be recomputed: {exc}")
    run_record = metadata.get("run_record"); record_path = safe(run_record.get("path") if isinstance(run_record, dict) else None, "run_record.path")
    if record_path != root / "run-record.json": bad("run_record.path must be exactly run-record.json")
    elif isinstance(run_record, dict):
        if not record_path.is_file() or _sha256_file(record_path) != run_record.get("sha256"): bad("run_record.sha256 does not match the retained record bytes")
        loaded = load(record_path, "run-record.json")
        if loaded is not None and loaded != record: bad("retained run-record.json differs from the record being validated")
    manifest = metadata.get("evidence_files"); listed: dict[str, str] = {}
    if not isinstance(manifest, list): bad("evidence_files must be a list")
    else:
        for item in manifest:
            if not isinstance(item, dict): bad("evidence_files contains a non-object entry"); continue
            relative, path = item.get("path"), safe(item.get("path"), "evidence_files.path")
            if path is None: continue
            if relative in listed: bad(f"evidence_files contains a duplicate path: {relative}"); continue
            digest = item.get("sha256"); listed[relative] = digest
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or not path.is_file() or _sha256_file(path) != digest: bad(f"evidence_files hash does not match {relative}")
    required = {"run-record.json", "private-inputs/task.txt", "private-inputs/prompt-correction.txt", "private-inputs/plan-correction.txt", "private-inputs/worker-config.json", *(f"{label}/{name}" for label in ("r6s", "r6o") for name in ("semantic-evidence.json", "imported-modules.json", "source-inventory-before.json", "source-inventory-after.json"))}
    for path in sorted(required):
        if path not in listed: bad(f"evidence_files is missing required artifact {path}")
    attestation = record.get("input_attestation") if isinstance(record.get("input_attestation"), dict) else {}; private = root / "private-inputs"
    for name, field in (("task", "task_sha256"), ("prompt-correction", "prompt_correction_sha256"), ("plan-correction", "plan_correction_sha256")):
        path = private / f"{name}.txt"
        if not path.is_file() or _sha256_file(path) != attestation.get(field): bad(f"retained {name} bytes do not match the top-level attestation")

    expected_sources = {"r6s": (source, "paragon-ux/PDL-Standard-REPL-Harness", R6S_COMMIT, R6S_TREE), "r6o": (control, "paragon-ux/PDL-Standard-R6O", R6O_COMMIT, R6O_TREE)}; inventories: dict[str, dict[str, Any]] = {}
    for label, (source_root, repository, commit, tree) in expected_sources.items():
        baseline = record.get("baselines", {}).get(label, {}) if isinstance(record.get("baselines"), dict) else {}; inventories[label] = {}
        for phase in ("before", "after"):
            inventory = load(root / label / f"source-inventory-{phase}.json", f"{label}/source-inventory-{phase}.json")
            if not isinstance(inventory, dict) or inventory.get("side") != label or inventory.get("root") != str(source_root): bad(f"{label} {phase} source inventory identity is inconsistent"); continue
            entries, digest = inventory.get("entries"), inventory.get("digest_sha256"); inventories[label][phase] = (digest, entries)
            if not isinstance(entries, list) or digest != sha256_json(entries): bad(f"{label} {phase} source inventory digest is not recomputable")
            if digest != baseline.get(f"physical_inventory_{phase}_sha256"): bad(f"{label} {phase} source inventory is not bound to the record")
            if phase == "after":
                try:
                    if physical_inventory(source_root) != (digest, entries): bad(f"{label} source changed after retained after-inventory")
                except (OSError, ValueError) as exc: bad(f"{label} source inventory cannot be recomputed: {exc}")
        if baseline.get("physical_inventory_equal") is True and inventories[label].get("before") != inventories[label].get("after"): bad(f"{label} before/after source inventories differ despite the record equality claim")
        try:
            identity = git_identity(source_root, repository)
            if (identity.get("repository"), identity.get("commit"), identity.get("tree")) != (repository, commit, tree) or identity.get("git_clean") is not True or baseline.get("git_clean_after") is not True: bad(f"{label} Git identity or cleanliness differs from the pinned baseline")
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc: bad(f"{label} Git identity cannot be recomputed: {exc}")

    imported_roots = {"r6s": {"r6s": source}, "r6o": {"r6o": control, "r6s": source}}; anti = record.get("anti_hardcode") if isinstance(record.get("anti_hardcode"), dict) else {}
    for label, roots in imported_roots.items():
        evidence = load(root / label / "imported-modules.json", f"{label}/imported-modules.json")
        if not isinstance(evidence, dict): continue
        if not isinstance(evidence.get("containment_violations"), list) or evidence.get("containment_violations"): bad(f"{label} imported module evidence reports containment violations")
        scan, errors = verify_imported_module_evidence(roots, evidence)
        for error in errors: bad(f"{label} imported module evidence: {error}")
        if scan != anti.get(label): bad(f"{label} imported module scan differs from the accepted anti-hardcode record")

    sessions: list[Any] = []; workspaces: list[Any] = []; workdirs: list[Any] = []
    for label in ("r6s", "r6o"):
        side = record.get(label); evidence = load(root / label / "semantic-evidence.json", f"{label}/semantic-evidence.json")
        if not isinstance(side, dict) or not isinstance(evidence, dict): continue
        if evidence.get("schema_version") != "pdl-live-functional-parity-semantic-evidence-1": bad(f"{label} semantic evidence schema_version is not accepted")
        if evidence.get("side") != label or evidence.get("operations") != side.get("operations"): bad(f"{label} semantic evidence is not bound to the accepted record")
        expected_hashes = {"task": attestation.get("task_sha256"), "prompt_correction": attestation.get("prompt_correction_sha256"), "plan_correction": attestation.get("plan_correction_sha256")}
        if evidence.get("input_hashes") != expected_hashes: bad(f"{label} child-decoded input hashes differ from retained input hashes")
        worker = evidence.get("worker") if isinstance(evidence.get("worker"), dict) else {}; expected_workdir = (root / label / "worker-workdir").resolve(); workdirs.append(worker.get("workdir"))
        if worker.get("workdir") != str(expected_workdir) or worker.get("workdir_sha256") != sha256_text(str(expected_workdir)) or worker.get("configuration_sha256") != record.get("worker_configuration", {}).get("configuration_sha256"): bad(f"{label} worker binding is invalid")
        sessions.append(side.get("session_id")); workspaces.append(side.get("workspace_id")); snapshots = evidence.get("snapshots") if isinstance(evidence.get("snapshots"), dict) else {}
        required_snapshots = {"prompt_before", "prompt_after", "plan_before", "plan_after", "resume_before", "resume_after", "terminal"}
        if set(snapshots) != required_snapshots: bad(f"{label} semantic evidence must retain exactly the required controller snapshots")
        resume = side.get("resume") if isinstance(side.get("resume"), dict) else {}; prompt = side.get("prompt_correction") if isinstance(side.get("prompt_correction"), dict) else {}; plan = side.get("plan_correction") if isinstance(side.get("plan_correction"), dict) else {}
        expected_points = {"prompt_before": (prompt, "before"), "prompt_after": (prompt, "after"), "plan_before": (plan, "before"), "plan_after": (plan, "after"), "resume_before": (resume, "before"), "resume_after": (resume, "after")}; workspace_path: Path | None = None
        for name, snapshot in snapshots.items():
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("controller_state"), dict): bad(f"{label}.{name} snapshot does not retain a controller state"); continue
            if snapshot.get("controller_state_sha256") != sha256_json(snapshot["controller_state"]) or snapshot.get("workspace_path_sha256") != sha256_text(str(snapshot.get("workspace_path", ""))): bad(f"{label}.{name} snapshot hash is invalid")
            if snapshot.get("session_id") != side.get("session_id") or snapshot.get("workspace_id") != side.get("workspace_id"): bad(f"{label}.{name} session/workspace identity is not bound")
            if name in expected_points:
                expected, point_name = expected_points[name]
                if name.startswith("resume_"):
                    point = expected.get(point_name, {})
                    for field in ("workspace_path_sha256", "workspace_id", "session_or_instance_id", "controller_state_sha256", "prompt", "plan", "pending_change_sha256", "pending_input_sha256", "in_flight_action_sha256"):
                        if snapshot.get(field) != point.get(field): bad(f"{label}.{name}.{field} is disconnected from the accepted resume record")
                else:
                    kind = "prompt" if name.startswith("prompt_") else "plan"; artifact = snapshot.get(kind) if isinstance(snapshot.get(kind), dict) else {}
                    if artifact.get("artifact_id") != expected.get(f"artifact_id_{point_name}") or artifact.get("body_sha256") != expected.get(f"body_sha256_{point_name}"): bad(f"{label}.{name} artifact is disconnected from the accepted correction")
            if name == "resume_after": workspace_path = Path(str(snapshot.get("workspace_path", ""))).resolve()
        terminal = snapshots.get("terminal") if isinstance(snapshots.get("terminal"), dict) else {}; terminal_state = terminal.get("controller_state") if isinstance(terminal.get("controller_state"), dict) else {}
        if record.get("status") == "PASS" and terminal_state.get("stage") != "CLOSED_SUCCESS": bad(f"{label} terminal controller state is not CLOSED_SUCCESS")
        if workspace_path is None or not _inside(workspace_path, root / label / "workspace"): bad(f"{label} retained workspace path is outside its run workspace"); continue
        output = workspace_path / "stages" / "50_execution" / "output"; result = side.get("result") if isinstance(side.get("result"), dict) else {}
        try: current_json = json.loads((output / "current.json").read_bytes().decode("utf-8")); current_body = (output / "current.md").read_bytes().decode("utf-8").rstrip("\n")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc: bad(f"{label} persisted execution result is unreadable: {exc}"); current_json, current_body = {}, ""
        if current_json.get("kind") != result.get("execution_kind") or sha256_text(current_body) != result.get("body_sha256"): bad(f"{label} persisted execution result is disconnected from the record")
        if record.get("status") == "PASS" and (current_json.get("kind") != "RESULT" or not current_body): bad(f"{label} persisted execution result is not a nonempty RESULT")
        lifecycle = evidence.get("lifecycle_result_body_sha256")
        if label == "r6o":
            if lifecycle != result.get("body_sha256") or result.get("lifecycle_result_matches_persisted") is not True: bad("r6o lifecycle Result body is not bound to persisted output")
            before_public = snapshots.get("resume_before", {}).get("public_semantic_state") if isinstance(snapshots.get("resume_before"), dict) else None; after_public = snapshots.get("resume_after", {}).get("public_semantic_state") if isinstance(snapshots.get("resume_after"), dict) else None
            if not isinstance(before_public, dict) or not isinstance(after_public, dict) or sha256_json(before_public) != sha256_json(after_public): bad("r6o public projection changed across restore")
        elif lifecycle is not None or result.get("lifecycle_result_matches_persisted") is not None: bad("r6s must not claim an R6O lifecycle Result binding")

        for kind, correction in (("prompt", prompt), ("plan", plan)):
            stage = "10_prompt" if kind == "prompt" else "30_plan"; artifact_output = workspace_path / "stages" / stage / "output"
            for point_name in ("before", "after"):
                artifact_id, body_hash = correction.get(f"artifact_id_{point_name}"), correction.get(f"body_sha256_{point_name}"); version = artifact_output / "versions" / f"{artifact_id}.md"
                try: body = version.read_bytes().decode("utf-8").rstrip("\n")
                except (OSError, UnicodeError) as exc: bad(f"{label} {kind} version is unreadable: {exc}"); continue
                if sha256_text(body) != body_hash: bad(f"{label} {kind} version hash differs from the record")
            try: current_meta = json.loads((artifact_output / "current.json").read_bytes().decode("utf-8")); current_body = (artifact_output / "current.md").read_bytes().decode("utf-8").rstrip("\n")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc: bad(f"{label} current {kind} artifact is unreadable: {exc}"); continue
            if current_meta.get("artifact_id") != correction.get("artifact_id_after") or sha256_text(current_body) != correction.get("body_sha256_after"): bad(f"{label} current {kind} artifact is not the corrected version")
            if kind == "plan" and current_meta.get("source_prompt_id") != prompt.get("artifact_id_after"): bad(f"{label} corrected Plan is not bound to corrected Prompt")
        execution = evidence.get("execution_input") if isinstance(evidence.get("execution_input"), dict) else {}; continuation = side.get("execution_continuation") if isinstance(side.get("execution_continuation"), dict) else {}; conditional = metadata.get("conditional_inputs") if isinstance(metadata.get("conditional_inputs"), dict) else {}
        if conditional.get(label) != execution: bad(f"{label} metadata conditional-input binding differs from child evidence")
        if execution.get("request_observed"):
            request_file = root / f"{label}/execution-request.json"
            if f"{label}/execution-request.json" not in listed or execution.get("request_evidence_path") != f"{label}/execution-request.json" or not request_file.is_file() or execution.get("request_evidence_sha256") != _sha256_file(request_file): bad(f"{label} conditional request evidence is missing or incorrectly bound")
            if execution.get("input_supplied"):
                input_file = private / f"execution-input-{label}.txt"; digest = _sha256_file(input_file) if input_file.is_file() else None
                if f"private-inputs/execution-input-{label}.txt" not in listed or execution.get("input_path") != f"private-inputs/execution-input-{label}.txt" or digest != execution.get("input_sha256") or digest != execution.get("child_decoded_sha256"): bad(f"{label} conditional execution bytes are missing or incorrectly bound")
            elif continuation.get("disposition") != "REQUESTED_INCOMPLETE": bad(f"{label} unsupplied conditional input must be REQUESTED_INCOMPLETE")
        elif execution.get("input_supplied") or execution.get("input_path") or execution.get("request_evidence_path") or (root / f"{label}/execution-request.json").is_file() or continuation.get("disposition") != "NOT_REQUESTED": bad(f"{label} continuation evidence is inconsistent with NOT_REQUESTED")
    status = load(root / "run-status.json", "run-status.json") if (root / "run-status.json").is_file() else None
    if isinstance(status, dict):
        if status.get("run_id") != record.get("run_id"): bad("run-status run_id does not match the record")
        for field, path in (("run_record_sha256", root / "run-record.json"), ("execution_metadata_sha256", root / "execution-metadata.json"), ("structural_validation_sha256", root / "validation" / "structural.json"), ("semantic_validation_sha256", root / "validation" / "semantic.json")):
            actual = _sha256_file(path) if path.is_file() else None
            if status.get(field) != actual: bad(f"run-status {field} is not bound to the retained artifact")
        if status.get("disposition") == "PASS" and (record.get("status") != "PASS" or status.get("pass_markers_authorized") is not True): bad("run-status authorizes PASS markers without complete PASS evidence")
        if status.get("disposition") != "PASS" and status.get("pass_markers_authorized") is True: bad("run-status authorizes PASS markers for a non-PASS disposition")
    if len([value for value in sessions if value is not None]) == 2 and len(set(sessions)) != 2: bad("R6S and R6O reused a session identity")
    if len([value for value in workspaces if value is not None]) == 2 and len(set(workspaces)) != 2: bad("R6S and R6O reused a workspace identity")
    if len([value for value in workdirs if value is not None]) == 2 and len(set(workdirs)) != 2: bad("R6S and R6O reused a worker workdir")
    return findings
