from __future__ import annotations

"""Qualify the H2 Sidecar component against a synthetic fullscreen Tk owner."""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.views.sidecar import Rect, SidecarMode, SidecarWindow, calculate_sidecar_layout


DEFAULT_EVIDENCE_DIR = ROOT / "r6o_evidence" / "H2-C-QUALIFICATION"
REFERENCE_PATH = "references/REFERENCE_UI-HARNESS.png"
REFERENCE_SHA256 = "a4defa180dbcebbcc443cd486474a1e6869cbeeb1a58359abb00c07b22facb2e"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
BEHAVIOR_KEYS = {
    "frameless",
    "synthetic_owner",
    "floating",
    "custom_chrome",
    "standard_geometry",
    "expanded_geometry",
    "expand_collapse",
    "close_view_only",
    "window_lock",
    "artifact_scroll",
    "primary_action_focus",
    "terminal_dismissal",
}
REPORT_KEYS = {
    "schema_version",
    "gate",
    "status",
    "overall_h2_pass_authorized",
    "real_codex_host_tested",
    "qualification_parent",
    "visual_reference",
    "claims",
    "behaviors",
    "modes",
    "geometry_evidence",
}
MODE_KEYS = {
    "layout",
    "observed_window",
    "observed_artifact",
    "observed_review_options",
    "screenshot",
    "screenshot_sha256",
}
FORBIDDEN_CLAIMS = {
    "CODEX_ATTACHMENT_PASS",
    "CODEX_Z_ORDER_PASS",
    "CODEX_FOCUS_PASS",
    "CODEX_COMPOSER_PASS",
    "SIDECAR_E2E_PASS",
    "H2_PASS",
}


def _normalized_words(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", value.casefold()))


def _reject_forbidden_authority(value: Any, path: str = "result") -> None:
    """Reject component evidence that claims later-gate or overall authority anywhere."""

    if isinstance(value, dict):
        for key, nested in value.items():
            key_words = set(_normalized_words(str(key)))
            if nested is True and "pass" in key_words and (
                "h2" in key_words
                or "codex" in key_words
                or "e2e" in key_words
                or key_words & {"attachment", "zorder", "focus", "composer"}
                or ({"z", "order"} <= key_words)
            ):
                raise AssertionError(f"H2-C evidence claims forbidden authority at {path}.{key}")
            _reject_forbidden_authority(nested, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_authority(nested, f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    words = set(_normalized_words(value))
    if "pass" not in words:
        return
    forbidden = (
        "h2" in words
        or "codex" in words
        or "e2e" in words
        or words & {"attachment", "zorder", "focus", "composer"}
        or ({"z", "order"} <= words)
    )
    if forbidden:
        raise AssertionError(f"H2-C evidence claims forbidden authority at {path}: {value!r}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError(f"{label} must be a JSON object")
    return value


def _rect_from_evidence(value: Any, label: str) -> Rect:
    rectangle = require_object(value, label)
    if set(rectangle) != {"x", "y", "width", "height"} or any(
        type(rectangle[key]) is not int for key in ("x", "y", "width", "height")
    ):
        raise AssertionError(f"{label} must be an exact integer rectangle")
    try:
        return Rect(**rectangle)
    except ValueError as exc:
        raise AssertionError(f"{label} is invalid: {exc}") from exc


def validate_evidence(value: Any, *, evidence_dir: Path | None = None) -> dict[str, Any]:
    _reject_forbidden_authority(value)
    report = require_object(value, "H2-C result")
    if set(report) != REPORT_KEYS:
        raise AssertionError("H2-C result fields differ")
    expected_identity = {
        "schema_version": "r6o-h2-c-component-result-1",
        "gate": "H2-C-QUALIFICATION",
        "status": "MECHANICAL_PASS",
        "overall_h2_pass_authorized": False,
        "real_codex_host_tested": False,
        "qualification_parent": "SYNTHETIC_FULLSCREEN_TK",
    }
    for key, expected in expected_identity.items():
        if report.get(key) != expected:
            raise AssertionError(f"H2-C {key} must be {expected!r}")
    reference = require_object(report.get("visual_reference"), "visual_reference")
    if reference != {"path": REFERENCE_PATH, "sha256": REFERENCE_SHA256}:
        raise AssertionError("H2-C visual reference identity differs")
    claims = report.get("claims")
    if not isinstance(claims, list) or not claims or any(not isinstance(item, str) for item in claims):
        raise AssertionError("H2-C claims must be a non-empty string array")
    normalized_claims = {item.upper().replace(" ", "_") for item in claims}
    forbidden = normalized_claims & FORBIDDEN_CLAIMS
    if forbidden:
        raise AssertionError(f"H2-C evidence claims forbidden authority: {sorted(forbidden)}")
    if any("CODEX" in item or "E2E" in item or item.startswith("H2_PASS") for item in normalized_claims):
        raise AssertionError("H2-C claims exceed component-only authority")
    behaviors = require_object(report.get("behaviors"), "behaviors")
    if set(behaviors) != BEHAVIOR_KEYS or any(value is not True for value in behaviors.values()):
        raise AssertionError("every required H2-C component behavior must be true")
    modes = require_object(report.get("modes"), "modes")
    if set(modes) != {"STANDARD", "EXPANDED"}:
        raise AssertionError("H2-C must contain STANDARD and EXPANDED evidence")
    for mode_name, mode_value in modes.items():
        mode = require_object(mode_value, f"modes.{mode_name}")
        if set(mode) != MODE_KEYS:
            raise AssertionError(f"modes.{mode_name} fields differ")
        layout = require_object(mode.get("layout"), f"modes.{mode_name}.layout")
        owner_rect = _rect_from_evidence(layout.get("owner"), f"modes.{mode_name}.layout.owner")
        composer_rect = _rect_from_evidence(
            layout.get("composer"), f"modes.{mode_name}.layout.composer"
        )
        try:
            expected_layout = calculate_sidecar_layout(
                owner_rect,
                composer_rect,
                SidecarMode(mode_name),
            ).to_dict()
        except ValueError as exc:
            raise AssertionError(f"modes.{mode_name} layout inputs are invalid: {exc}") from exc
        if layout != expected_layout:
            raise AssertionError(f"modes.{mode_name} layout differs from authoritative calculation")
        observed = require_object(mode.get("observed_window"), f"modes.{mode_name}.observed_window")
        if layout.get("mode") != mode_name or layout.get("window") != observed:
            raise AssertionError(f"modes.{mode_name} observed geometry differs from calculation")
        if layout.get("artifact") != mode.get("observed_artifact"):
            raise AssertionError(f"modes.{mode_name} observed artifact pane differs")
        if layout.get("review_options") != mode.get("observed_review_options"):
            raise AssertionError(f"modes.{mode_name} observed review-options pane differs")
        expected_composition = (
            "ARTIFACT_LEFT_REVIEW_OPTIONS_RIGHT"
            if mode_name == "STANDARD"
            else "ARTIFACT_TOP_REVIEW_OPTIONS_BELOW"
        )
        if layout.get("composition") != expected_composition:
            raise AssertionError(f"modes.{mode_name} composition differs")
        if mode_name == "STANDARD" and layout.get("composer_anchor_gap") != 10:
            raise AssertionError("STANDARD is not anchored directly above the composer")
        if mode_name == "EXPANDED":
            owner = require_object(layout.get("owner"), "EXPANDED owner")
            window = require_object(layout.get("window"), "EXPANDED window")
            owner_width = owner.get("width")
            if not isinstance(owner_width, int) or owner_width <= 0:
                raise AssertionError("EXPANDED owner width is invalid")
            expected_width = round(owner_width * 0.30)
            expected_fraction = round(expected_width / owner_width, 6)
            if (
                window.get("width") != expected_width
                or layout.get("parent_width_fraction") != expected_fraction
            ):
                raise AssertionError("EXPANDED width must be pixel-rounded from 30% of the parent")
        screenshot = mode.get("screenshot")
        screenshot_hash = mode.get("screenshot_sha256")
        expected_screenshot = f"sidecar-{mode_name.casefold()}.png"
        if screenshot != expected_screenshot:
            raise AssertionError(
                f"modes.{mode_name} screenshot must be the local file {expected_screenshot}"
            )
        if not isinstance(screenshot_hash, str) or SHA256_PATTERN.fullmatch(screenshot_hash) is None:
            raise AssertionError(f"modes.{mode_name} screenshot hash is invalid")
        if evidence_dir is not None:
            screenshot_path = evidence_dir / screenshot
            if not screenshot_path.is_file() or sha256_file(screenshot_path) != screenshot_hash:
                raise AssertionError(f"modes.{mode_name} screenshot evidence differs")
    if modes["STANDARD"]["screenshot_sha256"] == modes["EXPANDED"]["screenshot_sha256"]:
        raise AssertionError("STANDARD and EXPANDED screenshots must be visibly distinct")
    geometry_name = report.get("geometry_evidence")
    if geometry_name != "geometry.json":
        raise AssertionError("geometry_evidence must name the local geometry.json file")
    if evidence_dir is not None and not (evidence_dir / geometry_name).is_file():
        raise AssertionError("geometry evidence file is missing")
    if evidence_dir is not None:
        geometry = require_object(
            json.loads((evidence_dir / geometry_name).read_text(encoding="utf-8")),
            "geometry evidence",
        )
        if set(geometry) != {
            "schema_version",
            "qualification_parent",
            "composer_anchor",
            "STANDARD",
            "EXPANDED",
        } or geometry.get("schema_version") != "r6o-h2-c-geometry-1":
            raise AssertionError("geometry evidence fields differ")
        for mode_name in ("STANDARD", "EXPANDED"):
            expected_geometry = {
                "layout": modes[mode_name]["layout"],
                "observed_window": modes[mode_name]["observed_window"],
                "observed_artifact": modes[mode_name]["observed_artifact"],
                "observed_review_options": modes[mode_name]["observed_review_options"],
            }
            if geometry.get(mode_name) != expected_geometry:
                raise AssertionError(f"geometry evidence differs for {mode_name}")
    return report


def validate_evidence_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return validate_evidence(value, evidence_dir=path.resolve().parent)


def sample_projection(*, terminal: bool = False) -> dict[str, Any]:
    if terminal:
        return {
            "stage": "CLOSED_SUCCESS",
            "artifact": None,
            "actions": [],
            "lifecycle": {"terminal": True},
        }
    body = "# Prompt\n\nBuild a task manager with:\n\n" + "\n".join(
        f"- Qualification requirement {index:02d}: preserve authoritative projection behavior."
        for index in range(1, 46)
    )
    return {
        "stage": "PROMPT_REVIEW",
        "artifact": {
            "artifact_ref": "artifact://h2-c/qualification-prompt",
            "artifact_revision": "revision-1",
            "artifact_kind": "prompt",
            "title": "Authoritative Prompt (PDL.md)",
            "body": body,
        },
        "actions": [
            {"action_id": "confirm_prompt", "ordinal": 1, "label": "Confirm prompt", "emphasis": "PRIMARY", "enabled": True},
            {"action_id": "change_task", "ordinal": 2, "label": "Change the task", "emphasis": "NORMAL", "enabled": True},
            {"action_id": "change_approach", "ordinal": 3, "label": "Change approach", "emphasis": "NORMAL", "enabled": True},
            {"action_id": "something_else", "ordinal": 4, "label": "Something else...", "emphasis": "NORMAL", "enabled": True},
        ],
        "lifecycle": {"terminal": False},
    }


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def _capture_parent(path: Path, root: Any, sidecar_rect: Rect) -> None:
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError("Pillow is required for H2-C screenshot evidence") from exc
    root.update()
    bbox = (
        root.winfo_rootx(),
        root.winfo_rooty(),
        root.winfo_rootx() + root.winfo_width(),
        root.winfo_rooty() + root.winfo_height(),
    )
    image = ImageGrab.grab(bbox=bbox, all_screens=True)
    sample = image.convert("RGB").getpixel((image.width // 2, min(120, image.height - 1)))
    expected = (11, 17, 24)
    if any(abs(actual - wanted) > 8 for actual, wanted in zip(sample, expected, strict=True)):
        raise AssertionError(
            "synthetic qualification parent is not visibly foregrounded in screenshot evidence: "
            f"expected {expected}, got {sample}"
        )
    sidecar_x = sidecar_rect.x - root.winfo_rootx() + 6
    sidecar_y = sidecar_rect.y - root.winfo_rooty() + 6
    sidecar_sample = image.convert("RGB").getpixel((sidecar_x, sidecar_y))
    sidecar_expected = (17, 24, 32)
    if any(
        abs(actual - wanted) > 8
        for actual, wanted in zip(sidecar_sample, sidecar_expected, strict=True)
    ):
        raise AssertionError(
            "Sidecar chrome is not visibly foregrounded in screenshot evidence: "
            f"expected {sidecar_expected}, got {sidecar_sample}"
        )
    image.save(path, format="PNG")


def _observed_rect(window: Any) -> Rect:
    window.update_idletasks()
    return Rect(window.winfo_x(), window.winfo_y(), window.winfo_width(), window.winfo_height())


def _observed_local_rect(widget: Any, window: Any) -> Rect:
    widget.update_idletasks()
    return Rect(
        widget.winfo_rootx() - window.winfo_rootx(),
        widget.winfo_rooty() - window.winfo_rooty(),
        widget.winfo_width(),
        widget.winfo_height(),
    )


def run_display_qualification(
    *,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    hold_seconds: float = 1.0,
) -> dict[str, Any]:
    if hold_seconds < 0:
        raise ValueError("hold_seconds cannot be negative")
    _enable_dpi_awareness()
    import tkinter as tk

    evidence = evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    standard_path = evidence / "sidecar-standard.png"
    expanded_path = evidence / "sidecar-expanded.png"
    geometry_path = evidence / "geometry.json"
    result_path = evidence / "component-result.json"
    root = tk.Tk()
    root.title("Synthetic H2-C Qualification Parent — NOT CODEX")
    root.configure(bg="#0b1118")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    root.update()
    width = root.winfo_width()
    height = root.winfo_height()
    if width < 1024 or height < 700:
        raise RuntimeError(f"H2-C display requires at least 1024x700, got {width}x{height}")
    tk.Label(
        root,
        text="SYNTHETIC H2-C QUALIFICATION PARENT — NOT CODEX",
        bg="#0b1118",
        fg="#8291a0",
        font=("Segoe UI Semibold", 11),
    ).place(x=24, y=18)
    tk.Label(
        root,
        text="Component-only owner fixture\nNo host attachment, z-order, composer, or E2E authority",
        bg="#0b1118",
        fg="#536271",
        justify="left",
        font=("Segoe UI", 10),
    ).place(x=24, y=58)
    composer_margin = max(24, round(width * 0.025))
    composer_height = max(120, round(height * 0.14))
    composer_y = height - composer_margin - composer_height
    composer_frame = tk.Frame(root, bg="#111a23", highlightbackground="#34424f", highlightthickness=1)
    composer_frame.place(
        x=composer_margin,
        y=composer_y,
        width=width - 2 * composer_margin,
        height=composer_height,
    )
    tk.Label(
        composer_frame,
        text="Synthetic composer anchor (component geometry only)",
        bg="#111a23",
        fg="#748493",
        anchor="w",
        font=("Segoe UI", 10),
    ).pack(fill="both", expand=True, padx=18)
    root.update()
    owner_rect = Rect(root.winfo_rootx(), root.winfo_rooty(), width, height)
    composer_rect = Rect(
        root.winfo_rootx() + composer_margin,
        root.winfo_rooty() + composer_y,
        width - 2 * composer_margin,
        composer_height,
    )
    actions: list[str] = []
    close_events: list[str] = []
    sidecar = SidecarWindow(
        root,
        owner_rect,
        composer_rect,
        on_action=actions.append,
        on_close_view=lambda: close_events.append("CLOSE_VIEW"),
        global_topmost=True,
    )
    try:
        standard = sidecar.render(sample_projection())
        assert standard is not None
        root.update()
        standard_observed = _observed_rect(sidecar.window)
        standard_artifact_observed = _observed_local_rect(sidecar.artifact_panel, sidecar.window)
        standard_options_observed = _observed_local_rect(sidecar.options_panel, sidecar.window)
        if standard_observed != standard.window:
            raise AssertionError(f"STANDARD window differs: {standard_observed} != {standard.window}")
        if standard_artifact_observed != standard.artifact:
            raise AssertionError(
                f"STANDARD artifact pane differs: {standard_artifact_observed} != {standard.artifact}"
            )
        if standard_options_observed != standard.review_options:
            raise AssertionError(
                f"STANDARD review-options pane differs: {standard_options_observed} != {standard.review_options}"
            )
        if not bool(sidecar.window.overrideredirect()):
            raise AssertionError("Sidecar native chrome was not removed")
        if not sidecar.window.transient():
            raise AssertionError("Sidecar has no synthetic owner relationship")
        floating_pass = bool(sidecar.window.attributes("-topmost"))
        if not floating_pass:
            raise AssertionError("synthetic qualification Sidecar is not floating above its owner")
        sidecar.focus_primary_action()
        root.update()
        focus_pass = sidecar.window.focus_get() is sidecar._action_buttons[0]
        sidecar._action_buttons[0].invoke()
        if actions != ["confirm_prompt"]:
            raise AssertionError("projected action callback did not preserve action_id")
        initial_scroll = sidecar.artifact_body.yview()
        sidecar.scroll_artifact(12)
        root.update()
        scroll_pass = sidecar.artifact_body.yview() != initial_scroll
        sidecar.artifact_body.yview_moveto(0.0)
        root.update()
        if hold_seconds:
            time.sleep(hold_seconds)
            root.update()
        _capture_parent(standard_path, root, standard.window)

        start_x = sidecar.window.winfo_x()
        start_y = sidecar.window.winfo_y()
        sidecar._begin_drag(SimpleNamespace(x_root=100, y_root=100))
        sidecar._drag(SimpleNamespace(x_root=125, y_root=120))
        root.update()
        locked_position_pass = (sidecar.window.winfo_x(), sidecar.window.winfo_y()) == (start_x, start_y)
        unlocked = sidecar.toggle_lock() is False
        sidecar._begin_drag(SimpleNamespace(x_root=100, y_root=100))
        sidecar._drag(SimpleNamespace(x_root=125, y_root=120))
        root.update()
        unlocked_drag_pass = (sidecar.window.winfo_x(), sidecar.window.winfo_y()) == (start_x + 25, start_y + 20)
        relocked = sidecar.toggle_lock() is True
        root.update()
        relocked_position_pass = _observed_rect(sidecar.window) == standard.window
        window_lock_pass = (
            locked_position_pass
            and unlocked
            and unlocked_drag_pass
            and relocked
            and relocked_position_pass
        )
        if not window_lock_pass:
            raise AssertionError("window lock did not block, allow, and restore drag geometry")
        if sidecar.toggle_mode() is not SidecarMode.EXPANDED:
            raise AssertionError("Expand did not enter EXPANDED mode")
        root.update()
        expanded = sidecar.layout
        assert expanded is not None
        expanded_observed = _observed_rect(sidecar.window)
        expanded_artifact_observed = _observed_local_rect(sidecar.artifact_panel, sidecar.window)
        expanded_options_observed = _observed_local_rect(sidecar.options_panel, sidecar.window)
        if expanded_observed != expanded.window:
            raise AssertionError(f"EXPANDED window differs: {expanded_observed} != {expanded.window}")
        if expanded_artifact_observed != expanded.artifact:
            raise AssertionError(
                f"EXPANDED artifact pane differs: {expanded_artifact_observed} != {expanded.artifact}"
            )
        if expanded_options_observed != expanded.review_options:
            raise AssertionError(
                f"EXPANDED review-options pane differs: {expanded_options_observed} != {expanded.review_options}"
            )
        if expanded.window.width != round(owner_rect.width * 0.30):
            raise AssertionError("EXPANDED window is not the pixel-rounded 30% parent width")
        chrome_widgets = (
            sidecar.title_label,
            sidecar.stage_label,
            sidecar.active_label,
            sidecar.lock_button,
            sidecar.expand_button,
            sidecar.close_button,
        )
        chrome_bounds_pass = all(
            widget.winfo_ismapped()
            and widget.winfo_rootx() >= sidecar.window.winfo_rootx()
            and widget.winfo_rootx() + widget.winfo_width()
            <= sidecar.window.winfo_rootx() + sidecar.window.winfo_width()
            for widget in chrome_widgets
        )
        if not chrome_bounds_pass:
            raise AssertionError("EXPANDED custom chrome controls are clipped")
        if hold_seconds:
            time.sleep(hold_seconds)
            root.update()
        _capture_parent(expanded_path, root, expanded.window)
        collapse_mode_pass = sidecar.toggle_mode() is SidecarMode.STANDARD
        root.update()
        collapsed_layout = sidecar.layout
        assert collapsed_layout is not None
        collapse_pass = (
            collapse_mode_pass
            and collapsed_layout == standard
            and _observed_rect(sidecar.window) == standard.window
            and _observed_local_rect(sidecar.artifact_panel, sidecar.window) == standard.artifact
            and _observed_local_rect(sidecar.options_panel, sidecar.window) == standard.review_options
        )
        if not collapse_pass:
            raise AssertionError("Collapse did not restore complete STANDARD geometry")
        close_view = sidecar.window
        sidecar.close_view()
        root.update()
        close_only_pass = not bool(close_view.winfo_exists()) and bool(root.winfo_exists()) and close_events == ["CLOSE_VIEW"]

        terminal_sidecar = SidecarWindow(root, owner_rect, composer_rect, global_topmost=True)
        terminal_sidecar.render(sample_projection())
        root.update()
        terminal_window = terminal_sidecar.window
        terminal_sidecar.render(sample_projection(terminal=True))
        root.update()
        terminal_pass = not bool(terminal_window.winfo_exists()) and bool(root.winfo_exists())

        geometry = {
            "schema_version": "r6o-h2-c-geometry-1",
            "qualification_parent": owner_rect.to_dict(),
            "composer_anchor": composer_rect.to_dict(),
            "STANDARD": {
                "layout": standard.to_dict(),
                "observed_window": standard_observed.to_dict(),
                "observed_artifact": standard_artifact_observed.to_dict(),
                "observed_review_options": standard_options_observed.to_dict(),
            },
            "EXPANDED": {
                "layout": expanded.to_dict(),
                "observed_window": expanded_observed.to_dict(),
                "observed_artifact": expanded_artifact_observed.to_dict(),
                "observed_review_options": expanded_options_observed.to_dict(),
            },
        }
        geometry_path.write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8", newline="\n")
        report = {
            "schema_version": "r6o-h2-c-component-result-1",
            "gate": "H2-C-QUALIFICATION",
            "status": "MECHANICAL_PASS",
            "overall_h2_pass_authorized": False,
            "real_codex_host_tested": False,
            "qualification_parent": "SYNTHETIC_FULLSCREEN_TK",
            "visual_reference": {"path": REFERENCE_PATH, "sha256": REFERENCE_SHA256},
            "claims": [
                "SIDECAR_COMPONENT_RENDERING",
                "WINDOW_CHROME",
                "SYNTHETIC_OWNER_GEOMETRY",
            ],
            "behaviors": {
                "frameless": True,
                "synthetic_owner": True,
                "floating": floating_pass,
                "custom_chrome": chrome_bounds_pass,
                "standard_geometry": (
                    standard_observed == standard.window
                    and standard_artifact_observed == standard.artifact
                    and standard_options_observed == standard.review_options
                ),
                "expanded_geometry": (
                    expanded_observed == expanded.window
                    and expanded_artifact_observed == expanded.artifact
                    and expanded_options_observed == expanded.review_options
                ),
                "expand_collapse": collapse_pass,
                "close_view_only": close_only_pass,
                "window_lock": window_lock_pass,
                "artifact_scroll": scroll_pass,
                "primary_action_focus": focus_pass,
                "terminal_dismissal": terminal_pass,
            },
            "modes": {
                "STANDARD": {
                    "layout": standard.to_dict(),
                    "observed_window": standard_observed.to_dict(),
                    "observed_artifact": standard_artifact_observed.to_dict(),
                    "observed_review_options": standard_options_observed.to_dict(),
                    "screenshot": standard_path.name,
                    "screenshot_sha256": sha256_file(standard_path),
                },
                "EXPANDED": {
                    "layout": expanded.to_dict(),
                    "observed_window": expanded_observed.to_dict(),
                    "observed_artifact": expanded_artifact_observed.to_dict(),
                    "observed_review_options": expanded_options_observed.to_dict(),
                    "screenshot": expanded_path.name,
                    "screenshot_sha256": sha256_file(expanded_path),
                },
            },
            "geometry_evidence": geometry_path.name,
        }
        validate_evidence(report, evidence_dir=evidence)
        result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        return report
    finally:
        if root.winfo_exists():
            root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--display", action="store_true", help="run the synthetic fullscreen component qualification")
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
