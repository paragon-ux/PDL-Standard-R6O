from __future__ import annotations

"""Projection-only Tk Sidecar component for H2 component and host bindings."""

import tkinter as tk
from collections.abc import Callable
from typing import Any

from r6o.views.sidecar.model import Rect, SidecarLayout, SidecarMode, calculate_sidecar_layout


TERMINAL_STAGES = frozenset({"CLOSED_SUCCESS", "CLOSED_CANCELLED"})


class SidecarWindow:
    """Render a FocusProjection in a disposable, owner-relative Sidecar."""

    BG = "#111820"
    PANEL = "#151e27"
    PANEL_ALT = "#0d141b"
    BORDER = "#33404d"
    TEXT = "#edf3f8"
    MUTED = "#9facb8"
    ACCENT = "#7c5cff"
    ACTIVE = "#48d477"
    FOCUS = "#53a9ff"

    def __init__(
        self,
        owner: tk.Misc,
        owner_rect: Rect,
        composer_rect: Rect,
        *,
        on_action: Callable[[str], None] | None = None,
        on_close_view: Callable[[], None] | None = None,
        global_topmost: bool = False,
    ) -> None:
        self.owner = owner
        self.owner_rect = owner_rect
        self.composer_rect = composer_rect
        self.on_action = on_action or (lambda _action_id: None)
        self.on_close_view = on_close_view or (lambda: None)
        self.mode = SidecarMode.STANDARD
        self.locked = True
        self.projection: dict[str, Any] | None = None
        self.layout: SidecarLayout | None = None
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._action_buttons: list[tk.Button] = []

        self.window = tk.Toplevel(owner)
        self.window.withdraw()
        self.window.configure(bg=self.BG, highlightbackground=self.BORDER, highlightthickness=1)
        self.window.overrideredirect(True)
        self.window.transient(owner)
        if global_topmost:
            self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self.close_view)

        self.chrome = tk.Frame(self.window, bg=self.BG, height=50)
        self.chrome.pack(fill="x", side="top")
        self.chrome.pack_propagate(False)
        self.chrome.bind("<ButtonPress-1>", self._begin_drag)
        self.chrome.bind("<B1-Motion>", self._drag)

        self.title_label = tk.Label(
            self.chrome,
            text="PDLt Review",
            bg=self.BG,
            fg=self.TEXT,
            font=("Segoe UI Semibold", 12),
        )
        self.title_label.pack(side="left", padx=(12, 8))
        self.stage_label = tk.Label(
            self.chrome,
            text="REVIEW",
            bg="#2a2045",
            fg="#d9ccff",
            font=("Segoe UI Semibold", 8),
            padx=8,
            pady=3,
        )
        self.stage_label.pack(side="left")
        self.active_label = tk.Label(
            self.chrome,
            text="● ACTIVE",
            bg=self.BG,
            fg=self.ACTIVE,
            font=("Segoe UI Semibold", 8),
        )
        self.active_label.pack(side="left", padx=10)

        self.close_button = self._chrome_button("CLOSE", self.close_view)
        self.close_button.pack(side="right", padx=(0, 8), pady=8)
        self.expand_button = self._chrome_button("EXPAND", self.toggle_mode)
        self.expand_button.pack(side="right", padx=4, pady=8)
        self.lock_button = self._chrome_button("LOCKED", self.toggle_lock)
        self.lock_button.pack(side="right", padx=4, pady=8)

        self.content = tk.Frame(self.window, bg=self.BG)
        self.content.pack(fill="both", expand=True, padx=12, pady=12)
        self.artifact_panel = tk.Frame(self.content, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)
        self.options_panel = tk.Frame(self.content, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)
        self._build_artifact_panel()
        self._build_options_panel()
        self._compose_panels()

    def _chrome_button(self, text: str, command: Callable[[], None]) -> tk.Button:
        return tk.Button(
            self.chrome,
            text=text,
            command=command,
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground="#263341",
            activeforeground=self.TEXT,
            relief="flat",
            bd=0,
            padx=9,
            pady=4,
            cursor="hand2",
            takefocus=True,
        )

    def _build_artifact_panel(self) -> None:
        header = tk.Frame(self.artifact_panel, bg=self.PANEL)
        header.pack(fill="x", padx=10, pady=(9, 5))
        self.artifact_title = tk.Label(
            header,
            text="Authoritative Artifact",
            bg=self.PANEL,
            fg=self.TEXT,
            anchor="w",
            font=("Segoe UI Semibold", 9),
        )
        self.artifact_title.pack(side="left", fill="x", expand=True)
        body_frame = tk.Frame(self.artifact_panel, bg=self.PANEL_ALT)
        body_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.artifact_body = tk.Text(
            body_frame,
            wrap="word",
            bg=self.PANEL_ALT,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            selectbackground=self.ACCENT,
            relief="flat",
            bd=0,
            padx=10,
            pady=10,
            font=("Consolas", 9),
            takefocus=True,
        )
        self.artifact_scrollbar = tk.Scrollbar(
            body_frame,
            orient="vertical",
            command=self.artifact_body.yview,
        )
        self.artifact_body.configure(yscrollcommand=self.artifact_scrollbar.set)
        self.artifact_scrollbar.pack(side="right", fill="y")
        self.artifact_body.pack(side="left", fill="both", expand=True)
        self.artifact_source = tk.Label(
            self.artifact_panel,
            text="Projection snapshot · opaque artifact reference",
            bg=self.PANEL,
            fg=self.MUTED,
            anchor="w",
            font=("Segoe UI", 8),
        )
        self.artifact_source.pack(fill="x", padx=10, pady=(0, 8))

    def _build_options_panel(self) -> None:
        tk.Label(
            self.options_panel,
            text="Review Options",
            bg=self.PANEL,
            fg=self.TEXT,
            anchor="w",
            font=("Segoe UI Semibold", 9),
        ).pack(fill="x", padx=10, pady=(9, 5))
        options_container = tk.Frame(self.options_panel, bg=self.PANEL)
        options_container.pack(fill="both", expand=True, padx=10)
        self.options_canvas = tk.Canvas(
            options_container,
            bg=self.PANEL,
            highlightthickness=0,
            bd=0,
        )
        self.options_scrollbar = tk.Scrollbar(
            options_container,
            orient="vertical",
            command=self.options_canvas.yview,
        )
        self.options_canvas.configure(yscrollcommand=self.options_scrollbar.set)
        self.options_scrollbar.pack(side="right", fill="y")
        self.options_canvas.pack(side="left", fill="both", expand=True)
        self.options_inner = tk.Frame(self.options_canvas, bg=self.PANEL)
        self.options_window = self.options_canvas.create_window((0, 0), window=self.options_inner, anchor="nw")
        self.options_inner.bind("<Configure>", self._sync_options_scrollregion)
        self.options_canvas.bind("<Configure>", self._sync_options_width)
        tk.Label(
            self.options_panel,
            text="Tip: choose Something else... to focus the host free-response surface.",
            bg=self.PANEL,
            fg=self.MUTED,
            anchor="w",
            justify="left",
            wraplength=280,
            font=("Segoe UI", 8),
        ).pack(fill="x", padx=10, pady=8)

    def _sync_options_scrollregion(self, _event: tk.Event[Any] | None = None) -> None:
        self.options_canvas.configure(scrollregion=self.options_canvas.bbox("all"))

    def _sync_options_width(self, event: tk.Event[Any]) -> None:
        self.options_canvas.itemconfigure(self.options_window, width=event.width)

    def _compose_panels(self) -> None:
        self.artifact_panel.pack_forget()
        self.options_panel.pack_forget()
        if self.mode is SidecarMode.STANDARD:
            self.artifact_panel.pack(side="left", fill="both", expand=True)
            self.options_panel.pack(side="left", fill="both", padx=(10, 0))
            self.options_panel.pack_propagate(False)
        else:
            self.options_panel.pack_propagate(False)
            self.artifact_panel.pack(side="top", fill="both", expand=True)
            self.options_panel.pack(side="top", fill="both", pady=(10, 0))

    def _apply_layout(self) -> SidecarLayout:
        self.layout = calculate_sidecar_layout(self.owner_rect, self.composer_rect, self.mode)
        rect = self.layout.window
        self.window.geometry(f"{rect.width}x{rect.height}+{rect.x}+{rect.y}")
        if self.mode is SidecarMode.STANDARD:
            self.options_panel.configure(width=self.layout.review_options.width)
        else:
            self.options_panel.configure(height=self.layout.review_options.height)
        self.window.update_idletasks()
        return self.layout

    def update_anchor(self, owner_rect: Rect, composer_rect: Rect) -> SidecarLayout:
        self.owner_rect = owner_rect
        self.composer_rect = composer_rect
        return self._apply_layout()

    def toggle_mode(self) -> SidecarMode:
        self.mode = SidecarMode.EXPANDED if self.mode is SidecarMode.STANDARD else SidecarMode.STANDARD
        self.expand_button.configure(text="COLLAPSE" if self.mode is SidecarMode.EXPANDED else "EXPAND")
        self._compose_panels()
        self._apply_layout()
        return self.mode

    def toggle_lock(self) -> bool:
        self.locked = not self.locked
        self.lock_button.configure(text="LOCKED" if self.locked else "MOVE")
        if self.locked:
            self._apply_layout()
        return self.locked

    def _begin_drag(self, event: tk.Event[Any]) -> None:
        if not self.locked:
            self._drag_origin = (event.x_root, event.y_root, self.window.winfo_x(), self.window.winfo_y())

    def _drag(self, event: tk.Event[Any]) -> None:
        if self.locked or self._drag_origin is None:
            return
        start_x, start_y, window_x, window_y = self._drag_origin
        self.window.geometry(f"+{window_x + event.x_root - start_x}+{window_y + event.y_root - start_y}")

    def _render_actions(self, actions: list[dict[str, Any]]) -> None:
        for child in self.options_inner.winfo_children():
            child.destroy()
        self._action_buttons.clear()
        for action in actions:
            action_id = str(action["action_id"])
            row = tk.Frame(self.options_inner, bg=self.PANEL)
            row.pack(fill="x", pady=3)
            ordinal = tk.Label(
                row,
                text=str(action["ordinal"]),
                width=2,
                bg="#162331",
                fg=self.ACTIVE if action.get("emphasis") == "PRIMARY" else self.FOCUS,
                relief="solid",
                bd=1,
                font=("Segoe UI Semibold", 9),
            )
            ordinal.pack(side="left", padx=(0, 7), ipady=5)
            button = tk.Button(
                row,
                text=str(action["label"]),
                command=lambda selected=action_id: self.on_action(selected),
                state="normal" if action.get("enabled", True) else "disabled",
                bg=self.PANEL_ALT,
                fg=self.TEXT,
                activebackground="#263341",
                activeforeground=self.TEXT,
                disabledforeground="#66717c",
                relief="solid",
                bd=1,
                anchor="w",
                padx=9,
                pady=6,
                takefocus=True,
            )
            button.pack(side="left", fill="x", expand=True)
            self._action_buttons.append(button)
        self.options_inner.update_idletasks()
        self._sync_options_scrollregion()

    def render(self, projection: dict[str, Any]) -> SidecarLayout | None:
        stage = projection.get("stage")
        lifecycle = projection.get("lifecycle") or {}
        if stage in TERMINAL_STAGES or lifecycle.get("terminal") is True:
            self.dismiss_terminal()
            return None
        artifact = projection.get("artifact")
        actions = projection.get("actions")
        if not isinstance(artifact, dict) or not isinstance(actions, list) or not actions:
            raise ValueError("active Sidecar projection requires an artifact and projected actions")
        self.projection = projection
        self.stage_label.configure(text=str(stage or "REVIEW").replace("_", " "))
        self.artifact_title.configure(text=str(artifact.get("title") or "Authoritative Artifact"))
        self.artifact_body.configure(state="normal")
        self.artifact_body.delete("1.0", "end")
        self.artifact_body.insert("1.0", str(artifact.get("body") or ""))
        self.artifact_body.configure(state="disabled")
        self.artifact_source.configure(text=f"Projection snapshot · {artifact.get('artifact_ref', 'opaque reference')}")
        self._render_actions(actions)
        layout = self._apply_layout()
        self.window.deiconify()
        self.window.lift()
        self.focus_primary_action()
        return layout

    def focus_primary_action(self) -> None:
        if self._action_buttons:
            self._action_buttons[0].focus_force()

    def scroll_artifact(self, units: int) -> None:
        self.artifact_body.yview_scroll(units, "units")

    def close_view(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()
        self.owner.focus_force()
        self.on_close_view()

    def dismiss_terminal(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()
        self.owner.focus_force()
