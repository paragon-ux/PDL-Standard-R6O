from __future__ import annotations

"""Toolkit-neutral presentation geometry for the H2-C Sidecar."""

from enum import Enum


STANDARD_SIZE = (675, 300)
EXPANDED_SIZE = (412, 806)


class SidecarMode(str, Enum):
    STANDARD = "STANDARD"
    EXPANDED = "EXPANDED"

    @property
    def size(self) -> tuple[int, int]:
        return STANDARD_SIZE if self is SidecarMode.STANDARD else EXPANDED_SIZE

    @classmethod
    def parse(cls, value: str | "SidecarMode") -> "SidecarMode":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(f"unsupported Sidecar mode: {value!r}") from exc
