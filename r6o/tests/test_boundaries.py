from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.runtime_loader import FrozenRuntimeLoader
from r6o.viewmodel.dispatcher import handle_input
from r6o.viewmodel.projection import build_focus_projection_from_port

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parent
G06 = "Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers."


def _physical_inventory(root: Path) -> dict[str, tuple[int, int, str]]:
    inventory = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file() and ".git" not in item.parts):
        stat = path.stat()
        inventory[path.relative_to(root).as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return inventory


def test_viewmodel_has_no_controller_state_or_runtime_imports() -> None:
    for path in sorted((PACKAGE / "viewmodel").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "controller_state" not in source
        for forbidden in ("host.app", "session_engine", "mechanical_controller", "from runtime", "from controller", "import runtime", "import controller"):
            assert forbidden not in source, f"{path.name} contains {forbidden!r}"


def test_lifecycle_has_no_filesystem_persistence() -> None:
    source = (PACKAGE / "viewmodel" / "lifecycle.py").read_text(encoding="utf-8")
    for forbidden in ("Path", "mkdir", "tempfile", "os.replace", "fsync", "unlink", "open("):
        assert forbidden not in source


def test_no_view_technology_dependency_in_viewmodel() -> None:
    for path in sorted((PACKAGE / "viewmodel").glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        assert "tui" not in source and "sidecar" not in source


def test_public_contracts_have_no_path_property() -> None:
    for path in sorted((PACKAGE / "contracts").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        for key in (schema.get("properties") or {}):
            assert "path" not in key.lower(), f"{path.name} exposes {key!r}"


def test_fake_wait_operation_is_absent() -> None:
    production = [path for path in PACKAGE.rglob("*.py") if "tests" not in path.parts]
    assert all("wait_for_revision" not in path.read_text(encoding="utf-8") for path in production)


def test_clean_production_loader_import_in_fresh_subprocess(baseline_repo) -> None:
    script = f"""
import sys
sys.path.insert(0, {str(REPO)!r})
from r6o.model_binding.runtime_loader import FrozenRuntimeLoader
host = FrozenRuntimeLoader({str(baseline_repo)!r}).load_host_class()
assert host.__module__ == 'host.app'
print(host.__module__)
"""
    process = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert process.stdout.strip() == "host.app"


def test_wrong_preinstalled_host_module_fails_closed_in_subprocess(tmp_path, baseline_repo) -> None:
    fake = tmp_path / "host.py"
    fake.write_text("# collision\n", encoding="utf-8")
    script = f"""
import sys, types
sys.path.insert(0, {str(REPO)!r})
fake = types.ModuleType('host')
fake.__file__ = {str(fake)!r}
fake.__path__ = [{str(tmp_path)!r}]
sys.modules['host'] = fake
from r6o.model_binding.runtime_loader import FrozenRuntimeLoader
try:
    FrozenRuntimeLoader({str(baseline_repo)!r}).load_host_class()
except RuntimeError as exc:
    assert 'collision' in str(exc)
else:
    raise AssertionError('collision accepted')
"""
    process = subprocess.run([sys.executable, "-I", "-c", script], cwd=REPO, capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr


def test_loader_module_provenance_and_no_baseline_physical_writes(baseline_repo) -> None:
    before = _physical_inventory(baseline_repo)
    host_type = FrozenRuntimeLoader(baseline_repo).load_host_class()
    assert Path(sys.modules[host_type.__module__].__file__).resolve().is_relative_to(baseline_repo)
    for name in ("runtime.session_engine", "controller.mechanical_controller"):
        assert Path(sys.modules[name].__file__).resolve().is_relative_to(baseline_repo)
    assert _physical_inventory(baseline_repo) == before


@pytest.mark.parametrize("relative", [Path("."), Path("runs"), Path("runs/workspaces")])
def test_workspace_root_inside_baseline_is_rejected(relative, baseline_repo, recorded_worker_factory) -> None:
    with pytest.raises(ValueError):
        LocalRuntimeModelBinding(
            baseline_repo,
            worker=recorded_worker_factory(["G06"]),
            workspace_root=baseline_repo / relative,
        )


def test_workspace_symlink_into_baseline_is_rejected(tmp_path, baseline_repo, recorded_worker_factory) -> None:
    link = tmp_path / "baseline-link"
    try:
        link.symlink_to(baseline_repo, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(ValueError):
        LocalRuntimeModelBinding(baseline_repo, worker=recorded_worker_factory(["G06"]), workspace_root=link)


def test_cwd_baseline_still_allocates_workspace_outside_baseline(monkeypatch, baseline_repo, recorded_worker_factory) -> None:
    monkeypatch.chdir(baseline_repo)
    binding = LocalRuntimeModelBinding(baseline_repo, worker=recorded_worker_factory(["G06"]))
    snapshot = binding.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06))
    workspace = Path(binding._host.status()["workspace_path"]).resolve()
    assert not workspace.is_relative_to(baseline_repo)
    assert snapshot.workspace_id.startswith("W-")
    binding.close()


def test_ambient_temp_inside_baseline_is_rejected_before_physical_write(
    monkeypatch, baseline_repo, recorded_worker_factory
) -> None:
    before = _physical_inventory(baseline_repo)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(baseline_repo))
    with pytest.raises(ValueError, match="temporary directory"):
        LocalRuntimeModelBinding(baseline_repo, worker=recorded_worker_factory(["G06"]))
    with pytest.raises(RuntimeError, match="import-cache"):
        FrozenRuntimeLoader(baseline_repo).load_host_class()
    assert _physical_inventory(baseline_repo) == before


def test_verifier_rejects_ambient_temp_inside_baseline_before_write(baseline_repo) -> None:
    before = _physical_inventory(baseline_repo)
    environment = dict(os.environ)
    environment.update(
        {
            "TEMP": str(baseline_repo),
            "TMP": str(baseline_repo),
            "TMPDIR": str(baseline_repo),
            "PDL_R6S_BASELINE_REPO": str(baseline_repo),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "verify_r6o1.py")],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "ambient temporary directory" in result.stdout
    assert _physical_inventory(baseline_repo) == before


def test_public_resume_cannot_escape_workspace_root(tmp_path, baseline_repo, recorded_worker_factory) -> None:
    root = tmp_path / "safe"
    root.mkdir()
    (root / ".r6o-session-locator.json").write_text(json.dumps({"I-malicious": str(tmp_path / "outside")}), encoding="utf-8")
    binding = LocalRuntimeModelBinding(baseline_repo, worker=recorded_worker_factory(["G06"]), workspace_root=root)
    with pytest.raises(KeyError):
        binding.start_or_resume(ModelSessionRequest(request_id="resume", resume_session_id="I-malicious"))


def test_loader_rejects_dirty_tracked_or_untracked_importable_oracle_bytes(tmp_path, baseline_repo) -> None:
    for case in ("tracked", "untracked", "root-shadow", "uppercase-shadow"):
        clone = tmp_path / case
        subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(baseline_repo), str(clone)], check=True)
        if case == "tracked":
            with (clone / "host" / "app.py").open("a", encoding="utf-8") as handle:
                handle.write("\n# dirty oracle\n")
            expected = "tracked working tree"
        elif case == "untracked":
            (clone / "host" / "injected.py").write_text("VALUE = 'untrusted'\n", encoding="utf-8")
            expected = "untracked importable"
        elif case == "root-shadow":
            (clone / "uuid.py").write_text("raise RuntimeError('shadow executed')\n", encoding="utf-8")
            expected = "untracked importable"
        else:
            (clone / "uuid.PY").write_text("raise RuntimeError('shadow executed')\n", encoding="utf-8")
            expected = "untracked importable"
        with pytest.raises(RuntimeError, match=expected):
            FrozenRuntimeLoader(clone).validate_identity()


def test_loader_rejects_untracked_importable_directory_symlink(tmp_path, baseline_repo) -> None:
    clone = tmp_path / "symlink-clone"
    external = tmp_path / "external-uuid"
    external.mkdir()
    (external / "__init__.py").write_text("raise RuntimeError('shadow executed')\n", encoding="utf-8")
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(baseline_repo), str(clone)], check=True)
    try:
        (clone / "uuid").symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    with pytest.raises(RuntimeError, match="untracked importable baseline symlink"):
        FrozenRuntimeLoader(clone).validate_identity()


def test_public_start_consumes_task_and_projects_real_workspace(tmp_path, baseline_repo, operation_worker_factory) -> None:
    worker = operation_worker_factory("G06")
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "root")
    snapshot = binding.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06))
    assert worker.calls == ["DRAFT_PROMPT"]
    assert snapshot.stage == "PROMPT_REVIEW"
    assert snapshot.session_id.startswith("I-")
    assert snapshot.workspace_id.startswith("W-")
    binding.close()


def test_public_resume_by_session_id(tmp_path, baseline_repo, operation_worker_factory) -> None:
    root = tmp_path / "root"
    first = LocalRuntimeModelBinding(baseline_repo, worker=operation_worker_factory("G06"), workspace_root=root)
    started = first.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06))
    first.close()
    actual_workspace = root / started.workspace_id
    (actual_workspace / ".r6o-session.json").write_text("not-json\n", encoding="utf-8")
    bad_workspace = root / "W-invalid-marker"
    bad_workspace.mkdir()
    (bad_workspace / ".r6o-session.json").write_text("[]\n", encoding="utf-8")
    resumed_binding = LocalRuntimeModelBinding(baseline_repo, worker=operation_worker_factory("G06"), workspace_root=root)
    resumed = resumed_binding.start_or_resume(ModelSessionRequest(request_id="resume", resume_session_id=started.session_id))
    assert resumed.session_id == started.session_id
    assert resumed.workspace_id == started.workspace_id
    assert resumed.model_revision == started.model_revision
    resumed_binding.close()


def test_new_task_transition_rebinds_public_session_identity(
    tmp_path, baseline_repo, operation_worker_factory
) -> None:
    worker = operation_worker_factory("G06")
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "workspaces")
    started = binding.start_or_resume(ModelSessionRequest(request_id="start", task_text=G06))
    old_projection = build_focus_projection_from_port(binding, started.session_id)
    worker.responses["INTERPRET_PROMPT_REVIEW"] = '{"kind":"NEW_TASK"}'
    result = handle_input(
        {
            "schema_version": "r6o-input-envelope-1",
            "session_id": started.session_id,
            "source": "HOST_COMPOSER_TEXT",
            "model_revision": old_projection["model_revision"],
            "text": "Start an independent task about locking retries.",
            "action_id": None,
            "projection_id": None,
        },
        binding,
    )
    assert result["result_type"] == "REVISION", result
    new_session = result["projection"]["session_id"]
    assert new_session != started.session_id
    assert binding.read_state(new_session).session_id == new_session
    with pytest.raises(KeyError, match="unknown session"):
        binding.read_state(started.session_id)
    binding.close()


def test_public_new_preserves_controllerless_blocked_response(
    tmp_path, baseline_repo, operation_worker_factory
) -> None:
    worker = operation_worker_factory("G06")
    worker.responses["DRAFT_PROMPT"] = json.dumps(
        {
            "kind": "TASK_BLOCKED_BY_HIGHER_PRIORITY",
            "response": "Blocked by policy.",
            "blocking_basis": "PROVIDER_PLATFORM_SAFETY_PRIVACY_PERMISSION_OR_TOOL",
        }
    )
    binding = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "workspaces")
    snapshot = binding.start_or_resume(ModelSessionRequest(request_id="start", task_text=G06))
    projection = build_focus_projection_from_port(binding, snapshot.session_id)
    assert projection["stage"] == "CLOSED_CANCELLED"
    assert projection["model_response"] == "Blocked by policy."
    assert projection["lifecycle"]["handoff_ready"] is False
    binding.close()
    resumed_binding = LocalRuntimeModelBinding(
        baseline_repo, worker=operation_worker_factory("G06"), workspace_root=tmp_path / "workspaces"
    )
    resumed = resumed_binding.start_or_resume(
        ModelSessionRequest(request_id="resume", resume_session_id=snapshot.session_id)
    )
    assert resumed == snapshot
    with pytest.raises(RuntimeError, match="already active"):
        resumed_binding.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06))
    resumed_binding.close()


def test_detached_resume_still_validates_exact_oracle(
    tmp_path, baseline_repo, operation_worker_factory, monkeypatch
) -> None:
    root = tmp_path / "workspaces"
    worker = operation_worker_factory("G06")
    worker.responses["DRAFT_PROMPT"] = json.dumps(
        {
            "kind": "TASK_BLOCKED_BY_HIGHER_PRIORITY",
            "response": "Blocked by policy.",
            "blocking_basis": "PROVIDER_PLATFORM_SAFETY_PRIVACY_PERMISSION_OR_TOOL",
        }
    )
    first = LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=root)
    snapshot = first.start_or_resume(ModelSessionRequest(request_id="new", task_text=G06))
    first.close()
    second = LocalRuntimeModelBinding(baseline_repo, worker=operation_worker_factory("G06"), workspace_root=root)
    monkeypatch.setattr(
        second._loader,
        "validate_identity",
        lambda: (_ for _ in ()).throw(RuntimeError("frozen baseline tracked working tree differs")),
    )
    with pytest.raises(RuntimeError, match="tracked working tree"):
        second.start_or_resume(ModelSessionRequest(request_id="resume", resume_session_id=snapshot.session_id))


def test_public_api_tests_do_not_use_private_session_identity() -> None:
    for path in sorted((PACKAGE / "tests").glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        assert "._session_id" not in path.read_text(encoding="utf-8"), path.name
