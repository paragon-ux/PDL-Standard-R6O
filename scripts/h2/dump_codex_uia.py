from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.host.codex.windows.discovery import HostDiscoveryError, discover_codex_host  # noqa: E402
from r6o.host.codex.windows.uia import (  # noqa: E402
    UiaContractError,
    activate_host,
    connect_to_host,
    dump_uia_tree,
    sha256_file,
    write_canonical_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump a redacted actual Codex UIA subtree")
    parser.add_argument("--host-record", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        host_record_path = args.host_record.resolve()
        host_record = json.loads(host_record_path.read_text(encoding="utf-8"))
        recorded = host_record["codex"]
        candidate = discover_codex_host()
        identity = (
            "hwnd",
            "pid",
            "executable",
            "product_name",
            "product_version",
            "file_version",
            "package_version",
        )
        if any(recorded[key] != getattr(candidate, key) for key in identity):
            raise UiaContractError("HOST_RECORD_STALE")
        _, root = connect_to_host(candidate.hwnd)
        activate_host(root)
        document = dump_uia_tree(root)
        document["captured_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        document["host_record_sha256"] = sha256_file(host_record_path)
        document["host_identity"] = {
            "hwnd": candidate.hwnd,
            "pid": candidate.pid,
            "product_name": candidate.product_name,
            "product_version": candidate.product_version,
            "file_version": candidate.file_version,
            "package_version": candidate.package_version,
        }
        write_canonical_json(args.output.resolve(), document)
    except (OSError, KeyError, json.JSONDecodeError, HostDiscoveryError, UiaContractError) as exc:
        print(f"FAIL HOST_UIA_DUMP_UNVERIFIED {exc}")
        return 1
    print(f"CODEX_UIA_DUMPED {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
