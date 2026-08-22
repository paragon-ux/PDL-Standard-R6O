from __future__ import annotations

import os
import tkinter as tk

import pytest

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.memory_model import StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.tests.helpers import artifact, state
from r6o.views.sidecar import SidecarHarness, SidecarModel
from r6o.views.sidecar.app import (
    EXPANDED_BOTTOM_INSET,
    EXPANDED_COMPOSER_CLEARANCE,
    EXPANDED_RIGHT_INSET,
    EXPANDED_TOP_INSET,
    EXPANDED_WIDTH_RATIO,
    STANDARD_GAP,
    STANDARD_HEIGHT,
    SURFACE,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("R6O2_RUN_DISPLAY_TESTS") != "1",
    reason="LOCAL_DISPLAY_GATE_REQUIRED",
)

G06_ACTIVATION = "Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers."
A02_ACTIVATION = "Use $confirm-with-pseudocode to compare Kafka and RabbitMQ for event delivery."
A02_REVISION = "This is not confirmed. The audience should be data engineers, not backend engineers."


@pytest.fixture(scope="module")
def display_master():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"LOCAL_DISPLAY_GATE_REQUIRED: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def _harness(
    display_master,
    *,
    model: SidecarModel | None = None,
    composer_prefill: str | None = None,
) -> SidecarHarness:
    root = tk.Toplevel(display_master)
    model = model or SidecarModel(
        PresentationAdapter(StaticModelPort(state(), {"prompt:P1": artifact()})),
        "I-1",
    )
    harness = SidecarHarness(
        model,
        root=root,
        composer_prefill=composer_prefill,
    )
    harness.root.update()
    return harness


def _scaled(value: int, geometry: dict[str, object]) -> int:
    return round(value * float(geometry["scale"]))


def _rect(geometry: dict[str, object], prefix: str) -> tuple[int, int, int, int]:
    return tuple(int(geometry[f"{prefix}_{field}"]) for field in ("x", "y", "width", "height"))


def test_fullscreen_parent_and_standard_floating_geometry(display_master) -> None:
    harness = _harness(display_master)
    try:
        geometry = harness.geometry_snapshot()
        assert _rect(geometry, "parent") == _rect(geometry, "work_area")
        assert geometry["sidecar_frameless"] is True
        assert geometry["sidecar_resizable"] is False
        assert geometry["sidecar_transient"] is True
        assert geometry["sidecar_native_owner_attached"] is True
        assert geometry["sidecar_above_owner"] is True
        assert geometry["sidecar_global_topmost"] is False
        assert geometry["native_sidecar_chrome"] is False
        assert geometry["panel_x"] == geometry["composer_x"]
        assert geometry["panel_width"] == geometry["composer_width"]
        assert geometry["panel_height"] == _scaled(STANDARD_HEIGHT, geometry)
        assert (
            geometry["panel_y"]
            + geometry["panel_height"]
            + _scaled(STANDARD_GAP, geometry)
            == geometry["composer_y"]
        )
        total = int(geometry["artifact_width"]) + int(geometry["options_width"])
        assert 0.65 <= int(geometry["artifact_width"]) / total <= 0.75
        assert abs(int(geometry["artifact_y"]) - int(geometry["options_y"])) <= 2
        assert harness.panel is not None and harness.panel.source_label is None
    finally:
        harness.close()


def test_public_capture_contains_the_live_sidecar_pixels(
    tmp_path, display_master
) -> None:
    harness = _harness(display_master)
    try:
        destination = harness.capture(tmp_path / "sidecar-visible.png")
        geometry = harness.geometry_snapshot()
        from PIL import Image

        image = Image.open(destination).convert("RGB")
        x = int(geometry["sidecar_x"]) - int(geometry["parent_x"]) + 2
        y = int(geometry["sidecar_y"]) - int(geometry["parent_y"]) + 2
        expected = tuple(bytes.fromhex(SURFACE.removeprefix("#")))
        assert image.getpixel((x, y)) == expected
        assert geometry["sidecar_native_owner_attached"] is True
        assert geometry["sidecar_above_owner"] is True
    finally:
        harness.close()


def test_live_expand_lock_and_collapse_restore_standard(display_master) -> None:
    harness = _harness(display_master)
    try:
        before_projection = (
            harness.model.projection["model_revision"],
            harness.model.projection["stage"],
        )
        standard = harness.geometry_snapshot()
        harness.invoke_mode_control()
        expanded = harness.geometry_snapshot()
        assert expanded["mode"] == "EXPANDED"
        assert expanded["panel_width"] == round(
            int(expanded["parent_width"]) * EXPANDED_WIDTH_RATIO
        )
        assert (
            int(expanded["panel_x"]) + int(expanded["panel_width"])
            == int(expanded["parent_x"])
            + int(expanded["parent_width"])
            - _scaled(EXPANDED_RIGHT_INSET, expanded)
        )
        assert expanded["panel_y"] == int(expanded["parent_y"]) + _scaled(
            EXPANDED_TOP_INSET, expanded
        )
        assert (
            int(expanded["panel_y"]) + int(expanded["panel_height"])
            == int(expanded["parent_y"])
            + int(expanded["parent_height"])
            - _scaled(EXPANDED_BOTTOM_INSET, expanded)
        )
        assert (
            int(expanded["composer_x"]) + int(expanded["composer_width"])
            <= int(expanded["panel_x"])
            - _scaled(EXPANDED_COMPOSER_CLEARANCE, expanded)
            + 2
        )
        assert int(expanded["artifact_y"]) + int(expanded["artifact_height"]) <= int(
            expanded["options_y"]
        ) + 2
        assert abs(int(expanded["artifact_width"]) - int(expanded["options_width"])) <= 2
        assert int(expanded["artifact_height"]) > int(expanded["options_height"])
        assert harness.panel is not None
        assert abs(
            int(expanded["options_height"]) - harness.panel.options_card.winfo_reqheight()
        ) <= 2

        locked = harness.sidecar_rect()
        harness.panel.artifact_text.yview_scroll(1, "units")
        harness.panel._action_buttons["confirm_prompt"].focus_set()
        harness.invoke_action("something_else")
        harness.root.update()
        assert harness.sidecar_rect() == locked
        focused = harness.geometry_snapshot()
        assert focused["sidecar_native_owner_attached"] is True
        assert focused["sidecar_above_owner"] is True

        harness.invoke_mode_control()
        collapsed = harness.geometry_snapshot()
        assert collapsed["mode"] == "STANDARD"
        assert _rect(collapsed, "panel") == _rect(standard, "panel")
        assert _rect(collapsed, "composer") == _rect(standard, "composer")
        assert before_projection == (
            harness.model.projection["model_revision"],
            harness.model.projection["stage"],
        )
    finally:
        harness.close()


def test_close_has_no_launcher_and_fresh_view_reattaches(display_master) -> None:
    port = StaticModelPort(state(), {"prompt:P1": artifact()})
    adapter = PresentationAdapter(port)
    model = SidecarModel(adapter, "I-1")
    harness = _harness(display_master, model=model)
    try:
        before = (model.projection["model_revision"], model.projection["stage"])
        assert harness.panel is not None
        harness.panel.close_button.invoke()
        harness.root.update()
        assert harness.window is None
        assert harness.composer_focus_requested
        assert not hasattr(harness, "reopen_button")
        assert before == (model.projection["model_revision"], model.projection["stage"])

        attached = SidecarModel(adapter, "I-1")
        harness.attach_sidecar(attached)
        harness.root.update()
        assert harness.window is not None and harness.window.mapped
        assert attached.projection == model.projection
    finally:
        harness.close()


def test_real_g06_terminal_dismisses_sidecar_and_focuses_composer(
    tmp_path, baseline_repo, recorded_worker_factory, display_master
) -> None:
    binding = LocalRuntimeModelBinding(
        baseline_repo,
        worker=recorded_worker_factory(["G06"]),
        workspace_root=tmp_path / "g06-sidecar",
    )
    started = binding.start_or_resume(
        ModelSessionRequest(request_id="g06-sidecar", task_text=G06_ACTIVATION)
    )
    harness = _harness(
        display_master,
        model=SidecarModel(PresentationAdapter(binding), started.session_id),
    )
    try:
        harness.invoke_action("confirm_prompt")
        assert harness.model.projection["stage"] == "PLAN_REVIEW"
        harness.invoke_action("confirm_plan")
        assert harness.model.projection["stage"] == "CLOSED_SUCCESS"
        assert harness.model.projection["model_response"]
        assert harness.window is None
        assert harness.composer_focus_requested
    finally:
        harness.close()
        binding.close()


def test_real_a02_composer_revision_keeps_window_locked(
    tmp_path, baseline_repo, recorded_worker_factory, display_master
) -> None:
    binding = LocalRuntimeModelBinding(
        baseline_repo,
        worker=recorded_worker_factory(["A02"]),
        workspace_root=tmp_path / "a02-sidecar",
    )
    started = binding.start_or_resume(
        ModelSessionRequest(request_id="a02-sidecar", task_text=A02_ACTIVATION)
    )
    harness = _harness(
        display_master,
        model=SidecarModel(
            PresentationAdapter(binding),
            started.session_id,
            qualification_case="A02",
        ),
        composer_prefill=A02_REVISION,
    )
    try:
        locked = harness.sidecar_rect()
        assert harness.composer_entry.get() == A02_REVISION
        assert "preloaded" in harness.model.notice
        harness.invoke_action("something_else")
        assert harness.composer_focus_requested
        assert harness.geometry_snapshot()["sidecar_above_owner"] is True
        harness._submit_composer()
        assert harness.model.projection["stage"] == "PROMPT_REVIEW"
        assert harness.sidecar_rect() == locked
        assert (
            binding.read_artifact(harness.model.state.session_id, "prompt:current").body
            == "COMPARE Kafka and RabbitMQ for event delivery, intended for data engineers."
        )
    finally:
        harness.close()
        binding.close()
