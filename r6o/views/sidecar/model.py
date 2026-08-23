from __future__ import annotations

"""Pure window and pane geometry for the reusable H2 Sidecar component."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SidecarMode(str, Enum):
    STANDARD = "STANDARD"
    EXPANDED = "EXPANDED"


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("rectangle width and height must be positive")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, other: "Rect") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.right >= other.right
            and self.bottom >= other.bottom
        )

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class SidecarLayout:
    mode: SidecarMode
    owner: Rect
    composer: Rect
    window: Rect
    chrome: Rect
    artifact: Rect
    review_options: Rect
    parent_width_fraction: float
    composition: str
    composer_anchor_gap: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "owner": self.owner.to_dict(),
            "composer": self.composer.to_dict(),
            "window": self.window.to_dict(),
            "chrome": self.chrome.to_dict(),
            "artifact": self.artifact.to_dict(),
            "review_options": self.review_options.to_dict(),
            "parent_width_fraction": self.parent_width_fraction,
            "composition": self.composition,
            "composer_anchor_gap": self.composer_anchor_gap,
        }


def _validate_anchor(owner: Rect, composer: Rect) -> None:
    if not owner.contains(composer):
        raise ValueError("composer rectangle must be fully contained by the qualification owner")
    if owner.width < 640 or owner.height < 480:
        raise ValueError("qualification owner must be at least 640x480")


def calculate_sidecar_layout(owner: Rect, composer: Rect, mode: SidecarMode) -> SidecarLayout:
    """Calculate the frozen H2-C STANDARD or EXPANDED relationship.

    Pane rectangles are local to the Sidecar window. Owner, composer, and
    window rectangles use screen coordinates.
    """

    _validate_anchor(owner, composer)
    margin = max(12, round(owner.width * 0.0125))
    window_border = 1
    chrome_height = 50
    padding = 12
    pane_gap = 10

    if mode is SidecarMode.STANDARD:
        anchor_gap = 10
        available_height = composer.y - owner.y - margin - anchor_gap
        if available_height < 220:
            raise ValueError("qualification owner has insufficient space above the composer")
        window_height = min(max(260, round(owner.height * 0.34)), available_height)
        window = Rect(composer.x, composer.y - anchor_gap - window_height, composer.width, window_height)
        content_y = window_border + chrome_height + padding
        content_height = window.height - content_y - window_border - padding
        content_width = window.width - 2 * (window_border + padding)
        artifact_width = round((content_width - pane_gap) * 0.64)
        content_x = window_border + padding
        artifact = Rect(content_x, content_y, artifact_width, content_height)
        review_options = Rect(
            artifact.right + pane_gap,
            content_y,
            content_width - artifact_width - pane_gap,
            content_height,
        )
        composition = "ARTIFACT_LEFT_REVIEW_OPTIONS_RIGHT"
    else:
        anchor_gap = None
        window_width = round(owner.width * 0.30)
        window = Rect(owner.right - margin - window_width, owner.y + margin, window_width, owner.height - 2 * margin)
        content_y = window_border + chrome_height + padding
        content_height = window.height - content_y - window_border - padding
        content_width = window.width - 2 * (window_border + padding)
        artifact_height = round((content_height - pane_gap) * 0.60)
        content_x = window_border + padding
        artifact = Rect(content_x, content_y, content_width, artifact_height)
        review_options = Rect(
            content_x,
            artifact.bottom + pane_gap,
            content_width,
            content_height - artifact_height - pane_gap,
        )
        composition = "ARTIFACT_TOP_REVIEW_OPTIONS_BELOW"

    return SidecarLayout(
        mode=mode,
        owner=owner,
        composer=composer,
        window=window,
        chrome=Rect(window_border, window_border, window.width - 2 * window_border, chrome_height),
        artifact=artifact,
        review_options=review_options,
        parent_width_fraction=round(window.width / owner.width, 6),
        composition=composition,
        composer_anchor_gap=anchor_gap,
    )
