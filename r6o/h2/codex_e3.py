from __future__ import annotations

"""H2-E3 A02-FULL coordination at the accepted E1/E2 presentation seams."""

import time
from collections.abc import Callable
from typing import Any, Protocol

from r6o.h2.codex_e2 import (
    AttachedCodexSidecarPresentation,
    H2E2IntegrationError,
    TERMINAL_STAGE,
    build_structured_action_envelope,
)
from r6o.model_binding.base import ModelPort, ModelSessionRequest
from r6o.viewmodel.dispatcher import handle_input, validate_command_result
from r6o.viewmodel.projection import build_focus_projection_from_port


_EXPECTED_STAGES = {
    "PROMPT_REVIEW": ("prompt", "confirm_prompt"),
    "PLAN_REVIEW": ("plan", "confirm_plan"),
}
_TRANSITIONS = {
    "START": ("A02-T0-CODEX", "A02-S1"),
    "something_else": ("A02-T1-FOCUS-CODEX", "A02-S1"),
    "HOST_COMPOSER_TEXT": ("A02-T2-REVISE-CODEX", "A02-S2"),
    "confirm_prompt": ("A02-T3-CODEX", "A02-S3"),
    "confirm_plan": ("A02-T4-CODEX", "A02-S4"),
}


class H2E3IntegrationError(H2E2IntegrationError):
    """A fail-closed H2-E3 integration error."""


class ComposerInputBinding(Protocol):
    """The accepted E1 lifecycle boundary used by the E3 coordinator."""

    def activate(self, projection: dict[str, Any], *, timeout: float = 5.0) -> None: ...

    def deactivate(self) -> None: ...


class E3SidecarPresentation(Protocol):
    """Sidecar presentation plus the actual-composer focus handoff."""

    def present(self, projection: dict[str, Any], *, initial: bool = False) -> dict[str, Any]: ...

    def focus_actual_composer(self, projection: dict[str, Any]) -> dict[str, Any]: ...


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


def _projected_action(
    projection: dict[str, Any], action_id: str, *, expected_kind: str | None = None
) -> dict[str, Any] | None:
    actions = projection.get("actions")
    if not isinstance(actions, list):
        return None
    for action in actions:
        if not isinstance(action, dict) or action.get("action_id") != action_id:
            continue
        if action.get("enabled") is not True:
            return None
        if expected_kind is not None and action.get("kind") != expected_kind:
            return None
        return action
    return None


def _validate_a02_projection(
    projection: dict[str, Any],
    expected_stage: str,
    *,
    previous: dict[str, Any] | None = None,
    require_changed: bool = False,
) -> None:
    if not isinstance(projection, dict):
        raise H2E3IntegrationError("INVALID_RETURNED_PROJECTION")
    if projection.get("schema_version") != "r6o-focus-projection-1":
        raise H2E3IntegrationError("INVALID_RETURNED_PROJECTION")
    if projection.get("stage") != expected_stage:
        raise H2E3IntegrationError(
            f"UNEXPECTED_A02_STAGE:{projection.get('stage')}:{expected_stage}"
        )
    lifecycle = projection.get("lifecycle")
    if not isinstance(lifecycle, dict):
        raise H2E3IntegrationError("INVALID_RETURNED_PROJECTION")

    if expected_stage == TERMINAL_STAGE:
        if (
            projection.get("artifact") is not None
            or projection.get("actions") != []
            or lifecycle.get("terminal") is not True
            or lifecycle.get("terminal_disposition") != "HOST_HANDOFF"
        ):
            raise H2E3IntegrationError("INVALID_A02_TERMINAL_PROJECTION")
        return

    expected_artifact_kind, expected_action = _EXPECTED_STAGES[expected_stage]
    artifact = projection.get("artifact")
    if not isinstance(artifact, dict):
        raise H2E3IntegrationError("INVALID_RETURNED_PROJECTION")
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
        raise H2E3IntegrationError("INVALID_RETURNED_PROJECTION")

    if previous is not None and expected_stage == "PLAN_REVIEW":
        previous_artifact = previous.get("artifact")
        if isinstance(previous_artifact, dict) and (
            artifact["artifact_ref"],
            artifact["artifact_revision"],
        ) == (
            previous_artifact.get("artifact_ref"),
            previous_artifact.get("artifact_revision"),
        ):
            raise H2E3IntegrationError("PLAN_ARTIFACT_NOT_NEW")

    if require_changed:
        previous_artifact = previous.get("artifact") if previous else None
        if not isinstance(previous_artifact, dict) or (
            artifact["artifact_ref"],
            artifact["artifact_revision"],
        ) == (
            previous_artifact.get("artifact_ref"),
            previous_artifact.get("artifact_revision"),
        ):
            raise H2E3IntegrationError("PROMPT_ARTIFACT_NOT_REVISED")


class AttachedCodexE3Presentation:
    """Compose the accepted E2 Sidecar presenter with the accepted E1 binding."""

    def __init__(self, binding: Any, input_binding: ComposerInputBinding) -> None:
        self.binding = binding
        self.input_binding = input_binding
        self._sidecar = AttachedCodexSidecarPresentation(binding)
        self._terminal_dismissed = False

    def present(self, projection: dict[str, Any], *, initial: bool = False) -> dict[str, Any]:
        if projection.get("stage") == TERMINAL_STAGE:
            return self._present_terminal(projection, initial=initial)
        if self._terminal_dismissed:
            raise H2E3IntegrationError("ACTIVE_PROJECTION_AFTER_TERMINAL")
        return self._sidecar.present(projection, initial=initial)

    def _present_terminal(
        self, projection: dict[str, Any], *, initial: bool
    ) -> dict[str, Any]:
        if initial or self._terminal_dismissed:
            raise H2E3IntegrationError("TERMINAL_CLOSE_NOT_EXACTLY_ONCE")
        if self.binding.sidecar.render(projection):
            raise H2E3IntegrationError("TERMINAL_PROJECTION_REMAINED_VISIBLE")
        self.binding.sidecar.dismiss_terminal()
        try:
            self.binding.refresh_controls().composer.set_focus()
        except Exception as exc:
            raise H2E3IntegrationError("COMPOSER_FOCUS_RETURN_FAILED") from exc

        deadline = time.monotonic() + 5.0
        sidecar_visible = True
        while time.monotonic() < deadline:
            try:
                from PySide6.QtCore import QCoreApplication, QEventLoop

                app = QCoreApplication.instance()
                if app is not None:
                    app.processEvents(QEventLoop.AllEvents, 25)
            except ImportError:
                pass
            try:
                focused = bool(
                    self.binding.refresh_controls().composer.has_keyboard_focus()
                )
                foreground = self.binding.native.foreground()
                sidecar_visible = self.binding.native.is_visible(
                    self.binding.sidecar_hwnd
                )
            except Exception:
                focused = False
                foreground = 0
            if focused and foreground == self.binding.host_hwnd and not sidecar_visible:
                self._terminal_dismissed = True
                return {
                    "sidecar_visibility": "DISMISSED",
                    "focus_owner": "ACTUAL_CODEX_COMPOSER",
                    "focus_return": {
                        "sidecar_visible": False,
                        "composer_keyboard_focus": True,
                        "foreground_hwnd": foreground,
                        "expected_foreground_hwnd": self.binding.host_hwnd,
                    },
                }
            time.sleep(0.025)
        if sidecar_visible:
            raise H2E3IntegrationError("TERMINAL_SIDECAR_NOT_DISMISSED")
        raise H2E3IntegrationError("COMPOSER_FOCUS_RETURN_UNVERIFIED")

    def focus_actual_composer(self, projection: dict[str, Any]) -> dict[str, Any]:
        self.input_binding.activate(projection)
        try:
            attachment = self.binding.observe()
        except Exception as exc:
            raise H2E3IntegrationError("ACTUAL_COMPOSER_FOCUS_UNVERIFIED") from exc
        return {
            "sidecar_visibility": "VISIBLE_STANDARD",
            "focus_owner": "ACTUAL_CODEX_COMPOSER",
            "attachment": attachment,
        }


class CodexH2E3Session:
    """Execute the frozen A02-FULL Sidecar lifecycle through E1 and E2 seams."""

    def __init__(
        self,
        port: ModelPort,
        presentation: E3SidecarPresentation,
        input_binding: ComposerInputBinding,
        request: ModelSessionRequest,
        *,
        on_transition: TransitionCallback | None = None,
        input_handler: InputHandler = handle_input,
        projection_builder: ProjectionBuilder = build_focus_projection_from_port,
    ) -> None:
        self.port = port
        self.presentation = presentation
        self.input_binding = input_binding
        self.request = request
        self.on_transition = on_transition or (lambda _event: None)
        self.input_handler = input_handler
        self.projection_builder = projection_builder
        self.projection: dict[str, Any] | None = None
        self.envelopes: list[dict[str, Any]] = []
        self.terminal = False
        self._started = False
        self._busy = False
        self._free_response_armed = False

    @property
    def free_response_armed(self) -> bool:
        return self._free_response_armed

    def _emit(
        self,
        transition_key: str,
        projection: dict[str, Any],
        presentation: dict[str, Any],
        envelope: dict[str, Any] | None,
    ) -> None:
        transition_id, state_id = _TRANSITIONS[transition_key]
        self.on_transition(
            {
                "transition_id": transition_id,
                "state_id": state_id,
                "projection": projection,
                "presentation": presentation,
                "envelope": envelope,
            }
        )

    def _require_active(self) -> dict[str, Any]:
        if not self._started or self.projection is None:
            raise H2E3IntegrationError("SESSION_NOT_STARTED")
        if self.terminal:
            raise H2E3IntegrationError("ACTION_AFTER_TERMINAL")
        return self.projection

    def _dispatch(self, envelope: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.input_handler(envelope, self.port)
            validate_command_result(result)
        except Exception as exc:
            raise H2E3IntegrationError("INVALID_VIEWMODEL_COMMAND_RESULT") from exc
        return result

    @staticmethod
    def _require_revision(result: dict[str, Any]) -> dict[str, Any]:
        if not result.get("ok"):
            error = result.get("error")
            code = error.get("code") if isinstance(error, dict) else "UNKNOWN"
            raise H2E3IntegrationError(f"VIEWMODEL_SUBMISSION_FAILED:{code}")
        if result.get("result_type") != "REVISION":
            raise H2E3IntegrationError(
                f"UNEXPECTED_VIEWMODEL_RESULT:{result.get('result_type')}"
            )
        projection = result.get("projection")
        if not isinstance(projection, dict):
            raise H2E3IntegrationError("INVALID_RETURNED_PROJECTION")
        return projection

    def start(self) -> dict[str, Any]:
        if self._started:
            raise H2E3IntegrationError("SESSION_START_NOT_EXACTLY_ONCE")
        self._started = True
        started = self.port.start_or_resume(self.request)
        projection = self.projection_builder(self.port, started.session_id)
        _validate_a02_projection(projection, "PROMPT_REVIEW")
        presentation = self.presentation.present(projection, initial=True)
        self.projection = projection
        self._emit("START", projection, presentation, None)
        return projection

    def activate_action(self, action_id: str) -> dict[str, Any]:
        projection = self._require_active()
        if self._busy:
            raise H2E3IntegrationError("TRANSITION_IN_PROGRESS")
        if self._free_response_armed:
            raise H2E3IntegrationError("FREE_RESPONSE_SUBMISSION_PENDING")

        if action_id == "something_else":
            return self._activate_free_response(projection)

        if action_id not in {"confirm_prompt", "confirm_plan"}:
            raise H2E3IntegrationError(f"INVALID_OR_STALE_ACTION:{action_id}")
        if _primary_action(projection) != action_id:
            raise H2E3IntegrationError(f"INVALID_OR_STALE_ACTION:{action_id}")
        envelope = build_structured_action_envelope(projection, action_id)
        self._busy = True
        try:
            result = self._dispatch(envelope)
            next_projection = self._require_revision(result)
            expected_stage = (
                "PLAN_REVIEW" if action_id == "confirm_prompt" else TERMINAL_STAGE
            )
            _validate_a02_projection(
                next_projection,
                expected_stage,
                previous=projection,
            )
            presentation = self.presentation.present(next_projection)
            self.envelopes.append(dict(envelope))
            self.projection = next_projection
            self.terminal = expected_stage == TERMINAL_STAGE
            self._emit(action_id, next_projection, presentation, envelope)
            return next_projection
        finally:
            self._busy = False

    def _activate_free_response(self, projection: dict[str, Any]) -> dict[str, Any]:
        if projection.get("stage") != "PROMPT_REVIEW":
            raise H2E3IntegrationError("INVALID_OR_STALE_ACTION:something_else")
        if _projected_action(
            projection, "something_else", expected_kind="FREE_RESPONSE_FOCUS"
        ) is None:
            raise H2E3IntegrationError("INVALID_OR_STALE_ACTION:something_else")
        envelope = build_structured_action_envelope(projection, "something_else")
        self._busy = True
        try:
            result = self._dispatch(envelope)
            if (
                result.get("ok") is not True
                or result.get("result_type") != "FOCUS_REQUIRED"
                or result.get("focus_role") != "FREE_RESPONSE"
                or result.get("projection") is not None
            ):
                raise H2E3IntegrationError("INVALID_FREE_RESPONSE_FOCUS_RESULT")
            try:
                presentation = self.presentation.focus_actual_composer(projection)
            except H2E3IntegrationError:
                raise
            except Exception as exc:
                raise H2E3IntegrationError("ACTUAL_COMPOSER_FOCUS_UNVERIFIED") from exc
            self._free_response_armed = True
            self.envelopes.append(dict(envelope))
            try:
                self._emit("something_else", projection, presentation, envelope)
            except Exception:
                # A transition/evidence failure must not leave the semantic
                # session eligible to consume a capture queued during the
                # native focus handoff.  The E1 binding remains fail-closed
                # until the runner aborts and clears the attempt-owned input.
                self._free_response_armed = False
                self.envelopes.pop()
                raise
            return projection
        finally:
            self._busy = False

    def _validate_text_envelope(
        self, envelope: dict[str, Any], projection: dict[str, Any]
    ) -> None:
        if not isinstance(envelope, dict):
            raise H2E3IntegrationError("INVALID_HOST_COMPOSER_ENVELOPE")
        if (
            envelope.get("schema_version") != "r6o-input-envelope-1"
            or envelope.get("source") != "HOST_COMPOSER_TEXT"
            or envelope.get("session_id") != projection.get("session_id")
            or envelope.get("model_revision") != projection.get("model_revision")
            or envelope.get("action_id") is not None
            or envelope.get("projection_id") is not None
            or not isinstance(envelope.get("text"), str)
            or not envelope["text"].strip()
        ):
            raise H2E3IntegrationError("INVALID_HOST_COMPOSER_ENVELOPE")

    def submit_composer_text(self, envelope: dict[str, Any]) -> dict[str, Any]:
        projection = self._require_active()
        if not self._free_response_armed:
            raise H2E3IntegrationError("TEXT_OUTSIDE_FREE_RESPONSE_STATE")
        if self._busy:
            raise H2E3IntegrationError("TRANSITION_IN_PROGRESS")
        self._validate_text_envelope(envelope, projection)
        self._busy = True
        self._free_response_armed = False
        try:
            try:
                self.input_binding.deactivate()
            except Exception as exc:
                raise H2E3IntegrationError("INPUT_BINDING_DEACTIVATION_FAILED") from exc
            result = self._dispatch(envelope)
            next_projection = self._require_revision(result)
            _validate_a02_projection(
                next_projection,
                "PROMPT_REVIEW",
                previous=projection,
                require_changed=True,
            )
            presentation = self.presentation.present(next_projection)
            self.envelopes.append(dict(envelope))
            self.projection = next_projection
            self._emit("HOST_COMPOSER_TEXT", next_projection, presentation, envelope)
            return next_projection
        finally:
            self._busy = False
