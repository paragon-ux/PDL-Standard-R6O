from __future__ import annotations

"""Current Model binding over the qualified, frozen R6S runtime."""

import hashlib
import json
import os
import tempfile
import sys
import threading
from pathlib import Path
from typing import Any

from r6o.model_binding.base import (
    ArtifactSnapshot,
    LifecycleSnapshot,
    ModelSessionRequest,
    ModelStateSnapshot,
    ReviewSubject,
    StaleProjectionError,
)
from r6o.model_binding.runtime_loader import FrozenRuntimeLoader

_ARTIFACT_STAGE = {"prompt": "10_prompt", "plan": "30_plan"}
_ARTIFACT_TITLE = {
    "prompt": "Authoritative Prompt (PDL.md)",
    "plan": "Authoritative Response Plan (PDL.md)",
}
_REVIEW_STAGES = {"PROMPT_REVIEW", "PLAN_REVIEW", "WAITING_INPUT"}
_TERMINAL_STAGES = {"CLOSED_SUCCESS", "CLOSED_CANCELLED"}


def _canonical_hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _outside_baseline(path: str | Path, baseline_repo: Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if resolved == baseline_repo or _is_within(resolved, baseline_repo):
        raise ValueError(f"{label} must be outside the frozen baseline: {resolved}")
    return resolved


def _parse_ref(artifact_ref: str) -> tuple[str, str]:
    parts = artifact_ref.split(":", 1)
    if len(parts) != 2 or parts[0] not in _ARTIFACT_STAGE or not parts[1]:
        raise ValueError(f"invalid opaque artifact_ref: {artifact_ref!r}")
    return parts[0], parts[1]


class _SessionLocator:
    """Resolve sessions from authoritative workspaces under one safe root."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    @staticmethod
    def _write_marker(resolved: Path, payload: dict[str, Any]) -> None:
        marker = resolved / _SessionLocator.marker_name
        descriptor, temporary_name = tempfile.mkstemp(prefix=".r6o-session-", suffix=".tmp", dir=resolved)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if os.name == "nt":
                import ctypes

                move_file = ctypes.windll.kernel32.MoveFileExW
                move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
                move_file.restype = ctypes.c_int
                if not move_file(str(temporary), str(marker), 0x1 | 0x8):
                    raise ctypes.WinError()
            else:
                os.replace(temporary, marker)
                directory_descriptor = os.open(resolved, os.O_RDONLY)
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
        finally:
            if temporary.exists():
                temporary.unlink()

    marker_name = ".r6o-session.json"

    def register(self, session_id: str, workspace: Path, *, terminal_response: str | None = None) -> None:
        resolved = workspace.resolve()
        if not resolved.is_relative_to(self.workspace_root) or not resolved.is_dir():
            raise ValueError("session workspace must be contained by workspace_root")
        state_path = resolved / "state" / "controller-state.json"
        controllerless = not state_path.is_file()
        if controllerless:
            if terminal_response is None:
                raise RuntimeError("controllerless session requires a terminal response")
        else:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("instance_id") != session_id:
                raise RuntimeError("session workspace identity mismatch")
        payload = {
            "schema_version": "r6o-session-locator-1",
            "session_id": session_id,
            "workspace_id": resolved.name,
            "controllerless": controllerless,
            "terminal_response": terminal_response if controllerless else None,
        }
        self._write_marker(resolved, payload)

    def record_response(self, session_id: str, workspace: Path, response: str, controller_state: dict[str, Any]) -> None:
        resolved = workspace.resolve()
        if not resolved.is_relative_to(self.workspace_root) or not resolved.is_dir():
            raise ValueError("session workspace must be contained by workspace_root")
        if controller_state.get("instance_id") != session_id:
            raise RuntimeError("session workspace identity mismatch")
        self._write_marker(
            resolved,
            {
                "schema_version": "r6o-session-locator-1",
                "session_id": session_id,
                "workspace_id": resolved.name,
                "controllerless": False,
                "terminal_response": None,
                "controller_state_hash": _canonical_hash(controller_state),
                "last_response": response,
            },
        )

    def record(self, workspace: Path) -> dict[str, Any] | None:
        marker = workspace / self.marker_name
        if not marker.is_file():
            return None
        value = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("invalid session locator marker")
        if value.get("schema_version") != "r6o-session-locator-1":
            raise RuntimeError("invalid session locator marker")
        return value

    def resolve(self, session_id: str) -> Path:
        matches: list[Path] = []
        for candidate in self.workspace_root.glob("W-*"):
            resolved = candidate.resolve()
            if not resolved.is_relative_to(self.workspace_root) or not resolved.is_dir():
                continue
            state_path = resolved / "state" / "controller-state.json"
            if state_path.is_file():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(state, dict) and state.get("instance_id") == session_id:
                    matches.append(resolved)
                continue
            try:
                marker = self.record(resolved)
            except (OSError, json.JSONDecodeError, RuntimeError, AttributeError, TypeError):
                continue
            if marker and marker.get("session_id") == session_id:
                matches.append(resolved)
        if len(matches) != 1:
            raise KeyError(f"unknown or ambiguous session: {session_id}")
        return matches[0]


class LocalRuntimeModelBinding:
    """Translate R6S host/controller/workspace state into normalized snapshots."""

    port_version = "r6o-model-port-1"

    def __init__(
        self,
        baseline_repo: str | Path,
        *,
        worker: Any,
        workspace_root: str | Path | None = None,
        run_id: str = "r6o1",
    ) -> None:
        self.baseline_repo = Path(baseline_repo).resolve()
        if workspace_root is None:
            ambient_temp = Path(tempfile.gettempdir()).resolve()
            if ambient_temp == self.baseline_repo or _is_within(ambient_temp, self.baseline_repo):
                raise ValueError("ambient temporary directory must be outside the frozen baseline")
            workspace_root = tempfile.mkdtemp(prefix="pdl-r6o1-workspaces-")
        self.workspace_root = _outside_baseline(workspace_root, self.baseline_repo, "workspace_root")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.worker = worker
        self.run_id = run_id
        self._loader = FrozenRuntimeLoader(self.baseline_repo)
        self._locator = _SessionLocator(self.workspace_root)
        self._host: Any = None
        self._session_id: str | None = None
        self._last_response: str | None = None
        self._detached_snapshot: ModelStateSnapshot | None = None
        self._mutation_lock = threading.RLock()

    def _start_host(self, *, restore_path: Path | None = None) -> Any:
        if self._host is not None or self._detached_snapshot is not None:
            raise RuntimeError("a Model session is already active in this binding")
        if restore_path is not None:
            restore_path = _outside_baseline(restore_path, self.baseline_repo, "restore_path")
        host_type = self._loader.load_host_class()
        self._host = host_type(
            self.baseline_repo,
            worker=self.worker,
            workspace_root=self.workspace_root,
            restore_path=restore_path,
            run_id=self.run_id,
        ).start()
        return self._host

    def start_or_resume(self, request: ModelSessionRequest) -> ModelStateSnapshot:
        if request.mode == "NEW":
            host = self._start_host()
            turn = host.handle(request.task_text)
            self._last_response = turn.text
            snapshot = self._snapshot()
            self._session_id = snapshot.session_id
            workspace = _outside_baseline(host.status()["workspace_path"], self.baseline_repo, "workspace_path")
            if host.status().get("controller_state") is None:
                self._locator.register(snapshot.session_id, workspace, terminal_response=snapshot.model_response)
            return snapshot

        requested = request.resume_session_id
        if requested is None:
            raise ValueError("resume session identity missing")
        restore_path = _outside_baseline(self._locator.resolve(requested), self.baseline_repo, "restore_path")
        state_path = restore_path / "state" / "controller-state.json"
        marker = None if state_path.is_file() else self._locator.record(restore_path)
        if marker and marker.get("controllerless"):
            self._loader.validate_identity()
            response = marker.get("terminal_response")
            if not isinstance(response, str):
                raise RuntimeError("controllerless session marker has no terminal response")
            snapshot = self._controllerless_snapshot(str(marker.get("workspace_id") or ""), response)
            if snapshot.session_id != requested:
                raise RuntimeError("controllerless restored session identity mismatch")
            self._session_id = requested
            self._last_response = response
            self._detached_snapshot = snapshot
            return snapshot
        self._start_host(restore_path=restore_path)
        restored_status = self._host.status()
        restored_state = restored_status.get("controller_state") or {}
        restored_stage = restored_state.get("stage")
        presentation = sys.modules.get("runtime.presentation")
        response_marker = None
        try:
            candidate_marker = self._locator.record(restore_path)
            if (
                candidate_marker
                and not candidate_marker.get("controllerless")
                and candidate_marker.get("session_id") == requested
                and candidate_marker.get("controller_state_hash") == _canonical_hash(restored_state)
                and isinstance(candidate_marker.get("last_response"), str)
            ):
                response_marker = candidate_marker["last_response"]
        except (OSError, json.JSONDecodeError, RuntimeError, AttributeError, TypeError):
            response_marker = None
        if response_marker is not None:
            self._last_response = response_marker
        elif presentation is not None and restored_stage == "PROMPT_REVIEW" and restored_state.get("current_prompt"):
            self._last_response = presentation.prompt_artifact(restored_state["current_prompt"]["body"])
        elif presentation is not None and restored_stage == "PLAN_REVIEW" and restored_state.get("current_plan"):
            self._last_response = presentation.plan_artifact(restored_state["current_plan"]["body"])
        elif restored_stage == "WAITING_INPUT":
            metadata, body = self._execution_material(restore_path)
            if metadata.get("kind") != "REQUEST_INPUT":
                raise RuntimeError("WAITING_INPUT has no matching persisted input request")
            self._last_response = body
        elif restored_stage == "CLOSED_CANCELLED":
            try:
                metadata, body = self._execution_material(restore_path)
            except RuntimeError:
                metadata, body = {}, ""
            if metadata.get("kind") == "BLOCKED_BY_HIGHER_PRIORITY":
                self._last_response = body
            elif presentation is not None:
                self._last_response = presentation.cancelled()
        snapshot = self._snapshot()
        if snapshot.session_id != requested:
            self.close()
            raise RuntimeError(
                f"restored session identity mismatch: {snapshot.session_id} != {requested}"
            )
        self._session_id = requested
        return snapshot

    def _require_session(self, session_id: str) -> Any:
        if self._host is None or self._session_id is None:
            raise RuntimeError("start_or_resume must be called first")
        if session_id != self._session_id:
            raise KeyError(f"unknown session: {session_id}")
        return self._host

    @staticmethod
    def _controllerless_snapshot(workspace_id: str, response: str) -> ModelStateSnapshot:
        if not workspace_id or not response:
            raise RuntimeError("controllerless terminal state is incomplete")
        session_id = "I-" + _canonical_hash(
            {"workspace_id": workspace_id, "terminal_response": response}
        )[:10]
        lifecycle = LifecycleSnapshot(
            review_required=False,
            terminal=True,
            close_allowed=True,
            handoff_ready=False,
            terminal_disposition="CANCELLED",
            result_body=None,
            authorized_handoff_artifacts=(),
        )
        return ModelStateSnapshot(
            session_id=session_id,
            workspace_id=workspace_id,
            model_revision=_canonical_hash(
                {"workspace_id": workspace_id, "model_response": response, "lifecycle": lifecycle.to_dict()}
            ),
            stage="CLOSED_CANCELLED",
            interaction_state="TERMINAL",
            review_subject=None,
            lifecycle=lifecycle,
            model_response=response,
        )

    def _artifact_material(
        self,
        kind: str,
        controller_artifact: dict[str, Any] | None,
    ) -> tuple[str, str, str, dict[str, Any]]:
        if self._host is None:
            raise RuntimeError("Model session is not active")
        workspace = _outside_baseline(
            self._host.status()["workspace_path"], self.baseline_repo, "workspace_path"
        )
        output = workspace / "stages" / _ARTIFACT_STAGE[kind] / "output"
        metadata_path = output / "current.json"
        body_path = output / "current.md"
        for _ in range(3):
            before = (metadata_path.stat(), body_path.stat())
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            body = body_path.read_text(encoding="utf-8").rstrip("\n")
            after = (metadata_path.stat(), body_path.stat())
            if all((a.st_size, a.st_mtime_ns) == (b.st_size, b.st_mtime_ns) for a, b in zip(before, after)):
                break
        else:
            raise StaleProjectionError("artifact changed while it was being read")
        artifact_id = str(metadata["artifact_id"])
        revision = _canonical_hash(
            {
                "artifact_id": artifact_id,
                "metadata": metadata,
                "controller_metadata": controller_artifact or {},
                "body": body,
            }
        )
        if controller_artifact and controller_artifact.get("confirmed") and controller_artifact.get("body") != body:
            raise RuntimeError(f"confirmed {kind} artifact differs from authoritative controller body")
        return artifact_id, revision, body, metadata

    @staticmethod
    def _execution_material(workspace: Path) -> tuple[dict[str, Any], str]:
        output = workspace / "stages" / "50_execution" / "output"
        metadata_path = output / "current.json"
        body_path = output / "current.md"
        if not metadata_path.is_file() or not body_path.is_file():
            raise RuntimeError("persisted execution output is incomplete")
        for _ in range(3):
            before = (metadata_path.stat(), body_path.stat())
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            body = body_path.read_text(encoding="utf-8").rstrip("\n")
            after = (metadata_path.stat(), body_path.stat())
            if all((a.st_size, a.st_mtime_ns) == (b.st_size, b.st_mtime_ns) for a, b in zip(before, after)):
                if not isinstance(metadata, dict) or not body:
                    raise RuntimeError("persisted execution output is invalid")
                return metadata, body
        raise RuntimeError("persisted execution output changed while being read")

    def _reconstructible_stage_response(self, status: dict[str, Any]) -> str | None:
        state = status.get("controller_state") or {}
        stage = state.get("stage")
        presentation = sys.modules.get("runtime.presentation")
        if presentation is not None and stage == "PROMPT_REVIEW" and state.get("current_prompt"):
            return presentation.prompt_artifact(state["current_prompt"]["body"])
        if presentation is not None and stage == "PLAN_REVIEW" and state.get("current_plan"):
            return presentation.plan_artifact(state["current_plan"]["body"])
        if stage in {"WAITING_INPUT", "CLOSED_SUCCESS", "CLOSED_CANCELLED"}:
            try:
                metadata, body = self._execution_material(Path(status["workspace_path"]))
            except RuntimeError:
                metadata, body = {}, ""
            if stage == "WAITING_INPUT" and metadata.get("kind") == "REQUEST_INPUT":
                return body
            if stage == "CLOSED_SUCCESS" and metadata.get("kind") == "RESULT":
                return body
            if stage == "CLOSED_CANCELLED" and metadata.get("kind") == "BLOCKED_BY_HIGHER_PRIORITY":
                return body
            if stage == "CLOSED_CANCELLED" and presentation is not None:
                return presentation.cancelled()
        return None

    @staticmethod
    def _review_kind(stage: str, state: dict[str, Any]) -> str | None:
        if stage == "PROMPT_REVIEW":
            return "prompt"
        if stage in {"PLAN_REVIEW", "WAITING_INPUT"} and state.get("current_plan"):
            return "plan"
        return None

    def _snapshot(self) -> ModelStateSnapshot:
        if self._host is None:
            raise RuntimeError("Model session is not active")
        status = self._host.status()
        state = status.get("controller_state")
        if not isinstance(state, dict):
            workspace_id = str(status.get("workspace_id") or "")
            if not workspace_id or self._last_response is None:
                raise RuntimeError("authoritative controller state is unavailable")
            return self._controllerless_snapshot(workspace_id, self._last_response)
        session_id = str(state.get("instance_id") or "")
        if not session_id:
            raise RuntimeError("authoritative session identity is unavailable")
        stage = str(state.get("stage") or "UNKNOWN")
        kind = self._review_kind(stage, state)
        subject: ReviewSubject | None = None
        artifact_revision: str | None = None
        if kind:
            controller_artifact = state.get(f"current_{kind}")
            artifact_id, artifact_revision, _, _ = self._artifact_material(kind, controller_artifact)
            subject = ReviewSubject(
                artifact_ref=f"{kind}:{artifact_id}",
                artifact_revision=artifact_revision,
                artifact_kind=kind,
                title=_ARTIFACT_TITLE[kind],
            )
        if stage in _REVIEW_STAGES:
            interaction = "REVIEW_REQUIRED"
        elif stage in _TERMINAL_STAGES:
            interaction = "TERMINAL"
        elif stage == "UNKNOWN":
            interaction = "INACTIVE"
        else:
            interaction = "WORKING"
        terminal_disposition = None
        if stage == "CLOSED_SUCCESS":
            terminal_disposition = "HOST_HANDOFF"
        elif stage == "CLOSED_CANCELLED":
            terminal_disposition = "CANCELLED"
        authorized: list[ArtifactSnapshot] = []
        if stage == "CLOSED_SUCCESS":
            for authorized_kind in ("prompt", "plan"):
                controller_artifact = state.get(f"current_{authorized_kind}")
                if not controller_artifact:
                    continue
                artifact_id, revision, authorized_body, _ = self._artifact_material(authorized_kind, controller_artifact)
                authorized.append(
                    ArtifactSnapshot(
                        artifact_ref=f"{authorized_kind}:{artifact_id}",
                        artifact_revision=revision,
                        artifact_kind=authorized_kind,
                        title=_ARTIFACT_TITLE[authorized_kind],
                        body=authorized_body,
                        capabilities={"copy": True, "open_external": True},
                    )
                )
        result_body = self._last_response
        if stage == "CLOSED_SUCCESS":
            if len(authorized) != 2:
                raise RuntimeError("terminal Model output is incomplete; HOST_HANDOFF is not authorized")
            execution_metadata, persisted_result = self._execution_material(Path(status["workspace_path"]))
            if execution_metadata.get("kind") != "RESULT":
                raise RuntimeError("terminal execution outcome is not a successful RESULT")
            if result_body is not None and result_body != persisted_result:
                raise RuntimeError("terminal Model response differs from persisted execution output")
            result_body = persisted_result
        lifecycle = LifecycleSnapshot(
            review_required=stage in _REVIEW_STAGES,
            terminal=stage in _TERMINAL_STAGES,
            close_allowed=stage in _REVIEW_STAGES or stage in _TERMINAL_STAGES,
            handoff_ready=stage == "CLOSED_SUCCESS",
            terminal_disposition=terminal_disposition,
            result_body=result_body if stage == "CLOSED_SUCCESS" else None,
            authorized_handoff_artifacts=tuple(authorized),
        )
        model_revision = _canonical_hash(
            {
                "controller_state": state,
                "workspace_id": status.get("workspace_id"),
                "review_artifact_revision": artifact_revision,
                "model_response": result_body if stage == "CLOSED_SUCCESS" else self._last_response,
                "lifecycle_result_body": lifecycle.result_body,
                "authorized_handoff_artifacts": [item.to_dict() for item in authorized],
            }
        )
        return ModelStateSnapshot(
            session_id=session_id,
            workspace_id=str(status["workspace_id"]) if status.get("workspace_id") else None,
            model_revision=model_revision,
            stage=stage,
            interaction_state=interaction,
            review_subject=subject,
            lifecycle=lifecycle,
            model_response=result_body if stage == "CLOSED_SUCCESS" else self._last_response,
        )

    def read_state(self, session_id: str) -> ModelStateSnapshot:
        if self._detached_snapshot is not None:
            if session_id != self._session_id:
                raise KeyError(f"unknown session: {session_id}")
            return self._detached_snapshot
        self._require_session(session_id)
        return self._snapshot()

    def read_artifact(
        self,
        session_id: str,
        artifact_ref: str,
        expected_revision: str | None = None,
    ) -> ArtifactSnapshot:
        self._require_session(session_id)
        kind, requested_id = _parse_ref(artifact_ref)
        status = self._host.status()
        state = status.get("controller_state") or {}
        controller_artifact = state.get(f"current_{kind}")
        artifact_id, revision, body, _ = self._artifact_material(kind, controller_artifact)
        if requested_id not in {"current", artifact_id}:
            raise ValueError(
                f"artifact identity mismatch: {artifact_ref!r} vs {artifact_id!r}"
            )
        if expected_revision is not None and expected_revision != revision:
            raise StaleProjectionError(
                f"artifact revision {expected_revision} != {revision}"
            )
        return ArtifactSnapshot(
            artifact_ref=f"{kind}:{artifact_id}",
            artifact_revision=revision,
            artifact_kind=kind,
            title=_ARTIFACT_TITLE[kind],
            body=body,
            capabilities={"copy": True, "open_external": True},
        )

    def submit_user_message(
        self,
        session_id: str,
        text: str,
        expected_revision: str | None,
    ) -> ModelStateSnapshot:
        with self._mutation_lock:
            return self._submit_user_message_locked(session_id, text, expected_revision)

    def _submit_user_message_locked(
        self,
        session_id: str,
        text: str,
        expected_revision: str | None,
    ) -> ModelStateSnapshot:
        host = self._require_session(session_id)
        current = self._snapshot()
        if expected_revision is not None and expected_revision != current.model_revision:
            raise StaleProjectionError(
                f"revision {expected_revision} != {current.model_revision}"
            )
        immediately_before_mutation = self._snapshot()
        if expected_revision is not None and expected_revision != immediately_before_mutation.model_revision:
            raise StaleProjectionError("authoritative state changed before mutation")
        subject = immediately_before_mutation.review_subject
        workspace = host.engine.workspace
        original_sync = workspace.sync_unconfirmed_edit
        controller = host.engine.controller
        original_apply = controller.apply_review_decision if controller is not None else None
        mutation_artifact_id = _parse_ref(subject.artifact_ref)[1] if subject is not None else None
        mutation_artifact_revision = subject.artifact_revision if subject is not None else None

        def assert_review_subject_current(message: str) -> None:
            if subject is None:
                return
            controller_artifact = host.status()["controller_state"].get(f"current_{subject.artifact_kind}")
            actual_id, revision, _, _ = self._artifact_material(subject.artifact_kind, controller_artifact)
            if actual_id != mutation_artifact_id or revision != mutation_artifact_revision:
                raise StaleProjectionError(
                    f"{message}: {actual_id}/{revision} != {mutation_artifact_id}/{mutation_artifact_revision}"
                )

        def guarded_sync(kind: str, artifact_id: str, controller_body: str) -> str:
            nonlocal mutation_artifact_id, mutation_artifact_revision
            if subject is None or kind != subject.artifact_kind:
                raise StaleProjectionError("review subject changed before mutation")
            controller_artifact = host.status()["controller_state"].get(f"current_{kind}")
            actual_id, revision, body, metadata = self._artifact_material(kind, controller_artifact)
            if actual_id != artifact_id or revision != subject.artifact_revision:
                raise StaleProjectionError("review artifact changed at semantic synchronization")
            original_read = workspace.read_artifact

            def captured_read(requested_kind: str):
                if requested_kind == kind:
                    return dict(metadata), body
                return original_read(requested_kind)

            workspace.read_artifact = captured_read
            try:
                synchronized = original_sync(kind, artifact_id, controller_body)
            finally:
                workspace.read_artifact = original_read
            anticipated_controller = dict(controller_artifact or {})
            anticipated_controller["body"] = synchronized.strip()
            final_id, final_revision, final_body, _ = self._artifact_material(kind, anticipated_controller)
            if final_id != actual_id or final_body != body:
                raise StaleProjectionError("review artifact changed during semantic synchronization")
            mutation_artifact_id = final_id
            mutation_artifact_revision = final_revision
            return synchronized

        def guarded_apply(decision: Any, semantic_source: str) -> Any:
            assert original_apply is not None
            assert_review_subject_current("review artifact changed before controller mutation")
            return original_apply(decision, semantic_source)

        if subject is not None:
            workspace.sync_unconfirmed_edit = guarded_sync
            controller.apply_review_decision = guarded_apply
        try:
            try:
                turn = host.handle(text)
            except RuntimeError as exc:
                if str(exc).startswith("StaleProjectionError:"):
                    raise StaleProjectionError(str(exc).split(":", 1)[1].strip()) from exc
                raise
        finally:
            workspace.sync_unconfirmed_edit = original_sync
            if original_apply is not None:
                controller.apply_review_decision = original_apply
        self._last_response = turn.text
        status_after = host.status()
        controller_state_after = status_after.get("controller_state")
        if (
            turn.text is not None
            and isinstance(controller_state_after, dict)
            and turn.text != self._reconstructible_stage_response(status_after)
        ):
            response_workspace = _outside_baseline(
                status_after["workspace_path"], self.baseline_repo, "workspace_path"
            )
            self._locator.record_response(
                str(controller_state_after["instance_id"]),
                response_workspace,
                turn.text,
                controller_state_after,
            )
        snapshot = self._snapshot()
        if snapshot.session_id != self._session_id:
            self._session_id = snapshot.session_id
        return snapshot

    def finalize(self, session_id: str) -> ModelStateSnapshot:
        snapshot = self.read_state(session_id)
        self.close()
        return snapshot

    def close(self) -> None:
        if self._host is not None:
            self._host.close()
            self._host = None
        self._session_id = None
        self._last_response = None
        self._detached_snapshot = None
