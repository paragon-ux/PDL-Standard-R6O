from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.host.codex.windows.discovery import (  # noqa: E402
    HostDiscoveryError,
    HostCandidate,
    build_environment_record,
    discover_codex_host,
    validate_environment_record,
)
from r6o.host.codex.windows.uia import UiaContractError, activate_host, connect_to_host, write_canonical_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover and measure the actual Codex desktop host")
    parser.add_argument("--discover", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def capture_environment_record(candidate: HostCandidate) -> dict[str, Any]:
    _, root = connect_to_host(candidate.hwnd)
    activate_host(root)
    record = build_environment_record(candidate)
    record["codex"]["uia_connection"] = {
        "backend": "uia",
        "root_control_type": str(root.element_info.control_type or ""),
        "root_automation_id": str(root.element_info.automation_id or ""),
        "connected": True,
    }
    validate_environment_record(record)
    return record


def main() -> int:
    args = parse_args()
    try:
        candidate = discover_codex_host()
        record = capture_environment_record(candidate)
        write_canonical_json(args.output.resolve(), record)
    except HostDiscoveryError as exc:
        print(json.dumps(exc.as_record(), sort_keys=True))
        print(f"FAIL {exc.code}")
        return 1
    except UiaContractError as exc:
        print(f"FAIL {exc}")
        return 1
    print(f"CODEX_HOST_DISCOVERED {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
