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
from r6o.views.sidecar.app import STANDARD_HEIGHT, STANDARD_HEIGHT_TOLERANCE

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


def _harness(mode: str, display_master) -> SidecarHarness:
    root = tk.Toplevel(display_master)
    model = SidecarModel(
        PresentationAdapter(StaticModelPort(state(), {"prompt:P1": artifact()})),
        "I-1",
        mode,
    )
    return SidecarHarness(model, root=root)


def test_standard_geometry_is_compact_horizontal_and_above_composer(display_master) -> None:
    harness = _harness("STANDARD", display_master)
    try:
        harness.root.update()
        geometry = harness.geometry_snapshot()
        assert abs(geometry["panel_height"] - STANDARD_HEIGHT) <= STANDARD_HEIGHT_TOLERANCE
        assert geometry["panel_y"] + geometry["panel_height"] <= geometry["composer_y"] + 2
        total = geometry["artifact_width"] + geometry["options_width"]
        artifact_ratio = geometry["artifact_width"] / total
        assert 0.65 <= artifact_ratio <= 0.75
        assert abs(geometry["artifact_y"] - geometry["options_y"]) <= 2
    finally:
        harness.close()


def test_expanded_geometry_is_right_half_vertical_and_composer_left_only(display_master) -> None:
    harness = _harness("EXPANDED", display_master)
    try:
        harness.root.update()
        geometry = harness.geometry_snapshot()
        ratio = geometry["panel_width"] / geometry["client_width"]
        assert 0.45 <= ratio <= 0.55
        assert geometry["panel_x"] >= geometry["client_width"] * 0.45
        assert geometry["composer_x"] + geometry["composer_width"] <= geometry["panel_x"] + 2
        assert geometry["artifact_y"] + geometry["artifact_height"] <= geometry["options_y"] + 2
        assert geometry["artifact_height"] > geometry["options_height"]
    finally:
        harness.close()


def test_real_g06_sidecar_buttons_follow_prompt_plan_terminal_sequence(
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
    root = tk.Toplevel(display_master)
    harness = SidecarHarness(
        SidecarModel(PresentationAdapter(binding), started.session_id), root=root
    )
    try:
        harness.root.update()
        stages = [harness.model.projection["stage"]]
        harness.invoke_action("confirm_prompt")
        harness.root.update()
        stages.append(harness.model.projection["stage"])
        harness.invoke_action("confirm_plan")
        harness.root.update()
        stages.append(harness.model.projection["stage"])
        assert stages == ["PROMPT_REVIEW", "PLAN_REVIEW", "CLOSED_SUCCESS"]
    finally:
        harness.close()
        binding.close()


def test_real_a02_harness_composer_revises_without_duplicate_activation(
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
    root = tk.Toplevel(display_master)
    harness = SidecarHarness(
        SidecarModel(PresentationAdapter(binding), started.session_id), root=root
    )
    try:
        harness.composer_entry.insert(0, A02_REVISION)
        harness._submit_composer()
        assert harness.model.projection["stage"] == "PROMPT_REVIEW"
        assert (
            binding.read_artifact(harness.model.state.session_id, "prompt:current").body
            == "COMPARE Kafka and RabbitMQ for event delivery, intended for data engineers."
        )
    finally:
        harness.close()
        binding.close()
