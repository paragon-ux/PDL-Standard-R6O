from __future__ import annotations

"""Durable and in-memory HandoffStore implementations below the ViewModel."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from r6o.model_binding.base import HandoffReceipt


def canonical_envelope_bytes(envelope: dict[str, Any]) -> bytes:
    return (
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


class FileHandoffStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def persist(self, envelope: dict[str, Any]) -> HandoffReceipt:
        handoff_id = str(envelope.get("handoff_id") or "")
        if not handoff_id:
            raise ValueError("handoff envelope has no handoff_id")
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{handoff_id}.json"
        payload = canonical_envelope_bytes(envelope)
        digest = hashlib.sha256(payload).hexdigest()
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=destination.name + ".",
            suffix=".tmp",
            dir=self.directory,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            self._fsync_directory(self.directory)
        finally:
            if temporary.exists():
                temporary.unlink()
        return HandoffReceipt(
            handoff_ref=str(destination),
            handoff_id=handoff_id,
            digest=digest,
            durable=True,
        )


class InMemoryHandoffStore:
    def __init__(self) -> None:
        self.envelopes: dict[str, dict[str, Any]] = {}

    def persist(self, envelope: dict[str, Any]) -> HandoffReceipt:
        handoff_id = str(envelope.get("handoff_id") or "")
        if not handoff_id:
            raise ValueError("handoff envelope has no handoff_id")
        payload = canonical_envelope_bytes(envelope)
        self.envelopes[handoff_id] = json.loads(payload)
        return HandoffReceipt(
            handoff_ref=f"memory:{handoff_id}",
            handoff_id=handoff_id,
            digest=hashlib.sha256(payload).hexdigest(),
            durable=True,
        )
