from __future__ import annotations

"""H2-E2 G06 coordination over accepted Model, ViewModel, and Sidecar ports."""

import time
from collections.abc import Callable
from typing import Any, Protocol

from r6o.model_binding.base import ModelPort, ModelSessionRequest
from r6o.viewmodel.dispatcher import handle_input, validate_command_result
from r6o.viewmodel.projection import build_focus_projection_from_port


TERMINAL_STAGE = "CLOSED_SUCCESS"
_EXPECTED_STAGES = {
    "PROMPT_REVIEW": ("prompt", "confirm_prompt"),
    "PLAN_REVIEW": ("plan", "confirm_plan"),
}
_TRANSITIONS = {
    "START": ("G06-T0-CODEX", "G06-S1", "PROMPT_REVIEW"),
    "confirm_prompt": ("G06-T1-CODEX", "G06-S2", "PLAN_REVIEW"),
    "confirm_plan": ("G06-T2-CODEX", "G06-S3", TERMINAL_STAGE),
}


class H2E2IntegrationError(RuntimeError):
    """A fail-closed H2-E2 presentation integration error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SidecarPresentation(Protocol):
    """Narrow E2 presentation boundary implemented by the actual D2 binding."""

    def present(self, projection: dict[str, Any], *, initial: bool = False) -> dict[str, Any]: ...


TransitionCallback = Callable[[dict[str, Any]], None]
InputHandler = Callable[[dict[str, Any], ModelPort], dict[str, Any]]
ProjectionBuilder = Callable[[ModelPort, str], dict[str, Any]]


def _primary_action(projection: dict[str, Any]) -> str | None:
    actions = projection.get("actions")
    if not isinstance(actions, list) or not actions:
        return None
    first = actions[0]
    if not isinstance(first, dict) or first.get("enabled") is not True:
        return None
    action_id = first.get("action_id")
    return action_id if isinstance(action_id, str) and action_id else None


def _validate_g06_projection(
    projection: dict[str, Any],
    expected_stage: str,
    *,
    previous: dict[str, Any] | None = None,
) -> None:
    if not isinstance(projection, dict):
        raise H2E2IntegrationError("INVALID_RETURNED_PROJECTION")
    if projection.get("schema_version") != "r6o-focus-projection-1":
        raise H2E2IntegrationError("INVALID_RETURNED_PROJECTION")
    if projection.get("stage") != expected_stage:
        raise H2E2IntegrationError(
            f"UNEXPECTED_G06_STAGE:{projection.get('stage')}:{expected_stage}"
        )
    lifecycle = projection.get("lifecycle")
    if not isinstance(lifecycle, dict):
        raise H2E2IntegrationError("INVALID_RETURNED_PROJECTION")

    if expected_stage == TERMINAL_STAGE:
        if (
            projection.get("artifact") is not None
            or projection.get("actions") != []
            or lifecycle.get("terminal") is not True
            or lifecycle.get("terminal_disposition") != "HOST_HANDOFF"
        ):
            raise H2E2IntegrationError("INVALID_G06_TERMINAL_PROJECTION")
        return

    expected_artifact_kind, expected_action = _EXPECTED_STAGES[expected_stage]
    artifact = projection.get("artifact")
    if not isinstance(artifact, dict):
        raise H2E2IntegrationError("INVALID_RETURNED_PROJECTION")
    body = artifact.get("body")
    if (
        artifact.get("artifact_kind") != expected_artifact_kind
        or not isinstance(artifact.get("artifact_ref"), str)
        or not artifact["artifact_ref"]
        or not isinstance(artifact.get("artifact_revision"), str)
        or not artifact["artifact_revision"]
        or not isinstance(body, str)
        or not body.strip()
        or lifecycle.get("terminal") is not False
        or _primary_action(projection) != expected_action
    ):
        raise H2E2IntegrationError("INVALID_RETURNED_PROJECTION")
    if previous is not None and expected_stage == "PLAN_REVIEW":
        previous_artifact = previous.get("artifact")
        if isinstance(previous_artifact, dict) and (
            artifact["artifact_ref"], artifact["artifact_revision"]
        ) == (
            previous_artifact.get("artifact_ref"),
            previous_artifact.get("artifact_revision"),
        ):
            raise H2E2IntegrationError("PLAN_ARTIFACT_NOT_NEW")


def build_structured_action_envelope(
    projection: dict[str, Any], action_id: str
) -> dict[str, Any]:
    """Build the accepted structured-action shape without semantic text."""

    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": projection["session_id"],
        "source": "STRUCTURED_ACTION",
        "model_revision": projection["model_revision"],
        "text": None,
        "action_id": action_id,
        "projection_id": projection["projection_id"],
    }


class AttachedCodexSidecarPresentation:
    """Adapt the accepted D2 binding to the narrow E2 presentation boundary."""

    def __init__(self, binding: Any) -> None:
        self.binding = binding
        self._terminal_dismissed = False

    def _action_item(self, action_id: str) -> Any:
        object_name = f"reviewAction_{action_id}"
        try:
            pending = [self.binding.sidecar.window.contentItem()]
            while pending:
                item = pending.pop()
                if str(item.objectName()) == object_name:
                    return item
                pending.extend(item.childItems())
        except Exception as exc:
            raise H2E2IntegrationError("SIDECAR_PRIMARY_ACTION_FOCUS_UNVERIFIED") from exc
        raise H2E2IntegrationError("SIDECAR_PRIMARY_ACTION_FOCUS_UNVERIFIED")

    def _verify_primary_focus(self, action_id: str) -> None:
        bridge = getattr(self.binding.sidecar, "bridge", None)
        expected_actions = getattr(bridge, "actions", None)
        if not isinstance(expected_actions, list):
            action = self._action_item(action_id)
            if not bool(action.property("activeFocus")):
                raise H2E2IntegrationError("SIDECAR_PRIMARY_ACTION_FOCUS_UNVERIFIED")
            return
        expected_ids = tuple(item.get("action_id") for item in expected_actions)
        if not expected_ids or expected_ids[0] != action_id or any(
            not isinstance(item, str) or not item for item in expected_ids
        ):
            raise H2E2IntegrationError("SIDECAR_PRIMARY_ACTION_FOCUS_UNVERIFIED")
        try:
            from PySide6.QtCore import QCoreApplication, QEventLoop
        except Exception as exc:
            raise H2E2IntegrationError("SIDECAR_PRIMARY_ACTION_FOCUS_UNVERIFIED") from exc

        previous: tuple[tuple[Any, ...], ...] | None = None
        stable_observations = 0
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            app = QCoreApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.AllEvents, 25)
            pending = [self.binding.sidecar.window.contentItem()]
            found: dict[str, Any] = {}
            duplicate = False
            while pending:
                item = pending.pop()
                name = str(item.objectName())
                if name.startswith("reviewAction_"):
                    found_id = name.removeprefix("reviewAction_")
                    if found_id in found:
                        duplicate = True
                    found[found_id] = item
                pending.extend(item.childItems())
            snapshot: tuple[tuple[Any, ...], ...] | None = None
            if not duplicate and set(found) == set(expected_ids):
                ordered_ids = tuple(
                    item_id
                    for item_id, _item in sorted(
                        found.items(), key=lambda pair: float(pair[1].y())
                    )
                )
                primary = found[action_id]
                if (
                    ordered_ids == expected_ids
                    and bool(primary.property("activeFocus"))
                    and all(
                        bool(item.isEnabled())
                        and bool(item.isVisible())
                        and float(item.width()) > 0
                        and float(item.height()) > 0
                        for item in found.values()
                    )
                ):
                    snapshot = tuple(
                        (
                            item_id,
                            float(found[item_id].x()),
                            float(found[item_id].y()),
                            float(found[item_id].width()),
                            float(found[item_id].height()),
                        )
                        for item_id in expected_ids
                    )
            if snapshot is not None and snapshot == previous:
                stable_observations += 1
                if stable_observations >= 2:
                    return
            else:
                stable_observations = 0
            previous = snapshot
            time.sleep(0.01)
        raise H2E2IntegrationError("SIDECAR_PRIMARY_ACTION_FOCUS_UNVERIFIED")

    def present(self, projection: dict[str, Any], *, initial: bool = False) -> dict[str, Any]:
        stage = projection.get("stage")
        if stage == TERMINAL_STAGE:
            if initial or self._terminal_dismissed:
                raise H2E2IntegrationError("TERMINAL_CLOSE_NOT_EXACTLY_ONCE")
            if self.binding.sidecar.render(projection):
                raise H2E2IntegrationError("TERMINAL_PROJECTION_REMAINED_VISIBLE")
            focus = self.binding.close_view_and_verify_focus()
            if focus.get("sidecar_visible") is not False:
                raise H2E2IntegrationError("TERMINAL_SIDECAR_NOT_DISMISSED")
            self._terminal_dismissed = True
            return {
                "sidecar_visibility": "DISMISSED",
                "focus_owner": "ACTUAL_CODEX_COMPOSER",
                "focus_return": focus,
            }

        if self._terminal_dismissed:
            raise H2E2IntegrationError("ACTIVE_PROJECTION_AFTER_TERMINAL")
        if initial:
            attachment = self.binding.attach(projection)
        else:
            if not self.binding.sidecar.render(projection):
                raise H2E2IntegrationError("ACTIVE_PROJECTION_REJECTED")
            attachment = self.binding.observe()
        action_id = _primary_action(projection)
        if action_id is None:
            raise H2E2IntegrationError("ACTIVE_PROJECTION_HAS_NO_PRIMARY_ACTION")
        self._verify_primary_focus(action_id)
        return {
            "sidecar_visibility": "VISIBLE_STANDARD",
            "focus_owner": f"SIDECAR_ACTION_{action_id.upper()}",
            "attachment": attachment,
        }


class CodexH2E2Session:
    """Execute only the accepted G06 structured-action Sidecar path."""

    def __init__(
        self,
        port: ModelPort,
        presentation: SidecarPresentation,
        request: ModelSessionRequest,
        *,
        on_transition: TransitionCallback | None = None,
        input_handler: InputHandler = handle_input,
        projection_builder: ProjectionBuilder = build_focus_projection_from_port,
    ) -> None:
        self.port = port
        self.presentation = presentation
        self.request = request
        self.on_transition = on_transition or (lambda _event: None)
        self.input_handler = input_handler
        self.projection_builder = projection_builder
        self.projection: dict[str, Any] | None = None
        self.envelopes: list[dict[str, Any]] = []
        self.terminal = False
        self._started = False
        self._busy = False

    def _emit(
        self,
        transition_key: str,
        projection: dict[str, Any],
        presentation: dict[str, Any],
        envelope: dict[str, Any] | None,
    ) -> None:
        transition_id, state_id, _stage = _TRANSITIONS[transition_key]
        self.on_transition(
            {
                "transition_id": transition_id,
                "state_id": state_id,
                "projection": projection,
                "presentation": presentation,
                "envelope": envelope,
            }
        )

    def start(self) -> dict[str, Any]:
        if self._started:
            raise H2E2IntegrationError("SESSION_START_NOT_EXACTLY_ONCE")
        self._started = True
        started = self.port.start_or_resume(self.request)
        projection = self.projection_builder(self.port, started.session_id)
        _validate_g06_projection(projection, "PROMPT_REVIEW")
        presentation = self.presentation.present(projection, initial=True)
        self.projection = projection
        self._emit("START", projection, presentation, None)
        return projection

    def activate_action(self, action_id: str) -> dict[str, Any]:
        if not self._started or self.projection is None:
            raise H2E2IntegrationError("SESSION_NOT_STARTED")
        if self.terminal:
            raise H2E2IntegrationError("ACTION_AFTER_TERMINAL")
        if self._busy:
            raise H2E2IntegrationError("DUPLICATE_ACTION_ACTIVATION")
        expected_action = _primary_action(self.projection)
        if action_id != expected_action or action_id not in {"confirm_prompt", "confirm_plan"}:
            raise H2E2IntegrationError(f"INVALID_OR_STALE_ACTION:{action_id}")

        envelope = build_structured_action_envelope(self.projection, action_id)
        self._busy = True
        try:
            result = self.input_handler(envelope, self.port)
            try:
                validate_command_result(result)
            except Exception as exc:
                raise H2E2IntegrationError("INVALID_VIEWMODEL_COMMAND_RESULT") from exc
            if not result.get("ok"):
                error = result.get("error")
                code = error.get("code") if isinstance(error, dict) else "UNKNOWN"
                raise H2E2IntegrationError(f"VIEWMODEL_SUBMISSION_FAILED:{code}")
            if result.get("result_type") != "REVISION":
                raise H2E2IntegrationError(
                    f"UNEXPECTED_VIEWMODEL_RESULT:{result.get('result_type')}"
                )
            next_projection = result.get("projection")
            expected_stage = _TRANSITIONS[action_id][2]
            _validate_g06_projection(
                next_projection,
                expected_stage,
                previous=self.projection,
            )
            presentation = self.presentation.present(next_projection)
            self.envelopes.append(dict(envelope))
            self.projection = next_projection
            self.terminal = expected_stage == TERMINAL_STAGE
            self._emit(action_id, next_projection, presentation, envelope)
            return next_projection
        finally:
            self._busy = False
