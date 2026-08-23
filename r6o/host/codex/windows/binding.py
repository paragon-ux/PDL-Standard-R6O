from __future__ import annotations

"""Windows-only attachment of the locked Qt Sidecar to the frozen Codex host."""

import ctypes
from ctypes import wintypes
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from r6o.host.codex.windows.discovery import (
    HostCandidate,
    HostDiscoveryError,
    build_environment_record,
    enumerate_visible_top_level_windows,
    validate_environment_record,
)
from r6o.host.codex.windows.placement import (
    PLACEMENT_TOLERANCE_PX,
    Rect,
    canonical_physical_size,
    placement_for_mode,
    rect_from_record,
    rectangles_match,
    scale_logical,
)
from r6o.host.codex.windows.uia import (
    UiaContractError,
    connect_to_host,
    load_selectors,
    matches_ancestor_chain,
    matches_record,
    resolve_control,
    wrapper_record,
)
from r6o.views.sidecar.model import SidecarMode


COMPOSER_BOTTOM_ANCHOR_MAX_LOGICAL_PX = 180
COMPOSER_MIN_PRIMARY_WIDTH_RATIO = 0.35
GWLP_HWNDPARENT = -8
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_QUIT = 0x0012


class _MouseHookStruct(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class CodexBindingError(RuntimeError):
    """A stable, machine-readable D2 binding failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResolvedHostControls:
    root: Any
    composer: Any
    primary_content_region: Any
    composer_rectangle: Rect
    primary_content_rectangle: Rect
    composer_selector_match_count: int


def load_host_record(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexBindingError("HOST_RECORD_UNREADABLE") from exc
    if not isinstance(document, dict):
        raise CodexBindingError("HOST_RECORD_INVALID")
    try:
        validate_environment_record(document)
    except HostDiscoveryError as exc:
        raise CodexBindingError("HOST_RECORD_INVALID") from exc
    return document


def _normalized_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def verify_frozen_host_identity(
    record: dict[str, Any],
    *,
    enumerator: Callable[[], list[HostCandidate]] = enumerate_visible_top_level_windows,
) -> HostCandidate:
    """Resolve only the recorded HWND and reject stale or identity-shifted hosts."""

    expected = record["codex"]
    matches = [candidate for candidate in enumerator() if candidate.hwnd == expected["hwnd"]]
    if len(matches) != 1:
        raise CodexBindingError("FROZEN_HOST_HWND_STALE")
    candidate = matches[0]
    exact_fields = {
        "pid": candidate.pid,
        "product_name": candidate.product_name,
        "product_version": candidate.product_version,
        "file_version": candidate.file_version,
        "package_version": candidate.package_version,
        "window_class": candidate.class_name,
    }
    if any(exact_fields[key] != expected[key] for key in exact_fields):
        raise CodexBindingError("FROZEN_HOST_IDENTITY_MISMATCH")
    if _normalized_path(candidate.executable) != _normalized_path(expected["executable"]):
        raise CodexBindingError("FROZEN_HOST_IDENTITY_MISMATCH")
    if not candidate.visible:
        raise CodexBindingError("FROZEN_HOST_NOT_VISIBLE")
    return candidate


def verify_selector_host_compatibility(selectors: dict[str, Any], host_record: dict[str, Any]) -> None:
    expected = host_record["codex"]
    compatibility = selectors["host_compatibility"]
    for key in ("product_name", "product_version", "file_version", "package_version"):
        if compatibility[key] != expected[key]:
            raise CodexBindingError(f"SELECTOR_HOST_MISMATCH:{key}")


def _ancestor_records(wrapper: Any) -> list[dict[str, Any]]:
    ancestors: list[dict[str, Any]] = []
    seen: set[int] = set()
    current = wrapper
    while True:
        try:
            parent = current.parent()
        except Exception:
            return ancestors
        if parent is None:
            return ancestors
        marker = id(parent.element_info)
        if marker in seen:
            return ancestors
        seen.add(marker)
        ancestors.append(wrapper_record(parent))
        current = parent


def _wrapper_rectangle(wrapper: Any, *, label: str) -> Rect:
    try:
        rectangle = wrapper.rectangle()
        return Rect(
            left=int(rectangle.left),
            top=int(rectangle.top),
            right=int(rectangle.right),
            bottom=int(rectangle.bottom),
        )
    except Exception as exc:
        raise CodexBindingError(f"UIA_RECTANGLE_UNAVAILABLE:{label}") from exc


def _matching_wrappers(root: Any, selector: dict[str, Any]) -> list[Any]:
    matches: list[Any] = []
    try:
        descendants = root.descendants()
    except Exception as exc:
        raise CodexBindingError("HOST_UIA_UNAVAILABLE") from exc
    for wrapper in descendants:
        if matches_record(wrapper_record(wrapper), selector) and matches_ancestor_chain(
            _ancestor_records(wrapper), selector.get("ancestor_chain", [])
        ):
            matches.append(wrapper)
    return matches


def resolve_actual_composer(
    root: Any,
    selector: dict[str, Any],
    *,
    primary_content_region: Any,
    dpi: int,
) -> tuple[Any, Rect, int]:
    """Apply the D1 selector, then the D2 bottom-anchored geometry tie-breaker.

    Codex may expose other ProseMirror editors (for example a Goal editor).
    Those are selector matches but are not the host composer. The actual
    composer is the sole qualifying match in the lower half of the frozen
    primary content region, near its bottom edge, and at least 35% as wide.
    """

    if selector.get("fallback") != "PROHIBITED":
        raise CodexBindingError("COMPOSER_SELECTOR_FALLBACK_PROHIBITED")
    primary = _wrapper_rectangle(primary_content_region, label="primary_content_region")
    all_matches = _matching_wrappers(root, selector)
    max_bottom_distance = scale_logical(COMPOSER_BOTTOM_ANCHOR_MAX_LOGICAL_PX, dpi)
    qualifying: list[tuple[Any, Rect]] = []
    for wrapper in all_matches:
        rectangle = _wrapper_rectangle(wrapper, label="composer_candidate")
        if not primary.contains(rectangle, tolerance=PLACEMENT_TOLERANCE_PX):
            continue
        if rectangle.top < primary.top + primary.height // 2:
            continue
        if primary.bottom - rectangle.bottom > max_bottom_distance:
            continue
        if rectangle.width < primary.width * COMPOSER_MIN_PRIMARY_WIDTH_RATIO:
            continue
        qualifying.append((wrapper, rectangle))
    if len(qualifying) != 1:
        raise CodexBindingError(
            f"COMPOSER_GEOMETRY_CARDINALITY:{len(qualifying)}:SELECTOR_MATCHES:{len(all_matches)}"
        )
    wrapper, rectangle = qualifying[0]
    return wrapper, rectangle, len(all_matches)


def resolve_host_controls(root: Any, selectors: dict[str, Any], *, dpi: int) -> ResolvedHostControls:
    controls = selectors["controls"]
    try:
        primary = resolve_control(root, controls["primary_content_region"], label="primary_content_region")
    except UiaContractError as exc:
        raise CodexBindingError(str(exc)) from exc
    composer, composer_rectangle, selector_count = resolve_actual_composer(
        root,
        controls["composer"],
        primary_content_region=primary,
        dpi=dpi,
    )
    return ResolvedHostControls(
        root=root,
        composer=composer,
        primary_content_region=primary,
        composer_rectangle=composer_rectangle,
        primary_content_rectangle=_wrapper_rectangle(primary, label="primary_content_region"),
        composer_selector_match_count=selector_count,
    )


class NativeWindowApi:
    """Small Win32 adapter so ownership and observation remain testable."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise CodexBindingError("HOST_PLATFORM_UNSUPPORTED")
        try:
            import win32con
            import win32gui
        except ImportError as exc:
            raise CodexBindingError("HOST_DEPENDENCY_MISSING") from exc
        self.win32con = win32con
        self.win32gui = win32gui

    def set_owner(self, child_hwnd: int, owner_hwnd: int) -> None:
        user32 = ctypes.windll.user32
        function = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        function.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        function.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        previous = function(child_hwnd, GWLP_HWNDPARENT, owner_hwnd)
        error = ctypes.get_last_error()
        if previous is None and error:
            raise CodexBindingError(f"SIDECAR_OWNER_ASSIGNMENT_FAILED:{error}")
        if self.owner(child_hwnd) != owner_hwnd:
            raise CodexBindingError("SIDECAR_OWNER_UNVERIFIED")

    def owner(self, hwnd: int) -> int:
        return int(self.win32gui.GetWindow(hwnd, GW_OWNER) or 0)

    def move_resize(self, hwnd: int, rectangle: Rect) -> None:
        flags = (
            self.win32con.SWP_NOACTIVATE
            | self.win32con.SWP_NOZORDER
        )
        try:
            # Ownership keeps the Sidecar above Codex. Placement must not use
            # HWND_TOP or otherwise repair z-order immediately before evidence
            # observation; SWP_NOZORDER makes hWndInsertAfter intentionally inert.
            self.win32gui.SetWindowPos(
                hwnd,
                0,
                rectangle.left,
                rectangle.top,
                rectangle.width,
                rectangle.height,
                flags,
            )
        except Exception as exc:
            raise CodexBindingError("SIDECAR_PLACEMENT_FAILED") from exc

    def rectangle(self, hwnd: int) -> Rect:
        try:
            left, top, right, bottom = self.win32gui.GetWindowRect(hwnd)
            return Rect(int(left), int(top), int(right), int(bottom))
        except Exception as exc:
            raise CodexBindingError("SIDECAR_RECTANGLE_UNAVAILABLE") from exc

    def is_window(self, hwnd: int) -> bool:
        return bool(self.win32gui.IsWindow(hwnd))

    def is_visible(self, hwnd: int) -> bool:
        return bool(self.win32gui.IsWindowVisible(hwnd))

    def is_topmost(self, hwnd: int) -> bool:
        return bool(self.win32gui.GetWindowLong(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)

    def foreground(self) -> int:
        return int(self.win32gui.GetForegroundWindow() or 0)

    def z_order(self) -> list[int]:
        handles: list[int] = []
        self.win32gui.EnumWindows(lambda hwnd, _context: handles.append(int(hwnd)) or True, None)
        return handles


class HostClickFocusRouter:
    """Route an actual owner-surface click out of the active owned Sidecar.

    Windows redirects activation of an owner to its last active owned popup.
    The low-level mouse boundary lets the bounded D2 binding transfer
    foreground ownership to the exact recorded Codex HWND before the same
    physical click is delivered. It observes only left-button-down coordinates
    and never captures text or keyboard input.
    """

    def __init__(self, *, host_hwnd: int, sidecar_hwnd: int) -> None:
        if os.name != "nt":
            raise CodexBindingError("HOST_PLATFORM_UNSUPPORTED")
        self.host_hwnd = host_hwnd
        self.sidecar_hwnd = sidecar_hwnd
        self.transfer_count = 0
        self.sidecar_activation_count = 0
        self.last_point: tuple[int, int] | None = None
        self.last_transfer_succeeded = False
        self.last_thread_input_attached = False
        self.last_thread_input_detached = False
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error: str | None = None
        self._thread_id = 0
        self._hook = 0
        self._callback: Any | None = None
        self._thread: threading.Thread | None = None
        try:
            from PySide6.QtCore import QObject, Qt, Signal, Slot
        except ImportError as exc:
            raise CodexBindingError("SIDECAR_DEPENDENCY_MISSING") from exc

        host_callback = self._complete_host_transfer
        sidecar_callback = self._complete_sidecar_activation

        class _FocusDispatcher(QObject):
            hostRequested = Signal()
            sidecarRequested = Signal()

            def __init__(self) -> None:
                super().__init__()
                self.hostRequested.connect(self.run_host, Qt.QueuedConnection)
                self.sidecarRequested.connect(self.run_sidecar, Qt.QueuedConnection)

            @Slot()
            def run_host(self) -> None:
                host_callback()

            @Slot()
            def run_sidecar(self) -> None:
                sidecar_callback()

        self._dispatcher = _FocusDispatcher()

    @staticmethod
    def _contains(rectangle: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
        left, top, right, bottom = rectangle
        return left <= point[0] < right and top <= point[1] < bottom

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="h2-d2-host-click-focus", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise CodexBindingError("HOST_CLICK_FOCUS_ROUTER_START_TIMEOUT")
        if self._error:
            raise CodexBindingError(self._error)

    def _complete_host_transfer(self, user32: Any | None = None) -> None:
        user32 = user32 or ctypes.windll.user32
        self.last_transfer_succeeded = False
        self.last_thread_input_attached = False
        self.last_thread_input_detached = False
        style = int(user32.GetWindowLongW(self.sidecar_hwnd, GWL_EXSTYLE))
        user32.SetWindowLongW(self.sidecar_hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        sidecar_thread = int(user32.GetWindowThreadProcessId(self.sidecar_hwnd, None))
        host_thread = int(user32.GetWindowThreadProcessId(self.host_hwnd, None))
        attached = bool(user32.AttachThreadInput(sidecar_thread, host_thread, True))
        self.last_thread_input_attached = attached
        if not attached:
            self._error = "HOST_THREAD_INPUT_ATTACH_FAILED"
            return
        focus_calls_succeeded = False
        try:
            user32.SetForegroundWindow(self.host_hwnd)
            user32.SetActiveWindow(self.host_hwnd)
            focus_calls_succeeded = True
        except Exception:
            self._error = "HOST_FOCUS_TRANSFER_FAILED"
        finally:
            self.last_thread_input_detached = bool(
                user32.AttachThreadInput(sidecar_thread, host_thread, False)
            )
        if not self.last_thread_input_detached:
            self._error = "HOST_THREAD_INPUT_DETACH_FAILED"
            return
        self.last_transfer_succeeded = (
            focus_calls_succeeded
            and int(user32.GetForegroundWindow() or 0) == self.host_hwnd
        )

    def _complete_sidecar_activation(self) -> None:
        user32 = ctypes.windll.user32
        style = int(user32.GetWindowLongW(self.sidecar_hwnd, GWL_EXSTYLE))
        user32.SetWindowLongW(self.sidecar_hwnd, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE)
        user32.SetForegroundWindow(self.sidecar_hwnd)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hook_proc = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, hook_proc, ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        def callback(code: int, message: int, data_address: int) -> int:
            if code >= 0 and message == WM_LBUTTONDOWN:
                try:
                    data = ctypes.cast(
                        data_address, ctypes.POINTER(_MouseHookStruct)
                    ).contents
                    point = (int(data.pt.x), int(data.pt.y))
                    target = int(user32.WindowFromPoint(data.pt) or 0)
                    target_root = int(user32.GetAncestor(target, 2) or 0)
                except Exception:
                    point = (-1, -1)
                    target_root = 0
                try:
                    host_rect = wintypes.RECT()
                    sidecar_rect = wintypes.RECT()
                    host_ok = bool(user32.GetWindowRect(self.host_hwnd, ctypes.byref(host_rect)))
                    sidecar_ok = bool(user32.GetWindowRect(self.sidecar_hwnd, ctypes.byref(sidecar_rect)))
                    if host_ok and sidecar_ok:
                        host_tuple = (host_rect.left, host_rect.top, host_rect.right, host_rect.bottom)
                        sidecar_tuple = (
                            sidecar_rect.left,
                            sidecar_rect.top,
                            sidecar_rect.right,
                            sidecar_rect.bottom,
                        )
                        if (
                            target_root == self.host_hwnd
                            and self._contains(host_tuple, point)
                            and not self._contains(sidecar_tuple, point)
                        ):
                            self.last_point = point
                            # Execute focus mechanics on the Qt GUI thread that
                            # owns the current foreground Sidecar; Windows denies
                            # equivalent foreground calls from this hook thread.
                            self._dispatcher.hostRequested.emit()
                            self.transfer_count += 1
                        elif target_root == self.sidecar_hwnd and self._contains(sidecar_tuple, point):
                            self._dispatcher.sidecarRequested.emit()
                            self.sidecar_activation_count += 1
                except Exception:
                    self.last_transfer_succeeded = False
            return int(
                user32.CallNextHookEx(ctypes.c_void_p(self._hook), code, message, data_address)
            )

        try:
            self._callback = hook_proc(callback)
            self._thread_id = int(kernel32.GetCurrentThreadId())
            module = kernel32.GetModuleHandleW(None)
            self._hook = int(user32.SetWindowsHookExW(WH_MOUSE_LL, self._callback, module, 0) or 0)
            if not self._hook:
                self._error = "HOST_CLICK_FOCUS_ROUTER_INSTALL_FAILED"
                self._ready.set()
                return
            self._ready.set()
            message = wintypes.MSG()
            while not self._stop.is_set() and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception:
            self._error = "HOST_CLICK_FOCUS_ROUTER_RUNTIME_FAILED"
            self._ready.set()
        finally:
            if self._hook:
                user32.UnhookWindowsHookEx(ctypes.c_void_p(self._hook))
                self._hook = 0

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            raise CodexBindingError("HOST_CLICK_FOCUS_ROUTER_STOP_TIMEOUT")
        self._thread = None


class CodexSidecarBinding:
    """Bind one Sidecar instance to the exact H2-D1 Codex HWND."""

    def __init__(
        self,
        host_record_path: Path,
        selectors_path: Path,
        *,
        native: NativeWindowApi | Any | None = None,
        sidecar_factory: Callable[..., Any] | None = None,
        enumerator: Callable[[], list[HostCandidate]] = enumerate_visible_top_level_windows,
        environment_builder: Callable[[HostCandidate], dict[str, Any]] = build_environment_record,
    ) -> None:
        self.host_record_path = host_record_path.resolve()
        self.selectors_path = selectors_path.resolve()
        self.host_record = load_host_record(self.host_record_path)
        self.selectors = load_selectors(self.selectors_path)
        verify_selector_host_compatibility(self.selectors, self.host_record)
        self._enumerator = enumerator
        self.host_candidate = verify_frozen_host_identity(self.host_record, enumerator=enumerator)
        self.host_hwnd = int(self.host_record["codex"]["hwnd"])
        self._environment_builder = environment_builder
        self.refresh_host_geometry()
        try:
            self._app, root = connect_to_host(self.host_hwnd)
        except Exception as exc:
            raise CodexBindingError("FROZEN_HOST_UIA_CONNECTION_FAILED") from exc
        self.controls = resolve_host_controls(root, self.selectors, dpi=self.dpi)
        self.native = native or NativeWindowApi()
        if sidecar_factory is None:
            from r6o.views.sidecar.qt_app import QtSidecarWindow

            sidecar_factory = QtSidecarWindow
        self._close_focus_error: str | None = None
        self.sidecar: Any | None = None
        self.sidecar_hwnd = 0
        self.focus_router: HostClickFocusRouter | None = None
        self._initialize_native_sidecar(sidecar_factory)

    def _initialize_native_sidecar(self, sidecar_factory: Callable[..., Any]) -> None:
        sidecar = sidecar_factory(on_close_view=self._return_focus_to_composer)
        self.sidecar = sidecar
        try:
            self.sidecar_hwnd = int(sidecar.window.winId())
            if self.sidecar_hwnd <= 0 or not self.native.is_window(self.sidecar_hwnd):
                raise CodexBindingError("SIDECAR_NATIVE_WINDOW_UNAVAILABLE")
            self.native.set_owner(self.sidecar_hwnd, self.host_hwnd)
            if self.native.is_topmost(self.sidecar_hwnd):
                raise CodexBindingError("SIDECAR_GLOBAL_TOPMOST_PROHIBITED")
            self.focus_router = HostClickFocusRouter(
                host_hwnd=self.host_hwnd,
                sidecar_hwnd=self.sidecar_hwnd,
            )
        except Exception:
            try:
                if self.focus_router is not None:
                    self.focus_router.stop()
            except Exception:
                pass
            try:
                sidecar.close()
            except Exception:
                pass
            self.sidecar = None
            self.focus_router = None
            raise

    def refresh_host_geometry(self) -> dict[str, Any]:
        """Remeasure the verified D1 HWND without weakening its frozen identity."""

        try:
            self.host_candidate = verify_frozen_host_identity(
                self.host_record, enumerator=self._enumerator
            )
            live_record = self._environment_builder(self.host_candidate)
        except HostDiscoveryError as exc:
            raise CodexBindingError(f"LIVE_HOST_GEOMETRY_UNAVAILABLE:{exc.code}") from exc
        try:
            live = live_record["codex"]
            if int(live["hwnd"]) != self.host_hwnd:
                raise ValueError
            self.dpi = int(live["dpi"])
            self.host_client_rectangle = rect_from_record(
                live["client_rectangle"], label="live_host_client"
            )
            self.work_area_rectangle = rect_from_record(
                live["monitor"]["work_area"], label="live_work_area"
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CodexBindingError("LIVE_HOST_GEOMETRY_INVALID") from exc
        self.live_host_record = live_record
        return live_record

    def refresh_controls(self) -> ResolvedHostControls:
        """Reconnect after a Chromium focus/render boundary invalidates UIA wrappers."""

        self.host_candidate = verify_frozen_host_identity(
            self.host_record, enumerator=self._enumerator
        )
        try:
            self._app, root = connect_to_host(self.host_hwnd)
        except Exception as exc:
            raise CodexBindingError("FROZEN_HOST_UIA_CONNECTION_FAILED") from exc
        self.controls = resolve_host_controls(root, self.selectors, dpi=self.dpi)
        return self.controls

    @property
    def mode(self) -> SidecarMode:
        return SidecarMode.parse(self.sidecar.mode)

    def expected_rectangle(self, mode: SidecarMode | None = None) -> Rect:
        return placement_for_mode(
            mode or self.mode,
            composer=self.controls.composer_rectangle,
            host_client=self.host_client_rectangle,
            work_area=self.work_area_rectangle,
            dpi=self.dpi,
        )

    def attach(self, projection: dict[str, object], *, settle_seconds: float = 0.75) -> dict[str, Any]:
        self.refresh_host_geometry()
        self.refresh_controls()
        expected = self.expected_rectangle(SidecarMode.STANDARD)
        self.native.move_resize(self.sidecar_hwnd, expected)
        if not self.sidecar.render(projection):
            raise CodexBindingError("ACTIVE_PROJECTION_REJECTED")
        # Qt may recreate native style state during the first show. Reassert the
        # already-frozen owner once as attachment setup, before the steady-state
        # settling interval and any evidence observation.
        self.native.set_owner(self.sidecar_hwnd, self.host_hwnd)
        self.native.move_resize(self.sidecar_hwnd, expected)
        self.focus_router.start()
        self._settle(settle_seconds)
        return self.observe(expected=expected)

    def set_mode(self, mode: SidecarMode, *, settle_seconds: float = 0.75) -> dict[str, Any]:
        parsed = SidecarMode.parse(mode)
        self.refresh_host_geometry()
        self.refresh_controls()
        self.sidecar.set_mode(parsed)
        expected = self.expected_rectangle(parsed)
        self.native.move_resize(self.sidecar_hwnd, expected)
        self._settle(settle_seconds)
        return self.observe(expected=expected)

    def _settle(self, seconds: float) -> None:
        if seconds < 0:
            raise CodexBindingError("SETTLE_DURATION_INVALID")
        deadline = time.monotonic() + seconds
        try:
            from PySide6.QtCore import QCoreApplication, QEventLoop

            app = QCoreApplication.instance()
        except ImportError:
            app = None
        while time.monotonic() < deadline:
            if app is not None:
                app.processEvents(QEventLoop.AllEvents, 25)
            time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))

    def observe(self, *, expected: Rect | None = None) -> dict[str, Any]:
        """Observe steady state without changing focus, activation, or z-order."""

        if not self.native.is_window(self.sidecar_hwnd):
            raise CodexBindingError("SIDECAR_WINDOW_STALE")
        actual = self.native.rectangle(self.sidecar_hwnd)
        expected_rectangle = expected or self.expected_rectangle()
        owner = self.native.owner(self.sidecar_hwnd)
        topmost = self.native.is_topmost(self.sidecar_hwnd)
        z_order = self.native.z_order()
        try:
            sidecar_index = z_order.index(self.sidecar_hwnd)
            host_index = z_order.index(self.host_hwnd)
        except ValueError as exc:
            raise CodexBindingError("ATTACHMENT_Z_ORDER_UNOBSERVABLE") from exc
        record = {
            "owner_hwnd": owner,
            "expected_owner_hwnd": self.host_hwnd,
            "sidecar_hwnd": self.sidecar_hwnd,
            "mode": self.mode.value,
            "visible": self.native.is_visible(self.sidecar_hwnd),
            "global_topmost": topmost,
            "sidecar_above_host": sidecar_index < host_index,
            "z_order_indices": {"sidecar": sidecar_index, "host": host_index},
            "actual_rectangle": actual.as_record(),
            "expected_rectangle": expected_rectangle.as_record(),
            "placement_matches": rectangles_match(actual, expected_rectangle),
            "foreground_hwnd": self.native.foreground(),
            "composer_selector_match_count": self.controls.composer_selector_match_count,
            "host_geometry_source": "LIVE_REMEASURED_EXACT_D1_HWND",
            "host_client_rectangle": self.host_client_rectangle.as_record(),
            "work_area_rectangle": self.work_area_rectangle.as_record(),
            "dpi": self.dpi,
        }
        if owner != self.host_hwnd:
            raise CodexBindingError("SIDECAR_OWNER_CHANGED")
        if topmost:
            raise CodexBindingError("SIDECAR_GLOBAL_TOPMOST_PROHIBITED")
        if not record["visible"]:
            raise CodexBindingError("SIDECAR_NOT_VISIBLE")
        if not record["sidecar_above_host"]:
            raise CodexBindingError("SIDECAR_NOT_ABOVE_HOST")
        if not record["placement_matches"]:
            raise CodexBindingError("SIDECAR_PLACEMENT_MISMATCH")
        return record

    def _return_focus_to_composer(self) -> None:
        self._close_focus_error = None
        try:
            composer = self.refresh_controls().composer
            composer.set_focus()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    composer = self.refresh_controls().composer
                    focused = bool(composer.has_keyboard_focus())
                except Exception:
                    focused = False
                if focused and self.native.foreground() == self.host_hwnd:
                    return
                time.sleep(0.05)
            raise CodexBindingError("COMPOSER_FOCUS_RETURN_UNVERIFIED")
        except Exception as exc:
            self._close_focus_error = exc.code if isinstance(exc, CodexBindingError) else "COMPOSER_FOCUS_RETURN_FAILED"

    def close_view_and_verify_focus(self) -> dict[str, Any]:
        self.sidecar.close_view()
        self._settle(0.25)
        if self._close_focus_error:
            raise CodexBindingError(self._close_focus_error)
        focused = bool(self.refresh_controls().composer.has_keyboard_focus())
        foreground = self.native.foreground()
        if not focused or foreground != self.host_hwnd:
            raise CodexBindingError("COMPOSER_FOCUS_RETURN_UNVERIFIED")
        return {
            "sidecar_visible": self.native.is_visible(self.sidecar_hwnd),
            "composer_keyboard_focus": focused,
            "foreground_hwnd": foreground,
            "expected_foreground_hwnd": self.host_hwnd,
        }

    def close(self) -> None:
        try:
            if self.focus_router is not None:
                self.focus_router.stop()
        finally:
            if self.sidecar is not None:
                self.sidecar.close()

    def logical_and_physical_size(self, mode: SidecarMode) -> dict[str, list[int]]:
        return {
            "logical": list(SidecarMode.parse(mode).size),
            "physical": list(canonical_physical_size(SidecarMode.parse(mode), self.dpi)),
        }
