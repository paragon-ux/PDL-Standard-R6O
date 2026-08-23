"""Fail-closed Windows binding for the actual Codex desktop host."""

from .discovery import HostCandidate, HostDiscoveryError, discover_codex_host

__all__ = ["HostCandidate", "HostDiscoveryError", "discover_codex_host"]
