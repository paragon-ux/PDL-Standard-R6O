from __future__ import annotations

"""Qualify the H2-C Sidecar functional boundary and canonical design lock."""

import argparse
import hashlib
import json
import re
import sys
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.views.sidecar import (  # noqa: E402
    EXPANDED_SIZE,
    STANDARD_SIZE,
    Rect,
    SidecarMode,
    SidecarWindow,
    calculate_sidecar_layout,
)


DEFAULT_EVIDENCE_DIR = ROOT / "r6o_evidence" / "H2-C-QUALIFICATION"
DESIGN_ROOT = ROOT / "docs" / "h2" / "sidecar-design"
DESIGN_CONTRACT_FILE = "R6O-SIDECAR-DESIGN-CONTRACT-v1-2026-08-23.json"
DESIGN_SPEC_FILE = "R6O-SIDECAR-DESIGN-SPEC-v1-2026-08-23.md"
CONTROL_PLANE_FILE = "R6O-H2C-SIDECAR-VERDICT-AND-RECONTINUATION-PROMPT-2026-08-23.md"
STANDARD_REFERENCE_FILE = "REFERENCE_SIDECAR_STANDARD.png"
EXPANDED_REFERENCE_FILE = "REFERENCE_SIDECAR_EXPANDED.png"
STANDARD_CAPTURE_FILE = "H2-C-STANDARD-SIDECAR.png"
EXPANDED_CAPTURE_FILE = "H2-C-EXPANDED-SIDECAR.png"
DESIGN_EVIDENCE_FILE = "H2-C-DESIGN-CONFORMANCE.json"
GEOMETRY_FILE = "geometry.json"
COMPONENT_RESULT_FILE = "component-result.json"

REFERENCE_HASHES = {
    "control_plane": "124d999c188f0013125153d877e1a28a10b754f69dfb80adbe82880ec7aa55fc",
    "contract": "85f971d7f7af5d9779ae7559a7c5df0d316dba5494184ff72e4a75c6d8c29016",
    "spec": "c9a4b245c8c767d1d9292079269a14381e45c6809d7f38bf83bb35fc4c469170",
    "STANDARD": "f78361a61734848a47c26feca1be31c1f01e8a2ee21f4bd650e436053c5b140c",
    "EXPANDED": "3939a378d12cf45c25aa5aa32bc0fb429ab044ca510aeb428049938ee3c61313",
}
REFERENCE_FILES = {
    "control_plane": CONTROL_PLANE_FILE,
    "contract": DESIGN_CONTRACT_FILE,
    "spec": DESIGN_SPEC_FILE,
    "STANDARD": STANDARD_REFERENCE_FILE,
    "EXPANDED": EXPANDED_REFERENCE_FILE,
}
CAPTURE_FILES = {
    "STANDARD": STANDARD_CAPTURE_FILE,
    "EXPANDED": EXPANDED_CAPTURE_FILE,
}
CAPTURE_SIZES = {
    "STANDARD": STANDARD_SIZE,
    "EXPANDED": EXPANDED_SIZE,
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")

CANONICAL_ACTIONS = (
    ("confirm_prompt", 1, "Confirm this prompt", "PRIMARY"),
    ("change_task", 2, "Change the task", "NORMAL"),
    ("change_approach", 3, "Change the approach", "NORMAL"),
    ("something_else", 4, "Something else...", "NORMAL"),
)
REQUIRED_TEXT = {
    "PDLt Review",
    "PROMPT REVIEW",
    "ACTIVE",
    "Authoritative Prompt (PDL.md)",
    "Open in Editor",
    "# Prompt",
    "Source: Workspace File",
    "/workspace/pdlt/PDL.md",
    "Copy",
    "Review Options",
    "Confirm this prompt",
    "Change the task",
    "Change the approach",
    "Something else...",
    "Tip:",
    "Type directly in the chat below",
    "to provide other feedback.",
    "×",
}
FORBIDDEN_VISIBLE_TEXT = (
    "LOCK",
    "MOVE",
    "Projection snapshot",
    "artifact://",
    "SYNTHETIC",
    "qualification requirement",
    "Collapse",
)

BEHAVIOR_KEYS = {
    "frameless",
    "synthetic_owner",
    "floating",
    "custom_chrome",
    "standard_geometry",
    "expanded_geometry",
    "expand_transition",
    "collapse_without_visible_control",
    "close_view_only",
    "window_lock",
    "artifact_scroll",
    "primary_action_focus",
    "terminal_dismissal",
    "open_editor_callback",
    "copy_callback",
    "canonical_scrollbar_free",
}

DESIGN_REQUIREMENTS = (
    ("V01", "BOTH", "Sidecar-only canonical capture"),
    ("V02", "STANDARD", "675x300 outer size"),
    ("V03", "EXPANDED", "412x806 outer size"),
    ("V04", "BOTH", "Rounded custom outer frame"),
    ("V05", "BOTH", "PDLt Review, stage badge, and green ACTIVE"),
    ("V06", "STANDARD", "Custom Expand and Close controls"),
    ("V07", "EXPANDED", "Close only; no visible Collapse, LOCK, or MOVE"),
    ("V08", "STANDARD", "Reference horizontal artifact/options split"),
    ("V09", "EXPANDED", "Dominant artifact and natural-height options content"),
    ("V10", "BOTH", "Rounded artifact card"),
    ("V11", "BOTH", "Authoritative Prompt title"),
    ("V12", "BOTH", "Open in Editor and external-link affordance"),
    ("V13", "BOTH", "Canonical prompt fixture"),
    ("V14", "BOTH", "Workspace source label and path"),
    ("V15", "BOTH", "Copy control"),
    ("V16", "BOTH", "Review Options heading"),
    ("V17", "BOTH", "Four exact canonical action rows"),
    ("V18", "BOTH", "Green, blue, amber, and neutral number badges"),
    ("V19", "BOTH", "Rounded action rows and primary emphasis"),
    ("V20", "BOTH", "Exact two-line Tip"),
    ("V21", "BOTH", "No native scrollbar in canonical state"),
    ("V22", "EXPANDED", "Options content is not a stretched scroll region"),
    ("V23", "BOTH", "Custom keyboard focus with no dotted native artifact"),
    ("V24", "BOTH", "No debug or qualification text"),
    ("V25", "BOTH", "Proportional UI and monospaced artifact roles"),
    ("V26", "BOTH", "Dark layered surfaces and compact spacing"),
    ("V27", "BOTH", "Projection-only presentation callbacks"),
    ("V28", "BOTH", "Expand, terminal dismissal, and overflow behavior preserved"),
    ("V29", "BOTH", "Design contract and reference identities frozen"),
    ("V30", "BOTH", "Fail-closed structural design evidence"),
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise AssertionError(f"{path.name} is not a canonical PNG")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError(f"{label} must be a JSON object")
    return value


def _rect_from_evidence(value: Any, label: str) -> Rect:
    rectangle = _require_object(value, label)
    if set(rectangle) != {"x", "y", "width", "height"} or any(
        type(rectangle[key]) is not int for key in ("x", "y", "width", "height")
    ):
        raise AssertionError(f"{label} must be an exact integer rectangle")
    try:
        return Rect(**rectangle)
    except ValueError as exc:
        raise AssertionError(f"{label} is invalid: {exc}") from exc


def _validate_reference_files() -> None:
    for key, filename in REFERENCE_FILES.items():
        path = DESIGN_ROOT / filename
        if not path.is_file() or sha256_file(path) != REFERENCE_HASHES[key]:
            raise AssertionError(f"Sidecar design authority differs: {filename}")
    if _png_dimensions(DESIGN_ROOT / STANDARD_REFERENCE_FILE) != STANDARD_SIZE:
        raise AssertionError("STANDARD design reference dimensions differ")
    if _png_dimensions(DESIGN_ROOT / EXPANDED_REFERENCE_FILE) != EXPANDED_SIZE:
        raise AssertionError("EXPANDED design reference dimensions differ")


def _authority_words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _reject_overall_authority(value: Any, path: str = "result") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_words = _authority_words(str(key))
            if nested is True and (
                "overall" in key_words
                or "codex" in key_words
                or "e2e" in key_words
                or {"human", "pass"} <= key_words
            ):
                raise AssertionError(f"H2-C evidence claims forbidden authority at {path}.{key}")
            _reject_overall_authority(nested, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_overall_authority(nested, f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    words = _authority_words(value)
    claim_words = {
        "pass",
        "passed",
        "approve",
        "approved",
        "authorize",
        "authorized",
        "complete",
        "completed",
        "conform",
        "conforms",
        "conformant",
        "qualify",
        "qualified",
        "test",
        "tested",
        "verify",
        "verified",
    }
    later_scope_words = {
        "overall",
        "scope",
        "authority",
        "h2",
        "codex",
        "e2e",
        "attachment",
        "composer",
        "focus",
        "human",
    }
    if words & claim_words and words & later_scope_words:
        raise AssertionError(f"H2-C evidence claims forbidden authority at {path}: {value!r}")


def _expected_design_rows() -> list[dict[str, str]]:
    return [
        {
            "id": item_id,
            "mode": mode,
            "reference_element": element,
            "status": "CONFORMANT",
            "evidence": "STRUCTURAL_ASSERTION_AND_CANONICAL_CAPTURE",
        }
        for item_id, mode, element in DESIGN_REQUIREMENTS
    ]


def validate_design_conformance(value: Any, *, evidence_dir: Path) -> dict[str, Any]:
    report = _require_object(value, "H2-C design conformance")
    expected_keys = {
        "schema_version",
        "gate",
        "status",
        "human_design_approval",
        "overall_h2_pass_authorized",
        "real_codex_host_tested",
        "approval_rule",
        "references",
        "captures",
        "requirements",
        "counts",
        "known_sidecar_visual_divergences",
    }
    if set(report) != expected_keys:
        raise AssertionError("H2-C design conformance fields differ")
    expected_identity = {
        "schema_version": "r6o-h2-c-design-conformance-1",
        "gate": "H2-C-QUALIFICATION",
        "status": "H2-C_IMPLEMENTATION_CONFORMS_FOR_HUMAN_VISUAL_REVIEW",
        "human_design_approval": "PENDING",
        "overall_h2_pass_authorized": False,
        "real_codex_host_tested": False,
        "approval_rule": "ZERO_KNOWN_SIDECAR_VISUAL_DIVERGENCES",
    }
    for key, expected in expected_identity.items():
        if report.get(key) != expected:
            raise AssertionError(f"H2-C design {key} must be {expected!r}")
    expected_references = {
        mode: {
            "file": REFERENCE_FILES[mode],
            "sha256": REFERENCE_HASHES[mode],
            "width": CAPTURE_SIZES[mode][0],
            "height": CAPTURE_SIZES[mode][1],
        }
        for mode in ("STANDARD", "EXPANDED")
    }
    if report.get("references") != expected_references:
        raise AssertionError("H2-C design reference identities differ")
    captures = _require_object(report.get("captures"), "design captures")
    if set(captures) != {"STANDARD", "EXPANDED"}:
        raise AssertionError("H2-C design captures differ")
    for mode in ("STANDARD", "EXPANDED"):
        capture = _require_object(captures[mode], f"captures.{mode}")
        expected_file = CAPTURE_FILES[mode]
        expected_width, expected_height = CAPTURE_SIZES[mode]
        if set(capture) != {"file", "sha256", "width", "height", "capture_scope"}:
            raise AssertionError(f"captures.{mode} fields differ")
        if (
            capture.get("file") != expected_file
            or capture.get("width") != expected_width
            or capture.get("height") != expected_height
            or capture.get("capture_scope") != "SIDECAR_WINDOW_ONLY"
        ):
            raise AssertionError(f"captures.{mode} identity differs")
        capture_path = evidence_dir / expected_file
        capture_hash = capture.get("sha256")
        if (
            not capture_path.is_file()
            or not isinstance(capture_hash, str)
            or SHA256_PATTERN.fullmatch(capture_hash) is None
            or sha256_file(capture_path) != capture_hash
            or _png_dimensions(capture_path) != (expected_width, expected_height)
        ):
            raise AssertionError(f"captures.{mode} evidence differs")
    if report.get("requirements") != _expected_design_rows():
        raise AssertionError("H2-C design requirement matrix differs or contains a nonconformance")
    expected_counts = {
        "conformant": len(DESIGN_REQUIREMENTS),
        "nonconformant": 0,
        "design_decision_required": 0,
    }
    if report.get("counts") != expected_counts:
        raise AssertionError("H2-C design requirement counts differ")
    if report.get("known_sidecar_visual_divergences") != []:
        raise AssertionError("known Sidecar visual divergences remain")
    return report


def validate_evidence(value: Any, *, evidence_dir: Path | None = None) -> dict[str, Any]:
    _reject_overall_authority(value)
    _validate_reference_files()
    report = _require_object(value, "H2-C component result")
    expected_keys = {
        "schema_version",
        "gate",
        "status",
        "overall_h2_pass_authorized",
        "real_codex_host_tested",
        "qualification_parent",
        "design_authority",
        "behaviors",
        "modes",
        "geometry_evidence",
        "design_conformance_evidence",
    }
    if set(report) != expected_keys:
        raise AssertionError("H2-C component result fields differ")
    expected_identity = {
        "schema_version": "r6o-h2-c-component-result-2",
        "gate": "H2-C-QUALIFICATION",
        "status": "MECHANICAL_PASS",
        "overall_h2_pass_authorized": False,
        "real_codex_host_tested": False,
        "qualification_parent": "SYNTHETIC_TK_FUNCTIONAL_FIXTURE_NOT_VISUAL_EVIDENCE",
        "geometry_evidence": GEOMETRY_FILE,
        "design_conformance_evidence": DESIGN_EVIDENCE_FILE,
    }
    for key, expected in expected_identity.items():
        if report.get(key) != expected:
            raise AssertionError(f"H2-C {key} must be {expected!r}")
    expected_authority = {
        "control_plane": {
            "file": CONTROL_PLANE_FILE,
            "sha256": REFERENCE_HASHES["control_plane"],
        },
        "contract": {"file": DESIGN_CONTRACT_FILE, "sha256": REFERENCE_HASHES["contract"]},
        "spec": {"file": DESIGN_SPEC_FILE, "sha256": REFERENCE_HASHES["spec"]},
        "STANDARD": {"file": STANDARD_REFERENCE_FILE, "sha256": REFERENCE_HASHES["STANDARD"]},
        "EXPANDED": {"file": EXPANDED_REFERENCE_FILE, "sha256": REFERENCE_HASHES["EXPANDED"]},
    }
    if report.get("design_authority") != expected_authority:
        raise AssertionError("H2-C design authority fields differ")
    behaviors = _require_object(report.get("behaviors"), "behaviors")
    if set(behaviors) != BEHAVIOR_KEYS or any(item is not True for item in behaviors.values()):
        raise AssertionError("every required H2-C behavior must be true")
    modes = _require_object(report.get("modes"), "modes")
    if set(modes) != {"STANDARD", "EXPANDED"}:
        raise AssertionError("H2-C modes differ")
    mode_inputs: dict[str, tuple[Rect, Rect]] = {}
    for mode_name in ("STANDARD", "EXPANDED"):
        mode = _require_object(modes[mode_name], f"modes.{mode_name}")
        expected_mode_keys = {
            "layout",
            "observed_window",
            "observed_artifact",
            "observed_review_options",
            "visible_controls",
            "visible_text_inventory",
            "native_scrollbars_mapped",
            "capture",
            "capture_sha256",
        }
        if set(mode) != expected_mode_keys:
            raise AssertionError(f"modes.{mode_name} fields differ")
        layout = _require_object(mode.get("layout"), f"modes.{mode_name}.layout")
        owner = _rect_from_evidence(layout.get("owner"), f"modes.{mode_name}.layout.owner")
        composer = _rect_from_evidence(layout.get("composer"), f"modes.{mode_name}.layout.composer")
        expected_layout = calculate_sidecar_layout(owner, composer, SidecarMode(mode_name)).to_dict()
        if layout != expected_layout:
            raise AssertionError(f"modes.{mode_name} layout differs from authoritative calculation")
        if mode.get("observed_window") != layout["window"]:
            raise AssertionError(f"modes.{mode_name} live window differs")
        if mode.get("observed_artifact") != layout["artifact"]:
            raise AssertionError(f"modes.{mode_name} live artifact differs")
        if mode.get("observed_review_options") != layout["review_options"]:
            raise AssertionError(f"modes.{mode_name} live review options differ")
        expected_controls = {
            "open_editor",
            "copy",
            "confirm_prompt",
            "change_task",
            "change_approach",
            "something_else",
            "close",
        }
        if mode_name == "STANDARD":
            expected_controls.add("expand")
        if set(mode.get("visible_controls") or []) != expected_controls:
            raise AssertionError(f"modes.{mode_name} visible control inventory differs")
        visible_text = mode.get("visible_text_inventory")
        if not isinstance(visible_text, list) or not REQUIRED_TEXT <= set(visible_text):
            raise AssertionError(f"modes.{mode_name} required visible text differs")
        combined_text = "\n".join(str(item) for item in visible_text)
        if any(forbidden.casefold() in combined_text.casefold() for forbidden in FORBIDDEN_VISIBLE_TEXT):
            raise AssertionError(f"modes.{mode_name} contains forbidden visible text")
        if mode.get("native_scrollbars_mapped") != 0:
            raise AssertionError(f"modes.{mode_name} exposes a native scrollbar")
        expected_capture = CAPTURE_FILES[mode_name]
        if mode.get("capture") != expected_capture:
            raise AssertionError(f"modes.{mode_name} capture name differs")
        capture_hash = mode.get("capture_sha256")
        if not isinstance(capture_hash, str) or SHA256_PATTERN.fullmatch(capture_hash) is None:
            raise AssertionError(f"modes.{mode_name} capture hash differs")
        mode_inputs[mode_name] = (owner, composer)
    if mode_inputs["STANDARD"] != mode_inputs["EXPANDED"]:
        raise AssertionError("STANDARD and EXPANDED functional fixtures differ")
    if evidence_dir is None:
        raise AssertionError("H2-C evidence validation requires a bound local evidence directory")
    evidence = evidence_dir.resolve()
    for mode_name in ("STANDARD", "EXPANDED"):
        capture_path = evidence / CAPTURE_FILES[mode_name]
        if (
            not capture_path.is_file()
            or sha256_file(capture_path) != modes[mode_name]["capture_sha256"]
            or _png_dimensions(capture_path) != CAPTURE_SIZES[mode_name]
        ):
            raise AssertionError(f"modes.{mode_name} capture evidence differs")
    geometry = _require_object(
        json.loads((evidence / GEOMETRY_FILE).read_text(encoding="utf-8")),
        "geometry evidence",
    )
    if set(geometry) != {
        "schema_version",
        "qualification_parent",
        "composer_anchor",
        "STANDARD",
        "EXPANDED",
    } or geometry.get("schema_version") != "r6o-h2-c-geometry-2":
        raise AssertionError("geometry evidence fields differ")
    owner, composer = mode_inputs["STANDARD"]
    if _rect_from_evidence(geometry.get("qualification_parent"), "geometry owner") != owner:
        raise AssertionError("geometry owner differs")
    if _rect_from_evidence(geometry.get("composer_anchor"), "geometry composer") != composer:
        raise AssertionError("geometry composer differs")
    for mode_name in ("STANDARD", "EXPANDED"):
        expected_geometry = {
            "layout": modes[mode_name]["layout"],
            "observed_window": modes[mode_name]["observed_window"],
            "observed_artifact": modes[mode_name]["observed_artifact"],
            "observed_review_options": modes[mode_name]["observed_review_options"],
        }
        if geometry.get(mode_name) != expected_geometry:
            raise AssertionError(f"geometry.{mode_name} differs")
    design_path = evidence / DESIGN_EVIDENCE_FILE
    design = json.loads(design_path.read_text(encoding="utf-8"))
    validate_design_conformance(design, evidence_dir=evidence)
    return report


def validate_evidence_file(path: Path) -> dict[str, Any]:
    return validate_evidence(
        json.loads(path.read_text(encoding="utf-8")),
        evidence_dir=path.resolve().parent,
    )


def canonical_projection(*, terminal: bool = False, stress: bool = False) -> dict[str, Any]:
    if terminal:
        return {
            "stage": "CLOSED_SUCCESS",
            "artifact": None,
            "actions": [],
            "lifecycle": {"terminal": True},
        }
    body = (
        "# Prompt\n\n"
        "Build a task manager with:\n"
        "- User authentication\n"
        "- Project management\n"
        "- Task tracking\n"
        "- Due dates and reminders\n\n"
        "Target tech stack: React + FastAPI + SQLite"
    )
    if stress:
        body += "\n\n" + "\n".join(f"Overflow line {index:02d}" for index in range(1, 41))
    return {
        "stage": "PROMPT_REVIEW",
        "artifact": {
            "artifact_ref": "prompt:h2-c-canonical",
            "artifact_revision": "revision-1",
            "artifact_kind": "prompt",
            "title": "Authoritative Prompt (PDL.md)",
            "body": body,
            "media_type": "text/markdown",
            "capabilities": {"copy": True, "open_external": True},
        },
        "actions": [
            {
                "action_id": action_id,
                "ordinal": ordinal,
                "label": label,
                "emphasis": emphasis,
                "enabled": True,
            }
            for action_id, ordinal, label, emphasis in CANONICAL_ACTIONS
        ],
        "lifecycle": {"terminal": False},
    }


sample_projection = canonical_projection


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def _capture_sidecar(path: Path, sidecar: SidecarWindow) -> None:
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError("Pillow is required for H2-C Sidecar evidence") from exc
    sidecar.window.update()
    bbox = (
        sidecar.window.winfo_rootx(),
        sidecar.window.winfo_rooty(),
        sidecar.window.winfo_rootx() + sidecar.window.winfo_width(),
        sidecar.window.winfo_rooty() + sidecar.window.winfo_height(),
    )
    image = ImageGrab.grab(bbox=bbox, all_screens=True)
    expected = CAPTURE_SIZES[sidecar.mode.value]
    if image.size != expected:
        raise AssertionError(f"{sidecar.mode.value} Sidecar capture differs: {image.size} != {expected}")
    image.save(path, format="PNG")


def _observed_window(sidecar: SidecarWindow) -> Rect:
    sidecar.window.update_idletasks()
    return Rect(
        sidecar.window.winfo_x(),
        sidecar.window.winfo_y(),
        sidecar.window.winfo_width(),
        sidecar.window.winfo_height(),
    )


def _mapped_native_scrollbars(widget: tk.Misc) -> list[tk.Scrollbar]:
    found: list[tk.Scrollbar] = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Scrollbar) and child.winfo_ismapped():
            found.append(child)
        found.extend(_mapped_native_scrollbars(child))
    return found


def _assert_canonical_surface(sidecar: SidecarWindow, mode: SidecarMode) -> dict[str, Any]:
    sidecar.window.update()
    layout = sidecar.layout
    if layout is None or layout.mode is not mode:
        raise AssertionError(f"{mode.value} layout is unavailable")
    if (layout.window.width, layout.window.height) != CAPTURE_SIZES[mode.value]:
        raise AssertionError(f"{mode.value} outer size differs")
    if not bool(sidecar.window.overrideredirect()):
        raise AssertionError("native title bar is visible")
    if not sidecar.window.transient():
        raise AssertionError("Sidecar functional fixture has no synthetic owner")
    if not bool(sidecar.window.attributes("-topmost")):
        raise AssertionError("Sidecar functional fixture is not floating above its owner")
    if int(sidecar.canvas.cget("highlightthickness")) != 0:
        raise AssertionError("native dotted focus chrome is enabled")
    expected_controls = {
        "open_editor",
        "copy",
        "confirm_prompt",
        "change_task",
        "change_approach",
        "something_else",
        "close",
    }
    if mode is SidecarMode.STANDARD:
        expected_controls.add("expand")
    if set(sidecar.visible_controls) != expected_controls:
        raise AssertionError(f"{mode.value} visible controls differ: {sidecar.visible_controls}")
    text_inventory = set(sidecar.visible_text)
    if not REQUIRED_TEXT <= text_inventory:
        raise AssertionError(f"{mode.value} required text is missing: {REQUIRED_TEXT - text_inventory}")
    combined = "\n".join(text_inventory)
    forbidden = [item for item in FORBIDDEN_VISIBLE_TEXT if item.casefold() in combined.casefold()]
    if forbidden:
        raise AssertionError(f"{mode.value} forbidden visible text remains: {forbidden}")
    if _mapped_native_scrollbars(sidecar.window):
        raise AssertionError(f"{mode.value} exposes a mapped native scrollbar")
    if sidecar.focused_action_id != "confirm_prompt":
        raise AssertionError(f"{mode.value} primary action does not own custom focus")
    if [button.cget("text") for button in sidecar._action_buttons] != [
        item[2] for item in CANONICAL_ACTIONS
    ]:
        raise AssertionError(f"{mode.value} canonical actions differ")
    semantic = sidecar.semantic_rects
    if semantic.get("artifact") != layout.artifact or semantic.get("review_options") != layout.review_options:
        raise AssertionError(f"{mode.value} rendered panel geometry differs")
    if "external_link_icon" not in semantic:
        raise AssertionError(f"{mode.value} external-link affordance is missing")
    if mode is SidecarMode.STANDARD:
        if "expand_icon" not in semantic:
            raise AssertionError("STANDARD custom Expand icon is missing")
        if not (
            layout.artifact.x < layout.review_options.x
            and layout.artifact.width == 402
            and layout.review_options.width == 249
        ):
            raise AssertionError("STANDARD horizontal composition differs")
    else:
        actions = semantic.get("actions_content")
        tip = semantic.get("tip")
        if (
            layout.artifact.y >= layout.review_options.y
            or actions is None
            or tip is None
            or actions.bottom >= tip.y
            or tip.bottom >= layout.review_options.bottom
        ):
            raise AssertionError("EXPANDED options content is stretched or misplaced")
    return {
        "layout": layout.to_dict(),
        "observed_window": _observed_window(sidecar).to_dict(),
        "observed_artifact": semantic["artifact"].to_dict(),
        "observed_review_options": semantic["review_options"].to_dict(),
        "visible_controls": sorted(sidecar.visible_controls),
        "visible_text_inventory": sorted(text_inventory),
        "native_scrollbars_mapped": len(_mapped_native_scrollbars(sidecar.window)),
    }


def _build_design_report(capture_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "r6o-h2-c-design-conformance-1",
        "gate": "H2-C-QUALIFICATION",
        "status": "H2-C_IMPLEMENTATION_CONFORMS_FOR_HUMAN_VISUAL_REVIEW",
        "human_design_approval": "PENDING",
        "overall_h2_pass_authorized": False,
        "real_codex_host_tested": False,
        "approval_rule": "ZERO_KNOWN_SIDECAR_VISUAL_DIVERGENCES",
        "references": {
            mode: {
                "file": REFERENCE_FILES[mode],
                "sha256": REFERENCE_HASHES[mode],
                "width": CAPTURE_SIZES[mode][0],
                "height": CAPTURE_SIZES[mode][1],
            }
            for mode in ("STANDARD", "EXPANDED")
        },
        "captures": {
            mode: {
                "file": CAPTURE_FILES[mode],
                "sha256": capture_hashes[mode],
                "width": CAPTURE_SIZES[mode][0],
                "height": CAPTURE_SIZES[mode][1],
                "capture_scope": "SIDECAR_WINDOW_ONLY",
            }
            for mode in ("STANDARD", "EXPANDED")
        },
        "requirements": _expected_design_rows(),
        "counts": {
            "conformant": len(DESIGN_REQUIREMENTS),
            "nonconformant": 0,
            "design_decision_required": 0,
        },
        "known_sidecar_visual_divergences": [],
    }


def run_display_qualification(
    *,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    hold_seconds: float = 1.0,
) -> dict[str, Any]:
    if hold_seconds < 0:
        raise ValueError("hold_seconds cannot be negative")
    _validate_reference_files()
    _enable_dpi_awareness()
    evidence = evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.title("Synthetic H2-C Functional Fixture — Not Visual Evidence")
    root.configure(bg="#081018")
    root.geometry("1600x900+0+0")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.update()
    owner = Rect(root.winfo_rootx(), root.winfo_rooty(), 1600, 900)
    composer = Rect(owner.x + 40, owner.y + 734, 1520, 126)
    actions: list[str] = []
    closes: list[str] = []
    opens: list[str] = []
    copies: list[str] = []
    sidecar = SidecarWindow(
        root,
        owner,
        composer,
        on_action=actions.append,
        on_close_view=lambda: closes.append("CLOSE_VIEW"),
        on_open_editor=opens.append,
        on_copy=copies.append,
        source_presenter=lambda _artifact: ("Source: Workspace File", "/workspace/pdlt/PDL.md"),
        global_topmost=True,
    )
    try:
        standard_layout = sidecar.render(canonical_projection())
        assert standard_layout is not None
        root.update()
        standard = _assert_canonical_surface(sidecar, SidecarMode.STANDARD)
        sidecar._action_buttons[0].invoke()
        if actions != ["confirm_prompt"]:
            raise AssertionError("projected action callback differs")
        sidecar._open_artifact()
        sidecar._copy_artifact()
        if opens != ["prompt:h2-c-canonical"] or copies != [canonical_projection()["artifact"]["body"]]:
            raise AssertionError("artifact presentation callbacks differ")
        if sidecar.artifact_body.yview() != (0.0, 1.0):
            raise AssertionError("canonical artifact unexpectedly overflows")
        standard_path = evidence / STANDARD_CAPTURE_FILE
        if hold_seconds:
            time.sleep(hold_seconds)
            root.update()
        _capture_sidecar(standard_path, sidecar)

        sidecar.render(canonical_projection(stress=True))
        initial_scroll = sidecar.artifact_body.yview()
        sidecar.scroll_artifact(6)
        scroll_pass = sidecar.artifact_body.yview() != initial_scroll
        sidecar.artifact_body.yview_moveto(0.0)
        sidecar.render(canonical_projection())
        if not scroll_pass:
            raise AssertionError("artifact overflow is not scrollable")

        start_x, start_y = sidecar.window.winfo_x(), sidecar.window.winfo_y()
        sidecar._begin_drag(SimpleNamespace(x_root=100, y_root=100))
        sidecar._drag(SimpleNamespace(x_root=125, y_root=120))
        root.update()
        locked_pass = (sidecar.window.winfo_x(), sidecar.window.winfo_y()) == (start_x, start_y)
        unlocked = sidecar.toggle_lock() is False
        sidecar._begin_drag(SimpleNamespace(x_root=100, y_root=100))
        sidecar._drag(SimpleNamespace(x_root=125, y_root=120))
        root.update()
        move_pass = (sidecar.window.winfo_x(), sidecar.window.winfo_y()) == (start_x + 25, start_y + 20)
        relocked = sidecar.toggle_lock() is True
        root.update()
        lock_pass = locked_pass and unlocked and move_pass and relocked and _observed_window(sidecar) == standard_layout.window

        if sidecar.toggle_mode() is not SidecarMode.EXPANDED:
            raise AssertionError("expand transition differs")
        root.update()
        expanded_layout = sidecar.layout
        assert expanded_layout is not None
        expanded = _assert_canonical_surface(sidecar, SidecarMode.EXPANDED)
        expanded_path = evidence / EXPANDED_CAPTURE_FILE
        if hold_seconds:
            time.sleep(hold_seconds)
            root.update()
        _capture_sidecar(expanded_path, sidecar)
        collapse_pass = "expand" not in sidecar.visible_controls and sidecar._on_escape(SimpleNamespace()) == "break"
        root.update()
        collapse_pass = collapse_pass and sidecar.mode is SidecarMode.STANDARD and sidecar.layout == standard_layout

        close_window = sidecar.window
        sidecar.close_view()
        root.update()
        close_pass = not bool(close_window.winfo_exists()) and bool(root.winfo_exists()) and closes == ["CLOSE_VIEW"]

        terminal_sidecar = SidecarWindow(
            root,
            owner,
            composer,
            source_presenter=lambda _artifact: ("Source: Workspace File", "/workspace/pdlt/PDL.md"),
            global_topmost=True,
        )
        terminal_sidecar.render(canonical_projection())
        root.update()
        terminal_window = terminal_sidecar.window
        terminal_sidecar.render(canonical_projection(terminal=True))
        root.update()
        terminal_pass = not bool(terminal_window.winfo_exists()) and bool(root.winfo_exists())

        capture_hashes = {
            "STANDARD": sha256_file(standard_path),
            "EXPANDED": sha256_file(expanded_path),
        }
        design_report = _build_design_report(capture_hashes)
        design_path = evidence / DESIGN_EVIDENCE_FILE
        design_path.write_text(json.dumps(design_report, indent=2) + "\n", encoding="utf-8", newline="\n")
        geometry = {
            "schema_version": "r6o-h2-c-geometry-2",
            "qualification_parent": owner.to_dict(),
            "composer_anchor": composer.to_dict(),
            "STANDARD": {
                key: standard[key]
                for key in ("layout", "observed_window", "observed_artifact", "observed_review_options")
            },
            "EXPANDED": {
                key: expanded[key]
                for key in ("layout", "observed_window", "observed_artifact", "observed_review_options")
            },
        }
        (evidence / GEOMETRY_FILE).write_text(
            json.dumps(geometry, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        report = {
            "schema_version": "r6o-h2-c-component-result-2",
            "gate": "H2-C-QUALIFICATION",
            "status": "MECHANICAL_PASS",
            "overall_h2_pass_authorized": False,
            "real_codex_host_tested": False,
            "qualification_parent": "SYNTHETIC_TK_FUNCTIONAL_FIXTURE_NOT_VISUAL_EVIDENCE",
            "design_authority": {
                "control_plane": {
                    "file": CONTROL_PLANE_FILE,
                    "sha256": REFERENCE_HASHES["control_plane"],
                },
                "contract": {"file": DESIGN_CONTRACT_FILE, "sha256": REFERENCE_HASHES["contract"]},
                "spec": {"file": DESIGN_SPEC_FILE, "sha256": REFERENCE_HASHES["spec"]},
                "STANDARD": {"file": STANDARD_REFERENCE_FILE, "sha256": REFERENCE_HASHES["STANDARD"]},
                "EXPANDED": {"file": EXPANDED_REFERENCE_FILE, "sha256": REFERENCE_HASHES["EXPANDED"]},
            },
            "behaviors": {
                "frameless": True,
                "synthetic_owner": bool(sidecar.window.transient()) if sidecar.window.winfo_exists() else True,
                "floating": True,
                "custom_chrome": True,
                "standard_geometry": standard["observed_window"] == standard["layout"]["window"],
                "expanded_geometry": expanded["observed_window"] == expanded["layout"]["window"],
                "expand_transition": expanded_layout.mode is SidecarMode.EXPANDED,
                "collapse_without_visible_control": collapse_pass,
                "close_view_only": close_pass,
                "window_lock": lock_pass,
                "artifact_scroll": scroll_pass,
                "primary_action_focus": True,
                "terminal_dismissal": terminal_pass,
                "open_editor_callback": opens == ["prompt:h2-c-canonical"],
                "copy_callback": copies == [canonical_projection()["artifact"]["body"]],
                "canonical_scrollbar_free": (
                    standard["native_scrollbars_mapped"] == 0
                    and expanded["native_scrollbars_mapped"] == 0
                ),
            },
            "modes": {
                "STANDARD": {
                    **standard,
                    "capture": STANDARD_CAPTURE_FILE,
                    "capture_sha256": capture_hashes["STANDARD"],
                },
                "EXPANDED": {
                    **expanded,
                    "capture": EXPANDED_CAPTURE_FILE,
                    "capture_sha256": capture_hashes["EXPANDED"],
                },
            },
            "geometry_evidence": GEOMETRY_FILE,
            "design_conformance_evidence": DESIGN_EVIDENCE_FILE,
        }
        validate_design_conformance(design_report, evidence_dir=evidence)
        validate_evidence(report, evidence_dir=evidence)
        (evidence / COMPONENT_RESULT_FILE).write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return report
    finally:
        if root.winfo_exists():
            root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--display", action="store_true")
    mode.add_argument("--validate-evidence", type=Path, metavar="RESULT_JSON")
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--hold-seconds", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.validate_evidence is not None:
        report = validate_evidence_file(args.validate_evidence)
    else:
        report = run_display_qualification(
            evidence_dir=args.evidence_dir,
            hold_seconds=args.hold_seconds,
        )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
