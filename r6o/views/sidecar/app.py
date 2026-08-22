from __future__ import annotations

"""High-fidelity Tk Sidecar with contract-measured Standard/Expanded layouts."""

import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from r6o.views.sidecar.model import SidecarModel

SHELL_WIDTH = 1200
SHELL_HEIGHT = 800
STANDARD_HEIGHT = 280
STANDARD_HEIGHT_TOLERANCE = 24
EXPANDED_WIDTH_RATIO = 0.50

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


class SidecarPanel(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        model: SidecarModel,
        *,
        on_mode_change: Callable[[], None],
        on_close: Callable[[], None],
        on_focus_composer: Callable[[], None],
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
        self.mode_button = _header_button(
            self.header, "Expand", ACCENT, self._toggle_mode
        )
        self.mode_button.grid(row=0, column=3, padx=4, pady=7)
        self.close_button = _header_button(
            self.header, "Close", DANGER, self._close
        )
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
        artifact_frame.grid(row=1, column=0, sticky="nsew", padx=10)
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
        self.source_label = tk.Label(
            self.artifact_card,
            text="Projection snapshot · revision-bound",
            background=CARD,
            foreground=MUTED,
            anchor="w",
            font=("Segoe UI", 8),
        )
        self.source_label.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 8))

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
        self.artifact_title.configure(
            text=artifact.get("title") or "Authoritative Artifact"
        )
        body = artifact.get("body") or projection.get("model_response") or "(no artifact)"
        self.artifact_text.configure(state="normal")
        self.artifact_text.delete("1.0", "end")
        self.artifact_text.insert("1.0", body)
        self.artifact_text.configure(state="disabled")
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
                command=lambda action_id=action["action_id"]: self._invoke_action(
                    action_id
                ),
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
                lambda _event, target=button: target.configure(
                    highlightbackground=ACCENT
                ),
            )
            button.bind(
                "<FocusOut>",
                lambda _event, target=button: target.configure(
                    highlightbackground=BORDER
                ),
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
            self.body.rowconfigure(index, weight=0, minsize=0)
            self.body.columnconfigure(index, weight=0, minsize=0)
        if self.model.mode == "STANDARD":
            self.body.columnconfigure(0, weight=7, uniform="standard")
            self.body.columnconfigure(1, weight=3, uniform="standard")
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
        self.render()

    def _toggle_mode(self) -> None:
        self.model.toggle_mode()
        self.on_mode_change()

    def _close(self) -> None:
        self.model.close()
        self.on_close()


class SidecarHarness:
    """Qualification shell preserving the host/composer/Sidecar relationship."""

    def __init__(
        self,
        model: SidecarModel,
        *,
        root: tk.Tk | None = None,
        title: str = "PDLt R6O-2 Sidecar Qualification Harness",
    ) -> None:
        self.model = model
        self.root = root or tk.Tk()
        self.root.title(title)
        self.root.geometry(f"{SHELL_WIDTH}x{SHELL_HEIGHT}")
        self.root.minsize(900, 620)
        self.root.configure(background=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.client = tk.Frame(self.root, background=BG)
        self.client.grid(row=0, column=0, sticky="nsew")

        self.host = tk.Frame(self.client, background="#0d1621")
        self.host.columnconfigure(0, weight=1)
        self.host.rowconfigure(1, weight=1)
        host_header = tk.Frame(self.host, background="#111d2a", height=42)
        host_header.grid(row=0, column=0, sticky="ew")
        host_header.grid_propagate(False)
        tk.Label(
            host_header,
            text="Qualification Host · editor",
            background="#111d2a",
            foreground=MUTED,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=14, pady=10)
        self.reopen_button = tk.Button(
            host_header,
            text="Open PDLt Review",
            command=self.reopen,
            background="#173b26",
            foreground=PRIMARY,
            relief="flat",
            padx=10,
            pady=4,
        )
        self.editor = tk.Text(
            self.host,
            background="#09131f",
            foreground="#a9bed3",
            relief="flat",
            borderwidth=0,
            padx=18,
            pady=16,
            font=("Cascadia Mono", 11),
        )
        self.editor.insert(
            "1.0",
            "# Qualification host\n\n"
            "The host/editor remains independent of the PDLt Sidecar.\n"
            "Free-response review is entered in the composer below.\n",
        )
        self.editor.configure(state="disabled")
        self.editor.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

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

        self.panel = SidecarPanel(
            self.client,
            model,
            on_mode_change=self._mode_changed,
            on_close=self._panel_closed,
            on_focus_composer=self.focus_composer,
        )
        self._apply_shell_layout()

    def _apply_shell_layout(self) -> None:
        for widget in (self.host, self.composer, self.panel):
            widget.grid_forget()
        for index in range(3):
            self.client.rowconfigure(index, weight=0, minsize=0)
            self.client.columnconfigure(index, weight=0, minsize=0, uniform="")
        if self.model.mode == "STANDARD":
            self.client.columnconfigure(0, weight=1)
            self.client.rowconfigure(0, weight=1)
            self.client.rowconfigure(1, weight=0, minsize=STANDARD_HEIGHT)
            self.client.rowconfigure(2, weight=0, minsize=76)
            self.host.grid(row=0, column=0, sticky="nsew")
            self.panel.configure(height=STANDARD_HEIGHT)
            self.panel.grid_propagate(False)
            if self.model.visible:
                self.panel.grid(row=1, column=0, sticky="nsew", padx=10, pady=0)
            self.composer.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 10))
        else:
            self.client.columnconfigure(0, weight=1, uniform="expanded")
            self.client.columnconfigure(1, weight=1, uniform="expanded")
            self.client.rowconfigure(0, weight=1)
            self.client.rowconfigure(1, weight=0, minsize=76)
            self.host.grid(row=0, column=0, sticky="nsew")
            self.composer.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 10))
            self.panel.grid_propagate(True)
            if self.model.visible:
                self.panel.grid(
                    row=0,
                    column=1,
                    rowspan=2,
                    sticky="nsew",
                    padx=(6, 10),
                    pady=10,
                )
        self.panel.render()
        self.root.update_idletasks()

    def _mode_changed(self) -> None:
        self._apply_shell_layout()

    def _panel_closed(self) -> None:
        self.panel.grid_remove()
        self.reopen_button.pack(side="right", padx=12, pady=6)
        self.root.update_idletasks()

    def reopen(self) -> None:
        self.model.reopen()
        self.reopen_button.pack_forget()
        self._apply_shell_layout()

    def focus_composer(self) -> None:
        self.composer_entry.focus_set()

    def invoke_action(self, action_id: str) -> None:
        """Invoke one currently projected action through its visible widget."""
        self.panel._action_buttons[action_id].invoke()
        self.root.update_idletasks()

    def _submit_composer(self, _event: Any = None) -> str | None:
        value = self.composer_entry.get()
        result = self.model.host_composer_text(value)
        if result and result.get("result_type") == "REVISION":
            self.composer_entry.delete(0, "end")
        self.panel.render()
        return "break" if _event is not None else None

    def geometry_snapshot(self) -> dict[str, int | str | bool]:
        self.root.update_idletasks()
        root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()

        def geometry(prefix: str, widget: tk.Misc) -> dict[str, int]:
            return {
                f"{prefix}_x": widget.winfo_rootx() - root_x,
                f"{prefix}_y": widget.winfo_rooty() - root_y,
                f"{prefix}_width": widget.winfo_width(),
                f"{prefix}_height": widget.winfo_height(),
            }

        result: dict[str, int | str | bool] = {
            "mode": self.model.mode,
            "client_width": self.client.winfo_width(),
            "client_height": self.client.winfo_height(),
            "panel_visible": bool(self.panel.winfo_ismapped()),
        }
        result.update(geometry("panel", self.panel))
        result.update(geometry("composer", self.composer))
        result.update(geometry("artifact", self.panel.artifact_card))
        result.update(geometry("options", self.panel.options_card))
        return result

    def capture(self, destination: str | Path) -> Path:
        from PIL import ImageGrab

        self.root.update()
        x = self.root.winfo_rootx()
        y = self.root.winfo_rooty()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return path

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        self.model.state.close_view()
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
