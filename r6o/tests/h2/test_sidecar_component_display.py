from __future__ import annotations

import copy
import json
import tkinter as tk
from pathlib import Path

import pytest

from r6o.views.sidecar import (
    EXPANDED_SIZE,
    STANDARD_SIZE,
    Rect,
    SidecarMode,
    SidecarWindow,
    calculate_sidecar_layout,
)
from scripts.h2.verify_sidecar_component import (
    CAPTURE_FILES,
    CAPTURE_SIZES,
    DEFAULT_EVIDENCE_DIR,
    DESIGN_EVIDENCE_FILE,
    DESIGN_REQUIREMENTS,
    DESIGN_ROOT,
    REFERENCE_FILES,
    REFERENCE_HASHES,
    _png_dimensions,
    canonical_projection,
    sha256_file,
    validate_design_conformance,
    validate_evidence,
    validate_evidence_file,
)


ROOT = Path(__file__).resolve().parents[3]


def test_standard_layout_uses_locked_size_and_reference_horizontal_composition() -> None:
    owner = Rect(0, 0, 1920, 1080)
    composer = Rect(48, 900, 1824, 140)
    layout = calculate_sidecar_layout(owner, composer, SidecarMode.STANDARD)

    assert (layout.window.width, layout.window.height) == STANDARD_SIZE
    assert layout.window.x == composer.x
    assert composer.y - layout.window.bottom == 10
    assert layout.artifact == Rect(8, 44, 402, 256)
    assert layout.review_options == Rect(418, 44, 249, 256)
    assert layout.composition == "ARTIFACT_LEFT_REVIEW_OPTIONS_RIGHT"


def test_expanded_layout_uses_locked_size_and_reference_vertical_composition() -> None:
    owner = Rect(100, 50, 1920, 1080)
    composer = Rect(148, 950, 1824, 140)
    layout = calculate_sidecar_layout(owner, composer, SidecarMode.EXPANDED)

    assert (layout.window.width, layout.window.height) == EXPANDED_SIZE
    assert owner.right - layout.window.right == 24
    assert layout.artifact == Rect(8, 48, 396, 350)
    assert layout.review_options == Rect(8, 408, 396, 398)
    assert layout.artifact.bottom < layout.review_options.y
    assert layout.composition == "ARTIFACT_TOP_REVIEW_OPTIONS_BELOW"


@pytest.mark.parametrize("width", [1024, 1366, 1536, 1600, 1920])
def test_expanded_design_width_does_not_drift_with_owner_width(width: int) -> None:
    owner = Rect(0, 0, width, 900)
    composer = Rect(24, 734, width - 48, 126)
    layout = calculate_sidecar_layout(owner, composer, SidecarMode.EXPANDED)
    assert layout.window.width == 412
    assert layout.parent_width_fraction == round(412 / width, 6)


@pytest.mark.parametrize(
    ("owner", "composer", "mode", "message"),
    [
        (Rect(0, 0, 800, 900), Rect(10, 700, 900, 80), SidecarMode.STANDARD, "fully contained"),
        (Rect(0, 0, 600, 900), Rect(10, 730, 580, 120), SidecarMode.STANDARD, "at least 640x480"),
        (Rect(0, 0, 1024, 900), Rect(20, 300, 984, 100), SidecarMode.STANDARD, "insufficient space"),
        (Rect(0, 0, 800, 700), Rect(20, 530, 760, 120), SidecarMode.EXPANDED, "too small"),
    ],
)
def test_layout_rejects_invalid_owner_relationships(
    owner: Rect,
    composer: Rect,
    mode: SidecarMode,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_sidecar_layout(owner, composer, mode)


def test_vendored_design_authority_is_exact() -> None:
    for key, filename in REFERENCE_FILES.items():
        assert sha256_file(DESIGN_ROOT / filename) == REFERENCE_HASHES[key]
    assert _png_dimensions(DESIGN_ROOT / REFERENCE_FILES["STANDARD"]) == STANDARD_SIZE
    assert _png_dimensions(DESIGN_ROOT / REFERENCE_FILES["EXPANDED"]) == EXPANDED_SIZE


def test_committed_component_and_design_evidence_is_fail_closed() -> None:
    component = validate_evidence_file(DEFAULT_EVIDENCE_DIR / "component-result.json")
    design = json.loads((DEFAULT_EVIDENCE_DIR / DESIGN_EVIDENCE_FILE).read_text(encoding="utf-8"))
    validate_design_conformance(design, evidence_dir=DEFAULT_EVIDENCE_DIR)

    assert component["gate"] == "H2-C-QUALIFICATION"
    assert component["status"] == "MECHANICAL_PASS"
    assert component["overall_h2_pass_authorized"] is False
    assert component["real_codex_host_tested"] is False
    assert all(component["behaviors"].values())
    assert design["status"] == "H2-C_IMPLEMENTATION_CONFORMS_FOR_HUMAN_VISUAL_REVIEW"
    assert design["human_design_approval"] == "PENDING"
    assert design["counts"] == {
        "conformant": len(DESIGN_REQUIREMENTS),
        "nonconformant": 0,
        "design_decision_required": 0,
    }
    assert design["known_sidecar_visual_divergences"] == []


@pytest.mark.parametrize("mode", ["STANDARD", "EXPANDED"])
def test_canonical_capture_is_sidecar_only_at_exact_reference_dimensions(mode: str) -> None:
    capture = DEFAULT_EVIDENCE_DIR / CAPTURE_FILES[mode]
    assert _png_dimensions(capture) == CAPTURE_SIZES[mode]
    assert capture.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("key", ["overall_h2_pass_authorized", "real_codex_host_tested"])
def test_component_evidence_rejects_later_gate_authority(key: str) -> None:
    report = json.loads((DEFAULT_EVIDENCE_DIR / "component-result.json").read_text(encoding="utf-8"))
    report[key] = True
    with pytest.raises(AssertionError, match="forbidden authority"):
        validate_evidence(report, evidence_dir=DEFAULT_EVIDENCE_DIR)


def test_design_evidence_rejects_human_pass_divergence_and_fuzzy_authority() -> None:
    report = json.loads((DEFAULT_EVIDENCE_DIR / DESIGN_EVIDENCE_FILE).read_text(encoding="utf-8"))
    mutation = copy.deepcopy(report)
    mutation["human_design_approval"] = "HUMAN_PASS"
    with pytest.raises(AssertionError, match="human_design_approval"):
        validate_design_conformance(mutation, evidence_dir=DEFAULT_EVIDENCE_DIR)
    mutation = copy.deepcopy(report)
    mutation["known_sidecar_visual_divergences"] = ["one mismatch"]
    with pytest.raises(AssertionError, match="known Sidecar visual divergences"):
        validate_design_conformance(mutation, evidence_dir=DEFAULT_EVIDENCE_DIR)
    mutation = copy.deepcopy(report)
    mutation["fuzzy_similarity"] = 1.0
    with pytest.raises(AssertionError, match="fields differ"):
        validate_design_conformance(mutation, evidence_dir=DEFAULT_EVIDENCE_DIR)


def test_design_evidence_rejects_nonconformant_or_missing_requirement() -> None:
    report = json.loads((DEFAULT_EVIDENCE_DIR / DESIGN_EVIDENCE_FILE).read_text(encoding="utf-8"))
    mutation = copy.deepcopy(report)
    mutation["requirements"][0]["status"] = "NONCONFORMANT"
    with pytest.raises(AssertionError, match="requirement matrix"):
        validate_design_conformance(mutation, evidence_dir=DEFAULT_EVIDENCE_DIR)
    mutation = copy.deepcopy(report)
    del mutation["requirements"][-1]
    with pytest.raises(AssertionError, match="requirement matrix"):
        validate_design_conformance(mutation, evidence_dir=DEFAULT_EVIDENCE_DIR)


def test_component_evidence_rejects_path_escape_unbound_and_geometry_fabrication() -> None:
    report = json.loads((DEFAULT_EVIDENCE_DIR / "component-result.json").read_text(encoding="utf-8"))
    mutation = copy.deepcopy(report)
    mutation["modes"]["STANDARD"]["capture"] = "..\\outside.png"
    with pytest.raises(AssertionError, match="capture name"):
        validate_evidence(mutation, evidence_dir=DEFAULT_EVIDENCE_DIR)
    with pytest.raises(AssertionError, match="bound local evidence directory"):
        validate_evidence(report)
    mutation = copy.deepcopy(report)
    mutation["modes"]["STANDARD"]["layout"]["window"]["x"] += 100
    mutation["modes"]["STANDARD"]["observed_window"]["x"] += 100
    with pytest.raises(AssertionError, match="authoritative calculation"):
        validate_evidence(mutation, evidence_dir=DEFAULT_EVIDENCE_DIR)


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
    root.geometry("1600x900+0+0")
    root.update()
    return root


def _all_descendants(widget: tk.Misc) -> list[tk.Misc]:
    descendants: list[tk.Misc] = []
    for child in widget.winfo_children():
        descendants.append(child)
        descendants.extend(_all_descendants(child))
    return descendants


def test_live_design_locked_component_preserves_functional_contract() -> None:
    root = _tk_root_or_skip()
    actions: list[str] = []
    closes: list[str] = []
    opens: list[str] = []
    copies: list[str] = []
    owner = Rect(0, 0, 1600, 900)
    composer = Rect(40, 734, 1520, 126)
    sidecar = SidecarWindow(
        root,
        owner,
        composer,
        on_action=actions.append,
        on_close_view=lambda: closes.append("closed"),
        on_open_editor=opens.append,
        on_copy=copies.append,
        source_presenter=lambda _artifact: ("Source: Workspace File", "/workspace/pdlt/PDL.md"),
    )
    try:
        standard = sidecar.render(canonical_projection())
        root.update()
        assert standard is not None
        assert bool(sidecar.window.overrideredirect()) is True
        assert sidecar.window.transient()
        assert bool(sidecar.window.attributes("-topmost")) is False
        assert (sidecar.window.winfo_width(), sidecar.window.winfo_height()) == STANDARD_SIZE
        assert sidecar.focused_action_id == "confirm_prompt"
        assert sidecar.visible_controls == frozenset(
            {
                "open_editor",
                "copy",
                "confirm_prompt",
                "change_task",
                "change_approach",
                "something_else",
                "expand",
                "close",
            }
        )
        descendants = _all_descendants(sidecar.window)
        assert not any(isinstance(item, (tk.Button, tk.Scrollbar, tk.Text)) for item in descendants)
        assert int(sidecar.canvas.cget("highlightthickness")) == 0

        sidecar._action_buttons[0].invoke()
        sidecar._open_artifact()
        sidecar._copy_artifact()
        assert actions == ["confirm_prompt"]
        assert opens == ["prompt:h2-c-canonical"]
        assert copies == [canonical_projection()["artifact"]["body"]]

        sidecar.render(canonical_projection(stress=True))
        before = sidecar.artifact_body.yview()
        sidecar.scroll_artifact(5)
        assert sidecar.artifact_body.yview() != before
        sidecar.artifact_body.yview_moveto(0.0)
        sidecar.render(canonical_projection())

        assert sidecar.toggle_mode() is SidecarMode.EXPANDED
        root.update()
        assert (sidecar.window.winfo_width(), sidecar.window.winfo_height()) == EXPANDED_SIZE
        assert "expand" not in sidecar.visible_controls
        assert not ({"LOCK", "MOVE", "Collapse"} & set(sidecar.visible_text))
        assert sidecar.semantic_rects["actions_content"].bottom < sidecar.semantic_rects["tip"].y
        assert sidecar.semantic_rects["tip"].bottom < sidecar.semantic_rects["review_options"].bottom

        assert sidecar._on_escape(object()) == "break"
        root.update()
        assert sidecar.mode is SidecarMode.STANDARD
        assert sidecar.layout == standard
        sidecar._on_tab(object())
        assert sidecar._focused_role == "change_task"
        sidecar._on_shift_tab(object())
        assert sidecar.focused_action_id == "confirm_prompt"

        visible_before_lock = sidecar.visible_controls
        assert sidecar.toggle_lock() is False
        assert sidecar.toggle_lock() is True
        assert sidecar.visible_controls == visible_before_lock

        sidecar.close_view()
        root.update()
        assert bool(root.winfo_exists()) is True
        assert closes == ["closed"]

        terminal = SidecarWindow(
            root,
            owner,
            composer,
            source_presenter=lambda _artifact: ("Source: Workspace File", "/workspace/pdlt/PDL.md"),
        )
        terminal.render(canonical_projection())
        root.update()
        terminal_window = terminal.window
        terminal.render(canonical_projection(terminal=True))
        root.update()
        assert bool(root.winfo_exists()) is True
        assert bool(terminal_window.winfo_exists()) is False
    finally:
        if root.winfo_exists():
            root.destroy()
