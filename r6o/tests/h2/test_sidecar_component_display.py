from __future__ import annotations

import copy
import json
import tkinter as tk
from pathlib import Path

import pytest

from r6o.views.sidecar import Rect, SidecarMode, SidecarWindow, calculate_sidecar_layout
from scripts.h2.verify_sidecar_component import (
    DEFAULT_EVIDENCE_DIR,
    sample_projection,
    validate_evidence,
    validate_evidence_file,
)


ROOT = Path(__file__).resolve().parents[3]


def test_standard_layout_is_composer_anchored_with_horizontal_composition() -> None:
    owner = Rect(0, 0, 1920, 1080)
    composer = Rect(48, 900, 1824, 140)
    layout = calculate_sidecar_layout(owner, composer, SidecarMode.STANDARD)

    assert layout.window.x == composer.x
    assert layout.window.width == composer.width
    assert composer.y - layout.window.bottom == 10
    assert layout.composer_anchor_gap == 10
    assert layout.composition == "ARTIFACT_LEFT_REVIEW_OPTIONS_RIGHT"
    assert layout.artifact.x < layout.review_options.x
    assert layout.artifact.y == layout.review_options.y
    assert layout.artifact.height == layout.review_options.height
    assert layout.parent_width_fraction == round(composer.width / owner.width, 6)


def test_expanded_layout_is_exact_thirty_percent_right_rail_with_vertical_composition() -> None:
    owner = Rect(100, 50, 1920, 1080)
    composer = Rect(148, 950, 1824, 140)
    layout = calculate_sidecar_layout(owner, composer, SidecarMode.EXPANDED)

    assert layout.window.width == 576
    assert layout.parent_width_fraction == 0.3
    assert layout.window.right < owner.right
    assert owner.right - layout.window.right == 24
    assert layout.composition == "ARTIFACT_TOP_REVIEW_OPTIONS_BELOW"
    assert layout.artifact.y < layout.review_options.y
    assert layout.artifact.x == layout.review_options.x
    assert layout.artifact.width == layout.review_options.width
    assert layout.composer_anchor_gap is None


@pytest.mark.parametrize(
    ("owner", "composer", "message"),
    [
        (Rect(0, 0, 800, 600), Rect(10, 500, 900, 80), "fully contained"),
        (Rect(0, 0, 600, 480), Rect(10, 350, 580, 100), "at least 640x480"),
        (Rect(0, 0, 1024, 768), Rect(20, 180, 984, 100), "insufficient space"),
    ],
)
def test_layout_rejects_invalid_synthetic_owner_relationships(
    owner: Rect,
    composer: Rect,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_sidecar_layout(owner, composer, SidecarMode.STANDARD)


def test_committed_component_evidence_is_fail_closed_and_component_only() -> None:
    result_path = DEFAULT_EVIDENCE_DIR / "component-result.json"
    report = validate_evidence_file(result_path)

    assert report["gate"] == "H2-C-QUALIFICATION"
    assert report["status"] == "MECHANICAL_PASS"
    assert report["overall_h2_pass_authorized"] is False
    assert report["real_codex_host_tested"] is False
    assert all(report["behaviors"].values())
    for mode in ("STANDARD", "EXPANDED"):
        screenshot = DEFAULT_EVIDENCE_DIR / report["modes"][mode]["screenshot"]
        assert screenshot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_evidence_rejects_overall_h2_or_real_codex_authority() -> None:
    report = json.loads((DEFAULT_EVIDENCE_DIR / "component-result.json").read_text(encoding="utf-8"))
    for key in ("overall_h2_pass_authorized", "real_codex_host_tested"):
        mutation = copy.deepcopy(report)
        mutation[key] = True
        with pytest.raises(AssertionError, match=key):
            validate_evidence(mutation)
    mutation = copy.deepcopy(report)
    mutation["claims"].append("Codex attachment PASS")
    with pytest.raises(AssertionError, match="forbidden authority"):
        validate_evidence(mutation)


def test_evidence_rejects_deleted_behavior_and_non_object_root() -> None:
    report = json.loads((DEFAULT_EVIDENCE_DIR / "component-result.json").read_text(encoding="utf-8"))
    mutation = copy.deepcopy(report)
    del mutation["behaviors"]["terminal_dismissal"]
    with pytest.raises(AssertionError, match="every required"):
        validate_evidence(mutation)
    with pytest.raises(AssertionError, match="must be a JSON object"):
        validate_evidence([])


def test_sidecar_view_has_no_protected_runtime_or_controller_authority() -> None:
    source = (ROOT / "r6o" / "views" / "sidecar" / "app.py").read_text(encoding="utf-8").lower()
    for forbidden in (
        "mechanicalcontroller",
        "mechanical_controller",
        "sessionengine",
        "session_engine",
        "workeradapter",
        "worker_adapter",
        "reviewdecision",
        "review_decision",
        "localruntimemodelbinding",
        "workspace_root",
        "handle_input",
    ):
        assert forbidden not in source


def test_sidecar_screenshot_dependency_is_separate_and_exactly_pinned() -> None:
    assert (ROOT / "requirements-h2-sidecar.txt").read_text(encoding="utf-8").splitlines() == [
        "Pillow==12.3.0"
    ]


def _tk_root_or_skip() -> tk.Tk:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is unavailable: {exc}")
    root.geometry("1280x800+0+0")
    root.update()
    return root


def test_live_tk_component_is_frameless_owned_focusable_and_close_only() -> None:
    root = _tk_root_or_skip()
    actions: list[str] = []
    closes: list[str] = []
    owner = Rect(root.winfo_rootx(), root.winfo_rooty(), 1280, 800)
    composer = Rect(owner.x + 24, owner.y + 650, 1232, 120)
    sidecar = SidecarWindow(
        root,
        owner,
        composer,
        on_action=actions.append,
        on_close_view=lambda: closes.append("closed"),
    )
    try:
        standard = sidecar.render(sample_projection())
        root.update()
        assert standard is not None
        assert bool(sidecar.window.overrideredirect()) is True
        assert sidecar.window.transient()
        assert sidecar.window.winfo_exists()
        assert sidecar._action_buttons[0].cget("text") == "Confirm prompt"
        sidecar._action_buttons[0].invoke()
        assert actions == ["confirm_prompt"]
        assert sidecar.toggle_mode() is SidecarMode.EXPANDED
        assert sidecar.layout is not None and sidecar.layout.parent_width_fraction == 0.3
        assert sidecar.toggle_mode() is SidecarMode.STANDARD
        assert sidecar.toggle_lock() is False
        assert sidecar.toggle_lock() is True
        sidecar.close_view()
        root.update()
        assert bool(root.winfo_exists()) is True
        assert closes == ["closed"]

        terminal_sidecar = SidecarWindow(root, owner, composer)
        terminal_sidecar.render(sample_projection())
        root.update()
        terminal_sidecar.render(sample_projection(terminal=True))
        root.update()
        assert bool(root.winfo_exists()) is True
        assert bool(terminal_sidecar.window.winfo_exists()) is False
    finally:
        if root.winfo_exists():
            root.destroy()
