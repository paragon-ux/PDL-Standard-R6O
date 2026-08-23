from __future__ import annotations

"""Projection-only, design-locked Tk Sidecar for H2 component and host bindings."""

import textwrap
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from r6o.views.sidecar.model import Rect, SidecarLayout, SidecarMode, calculate_sidecar_layout


TERMINAL_STAGES = frozenset({"CLOSED_SUCCESS", "CLOSED_CANCELLED"})


@dataclass(frozen=True)
class _HitRegion:
    role: str
    rect: Rect
    command: Callable[[], None]


class _ArtifactScrollModel:
    """Toolkit-neutral artifact scrolling without a mapped native scrollbar."""

    def __init__(self, on_change: Callable[[], None]) -> None:
        self._on_change = on_change
        self._lines: list[str] = []
        self._offset = 0
        self._visible_lines = 1

    def configure(self, *, body: str, width_chars: int, visible_lines: int) -> None:
        self._visible_lines = max(1, visible_lines)
        lines: list[str] = []
        for source_line in body.splitlines() or [""]:
            if not source_line:
                lines.append("")
                continue
            lines.extend(
                textwrap.wrap(
                    source_line,
                    width=max(8, width_chars),
                    replace_whitespace=False,
                    drop_whitespace=False,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
                or [""]
            )
        self._lines = lines
        self._offset = min(self._offset, self._max_offset)

    @property
    def visible(self) -> list[str]:
        return self._lines[self._offset : self._offset + self._visible_lines]

    @property
    def _max_offset(self) -> int:
        return max(0, len(self._lines) - self._visible_lines)

    def yview(self) -> tuple[float, float]:
        total = max(1, len(self._lines))
        return (
            self._offset / total,
            min(1.0, (self._offset + self._visible_lines) / total),
        )

    def yview_scroll(self, units: int, _kind: str = "units") -> None:
        self._offset = min(self._max_offset, max(0, self._offset + units))
        self._on_change()

    def yview_moveto(self, fraction: float) -> None:
        self._offset = min(self._max_offset, max(0, round(self._max_offset * fraction)))
        self._on_change()


class _ActionHandle:
    """Small compatibility surface for tests and host bindings."""

    def __init__(
        self,
        sidecar: "SidecarWindow",
        *,
        action_id: str,
        label: str,
        ordinal: int,
        enabled: bool,
    ) -> None:
        self.sidecar = sidecar
        self.action_id = action_id
        self.label = label
        self.ordinal = ordinal
        self.enabled = enabled

    def cget(self, key: str) -> str:
        if key == "text":
            return self.label
        if key == "state":
            return "normal" if self.enabled else "disabled"
        raise tk.TclError(f"unknown action option {key!r}")

    def invoke(self) -> None:
        if self.enabled:
            self.sidecar._invoke_action(self.action_id)

    def focus_force(self) -> None:
        self.sidecar._set_focus(self.action_id)


class SidecarWindow:
    """Render a FocusProjection in a disposable, design-locked Sidecar."""

    # Reference-raster samples cluster tightly around these low-contrast
    # surfaces.  Keeping the layers close is important: the approved design
    # reads as one compact Sidecar, not four flat black rectangles.
    BG = "#11171d"
    SURFACE = "#0d141a"
    CARD = "#12181e"
    BODY = "#0b1117"
    BORDER = "#242a30"
    BORDER_SOFT = "#242a30"
    TEXT = "#eef2f5"
    MUTED = "#a8afb6"
    ACCENT = "#a891e9"
    ACTIVE = "#4bd477"
    BLUE = "#48a7e8"
    AMBER = "#e58b25"
    NEUTRAL = "#9aa4ad"

    def __init__(
        self,
        owner: tk.Misc,
        owner_rect: Rect,
        composer_rect: Rect,
        *,
        source_presenter: Callable[[dict[str, Any]], tuple[str, str]],
        on_action: Callable[[str], None] | None = None,
        on_close_view: Callable[[], None] | None = None,
        on_open_editor: Callable[[str], None] | None = None,
        on_copy: Callable[[str], None] | None = None,
        global_topmost: bool = False,
    ) -> None:
        self.owner = owner
        self.owner_rect = owner_rect
        self.composer_rect = composer_rect
        self.on_action = on_action or (lambda _action_id: None)
        self.on_close_view = on_close_view or (lambda: None)
        self.on_open_editor = on_open_editor or (lambda _artifact_ref: None)
        self.on_copy = on_copy
        self.source_presenter = source_presenter
        self.mode = SidecarMode.STANDARD
        self.locked = True
        self.projection: dict[str, Any] | None = None
        self.layout: SidecarLayout | None = None
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._action_buttons: list[_ActionHandle] = []
        self._hit_regions: list[_HitRegion] = []
        self._focus_order: list[str] = []
        self._focused_role: str | None = None
        self._source_label = "Source: Projected Artifact"
        self._source_value = "Opaque reference"
        self._artifact_body_text = ""
        self._visible_controls: set[str] = set()
        self._semantic_rects: dict[str, Rect] = {}

        self.window = tk.Toplevel(owner)
        self.window.withdraw()
        self.window.configure(bg=self.BG, highlightthickness=0, bd=0)
        self.window.overrideredirect(True)
        self.window.transient(owner)
        if global_topmost:
            self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self.close_view)

        self.canvas = tk.Canvas(
            self.window,
            bg=self.BG,
            highlightthickness=0,
            bd=0,
            relief="flat",
            takefocus=True,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Tab>", self._on_tab)
        self.canvas.bind("<Shift-Tab>", self._on_shift_tab)
        try:
            self.canvas.bind("<ISO_Left_Tab>", self._on_shift_tab)
        except tk.TclError:
            pass
        self.canvas.bind("<Return>", self._on_activate)
        self.canvas.bind("<space>", self._on_activate)
        self.canvas.bind("<Escape>", self._on_escape)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda _event: self.scroll_artifact(-3))
        self.canvas.bind("<Button-5>", lambda _event: self.scroll_artifact(3))

        self.artifact_body = _ArtifactScrollModel(self._draw)

    @property
    def focused_action_id(self) -> str | None:
        action_ids = {item.action_id for item in self._action_buttons}
        return self._focused_role if self._focused_role in action_ids else None

    @property
    def visible_controls(self) -> frozenset[str]:
        return frozenset(self._visible_controls)

    @property
    def visible_text(self) -> tuple[str, ...]:
        return tuple(
            str(self.canvas.itemcget(item, "text"))
            for item in self.canvas.find_all()
            if self.canvas.type(item) == "text"
        )

    @property
    def semantic_rects(self) -> dict[str, Rect]:
        return dict(self._semantic_rects)

    def _rounded_rect(
        self,
        rect: Rect,
        *,
        radius: int,
        fill: str,
        outline: str | None = None,
        width: int = 1,
    ) -> int:
        x1, y1, x2, y2 = rect.x, rect.y, rect.right, rect.bottom
        r = min(radius, rect.width // 2, rect.height // 2)
        points = (
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
        )
        return self.canvas.create_polygon(
            points,
            smooth=True,
            splinesteps=24,
            fill=fill,
            outline=outline or fill,
            width=width,
        )

    def _add_hit(self, role: str, rect: Rect, command: Callable[[], None]) -> None:
        self._hit_regions.append(_HitRegion(role, rect, command))
        self._visible_controls.add(role)

    def _draw_expand_icon(self, rect: Rect) -> None:
        center_x = rect.x + rect.width // 2
        center_y = rect.y + rect.height // 2
        color = self.TEXT
        for points in (
            (center_x - 7, center_y - 2, center_x - 7, center_y - 7, center_x - 2, center_y - 7),
            (center_x + 2, center_y - 7, center_x + 7, center_y - 7, center_x + 7, center_y - 2),
            (center_x - 7, center_y + 2, center_x - 7, center_y + 7, center_x - 2, center_y + 7),
            (center_x + 2, center_y + 7, center_x + 7, center_y + 7, center_x + 7, center_y + 2),
        ):
            self.canvas.create_line(*points, fill=color, width=1)
        self._semantic_rects["expand_icon"] = Rect(center_x - 7, center_y - 7, 14, 14)

    def _draw_external_link_icon(self, rect: Rect) -> None:
        center_x = rect.x + rect.width // 2
        center_y = rect.y + rect.height // 2
        color = self.MUTED
        self.canvas.create_line(
            center_x - 4,
            center_y - 3,
            center_x - 4,
            center_y + 4,
            center_x + 3,
            center_y + 4,
            center_x + 3,
            center_y + 1,
            fill=color,
            width=1,
        )
        self.canvas.create_line(
            center_x,
            center_y - 4,
            center_x + 4,
            center_y - 4,
            center_x + 4,
            center_y,
            fill=color,
            width=1,
        )
        self.canvas.create_line(
            center_x + 4,
            center_y - 4,
            center_x - 1,
            center_y + 1,
            fill=color,
            width=1,
        )
        self._semantic_rects["external_link_icon"] = Rect(center_x - 4, center_y - 4, 8, 8)

    def _draw(self) -> None:
        if not self.window.winfo_exists() or self.layout is None or self.projection is None:
            return
        self.canvas.delete("all")
        self._hit_regions.clear()
        self._visible_controls.clear()
        self._semantic_rects.clear()
        window_rect = Rect(0, 0, self.layout.window.width, self.layout.window.height)
        self._rounded_rect(
            Rect(1, 1, window_rect.width - 2, window_rect.height - 2),
            radius=12,
            fill=self.BG,
            outline="#34414a",
        )
        self._draw_header()
        self._draw_artifact()
        self._draw_options()
        self._focus_order = [
            item
            for item in (
                "open_editor",
                "copy",
                *(button.action_id for button in self._action_buttons),
                "expand" if self.mode is SidecarMode.STANDARD else None,
                "close",
            )
            if item is not None
        ]

    def _draw_header(self) -> None:
        expanded = self.mode is SidecarMode.EXPANDED
        self.canvas.create_text(
            18,
            22,
            text="PDLt Review",
            anchor="w",
            fill=self.TEXT,
            font=("Segoe UI Semibold", 12),
        )
        badge = Rect(134, 15, 97, 19)
        self._rounded_rect(badge, radius=4, fill="#2a2145", outline="#40325f")
        self.canvas.create_text(
            badge.x + badge.width // 2,
            badge.y + badge.height // 2,
            text=str(self.projection.get("stage") or "REVIEW").replace("_", " "),
            fill="#ded2ff",
            font=("Segoe UI Semibold", 7),
        )
        active_x = 245 if expanded else 506
        self.canvas.create_oval(active_x, 20, active_x + 7, 27, fill=self.ACTIVE, outline="")
        self.canvas.create_text(
            active_x + 13,
            24,
            text="ACTIVE",
            anchor="w",
            fill=self.ACTIVE,
            font=("Segoe UI Semibold", 9),
        )
        if not expanded:
            expand = Rect(587, 8, 32, 30)
            self._rounded_rect(expand, radius=6, fill=self.SURFACE, outline=self.BORDER)
            self._draw_expand_icon(expand)
            self._add_hit("expand", expand, self.toggle_mode)
        close = Rect(371, 8, 32, 30) if expanded else Rect(629, 8, 32, 30)
        self._rounded_rect(close, radius=6, fill=self.SURFACE, outline=self.BORDER)
        self.canvas.create_text(
            close.x + 16,
            close.y + 15,
            text="×",
            fill=self.TEXT,
            font=("Segoe UI", 16),
        )
        self._add_hit("close", close, self.close_view)

    def _draw_artifact(self) -> None:
        assert self.layout is not None
        expanded = self.mode is SidecarMode.EXPANDED
        panel = self.layout.artifact
        self._semantic_rects["artifact"] = panel
        self._rounded_rect(
            panel,
            radius=9,
            fill="#0f161c" if expanded else self.CARD,
            outline=self.BORDER_SOFT,
        )
        title_y = 71 if expanded else 63
        artifact = (self.projection or {}).get("artifact") or {}
        self.canvas.create_text(
            panel.x + 11,
            title_y,
            text=str(artifact.get("title") or "Authoritative Artifact"),
            anchor="w",
            fill=self.TEXT,
            font=("Segoe UI Semibold", 10),
        )
        open_rect = Rect(284, 52, 112, 31) if expanded else Rect(287, 51, 112, 28)
        self._rounded_rect(open_rect, radius=6, fill=self.SURFACE, outline=self.BORDER)
        self.canvas.create_text(
            open_rect.x + 10,
            open_rect.y + open_rect.height // 2,
            text="Open in Editor",
            anchor="w",
            fill=self.TEXT,
            font=("Segoe UI", 9),
        )
        self._draw_external_link_icon(
            Rect(open_rect.right - 20, open_rect.y + (open_rect.height - 16) // 2, 16, 16)
        )
        self._add_hit("open_editor", open_rect, self._open_artifact)

        body_rect = Rect(18, 91, 378, 248) if expanded else Rect(19, 82, 381, 167)
        self._rounded_rect(body_rect, radius=6, fill=self.BODY, outline=self.BORDER_SOFT)
        line_positions = (
            (114, 132, 155, 178, 202, 225, 249, 272, 298, 321)
            if expanded
            else (97, 106, 122, 140, 156, 172, 185, 202, 217)
        )
        body_font = ("Consolas", 10 if expanded else 9)
        for index, line in enumerate(self.artifact_body.visible):
            self.canvas.create_text(
                body_rect.x + 11,
                line_positions[index],
                text=line,
                anchor="w",
                fill=self.ACCENT if line.strip() == "# Prompt" else "#dce2e7",
                font=body_font,
            )

        if expanded:
            self.canvas.create_text(
                27,
                359,
                text=self._source_label,
                anchor="w",
                fill=self.MUTED,
                font=("Segoe UI", 9),
            )
            self.canvas.create_text(
                27,
                379,
                text=self._source_value,
                anchor="w",
                fill=self.MUTED,
                font=("Segoe UI", 9),
            )
            copy_rect = Rect(337, 352, 58, 31)
        else:
            self.canvas.create_text(
                21,
                273,
                text=self._source_label,
                anchor="w",
                fill=self.MUTED,
                font=("Segoe UI", 9),
            )
            self.canvas.create_text(
                149,
                273,
                text=self._source_value,
                anchor="w",
                fill=self.MUTED,
                font=("Segoe UI", 9),
            )
            copy_rect = Rect(343, 259, 56, 30)
        self._rounded_rect(copy_rect, radius=6, fill=self.SURFACE, outline=self.BORDER)
        self.canvas.create_text(
            copy_rect.x + copy_rect.width // 2,
            copy_rect.y + copy_rect.height // 2,
            text="Copy",
            fill=self.TEXT,
            font=("Segoe UI", 9),
        )
        self._add_hit("copy", copy_rect, self._copy_artifact)

    def _draw_options(self) -> None:
        assert self.layout is not None
        expanded = self.mode is SidecarMode.EXPANDED
        panel = self.layout.review_options
        self._semantic_rects["review_options"] = panel
        if not expanded:
            self._rounded_rect(panel, radius=9, fill=self.CARD, outline=self.BORDER_SOFT)
        else:
            # This is the open Sidecar surface, not a bordered or scrollable
            # options card.  The reference's lower-field sample is slightly
            # darker than the outer edge.
            self.canvas.create_rectangle(
                2,
                panel.y,
                self.layout.window.width - 2,
                self.layout.window.height - 2,
                fill="#0f161c",
                outline="",
            )
        self.canvas.create_text(
            18 if expanded else 431,
            425 if expanded else 63,
            text="Review Options",
            anchor="w",
            fill=self.TEXT,
            font=("Segoe UI Semibold", 10),
        )
        row_y = 449 if expanded else 80
        badge_x = 20 if expanded else 433
        action_x = 55 if expanded else 468
        action_width = 341 if expanded else 190
        self._semantic_rects["actions_content"] = Rect(
            18 if expanded else 431,
            row_y,
            378 if expanded else 226,
            151 if expanded else 139,
        )
        accents = (self.ACTIVE, self.BLUE, self.AMBER, self.NEUTRAL)
        expanded_row_offsets = (0, 41, 83, 124)
        for index, button in enumerate(self._action_buttons):
            if expanded and index < len(expanded_row_offsets):
                y = row_y + expanded_row_offsets[index]
            else:
                y = row_y + index * 36
            badge = Rect(badge_x, y, 30 if expanded else 28, 31)
            action = Rect(action_x, y, action_width, 31)
            accent = accents[index] if index < len(accents) else self.NEUTRAL
            self._rounded_rect(badge, radius=5, fill=self.SURFACE, outline=accent)
            self.canvas.create_text(
                badge.x + badge.width // 2,
                badge.y + badge.height // 2,
                text=str(button.ordinal),
                fill=accent,
                font=("Segoe UI Semibold", 10 if expanded else 9),
            )
            self._rounded_rect(
                action,
                radius=5,
                fill=self.SURFACE,
                # The reference expresses primary/focus emphasis through the
                # numbered badge.  A bright outline around the action body is
                # a visible design deviation even though it is custom chrome.
                outline=self.BORDER,
                width=1,
            )
            self.canvas.create_text(
                action.x + (6 if expanded else 7),
                action.y + action.height // 2,
                text=button.label,
                anchor="w",
                fill=self.TEXT if button.enabled else "#68727b",
                font=("Segoe UI", 9 if not expanded else 10),
            )
            self._add_hit(button.action_id, action, button.invoke)
        tip_y = 644 if expanded else 252
        tip_x = 18 if expanded else 431
        self._semantic_rects["tip"] = Rect(tip_x, tip_y - 8, 378 if expanded else 226, 40)
        self.canvas.create_text(
            tip_x,
            tip_y,
            text="Tip:",
            anchor="w",
            fill=self.TEXT,
            font=("Segoe UI Semibold", 9),
        )
        self.canvas.create_text(
            tip_x + 24,
            tip_y,
            text="Type directly in the chat below",
            anchor="w",
            fill=self.MUTED,
            font=("Segoe UI", 9),
        )
        self.canvas.create_text(
            tip_x,
            tip_y + 20,
            text="to provide other feedback.",
            anchor="w",
            fill=self.MUTED,
            font=("Segoe UI", 9),
        )

    def _apply_layout(self) -> SidecarLayout:
        self.layout = calculate_sidecar_layout(self.owner_rect, self.composer_rect, self.mode)
        rect = self.layout.window
        self.window.geometry(f"{rect.width}x{rect.height}+{rect.x}+{rect.y}")
        self.canvas.configure(width=rect.width, height=rect.height)
        self.artifact_body.configure(
            body=self._artifact_body_text,
            width_chars=43 if self.mode is SidecarMode.STANDARD else 45,
            visible_lines=9 if self.mode is SidecarMode.STANDARD else 10,
        )
        self.window.update_idletasks()
        return self.layout

    def update_anchor(self, owner_rect: Rect, composer_rect: Rect) -> SidecarLayout:
        self.owner_rect = owner_rect
        self.composer_rect = composer_rect
        layout = self._apply_layout()
        self._draw()
        return layout

    def toggle_mode(self) -> SidecarMode:
        self.mode = SidecarMode.EXPANDED if self.mode is SidecarMode.STANDARD else SidecarMode.STANDARD
        self._apply_layout()
        self._draw()
        return self.mode

    def toggle_lock(self) -> bool:
        """Retain the nonvisual movement diagnostic without public chrome."""

        self.locked = not self.locked
        if self.locked:
            self._apply_layout()
            self._draw()
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
        self._action_buttons = [
            _ActionHandle(
                self,
                action_id=str(action["action_id"]),
                label=str(action["label"]),
                ordinal=int(action["ordinal"]),
                enabled=bool(action.get("enabled", True)),
            )
            for action in actions
        ]

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
        self._artifact_body_text = str(artifact.get("body") or "")
        self._source_label, self._source_value = self.source_presenter(artifact)
        self._render_actions(actions)
        layout = self._apply_layout()
        self.window.deiconify()
        self.window.lift()
        self.focus_primary_action()
        self._draw()
        return layout

    def _set_focus(self, role: str) -> None:
        self._focused_role = role
        self.canvas.focus_force()
        self._draw()

    def focus_primary_action(self) -> None:
        if self._action_buttons:
            self._set_focus(self._action_buttons[0].action_id)

    def _invoke_action(self, action_id: str) -> None:
        self._set_focus(action_id)
        self.on_action(action_id)

    def _open_artifact(self) -> None:
        artifact = (self.projection or {}).get("artifact") or {}
        if (artifact.get("capabilities") or {}).get("open_external", False):
            self.on_open_editor(str(artifact.get("artifact_ref") or ""))

    def _copy_artifact(self) -> None:
        artifact = (self.projection or {}).get("artifact") or {}
        if not (artifact.get("capabilities") or {}).get("copy", False):
            return
        body = str(artifact.get("body") or "")
        if self.on_copy is not None:
            self.on_copy(body)
        else:
            self.window.clipboard_clear()
            self.window.clipboard_append(body)

    def _on_click(self, event: tk.Event[Any]) -> None:
        for hit in reversed(self._hit_regions):
            if hit.rect.x <= event.x < hit.rect.right and hit.rect.y <= event.y < hit.rect.bottom:
                self._set_focus(hit.role)
                hit.command()
                return

    def _on_tab(self, _event: tk.Event[Any]) -> str:
        self._advance_focus(1)
        return "break"

    def _on_shift_tab(self, _event: tk.Event[Any]) -> str:
        self._advance_focus(-1)
        return "break"

    def _advance_focus(self, delta: int) -> None:
        if not self._focus_order:
            return
        try:
            index = self._focus_order.index(self._focused_role or "")
        except ValueError:
            index = -1 if delta > 0 else 0
        self._set_focus(self._focus_order[(index + delta) % len(self._focus_order)])

    def _on_activate(self, _event: tk.Event[Any]) -> str:
        for hit in self._hit_regions:
            if hit.role == self._focused_role:
                hit.command()
                break
        return "break"

    def _on_escape(self, _event: tk.Event[Any]) -> str:
        if self.mode is SidecarMode.EXPANDED:
            self.toggle_mode()
        return "break"

    def _on_mousewheel(self, event: tk.Event[Any]) -> str:
        delta = getattr(event, "delta", 0)
        self.scroll_artifact(-3 if delta > 0 else 3)
        return "break"

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
