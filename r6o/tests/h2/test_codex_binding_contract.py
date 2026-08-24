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
    HostClickFocusRouter,
    NativeWindowApi,
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
from scripts.h2.verify_codex_attachment import clear_injected_composer_text


ROOT = Path(__file__).resolve().parents[3]
HISTORICAL_D2_EVIDENCE_DIR = ROOT / "r6o_evidence" / "H2-D2"
CURRENT_D1R_D2_EVIDENCE_DIR = ROOT / "r6o_evidence" / "H2-D1R" / "d2-actual-host"
HISTORICAL_D1_HOST_RECORD_SHA256 = "7cf1b2219f38b2d7e1f610dd25467969c688b681b3ac0632041eff3978ce9db5"
HISTORICAL_D2_SELECTORS_SHA256 = "cb5a1b5b3123c979c54ecd3ec2614aa1d7b3c927dec987cdcfbbddeae75a21ef"


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


def test_native_placement_never_mutates_z_order() -> None:
    calls: list[tuple[object, ...]] = []
    api = NativeWindowApi.__new__(NativeWindowApi)
    api.win32con = SimpleNamespace(SWP_NOACTIVATE=1, SWP_NOZORDER=2, SWP_SHOWWINDOW=4)
    api.win32gui = SimpleNamespace(SetWindowPos=lambda *args: calls.append(args))
    api.move_resize(303, Rect(10, 20, 110, 220))
    assert calls == [(303, 0, 10, 20, 100, 200, 3)]


@pytest.mark.parametrize(
    ("attach_results", "expected_error", "expected_success"),
    [
        ([False], "HOST_THREAD_INPUT_ATTACH_FAILED", False),
        ([True, False], "HOST_THREAD_INPUT_DETACH_FAILED", False),
        ([True, True], None, True),
    ],
)
def test_focus_transaction_requires_both_thread_input_attach_and_detach(
    attach_results: list[bool], expected_error: str | None, expected_success: bool
) -> None:
    class FakeUser32:
        def __init__(self) -> None:
            self.results = iter(attach_results)

        def GetWindowLongW(self, hwnd: int, index: int) -> int:
            return 0

        def SetWindowLongW(self, hwnd: int, index: int, style: int) -> int:
            return 0

        def GetWindowThreadProcessId(self, hwnd: int, pid: object) -> int:
            return 11 if hwnd == 303 else 22

        def AttachThreadInput(self, first: int, second: int, attach: bool) -> bool:
            return next(self.results)

        def SetForegroundWindow(self, hwnd: int) -> bool:
            return True

        def SetActiveWindow(self, hwnd: int) -> int:
            return hwnd

        def GetForegroundWindow(self) -> int:
            return 101

    router = HostClickFocusRouter.__new__(HostClickFocusRouter)
    router.host_hwnd = 101
    router.sidecar_hwnd = 303
    router._error = None
    router._complete_host_transfer(FakeUser32())
    assert router._error == expected_error
    assert router.last_transfer_succeeded is expected_success
    assert router.last_thread_input_attached is (attach_results[0] is True)
    assert router.last_thread_input_detached is (len(attach_results) == 2 and attach_results[1])


def test_binding_remeasures_exact_host_geometry_instead_of_using_frozen_d1_rectangles() -> None:
    binding = CodexSidecarBinding.__new__(CodexSidecarBinding)
    binding.host_candidate = candidate()
    binding.host_hwnd = 101
    binding.host_record = host_record(binding.host_candidate)
    binding._enumerator = lambda: [binding.host_candidate]
    binding._environment_builder = lambda selected: {
        "codex": {
            "hwnd": selected.hwnd,
            "dpi": 144,
            "client_rectangle": {
                "left": 100,
                "top": 50,
                "right": 1300,
                "bottom": 850,
                "width": 1200,
                "height": 800,
            },
            "monitor": {
                "work_area": {
                    "left": 0,
                    "top": 0,
                    "right": 1600,
                    "bottom": 860,
                    "width": 1600,
                    "height": 860,
                }
            },
        }
    }
    binding.refresh_host_geometry()
    assert binding.dpi == 144
    assert binding.host_client_rectangle == Rect(100, 50, 1300, 850)
    assert binding.work_area_rectangle == Rect(0, 0, 1600, 860)


def test_uia_refresh_revalidates_full_frozen_identity_before_reconnect() -> None:
    binding = bare_binding(FakeNative(Rect(377, 491, 1052, 791)))
    frozen = candidate()
    binding.host_record = host_record(frozen)
    binding._enumerator = lambda: [candidate(pid=999)]
    with pytest.raises(CodexBindingError, match="FROZEN_HOST_IDENTITY_MISMATCH"):
        binding.refresh_controls()


def test_partial_sidecar_initialization_closes_created_window() -> None:
    closed: list[bool] = []
    sidecar = SimpleNamespace(
        window=SimpleNamespace(winId=lambda: 303),
        close=lambda: closed.append(True),
    )
    binding = CodexSidecarBinding.__new__(CodexSidecarBinding)
    binding.host_hwnd = 101
    binding.sidecar = None
    binding.sidecar_hwnd = 0
    binding.focus_router = None
    binding.native = SimpleNamespace(is_window=lambda hwnd: False)
    with pytest.raises(CodexBindingError, match="SIDECAR_NATIVE_WINDOW_UNAVAILABLE"):
        binding._initialize_native_sidecar(lambda **kwargs: sidecar)
    assert closed == [True]
    assert binding.sidecar is None


def test_failure_cleanup_clears_partial_marker_without_requiring_full_marker_match() -> None:
    value = SimpleNamespace(CurrentValue="H2D2PARTIAL")
    composer = SimpleNamespace(
        iface_value=value,
        element_info=SimpleNamespace(name="Ask for follow-up changes"),
        descendants=lambda: [],
        set_focus=lambda: None,
        has_keyboard_focus=lambda: True,
    )
    binding = SimpleNamespace(
        refresh_controls=lambda: SimpleNamespace(composer=composer),
        native=SimpleNamespace(foreground=lambda: 101),
        host_hwnd=101,
    )

    def fake_send_keys(keys: str, *, pause: float) -> None:
        assert keys == "^a{BACKSPACE}"
        assert pause == 0.025
        value.CurrentValue = ""

    clear_injected_composer_text(
        binding,
        {
            "accessibility_name": "Ask for follow-up changes",
            "uia_values": [""],
        },
        fake_send_keys,
    )
    assert value.CurrentValue == ""


def test_marker_cleanup_is_armed_before_real_composer_injection() -> None:
    source = (ROOT / "scripts" / "h2" / "verify_codex_attachment.py").read_text(
        encoding="utf-8"
    )
    armed = source.index("marker_may_be_present = True")
    injection = source.index("send_keys(MARKER")
    assert armed < injection


def test_steady_state_observation_is_read_only_and_proves_owner_z_order_and_placement() -> None:
    expected = Rect(377, 491, 1052, 791)
    native = FakeNative(expected)
    record = bare_binding(native).observe(expected=expected)
    assert record["owner_hwnd"] == 101
    assert record["sidecar_above_host"] is True
    assert record["global_topmost"] is False
    assert record["placement_matches"] is True
    assert record["composer_selector_match_count"] == 2
    assert record["host_geometry_source"] == "LIVE_REMEASURED_EXACT_D1_HWND"
    assert record["host_client_rectangle"] == Rect(-1, -1, 1601, 899).as_record()
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
    assert "$env:QT_QUICK_BACKEND = 'software'" in readme
    assert "remeasures that exact" in normalized
    assert "remains hidden while a projection is validated" in normalized
    assert "Do not press Enter or click Codex Send" in normalized


def test_d2_qualification_dependencies_are_exactly_pinned() -> None:
    assert (ROOT / "requirements-h2-d2.txt").read_text(encoding="utf-8").splitlines() == [
        "-r requirements-r6o2-host.txt",
        "-r requirements-h2-sidecar.txt",
        "Pillow==12.3.0",
        "imageio-ffmpeg==0.6.0",
    ]


def _assert_d2_evidence(
    document: dict[str, object],
    *,
    evidence_dir: Path,
    expected_host_record_sha256: str,
    expected_selectors_sha256: str,
) -> None:
    assert document["schema_version"] == "r6o-h2-d2-attachment-result-1"
    assert document["status"] == "H2_D2_ATTACHMENT_PASS"
    assert document["real_codex_host_tested"] is True
    assert document["synthetic_owner_used"] is False
    host = document["host"]
    for mode in ("standard", "expanded"):
        observation = document[mode]
        assert observation["owner_hwnd"] == host["hwnd"]
        assert observation["expected_owner_hwnd"] == host["hwnd"]
        assert observation["actual_rectangle"] == observation["expected_rectangle"]
        assert observation["placement_matches"] is True
        assert observation["sidecar_above_host"] is True
        assert observation["global_topmost"] is False
        assert observation["visible"] is True
        assert observation["host_geometry_source"] == "LIVE_REMEASURED_EXACT_D1_HWND"

    non_interference = document["non_interference"]
    assert non_interference["composer_clicked_outside_sidecar"] is True
    assert non_interference["composer_empty_before"] is True
    assert non_interference["composer_received_keyboard_focus"] is True
    assert non_interference["marker_visible"] is True
    assert non_interference["marker_removed"] is True
    assert non_interference["marker_submitted"] is False
    assert non_interference["normal_codex_dispatch_observed"] is False
    assert non_interference["placement_unchanged"] is True
    assert non_interference["sidecar_above_host_after"] is True
    assert non_interference["sidecar_visible_after"] is True
    assert non_interference["visible_turn_count_after"] == non_interference["visible_turn_count_before"]

    unrelated = document["unrelated_window"]
    assert unrelated["host_focus_router_ignored_probe_click"] is True
    assert unrelated["probe_above_sidecar"] is True
    assert unrelated["probe_foreground"] is True
    assert unrelated["probe_global_topmost"] is False
    assert unrelated["probe_owner_hwnd"] == 0

    close_focus = document["close_focus_return"]
    assert close_focus["composer_keyboard_focus"] is True
    assert close_focus["sidecar_visible"] is False
    assert close_focus["foreground_hwnd"] == close_focus["expected_foreground_hwnd"] == host["hwnd"]
    assert document["recording"]["frame_count"] > 0
    assert document["recording"]["mandatory"] is True
    assert len(document["recording"]["sha256"]) == 64
    assert document["observer_ordering_mutation"] is False
    assert host["geometry_source"] == "LIVE_REMEASURED_EXACT_D1_HWND"
    assert host["client_rectangle"]["width"] > 0
    assert host["work_area"]["height"] > 0
    assert document["host_record_sha256"] == expected_host_record_sha256
    assert document["selectors_sha256"] == expected_selectors_sha256
    assert document["scope"] == {
        "normal_codex_submit_gesture_used": False,
        "r6o3_lease_implemented": False,
        "semantic_workflow_exercised": False,
    }
    expected_implementation = {
        source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
        for source in (
            "r6o/host/codex/windows/binding.py",
            "r6o/host/codex/windows/placement.py",
            "scripts/h2/verify_codex_attachment.py",
        )
    }
    assert document["implementation_sha256"] == expected_implementation
    assert document["runtime"]["qt_platform"] == "windows"
    assert document["runtime"]["qt_quick_backend"] == "software"
    assert document["runtime"]["dependencies"] == {
        "Pillow": "12.3.0",
        "PySide6": "6.11.2",
        "imageio-ffmpeg": "0.6.0",
        "pywin32": "312",
        "pywinauto": "0.6.9",
    }

    recording_hashes: list[str] = []
    for mode in ("standard", "expanded"):
        recording = document["recording"][mode]
        recording_path = ROOT / recording["path"]
        assert recording_path.resolve().parent == evidence_dir.resolve()
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

    event_path = evidence_dir / "win32-uia-events.jsonl"
    canonical_event_bytes = event_path.read_bytes().replace(b"\r\n", b"\n")
    assert document["event_log"]["sha256"] == hashlib.sha256(canonical_event_bytes).hexdigest()
    events = [json.loads(line) for line in canonical_event_bytes.decode("utf-8").splitlines()]
    assert document["event_log"]["event_count"] == len(events)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    clicked = next(event for event in events if event["event"] == "actual_codex_composer_clicked")
    assert clicked["focus_router_transfer_count"] >= 1
    assert clicked["exact_owner_preserved"] is True
    assert clicked["thread_input_attached"] is True
    assert clicked["thread_input_detached"] is True
    assert clicked["thread_input_attached_only_for_focus_transaction"] is True


def test_historical_d2_evidence_remains_bound_to_historical_d1_inputs() -> None:
    path = HISTORICAL_D2_EVIDENCE_DIR / "attachment-result.json"
    if not path.exists():
        pytest.skip("accepted historical D2 evidence is not present")
    document = json.loads(path.read_text(encoding="utf-8"))
    assert ROOT / document["event_log"]["path"] == HISTORICAL_D2_EVIDENCE_DIR / "win32-uia-events.jsonl"
    _assert_d2_evidence(
        document,
        evidence_dir=HISTORICAL_D2_EVIDENCE_DIR,
        expected_host_record_sha256=HISTORICAL_D1_HOST_RECORD_SHA256,
        expected_selectors_sha256=HISTORICAL_D2_SELECTORS_SHA256,
    )


def test_current_d1r_d2_evidence_is_bound_to_current_refreeze_inputs() -> None:
    path = CURRENT_D1R_D2_EVIDENCE_DIR / "attachment-result.json"
    if not path.exists():
        pytest.skip("current-host D1R D2 evidence is not present")
    document = json.loads(path.read_text(encoding="utf-8"))
    current_host_record = json.loads(
        (ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json").read_text(encoding="utf-8")
    )["codex"]
    current_selector_path = ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json"
    for key in ("hwnd", "pid", "product_name", "product_version", "file_version", "package_version"):
        assert document["host"][key] == current_host_record[key]
    _assert_d2_evidence(
        document,
        evidence_dir=CURRENT_D1R_D2_EVIDENCE_DIR,
        expected_host_record_sha256=hashlib.sha256(
            (ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json").read_bytes()
        ).hexdigest(),
        expected_selectors_sha256=hashlib.sha256(current_selector_path.read_bytes()).hexdigest(),
    )
