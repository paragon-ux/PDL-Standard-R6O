from __future__ import annotations

"""Tkinter Sidecar View (embeddable panel) and qualification harness.

The Sidecar panel owns no text input: free response belongs to the
surrounding harness composer and enters through HOST_COMPOSER_TEXT.
"""

import tkinter as tk
from tkinter import scrolledtext
from typing import Any, Callable

from r6o.views.sidecar.model import SidecarModel

STANDARD_WIDTH = 680
STANDARD_HEIGHT = 280
EXPANDED_WIDTH_RATIO = 0.5


def _stage_label(stage: Any) -> str:
    return str(stage or "UNKNOWN").replace("_", " ")


class SidecarPanel(tk.Frame):
    """Embeddable sidecar surface: artifact left, compact actions right."""

    def __init__(
        self,
        model: SidecarModel,
        master: Any,
        on_mode_changed: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, bg="#1a1a1f", highlightbackground="#3a3a44", highlightthickness=1)
        self.model = model
        self.on_mode_changed = on_mode_changed
        self.on_close = on_close
        self.header = tk.Label(self, text="", bg="#1a1a1f", fg="#ffffff", anchor="w", font=("Segoe UI", 11, "bold"))
        self.header.pack(fill="x", padx=8, pady=(6, 2))
        self.body = tk.Frame(self, bg="#1a1a1f")
        self.body.pack(fill="both", expand=True, padx=8, pady=4)
        self.artifact_text = scrolledtext.ScrolledText(
            self.body, wrap="word", bg="#232329", fg="#e8e8e8", insertbackground="#e8e8e8", relief="flat", font=("Consolas", 10)
        )
        self.actions_frame = tk.Frame(self.body, bg="#232329", highlightbackground="#3a3a44", highlightthickness=1)
        self.controls = tk.Frame(self, bg="#1a1a1f")
        self.controls.pack(fill="x", padx=8, pady=(0, 6))
        self.expand_button = tk.Button(self.controls, text="Expand", command=self._toggle_mode, bg="#2f2f37", fg="#ffffff")
        self.expand_button.pack(side="left")
        self.close_button = tk.Button(self.controls, text="Close", command=self._close, bg="#5a2b2b", fg="#ffffff")
        self.close_button.pack(side="left", padx=(6, 0))
        self.notice_label = tk.Label(self.controls, text="", bg="#1a1a1f", fg="#ffd166", anchor="e")
        self.notice_label.pack(side="right", fill="x", expand=True)
        self._buttons: dict[str, tk.Button] = {}
        self.render()

    def _toggle_mode(self) -> None:
        self.model.toggle_mode()
        self.render()
        if self.on_mode_changed is not None:
            self.on_mode_changed()

    def _close(self) -> None:
        self.model.close()
        if self.on_close is not None:
            self.on_close()
        else:
            self.pack_forget()

    def render(self) -> None:
        projection = self.model.projection
        stage = _stage_label(projection.get("stage"))
        self.header.config(text=f"PDLt Review · {stage} · {self.model.mode}")
        artifact = (projection.get("artifact") or {}).get("body") or "(no artifact)"
        self.artifact_text.config(state="normal")
        self.artifact_text.delete("1.0", "end")
        self.artifact_text.insert("1.0", artifact)
        self.artifact_text.config(state="disabled")
        for widget in self.actions_frame.winfo_children():
            widget.destroy()
        self._buttons.clear()
        actions = sorted(projection.get("actions", []), key=lambda a: a.get("ordinal", 0))
        for action in actions:
            ordinal = action.get("ordinal")
            label = action.get("label") or action.get("action_id") or "?"
            state = "normal" if action.get("enabled", True) else "disabled"
            button = tk.Button(
                self.actions_frame,
                text=f"{ordinal} {label}",
                command=lambda a=action: self._on_action(a),
                state=state,
                bg="#2f2f37",
                fg="#ffffff",
                anchor="w",
                width=28,
            )
            button.pack(fill="x", pady=2, padx=4)
            self._buttons[action.get("action_id")] = button
        self.notice_label.config(text=self.model.notice or "")
        self.expand_button.config(text="Collapse" if self.model.mode == "EXPANDED" else "Expand")
        self._apply_layout()

    def _apply_layout(self) -> None:
        self.artifact_text.pack_forget()
        self.actions_frame.pack_forget()
        if self.model.mode == "EXPANDED":
            self.artifact_text.pack(side="left", fill="both", expand=True)
            self.actions_frame.pack(side="right", anchor="n", fill="none", padx=(8, 0))
        else:
            self.artifact_text.pack(side="left", fill="both", expand=True)
            self.actions_frame.pack(side="right", anchor="n", fill="none", padx=(8, 0))

    def _on_action(self, action: dict[str, Any]) -> None:
        self.model.select_action(str(action.get("action_id")))
        self.render()


class TkSidecarView:
    """Standalone Sidecar window."""

    def __init__(self, model: SidecarModel, root: tk.Tk | None = None) -> None:
        self.model = model
        self.root = root or tk.Tk()
        self.root.title("PDLt Review")
        self.root.configure(bg="#1a1a1f")
        self.panel = SidecarPanel(model, self.root, on_mode_changed=self._apply_geometry, on_close=self.root.withdraw)
        self.panel.pack(fill="both", expand=True)
        self._apply_geometry()

    def _apply_geometry(self) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if self.model.mode == "EXPANDED":
            width = int(screen_w * EXPANDED_WIDTH_RATIO)
            height = screen_h
            x = screen_w - width
            y = 0
        else:
            width = STANDARD_WIDTH
            height = STANDARD_HEIGHT
            x = max(0, screen_w - width - 24)
            y = max(0, screen_h - height - 120)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(420, 240)

    def run(self) -> None:
        self.root.mainloop()


class HarnessShell:
    """Qualification harness: host editor + host composer + embedded Sidecar."""

    def __init__(self, model: SidecarModel) -> None:
        self.model = model
        self.root = tk.Tk()
        self.root.title("R6O-2 Harness (qualification shell)")
        self.root.geometry("1200x800")
        self.editor = scrolledtext.ScrolledText(self.root, wrap="word", bg="#101014", fg="#c8c8d0", insertbackground="#c8c8d0", font=("Consolas", 11))
        self.composer = tk.Frame(self.root, bg="#181820")
        self.composer_label = tk.Label(self.composer, text="Host composer", bg="#181820", fg="#9a9aa5")
        self.composer_entry = tk.Entry(self.composer, bg="#2a2a33", fg="#ffffff", insertbackground="#ffffff", relief="solid", font=("Segoe UI", 11))
        self.composer_entry.bind("<Return>", self._on_composer_submit)
        if self.model.focus_host_callback is None:
            self.model.focus_host_callback = lambda _label: self.composer_entry.focus_set()
        self.composer_button = tk.Button(self.composer, text="Send", command=self._on_composer_submit, bg="#2f2f37", fg="#ffffff")
        self.show_button = tk.Button(self.composer, text="Show PDLt", command=self._show_panel, bg="#2f2f37", fg="#ffffff")
        self.composer_label.pack(side="left", padx=6)
        self.composer_entry.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        self.composer_button.pack(side="left", padx=(0, 6))
        self.show_button.pack(side="left", padx=(0, 6))
        self.panel = SidecarPanel(
            model,
            self.root,
            on_mode_changed=self._apply_layout,
            on_close=lambda: self.panel.pack_forget(),
        )
        self._apply_layout()
        self.editor.insert("1.0", "# host harness (illustrative)\n# editor area for the surrounding application\n")

    def _apply_layout(self) -> None:
        self.editor.pack_forget()
        self.composer.pack_forget()
        self.panel.pack_forget()
        if self.model.mode == "EXPANDED":
            self.composer.pack(side="bottom", fill="x")
            self.editor.pack(side="left", fill="both", expand=True)
            self.panel.pack(side="right", fill="y")
        else:
            self.editor.pack(side="top", fill="both", expand=True)
            self.composer.pack(side="bottom", fill="x")
            self.panel.pack(side="bottom", fill="x")
            self.panel.configure(height=STANDARD_HEIGHT)
            self.panel.pack_propagate(False)
        self.panel.render()

    def _show_panel(self) -> None:
        self.model.open_()
        self._apply_layout()

    def _focus_composer(self, label: str) -> None:
        self.composer_entry.focus_set()

    def _on_composer_submit(self, _event: Any = None) -> None:
        text = self.composer_entry.get()
        if text:
            self.model.host_composer_text(text)
            self.composer_entry.delete(0, "end")
            self.panel.render()

    def run(self) -> None:
        self.root.mainloop()


