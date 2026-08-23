from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from r6o.host.codex.windows.binding import (
    CodexBindingError,
    CodexSidecarBinding,
    ResolvedHostControls,
    resolve_actual_composer,
    verify_frozen_host_identity,
    verify_selector_host_compatibility,
)
from r6o.host.codex.windows.discovery import HostCandidate
from r6o.host.codex.windows.placement import (
    PlacementError,
    Rect,
    canonical_physical_size,
    expanded_placement,
    rect_from_record,
    rectangles_match,
    scale_logical,
    standard_placement,
)
from r6o.views.sidecar.model import EXPANDED_SIZE, STANDARD_SIZE, SidecarMode


ROOT = Path(__file__).resolve().parents[3]


def candidate(**overrides: object) -> HostCandidate:
    values: dict[str, object] = {
        "hwnd": 101,
        "pid": 202,
        "executable": r"C:\Program Files\WindowsApps\OpenAI.Codex_1.2.3.4_x64\app\ChatGPT.exe",
        "product_name": "Codex",
        "product_version": "151.0.1.2",
        "file_version": "151.0.1.2",
        "package_version": "1.2.3.4",
        "title": "ChatGPT",
        "class_name": "Chrome_WidgetWin_1",
        "visible": True,
    }
    values.update(overrides)
    return HostCandidate(**values)  # type: ignore[arg-type]


def host_record(value: HostCandidate | None = None) -> dict[str, object]:
    selected = value or candidate()
    return {
        "codex": {
            "hwnd": selected.hwnd,
            "pid": selected.pid,
            "executable": selected.executable,
            "product_name": selected.product_name,
            "product_version": selected.product_version,
            "file_version": selected.file_version,
            "package_version": selected.package_version,
            "window_class": selected.class_name,
        }
    }


def test_frozen_host_binding_selects_exact_hwnd_even_with_other_codex_windows() -> None:
    frozen = candidate()
    other = candidate(hwnd=303, title="Select files")
    assert verify_frozen_host_identity(host_record(frozen), enumerator=lambda: [frozen, other]) == frozen


@pytest.mark.parametrize(
    "mutation",
    [
        {"pid": 999},
        {"product_version": "other"},
        {"file_version": "other"},
        {"package_version": "other"},
        {"class_name": "other"},
        {"executable": r"C:\other\ChatGPT.exe"},
    ],
)
def test_frozen_host_binding_rejects_identity_shift(mutation: dict[str, object]) -> None:
    frozen = candidate()
    changed = candidate(**mutation)
    with pytest.raises(CodexBindingError, match="FROZEN_HOST_IDENTITY_MISMATCH"):
        verify_frozen_host_identity(host_record(frozen), enumerator=lambda: [changed])


def test_frozen_host_binding_rejects_missing_or_duplicate_exact_hwnd() -> None:
    frozen = candidate()
    with pytest.raises(CodexBindingError, match="FROZEN_HOST_HWND_STALE"):
        verify_frozen_host_identity(host_record(frozen), enumerator=lambda: [])
    with pytest.raises(CodexBindingError, match="FROZEN_HOST_HWND_STALE"):
        verify_frozen_host_identity(host_record(frozen), enumerator=lambda: [frozen, frozen])


def test_selector_compatibility_is_exactly_bound_to_frozen_host() -> None:
    frozen = candidate()
    selectors = {
        "host_compatibility": {
            "product_name": frozen.product_name,
            "product_version": frozen.product_version,
            "file_version": frozen.file_version,
            "package_version": frozen.package_version,
        }
    }
    verify_selector_host_compatibility(selectors, host_record(frozen))
    changed = deepcopy(selectors)
    changed["host_compatibility"]["file_version"] = "wrong"
    with pytest.raises(CodexBindingError, match="SELECTOR_HOST_MISMATCH:file_version"):
        verify_selector_host_compatibility(changed, host_record(frozen))


class FakeRectangle:
    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class FakeWrapper:
    def __init__(
        self,
        *,
        control_type: str = "Group",
        automation_id: str = "",
        class_name: str = "",
        name: str = "",
        rectangle: tuple[int, int, int, int] = (0, 0, 100, 100),
        children: list["FakeWrapper"] | None = None,
        parent: "FakeWrapper | None" = None,
    ) -> None:
        self.element_info = SimpleNamespace(
            control_type=control_type,
            automation_id=automation_id,
            class_name=class_name,
            name=name,
        )
        self._rectangle = FakeRectangle(*rectangle)
        self._children = children or []
        self._parent = parent
        for child in self._children:
            child._parent = self

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def rectangle(self) -> FakeRectangle:
        return self._rectangle

    def parent(self) -> "FakeWrapper | None":
        return self._parent

    def descendants(self, control_type: str | None = None) -> list["FakeWrapper"]:
        values: list[FakeWrapper] = []
        for child in self._children:
            if control_type is None or child.element_info.control_type == control_type:
                values.append(child)
            values.extend(child.descendants(control_type))
        return values


COMPOSER_SELECTOR = {
    "control_type": "Edit",
    "automation_id": {"match": "ABSENT"},
    "name": {"match": "IGNORED_DYNAMIC"},
    "class_name": {"match": "TOKEN", "value": "ProseMirror"},
    "visible": True,
    "enabled": True,
    "ancestor_chain": [],
    "fallback": "PROHIBITED",
}


def prose_mirror(rectangle: tuple[int, int, int, int]) -> FakeWrapper:
    return FakeWrapper(control_type="Edit", class_name="content ProseMirror editor", rectangle=rectangle)


def test_composer_geometry_resolves_actual_bottom_editor_when_goal_editor_is_open() -> None:
    actual = prose_mirror((377, 799, 1090, 843))
    goal = prose_mirror((1203, 101, 1566, 366))
    root = FakeWrapper(children=[actual, goal], rectangle=(-1, -1, 1601, 899))
    primary = FakeWrapper(rectangle=(284, 35, 1601, 899))
    wrapper, rectangle, selector_count = resolve_actual_composer(
        root,
        COMPOSER_SELECTOR,
        primary_content_region=primary,
        dpi=96,
    )
    assert wrapper is actual
    assert rectangle == Rect(377, 799, 1090, 843)
    assert selector_count == 2


def test_composer_geometry_fails_closed_for_zero_or_multiple_bottom_editors() -> None:
    primary = FakeWrapper(rectangle=(284, 35, 1601, 899))
    only_goal = FakeWrapper(children=[prose_mirror((1203, 101, 1566, 366))])
    with pytest.raises(CodexBindingError, match="COMPOSER_GEOMETRY_CARDINALITY:0"):
        resolve_actual_composer(only_goal, COMPOSER_SELECTOR, primary_content_region=primary, dpi=96)
    ambiguous = FakeWrapper(
        children=[prose_mirror((377, 799, 1090, 843)), prose_mirror((700, 720, 1200, 780))]
    )
    with pytest.raises(CodexBindingError, match="COMPOSER_GEOMETRY_CARDINALITY:2"):
        resolve_actual_composer(ambiguous, COMPOSER_SELECTOR, primary_content_region=primary, dpi=96)


def test_composer_geometry_never_weakens_prohibited_fallback() -> None:
    selector = deepcopy(COMPOSER_SELECTOR)
    selector["fallback"] = "NAME_ONLY"
    root = FakeWrapper(children=[prose_mirror((377, 799, 1090, 843))])
    primary = FakeWrapper(rectangle=(284, 35, 1601, 899))
    with pytest.raises(CodexBindingError, match="COMPOSER_SELECTOR_FALLBACK_PROHIBITED"):
        resolve_actual_composer(root, selector, primary_content_region=primary, dpi=96)


def test_standard_placement_preserves_locked_qml_size_and_composer_anchor() -> None:
    composer = Rect(377, 799, 1090, 843)
    work_area = Rect(0, 0, 1600, 900)
    result = standard_placement(composer=composer, work_area=work_area, dpi=96)
    assert result == Rect(377, 491, 1052, 791)
    assert (result.width, result.height) == STANDARD_SIZE
    assert result.left == composer.left
    assert result.bottom + 8 == composer.top
    assert result.width != composer.width


def test_expanded_placement_preserves_locked_qml_size_and_host_insets() -> None:
    host_client = Rect(-1, -1, 1601, 899)
    work_area = Rect(0, 0, 1600, 900)
    result = expanded_placement(host_client=host_client, work_area=work_area, dpi=96)
    assert result == Rect(1165, 47, 1577, 853)
    assert (result.width, result.height) == EXPANDED_SIZE
    assert host_client.right - result.right == 24
    assert result.top - host_client.top == 48


def test_placement_scales_at_monitor_dpi_without_changing_logical_qml_contract() -> None:
    assert scale_logical(675, 144) == 1013
    assert canonical_physical_size(SidecarMode.STANDARD, 144) == (1013, 450)
    assert canonical_physical_size(SidecarMode.EXPANDED, 144) == (618, 1209)
    assert SidecarMode.STANDARD.size == STANDARD_SIZE
    assert SidecarMode.EXPANDED.size == EXPANDED_SIZE


def test_placement_rejects_off_work_area_and_malformed_records() -> None:
    with pytest.raises(PlacementError, match="STANDARD_PLACEMENT_OUT_OF_WORK_AREA"):
        standard_placement(composer=Rect(20, 100, 700, 150), work_area=Rect(0, 0, 800, 600), dpi=96)
    with pytest.raises(PlacementError, match="EXPANDED_PLACEMENT_EXCEEDS_HOST_CLIENT"):
        expanded_placement(host_client=Rect(0, 0, 800, 700), work_area=Rect(0, 0, 800, 700), dpi=96)
    with pytest.raises(PlacementError, match="RECTANGLE_RECORD_INVALID:test"):
        rect_from_record({"left": 0, "top": 0, "right": 10, "bottom": 10, "width": 9}, label="test")


class FakeNative:
    def __init__(self, actual: Rect) -> None:
        self.actual = actual
        self.calls: list[str] = []

    def is_window(self, hwnd: int) -> bool:
        self.calls.append("is_window")
        return True

    def rectangle(self, hwnd: int) -> Rect:
        self.calls.append("rectangle")
        return self.actual

    def owner(self, hwnd: int) -> int:
        self.calls.append("owner")
        return 101

    def is_topmost(self, hwnd: int) -> bool:
        self.calls.append("is_topmost")
        return False

    def z_order(self) -> list[int]:
        self.calls.append("z_order")
        return [303, 101]

    def is_visible(self, hwnd: int) -> bool:
        self.calls.append("is_visible")
        return True

    def foreground(self) -> int:
        self.calls.append("foreground")
        return 303


def bare_binding(native: FakeNative) -> CodexSidecarBinding:
    binding = CodexSidecarBinding.__new__(CodexSidecarBinding)
    binding.host_hwnd = 101
    binding.sidecar_hwnd = 303
    binding.dpi = 96
    binding.native = native
    binding.sidecar = SimpleNamespace(mode=SidecarMode.STANDARD)
    binding.controls = ResolvedHostControls(
        root=object(),
        composer=object(),
        primary_content_region=object(),
        composer_rectangle=Rect(377, 799, 1090, 843),
        primary_content_rectangle=Rect(284, 35, 1601, 899),
        composer_selector_match_count=2,
    )
    binding.host_client_rectangle = Rect(-1, -1, 1601, 899)
    binding.work_area_rectangle = Rect(0, 0, 1600, 900)
    return binding


def test_steady_state_observation_is_read_only_and_proves_owner_z_order_and_placement() -> None:
    expected = Rect(377, 491, 1052, 791)
    native = FakeNative(expected)
    record = bare_binding(native).observe(expected=expected)
    assert record["owner_hwnd"] == 101
    assert record["sidecar_above_host"] is True
    assert record["global_topmost"] is False
    assert record["placement_matches"] is True
    assert record["composer_selector_match_count"] == 2
    assert all(call not in native.calls for call in ("move_resize", "set_owner", "activate", "raise"))


@pytest.mark.parametrize(
    ("attribute", "value", "error"),
    [
        ("owner", 999, "SIDECAR_OWNER_CHANGED"),
        ("is_topmost", True, "SIDECAR_GLOBAL_TOPMOST_PROHIBITED"),
        ("z_order", [101, 303], "SIDECAR_NOT_ABOVE_HOST"),
        ("is_visible", False, "SIDECAR_NOT_VISIBLE"),
    ],
)
def test_steady_state_observation_fails_closed(
    attribute: str, value: object, error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = Rect(377, 491, 1052, 791)
    native = FakeNative(expected)
    if callable(getattr(native, attribute)):
        monkeypatch.setattr(native, attribute, lambda *args: value)
    with pytest.raises(CodexBindingError, match=error):
        bare_binding(native).observe(expected=expected)


def test_rectangle_comparison_uses_only_frozen_two_pixel_tolerance() -> None:
    expected = Rect(100, 100, 775, 400)
    assert rectangles_match(Rect(98, 102, 776, 399), expected)
    assert not rectangles_match(Rect(97, 100, 775, 400), expected)


def test_d2_host_binding_stays_outside_protected_semantic_layers() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "r6o" / "host" / "codex" / "windows" / "binding.py",
            ROOT / "r6o" / "host" / "codex" / "windows" / "placement.py",
        )
    ).lower()
    for forbidden in (
        "mechanicalcontroller",
        "sessionengine",
        "workeradapter",
        "reviewdecision",
        "r6o.viewmodel",
        "r6o.model_binding",
    ):
        assert forbidden not in sources


def test_d2_verifier_has_portable_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "h2" / "verify_codex_attachment.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_d2_contract_import_does_not_require_qt_runtime() -> None:
    script = """
import sys
class BlockPySide:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PySide6' or fullname.startswith('PySide6.'):
            raise ModuleNotFoundError('blocked PySide6')
        return None
sys.meta_path.insert(0, BlockPySide())
from r6o.host.codex.windows.binding import CodexBindingError
from r6o.host.codex.windows.placement import Rect
from r6o.views.sidecar import SidecarMode
assert CodexBindingError and Rect(0, 0, 1, 1).width == 1
assert SidecarMode.STANDARD.value == 'STANDARD'
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_readme_d2_qualification_is_branch_bound_and_paste_safe() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    assert "codex/h2-d2-codex-attachment" in readme
    assert "H2-D2 CHECKOUT VERIFIED" in readme
    assert "requirements-h2-d2.txt" in readme
    assert "verify_codex_attachment.py --host-record" in readme
    assert "H2_D2_ATTACHMENT_PASS" in readme
    assert "Do not press Enter or click Codex Send" in normalized


def test_d2_evidence_schema_and_required_observations_when_present() -> None:
    path = ROOT / "r6o_evidence" / "H2-D2" / "attachment-result.json"
    if not path.exists():
        pytest.skip("live D2 evidence is created only by the Windows verifier")
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == "r6o-h2-d2-attachment-result-1"
    assert document["status"] == "H2_D2_ATTACHMENT_PASS"
    assert document["real_codex_host_tested"] is True
    assert document["synthetic_owner_used"] is False
    assert document["standard"]["owner_hwnd"] == document["host"]["hwnd"]
    assert document["standard"]["sidecar_above_host"] is True
    assert document["standard"]["global_topmost"] is False
    assert document["non_interference"]["marker_submitted"] is False
    assert document["non_interference"]["placement_unchanged"] is True
    assert document["unrelated_window"]["host_focus_router_ignored_probe_click"] is True
    assert document["close_focus_return"]["composer_keyboard_focus"] is True
    assert document["recording"]["frame_count"] > 0
    assert len(document["recording"]["sha256"]) == 64
    assert document["observer_ordering_mutation"] is False
    assert document["host_record_sha256"] == hashlib.sha256(
        (ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json").read_bytes()
    ).hexdigest()
    assert document["selectors_sha256"] == hashlib.sha256(
        (ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json").read_bytes()
    ).hexdigest()

    recording_hashes: list[str] = []
    for mode in ("standard", "expanded"):
        recording = document["recording"][mode]
        recording_path = ROOT / recording["path"]
        assert recording_path.read_bytes()[4:8] == b"ftyp"
        actual_hash = hashlib.sha256(recording_path.read_bytes()).hexdigest()
        assert recording["sha256"] == actual_hash
        assert recording["observer_ordering_mutation"] is False
        recording_hashes.append(actual_hash)
    assert document["recording"]["sha256"] == hashlib.sha256(
        "".join(recording_hashes).encode("ascii")
    ).hexdigest()

    standard_crop = document["recording"]["standard"]["crop_rectangle"]
    standard_window = document["standard"]["actual_rectangle"]
    composer = document["composer_resolution"]["actual_composer_rectangle"]
    assert standard_crop["left"] == standard_window["left"] - 1
    assert standard_crop["right"] == standard_window["right"]
    assert standard_crop["top"] == standard_window["top"]
    assert standard_crop["bottom"] == composer["bottom"]
    assert document["recording"]["expanded"]["crop_rectangle"] == document["expanded"][
        "actual_rectangle"
    ]

    event_path = ROOT / document["event_log"]["path"]
    assert document["event_log"]["sha256"] == hashlib.sha256(event_path.read_bytes()).hexdigest()
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    clicked = next(event for event in events if event["event"] == "actual_codex_composer_clicked")
    assert clicked["focus_router_transfer_count"] >= 1
    assert clicked["exact_owner_preserved"] is True
    assert clicked["thread_input_attached_only_for_focus_transaction"] is True
