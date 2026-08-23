from __future__ import annotations

"""Pure window and pane geometry for the reusable H2 Sidecar component."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


STANDARD_SIZE = (675, 300)
EXPANDED_SIZE = (412, 806)


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
    """Place the design-locked Sidecar relative to its presentation owner.

    Pane rectangles are local to the Sidecar window. Owner, composer, and
    window rectangles use screen coordinates.
    """

    _validate_anchor(owner, composer)
    margin = max(12, round(owner.width * 0.0125))
    window_border = 1

    if mode is SidecarMode.STANDARD:
        anchor_gap = 10
        window_width, window_height = STANDARD_SIZE
        available_height = composer.y - owner.y - margin - anchor_gap
        if available_height < window_height:
            raise ValueError("qualification owner has insufficient space above the composer")
        window_x = min(max(composer.x, owner.x + margin), owner.right - margin - window_width)
        if window_x < owner.x + margin:
            raise ValueError("qualification owner is too narrow for the STANDARD Sidecar")
        window = Rect(window_x, composer.y - anchor_gap - window_height, window_width, window_height)
        artifact = Rect(8, 44, 402, 256)
        review_options = Rect(418, 44, 249, 256)
        composition = "ARTIFACT_LEFT_REVIEW_OPTIONS_RIGHT"
        chrome_height = 43
    else:
        anchor_gap = None
        window_width, window_height = EXPANDED_SIZE
        if owner.width < window_width + 2 * margin or owner.height < window_height + 2 * margin:
            raise ValueError("qualification owner is too small for the EXPANDED Sidecar")
        window = Rect(owner.right - margin - window_width, owner.y + margin, window_width, window_height)
        artifact = Rect(8, 48, 396, 350)
        review_options = Rect(8, 408, 396, 398)
        composition = "ARTIFACT_TOP_REVIEW_OPTIONS_BELOW"
        chrome_height = 47

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
