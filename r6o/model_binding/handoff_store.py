from __future__ import annotations

"""Durable HandoffStore implementation below the ViewModel."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from r6o.model_binding.base import HandoffReceipt

_HANDOFF_ID = re.compile(r"^handoff-[0-9a-f]{64}$")


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
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def persist(self, envelope: dict[str, Any]) -> HandoffReceipt:
        handoff_id = str(envelope.get("handoff_id") or "")
        if not _HANDOFF_ID.fullmatch(handoff_id):
            raise ValueError("handoff envelope has an unsafe or invalid handoff_id")
        if not self.directory.is_dir():
            raise FileNotFoundError("durable handoff directory must already exist")
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
            if os.name == "nt":
                import ctypes

                move_file = ctypes.windll.kernel32.MoveFileExW
                move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
                move_file.restype = ctypes.c_int
                move_file_replace_existing = 0x1
                move_file_write_through = 0x8
                if not move_file(str(temporary), str(destination), move_file_replace_existing | move_file_write_through):
                    raise ctypes.WinError()
            else:
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
