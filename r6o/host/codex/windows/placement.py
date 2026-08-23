from __future__ import annotations

"""Pure, DPI-aware placement rules for the locked Qt Sidecar."""

import math
from dataclasses import dataclass

from r6o.views.sidecar.model import SidecarMode


BASE_DPI = 96
STANDARD_GAP_LOGICAL_PX = 8
EXPANDED_RIGHT_INSET_LOGICAL_PX = 24
EXPANDED_TOP_INSET_LOGICAL_PX = 48
EXPANDED_BOTTOM_INSET_LOGICAL_PX = 24
PLACEMENT_TOLERANCE_PX = 2


class PlacementError(RuntimeError):
    """A stable, fail-closed D2 placement failure."""


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if any(isinstance(value, bool) or not isinstance(value, int) for value in self.as_tuple()):
            raise PlacementError("RECTANGLE_COORDINATE_INVALID")
        if self.right <= self.left or self.bottom <= self.top:
            raise PlacementError("RECTANGLE_EMPTY")

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom

    def as_record(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
        }

    def contains(self, other: "Rect", *, tolerance: int = 0) -> bool:
        return (
            other.left >= self.left - tolerance
            and other.top >= self.top - tolerance
            and other.right <= self.right + tolerance
            and other.bottom <= self.bottom + tolerance
        )


def rect_from_record(record: object, *, label: str) -> Rect:
    if not isinstance(record, dict):
        raise PlacementError(f"RECTANGLE_RECORD_INVALID:{label}")
    try:
        rectangle = Rect(
            left=record["left"],
            top=record["top"],
            right=record["right"],
            bottom=record["bottom"],
        )
    except (KeyError, PlacementError) as exc:
        raise PlacementError(f"RECTANGLE_RECORD_INVALID:{label}") from exc
    if record.get("width") not in (None, rectangle.width) or record.get("height") not in (
        None,
        rectangle.height,
    ):
        raise PlacementError(f"RECTANGLE_RECORD_INVALID:{label}")
    return rectangle


def scale_logical(value: int, dpi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PlacementError("LOGICAL_DISTANCE_INVALID")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise PlacementError("DPI_INVALID")
    return int(math.floor((value * dpi / BASE_DPI) + 0.5))


def canonical_physical_size(mode: SidecarMode, dpi: int) -> tuple[int, int]:
    width, height = SidecarMode.parse(mode).size
    return scale_logical(width, dpi), scale_logical(height, dpi)


def standard_placement(*, composer: Rect, work_area: Rect, dpi: int) -> Rect:
    """Anchor the locked 675x300 Sidecar to the actual composer's left edge.

    The August 23 H2-C fidelity authority supersedes the older provisional
    composer-width rule by locking the QML window to 675 logical pixels. D2
    preserves the remaining Standard equation: composer-left anchoring and an
    eight-logical-pixel gap directly above the actual composer.
    """

    width, height = canonical_physical_size(SidecarMode.STANDARD, dpi)
    gap = scale_logical(STANDARD_GAP_LOGICAL_PX, dpi)
    result = Rect(
        left=composer.left,
        top=composer.top - gap - height,
        right=composer.left + width,
        bottom=composer.top - gap,
    )
    if not work_area.contains(result, tolerance=PLACEMENT_TOLERANCE_PX):
        raise PlacementError("STANDARD_PLACEMENT_OUT_OF_WORK_AREA")
    return result


def expanded_placement(*, host_client: Rect, work_area: Rect, dpi: int) -> Rect:
    """Place the locked 412x806 rail at the approved host-relative insets."""

    width, height = canonical_physical_size(SidecarMode.EXPANDED, dpi)
    right_inset = scale_logical(EXPANDED_RIGHT_INSET_LOGICAL_PX, dpi)
    top_inset = scale_logical(EXPANDED_TOP_INSET_LOGICAL_PX, dpi)
    bottom_inset = scale_logical(EXPANDED_BOTTOM_INSET_LOGICAL_PX, dpi)
    result = Rect(
        left=host_client.right - right_inset - width,
        top=host_client.top + top_inset,
        right=host_client.right - right_inset,
        bottom=host_client.top + top_inset + height,
    )
    if result.bottom > host_client.bottom - bottom_inset + PLACEMENT_TOLERANCE_PX:
        raise PlacementError("EXPANDED_PLACEMENT_EXCEEDS_HOST_CLIENT")
    if not work_area.contains(result, tolerance=PLACEMENT_TOLERANCE_PX):
        raise PlacementError("EXPANDED_PLACEMENT_OUT_OF_WORK_AREA")
    return result


def placement_for_mode(
    mode: SidecarMode,
    *,
    composer: Rect,
    host_client: Rect,
    work_area: Rect,
    dpi: int,
) -> Rect:
    parsed = SidecarMode.parse(mode)
    if parsed is SidecarMode.STANDARD:
        return standard_placement(composer=composer, work_area=work_area, dpi=dpi)
    return expanded_placement(host_client=host_client, work_area=work_area, dpi=dpi)


def rectangles_match(actual: Rect, expected: Rect, *, tolerance: int = PLACEMENT_TOLERANCE_PX) -> bool:
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 0:
        raise PlacementError("PLACEMENT_TOLERANCE_INVALID")
    return all(abs(left - right) <= tolerance for left, right in zip(actual.as_tuple(), expected.as_tuple()))
