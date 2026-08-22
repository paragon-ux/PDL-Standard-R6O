from __future__ import annotations

"""Fullscreen neutral harness plus a locked, frameless floating Tk Sidecar."""

import os
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from r6o.views.sidecar.model import SidecarModel

STANDARD_HEIGHT = 300
STANDARD_GAP = 8
STANDARD_HEIGHT_TOLERANCE = 2
EXPANDED_WIDTH_RATIO = 0.30
EXPANDED_RIGHT_INSET = 24
EXPANDED_TOP_INSET = 48
EXPANDED_BOTTOM_INSET = 24
EXPANDED_COMPOSER_CLEARANCE = 16
HOST_MARGIN = 24
COMPOSER_HEIGHT = 72

BG = "#080f18"
SURFACE = "#101a26"
CARD = "#142131"
BORDER = "#2a3d52"
TEXT = "#e6edf6"
MUTED = "#92a5ba"
ACCENT = "#4aa3ff"
PRIMARY = "#86d15d"
WARNING = "#ffc857"
DANGER = "#ff6577"


@dataclass(frozen=True)
class WindowRect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class WorkArea(WindowRect):
    monitor_id: str
    dpi: float
    scale: float


def _scaled(value: int, scale: float) -> int:
    return max(1, round(value * scale))


def _geometry(rect: WindowRect) -> str:
    return f"{rect.width}x{rect.height}{rect.x:+d}{rect.y:+d}"


def _windows_toplevel_handle(widget: tk.Misc) -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        get_ancestor = ctypes.windll.user32.GetAncestor
        get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
        get_ancestor.restype = wintypes.HWND
        handle = get_ancestor(wintypes.HWND(widget.winfo_id()), 2)  # GA_ROOT
        return int(handle) if handle else None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _attach_native_owner(owner: tk.Misc, sidecar: tk.Misc) -> bool:
    """Attach the Win32 owner that Tk transient omits for this frameless window."""

    if os.name != "nt":
        return bool(sidecar.transient())
    try:
        import ctypes
        from ctypes import wintypes

        owner_handle = _windows_toplevel_handle(owner)
        sidecar_handle = _windows_toplevel_handle(sidecar)
        if owner_handle is None or sidecar_handle is None:
            return False
        user32 = ctypes.windll.user32
        setter = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        setter.restype = ctypes.c_void_p
        setter(
            wintypes.HWND(sidecar_handle),
            -8,  # GWLP_HWNDPARENT: owner for a top-level window
            ctypes.c_void_p(owner_handle),
        )
        get_window = user32.GetWindow
        get_window.argtypes = [wintypes.HWND, wintypes.UINT]
        get_window.restype = wintypes.HWND
        attached = get_window(wintypes.HWND(sidecar_handle), 4)  # GW_OWNER
        return bool(attached and int(attached) == owner_handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _native_window_above(sidecar: tk.Misc, owner: tk.Misc) -> bool | None:
    """Report whether the Sidecar precedes its owner in the Win32 Z-order."""

    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        owner_handle = _windows_toplevel_handle(owner)
        sidecar_handle = _windows_toplevel_handle(sidecar)
        if owner_handle is None or sidecar_handle is None:
            return False
        user32 = ctypes.windll.user32
        get_top = user32.GetTopWindow
        get_top.argtypes = [wintypes.HWND]
        get_top.restype = wintypes.HWND
        get_window = user32.GetWindow
        get_window.argtypes = [wintypes.HWND, wintypes.UINT]
        get_window.restype = wintypes.HWND
        handle = get_top(wintypes.HWND(0))
        for _ in range(4096):
            if not handle:
                break
            value = int(handle)
            if value == sidecar_handle:
                return True
            if value == owner_handle:
                return False
            handle = get_window(handle, 2)  # GW_HWNDNEXT
        return False
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _activate_windows_toplevel(widget: tk.Misc) -> bool | None:
    """Request foreground activation for deterministic local evidence capture."""

    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        handle = _windows_toplevel_handle(widget)
        if handle is None:
            return False
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        foreground_before = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(
            wintypes.HWND(foreground_before), None
        )
        current_thread = kernel32.GetCurrentThreadId()
        attached = bool(
            foreground_thread
            and foreground_thread != current_thread
            and user32.AttachThreadInput(current_thread, foreground_thread, True)
        )
        user32.ShowWindow(wintypes.HWND(handle), 5)  # SW_SHOW
        user32.BringWindowToTop(wintypes.HWND(handle))
        activated = user32.SetForegroundWindow(wintypes.HWND(handle))
        user32.SetFocus(wintypes.HWND(handle))
        foreground = user32.GetForegroundWindow()
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
        return bool(activated and foreground and int(foreground) == handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def detect_work_area(root: tk.Misc) -> WorkArea:
    """Return the selected monitor usable work area using stdlib/toolkit APIs."""

    root.update_idletasks()
    dpi = float(root.winfo_fpixels("1i"))
    scale = dpi / 96.0
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Rect(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            class MonitorInfo(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", Rect),
                    ("rcWork", Rect),
                    ("dwFlags", wintypes.DWORD),
                ]

            user32 = ctypes.windll.user32
            monitor = user32.MonitorFromWindow(
                wintypes.HWND(root.winfo_id()), 2  # MONITOR_DEFAULTTONEAREST
            )
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                rect = info.rcWork
                return WorkArea(
                    int(rect.left),
                    int(rect.top),
                    int(rect.right - rect.left),
                    int(rect.bottom - rect.top),
                    str(int(monitor)),
                    dpi,
                    scale,
                )
        except (AttributeError, OSError, TypeError, ValueError):
            pass
    return WorkArea(
        0,
        0,
        int(root.winfo_screenwidth()),
        int(root.winfo_screenheight()),
        "tk-primary",
        dpi,
        scale,
    )


class SidecarPlacementController:
    """Own only parent/composer/window geometry; never semantic state."""

    def __init__(self, parent: tk.Misc, composer: tk.Misc, work_area: WorkArea) -> None:
        self.parent = parent
        self.composer = composer
        self.work_area = work_area

    def composer_rect(self) -> WindowRect:
        self.parent.update_idletasks()
        return WindowRect(
            self.composer.winfo_rootx(),
            self.composer.winfo_rooty(),
            self.composer.winfo_width(),
            self.composer.winfo_height(),
        )

    def standard_rect(self) -> WindowRect:
        composer = self.composer_rect()
        height = _scaled(STANDARD_HEIGHT, self.work_area.scale)
        gap = _scaled(STANDARD_GAP, self.work_area.scale)
        return WindowRect(
            composer.x,
            composer.y - gap - height,
            composer.width,
            height,
        )

    def expanded_rect(self) -> WindowRect:
        area = self.work_area
        width = round(area.width * EXPANDED_WIDTH_RATIO)
        right = _scaled(EXPANDED_RIGHT_INSET, area.scale)
        top = _scaled(EXPANDED_TOP_INSET, area.scale)
        bottom = _scaled(EXPANDED_BOTTOM_INSET, area.scale)
        return WindowRect(
            area.x + area.width - right - width,
            area.y + top,
            width,
            area.height - top - bottom,
        )

    def rect_for(self, mode: str) -> WindowRect:
        return self.standard_rect() if mode == "STANDARD" else self.expanded_rect()


class SidecarPanel(tk.Frame):
    """Custom PDLt chrome and projection-driven content inside a Sidecar window."""

    def __init__(
        self,
        master: tk.Misc,
        model: SidecarModel,
        *,
        on_mode_change: Callable[[], None],
        on_close: Callable[[], None],
        on_focus_composer: Callable[[], None],
        on_result: Callable[[dict[str, Any] | None], None],
        debug_ui: bool = False,
    ) -> None:
        super().__init__(
            master,
            background=SURFACE,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.model = model
        self.on_mode_change = on_mode_change
        self.on_close = on_close
        self.on_focus_composer = on_focus_composer
        self.on_result = on_result
        self._action_buttons: dict[str, tk.Button] = {}

        self.header = tk.Frame(self, background=SURFACE, height=46)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.grid_propagate(False)
        self.header.columnconfigure(1, weight=1)
        self.title_label = tk.Label(
            self.header,
            text="PDLt Review",
            background=SURFACE,
            foreground=TEXT,
            font=("Segoe UI", 12, "bold"),
        )
        self.title_label.grid(row=0, column=0, padx=(14, 8), pady=10)
        self.stage_label = tk.Label(
            self.header,
            text="",
            background="#35265b",
            foreground="#d8c8ff",
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=3,
        )
        self.stage_label.grid(row=0, column=1, sticky="w", pady=10)
        self.status_label = tk.Label(
            self.header,
            text="● ACTIVE",
            background=SURFACE,
            foreground=PRIMARY,
            font=("Segoe UI", 9, "bold"),
        )
        self.status_label.grid(row=0, column=2, padx=8)
        self.mode_button = _header_button(self.header, "Expand", ACCENT, self._toggle_mode)
        self.mode_button.grid(row=0, column=3, padx=4, pady=7)
        self.close_button = _header_button(self.header, "Close", DANGER, self._close)
        self.close_button.grid(row=0, column=4, padx=(4, 10), pady=7)

        self.body = tk.Frame(self, background=SURFACE)
        self.body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.artifact_card = tk.Frame(
            self.body,
            background=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.artifact_card.rowconfigure(1, weight=1)
        self.artifact_card.columnconfigure(0, weight=1)
        self.artifact_title = tk.Label(
            self.artifact_card,
            text="Authoritative Artifact",
            background=CARD,
            foreground=TEXT,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        self.artifact_title.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        artifact_frame = tk.Frame(self.artifact_card, background=CARD)
        artifact_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        artifact_frame.rowconfigure(0, weight=1)
        artifact_frame.columnconfigure(0, weight=1)
        self.artifact_text = tk.Text(
            artifact_frame,
            wrap="word",
            background="#09131f",
            foreground=TEXT,
            insertbackground=TEXT,
            relief="flat",
            borderwidth=0,
            font=("Cascadia Mono", 10),
            padx=10,
            pady=8,
            takefocus=True,
        )
        self.artifact_text.grid(row=0, column=0, sticky="nsew")
        artifact_scroll = tk.Scrollbar(
            artifact_frame, orient="vertical", command=self.artifact_text.yview
        )
        artifact_scroll.grid(row=0, column=1, sticky="ns")
        self.artifact_text.configure(yscrollcommand=artifact_scroll.set)
        self.source_label: tk.Label | None = None
        if debug_ui:
            self.source_label = tk.Label(
                self.artifact_card,
                text="",
                background=CARD,
                foreground=MUTED,
                anchor="w",
                font=("Segoe UI", 8),
            )
            self.source_label.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

        self.options_card = tk.Frame(
            self.body,
            background=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.options_card.columnconfigure(0, weight=1)
        self.options_title = tk.Label(
            self.options_card,
            text="Review Options",
            background=CARD,
            foreground=TEXT,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        self.options_title.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 5))
        self.actions_frame = tk.Frame(self.options_card, background=CARD)
        self.actions_frame.grid(row=1, column=0, sticky="ew", padx=8)
        self.actions_frame.columnconfigure(0, weight=1)
        self.notice_label = tk.Label(
            self.options_card,
            text="",
            background=CARD,
            foreground=WARNING,
            justify="left",
            anchor="w",
            wraplength=260,
            font=("Segoe UI", 8),
        )
        self.notice_label.grid(row=2, column=0, sticky="ew", padx=10, pady=(5, 8))
        self.render()

    def render(self) -> None:
        projection = self.model.projection
        stage = str(projection.get("stage") or "UNKNOWN").replace("_", " ")
        self.stage_label.configure(text=stage)
        active = projection.get("interaction_state") == "REVIEW_REQUIRED"
        self.status_label.configure(
            text="● ACTIVE" if active else str(projection.get("interaction_state") or ""),
            foreground=PRIMARY if active else MUTED,
        )
        self.mode_button.configure(
            text="Collapse" if self.model.mode == "EXPANDED" else "Expand"
        )
        artifact = projection.get("artifact") or {}
        self.artifact_title.configure(text=artifact.get("title") or "Authoritative Artifact")
        body = artifact.get("body") if artifact else None
        self.artifact_text.configure(state="normal")
        self.artifact_text.delete("1.0", "end")
        self.artifact_text.insert("1.0", body if body is not None else "(no review artifact)")
        self.artifact_text.configure(state="disabled")
        if self.source_label is not None:
            revision = artifact.get("artifact_revision") or projection.get("model_revision")
            self.source_label.configure(text=f"Projection snapshot · revision {revision}")

        for child in self.actions_frame.winfo_children():
            child.destroy()
        self._action_buttons.clear()
        for row, action in enumerate(self.model.actions):
            emphasis = action.get("emphasis") == "PRIMARY"
            enabled = bool(action.get("enabled", True))
            button = tk.Button(
                self.actions_frame,
                text=f"{action.get('ordinal')}   {action.get('label')}",
                command=lambda action_id=action["action_id"]: self._invoke_action(action_id),
                state="normal" if enabled else "disabled",
                background="#173b26" if emphasis else "#172638",
                foreground=PRIMARY if emphasis else TEXT,
                activebackground="#225337" if emphasis else "#22364d",
                activeforeground=TEXT,
                disabledforeground="#5e7186",
                relief="flat",
                borderwidth=0,
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
                anchor="w",
                padx=10,
                pady=6,
                font=("Segoe UI", 9, "bold" if emphasis else "normal"),
                takefocus=True,
            )
            button.bind(
                "<FocusIn>",
                lambda _event, target=button: target.configure(highlightbackground=ACCENT),
            )
            button.bind(
                "<FocusOut>",
                lambda _event, target=button: target.configure(highlightbackground=BORDER),
            )
            button.grid(row=row, column=0, sticky="ew", pady=2)
            self._action_buttons[action["action_id"]] = button
        self.notice_label.configure(
            text=self.model.notice or "Use the host composer for free-response review."
        )
        self._apply_composition()

    def _apply_composition(self) -> None:
        self.artifact_card.grid_forget()
        self.options_card.grid_forget()
        for index in range(2):
            self.body.rowconfigure(index, weight=0, minsize=0, uniform="")
            self.body.columnconfigure(index, weight=0, minsize=0, uniform="")
        if self.model.mode == "STANDARD":
            self.body.columnconfigure(0, weight=7, uniform="standard-columns")
            self.body.columnconfigure(1, weight=3, uniform="standard-columns")
            self.body.rowconfigure(0, weight=1)
            self.artifact_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
            self.options_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        else:
            self.body.columnconfigure(0, weight=1)
            self.body.rowconfigure(0, weight=1)
            self.body.rowconfigure(1, weight=0)
            self.artifact_card.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
            self.options_card.grid(row=1, column=0, sticky="ew", pady=(5, 0))

    def _invoke_action(self, action_id: str) -> None:
        result = self.model.select_action(action_id)
        if result and result.get("result_type") == "FOCUS_REQUIRED":
            self.on_focus_composer()
        self.on_result(result)

    def _toggle_mode(self) -> None:
        self.model.toggle_mode()
        self.on_mode_change()

    def _close(self) -> None:
        self.model.close()
        self.on_close()


class SidecarWindow:
    """Owned frameless top-level containing the custom Sidecar panel."""

    def __init__(
        self,
        owner: tk.Misc,
        model: SidecarModel,
        rect: WindowRect,
        *,
        on_mode_change: Callable[[], None],
        on_close: Callable[[], None],
        on_focus_composer: Callable[[], None],
        on_result: Callable[[dict[str, Any] | None], None],
        debug_ui: bool,
    ) -> None:
        self.window = tk.Toplevel(owner)
        self.window.withdraw()
        self.window.configure(background=SURFACE)
        self.window.overrideredirect(True)
        self.window.resizable(False, False)
        self.window.transient(owner)
        self.window.protocol("WM_DELETE_WINDOW", on_close)
        self.panel = SidecarPanel(
            self.window,
            model,
            on_mode_change=on_mode_change,
            on_close=on_close,
            on_focus_composer=on_focus_composer,
            on_result=on_result,
            debug_ui=debug_ui,
        )
        self.panel.pack(fill="both", expand=True)
        self.apply(rect)
        self.window.deiconify()
        self.window.update_idletasks()
        self.native_owner_attached = _attach_native_owner(owner, self.window)
        self.raise_above_owner()

    def apply(self, rect: WindowRect) -> None:
        self.window.geometry(_geometry(rect))
        self.window.update_idletasks()

    def raise_above_owner(self) -> None:
        if self.window.winfo_exists():
            self.window.lift(self.window.master)
            self.window.update_idletasks()

    def destroy(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()

    @property
    def mapped(self) -> bool:
        return bool(self.window.winfo_exists() and self.window.winfo_ismapped())


class SidecarHarness:
    """Neutral fullscreen parent/composer fixture for the floating Sidecar."""

    def __init__(
        self,
        model: SidecarModel,
        *,
        root: tk.Tk | tk.Toplevel | None = None,
        title: str = "PDLt R6O-2 Sidecar Qualification Harness",
        work_area: WorkArea | None = None,
        debug_ui: bool = False,
        composer_prefill: str | None = None,
    ) -> None:
        self.model = model
        self.root = root or tk.Tk()
        self.debug_ui = debug_ui
        self.root.title(title)
        self.root.configure(background=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Control-q>", lambda _event: self.close())
        self.root.bind("<Control-Q>", lambda _event: self.close())
        self.work_area = work_area or detect_work_area(self.root)
        self.root.overrideredirect(True)
        self.root.geometry(_geometry(self.work_area))

        self.client = tk.Frame(self.root, background=BG)
        self.client.place(x=0, y=0, width=self.work_area.width, height=self.work_area.height)
        self.host_surface = tk.Frame(self.client, background="#0b1521")
        self.host_surface.place(x=0, y=0, width=self.work_area.width, height=self.work_area.height)

        self.composer = tk.Frame(
            self.client,
            background="#111d2a",
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.composer.columnconfigure(0, weight=1)
        self.composer_entry = tk.Entry(
            self.composer,
            background="#0b1521",
            foreground=TEXT,
            insertbackground=TEXT,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI", 11),
        )
        self.composer_entry.grid(row=0, column=0, sticky="ew", padx=(14, 8), pady=16)
        self.composer_entry.bind("<Return>", self._submit_composer)
        if composer_prefill:
            self.composer_entry.insert(0, composer_prefill)
            self.composer_entry.selection_range(0, "end")
        self.send_button = tk.Button(
            self.composer,
            text="Send",
            command=self._submit_composer,
            background="#4f3b9d",
            foreground=TEXT,
            activebackground="#6650bd",
            activeforeground=TEXT,
            relief="flat",
            padx=14,
            pady=7,
            font=("Segoe UI", 9, "bold"),
        )
        self.send_button.grid(row=0, column=1, padx=(0, 14), pady=10)

        self.window: SidecarWindow | None = None
        self.composer_focus_requested = False
        self._layout_composer(model.mode)
        self.root.update_idletasks()
        self.placement = SidecarPlacementController(self.root, self.composer, self.work_area)
        self.attach_sidecar(model)
        self.root.bind("<FocusIn>", self._owner_interaction, add="+")
        self.root.bind("<ButtonPress>", self._owner_interaction, add="+")

    def _owner_interaction(self, _event: Any = None) -> None:
        if self.window is not None:
            self.root.after_idle(self.window.raise_above_owner)

    def _layout_composer(self, mode: str) -> None:
        scale = self.work_area.scale
        margin = _scaled(HOST_MARGIN, scale)
        height = _scaled(COMPOSER_HEIGHT, scale)
        y = self.work_area.height - margin - height
        width = self.work_area.width - 2 * margin
        if mode == "EXPANDED":
            expanded_width = round(self.work_area.width * EXPANDED_WIDTH_RATIO)
            expanded_x_local = (
                self.work_area.width
                - _scaled(EXPANDED_RIGHT_INSET, scale)
                - expanded_width
            )
            right = expanded_x_local - _scaled(EXPANDED_COMPOSER_CLEARANCE, scale)
            width = max(1, right - margin)
        self.composer.place(x=margin, y=y, width=width, height=height)
        self.root.update_idletasks()

    def attach_sidecar(self, model: SidecarModel) -> None:
        """Externally attach a fresh View instance to the current session projection."""

        if self.window is not None:
            self.window.destroy()
        self.model = model
        if model.terminal:
            self.window = None
            self.focus_composer()
            return
        self._layout_composer(model.mode)
        rect = self.placement.rect_for(model.mode)
        self.window = SidecarWindow(
            self.root,
            model,
            rect,
            on_mode_change=self._mode_changed,
            on_close=self._panel_closed,
            on_focus_composer=self.focus_composer,
            on_result=self._after_result,
            debug_ui=self.debug_ui,
        )

    @property
    def panel(self) -> SidecarPanel | None:
        return self.window.panel if self.window is not None else None

    def _mode_changed(self) -> None:
        if self.window is None:
            return
        self._layout_composer(self.model.mode)
        self.window.panel.render()
        self.window.apply(self.placement.rect_for(self.model.mode))
        self.window.raise_above_owner()
        self.root.update_idletasks()

    def invoke_mode_control(self) -> None:
        if self.window is None:
            raise RuntimeError("Sidecar is not attached")
        self.window.panel.mode_button.invoke()
        self.root.update_idletasks()

    def set_mode_via_control(self, mode: str) -> None:
        if mode not in {"STANDARD", "EXPANDED"}:
            raise ValueError(f"unsupported Sidecar mode: {mode}")
        if self.model.mode != mode:
            self.invoke_mode_control()

    def _panel_closed(self) -> None:
        self.model.close()
        if self.window is not None:
            self.window.destroy()
            self.window = None
        self.focus_composer()
        self.root.update_idletasks()

    def _after_result(self, result: dict[str, Any] | None) -> None:
        if self.model.terminal:
            self.model.close()
            if self.window is not None:
                self.window.destroy()
                self.window = None
            self.focus_composer()
        elif self.window is not None:
            self.window.panel.render()
        self.root.update_idletasks()

    def focus_composer(self) -> None:
        self.composer_focus_requested = True
        self.composer_entry.focus_force()
        if self.window is not None:
            self.window.raise_above_owner()

    def invoke_action(self, action_id: str) -> None:
        """Invoke one currently projected action through its visible widget."""

        if self.window is None:
            raise RuntimeError("Sidecar is not attached")
        self.window.panel._action_buttons[action_id].invoke()
        self.root.update_idletasks()

    def _submit_composer(self, _event: Any = None) -> str | None:
        value = self.composer_entry.get()
        result = self.model.host_composer_text(value)
        if result and result.get("result_type") == "REVISION":
            self.composer_entry.delete(0, "end")
        self._after_result(result)
        return "break" if _event is not None else None

    @staticmethod
    def _widget_rect(widget: tk.Misc) -> WindowRect:
        return WindowRect(
            widget.winfo_rootx(),
            widget.winfo_rooty(),
            widget.winfo_width(),
            widget.winfo_height(),
        )

    def sidecar_rect(self) -> WindowRect | None:
        if self.window is None:
            return None
        return self._widget_rect(self.window.window)

    def geometry_snapshot(self) -> dict[str, int | float | str | bool]:
        self.root.update_idletasks()
        parent = self._widget_rect(self.root)
        composer = self._widget_rect(self.composer)
        frameless = bool(
            self.window is not None and self.window.window.overrideredirect()
        )
        resizable = bool(
            self.window is not None and any(self.window.window.resizable())
        )
        global_topmost = bool(
            self.window is not None
            and self.window.window.attributes("-topmost")
        )
        result: dict[str, int | float | str | bool] = {
            "mode": self.model.mode,
            "monitor_id": self.work_area.monitor_id,
            "dpi": self.work_area.dpi,
            "scale": self.work_area.scale,
            "parent_x": parent.x,
            "parent_y": parent.y,
            "parent_width": parent.width,
            "parent_height": parent.height,
            "work_area_x": self.work_area.x,
            "work_area_y": self.work_area.y,
            "work_area_width": self.work_area.width,
            "work_area_height": self.work_area.height,
            "client_width": parent.width,
            "client_height": parent.height,
            "composer_x": composer.x,
            "composer_y": composer.y,
            "composer_width": composer.width,
            "composer_height": composer.height,
            "sidecar_visible": self.window is not None and self.window.mapped,
            "panel_visible": self.window is not None and self.window.mapped,
            "sidecar_frameless": frameless,
            "sidecar_resizable": resizable,
            "sidecar_global_topmost": global_topmost,
            "sidecar_transient": bool(
                self.window is not None and self.window.window.transient()
            ),
            "sidecar_native_owner_attached": bool(
                self.window is not None and self.window.native_owner_attached
            ),
            "sidecar_above_owner": bool(
                self.window is not None
                and _native_window_above(self.window.window, self.root) is not False
            ),
            "native_sidecar_chrome": not frameless,
        }
        if self.window is not None:
            sidecar = self._widget_rect(self.window.window)
            artifact = self._widget_rect(self.window.panel.artifact_card)
            options = self._widget_rect(self.window.panel.options_card)
            for prefix, rect in (
                ("sidecar", sidecar),
                ("panel", sidecar),
                ("artifact", artifact),
                ("options", options),
            ):
                result.update(
                    {
                        f"{prefix}_x": rect.x,
                        f"{prefix}_y": rect.y,
                        f"{prefix}_width": rect.width,
                        f"{prefix}_height": rect.height,
                    }
                )
        return result

    def capture(self, destination: str | Path) -> Path:
        from PIL import ImageGrab

        if self.window is not None and not self.window.native_owner_attached:
            raise RuntimeError("Sidecar has no native fullscreen-window owner")
        # Tk can place an overrideredirect child below its owner when the parent is
        # activated, even after Win32 ownership is attached. Bring the group forward,
        # then restore and verify the owned Sidecar ordering before accepting pixels.
        self.root.lift()
        self.root.focus_force()
        _activate_windows_toplevel(self.root)
        self.root.update()
        if self.window is not None:
            self.window.raise_above_owner()
            self.root.update()
        if self.window is not None and not self.geometry_snapshot()["sidecar_above_owner"]:
            raise RuntimeError("Sidecar is not above its fullscreen owner")
        parent = self._widget_rect(self.root)
        image = ImageGrab.grab(
            bbox=(parent.x, parent.y, parent.right, parent.bottom), all_screens=True
        )
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return path

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None
        self.model.state.close_view()
        if self.root.winfo_exists():
            self.root.destroy()


def _header_button(
    master: tk.Misc, text: str, color: str, command: Callable[[], None]
) -> tk.Button:
    return tk.Button(
        master,
        text=text,
        command=command,
        background="#152638",
        foreground=color,
        activebackground="#20384f",
        activeforeground=TEXT,
        highlightthickness=1,
        highlightbackground=color,
        relief="flat",
        borderwidth=0,
        padx=9,
        pady=3,
        font=("Segoe UI", 9, "bold"),
        takefocus=True,
    )
