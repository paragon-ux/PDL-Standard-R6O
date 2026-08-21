from __future__ import annotations

"""ViewModel dependency boundary: the versioned MVVM Model Port.

The ViewModel depends on this port, never on concrete Python/runtime/filesystem
internals.
"""

from r6o.model_binding.base import (
    MODEL_PORT_VERSION,
    ArtifactSnapshot,
    ModelPort,
    ModelRevision,
    SessionInvocation,
    StaleProjectionError,
)

__all__ = [
    "MODEL_PORT_VERSION",
    "ArtifactSnapshot",
    "ModelPort",
    "ModelRevision",
    "SessionInvocation",
    "StaleProjectionError",
]
