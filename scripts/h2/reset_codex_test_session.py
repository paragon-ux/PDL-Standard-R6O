from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.host.codex.windows.discovery import HostDiscoveryError, discover_codex_host  # noqa: E402
from r6o.host.codex.windows.uia import (  # noqa: E402
    UiaContractError,
    activate_host,
    composer_empty_observation,
    connect_to_host,
    fresh_chat_observation,
    load_selectors,
    resolve_control,
    sha256_file,
)

DEFAULT_LOG = ROOT / "r6o_evidence" / "H2-D1" / "reset-session.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset the actual Codex host to a verified fresh chat")
    parser.add_argument("--selectors", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    return parser.parse_args()


def _write_log(path: Path, record: dict[str, object]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _fail(args: argparse.Namespace, code: str, details: dict[str, object] | None = None) -> int:
    record: dict[str, object] = {
        "schema_version": "r6o-h2-d1-reset-log-1",
        "status": "FAIL",
        "code": code,
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if details:
        record["details"] = details
    _write_log(args.output, record)
    print(f"FAIL HOST_RESET_UNVERIFIED {code}")
    return 1


def _failure_code(exc: BaseException) -> str:
    if isinstance(exc, HostDiscoveryError):
        return exc.code
    if isinstance(exc, UiaContractError):
        return str(exc) or "HOST_UIA_CONTRACT_ERROR"
    if isinstance(exc, KeyError):
        return "RESET_CONTRACT_KEY_MISSING"
    if isinstance(exc, OSError):
        return "HOST_IO_ERROR"
    return type(exc).__name__


def main() -> int:
    args = parse_args()
    selectors_path = args.selectors.resolve()
    try:
        selectors = load_selectors(selectors_path)
        candidate = discover_codex_host()
        compatibility = selectors.get("host_compatibility")
        expected_identity = {
            "product_name": candidate.product_name,
            "product_version": candidate.product_version,
            "file_version": candidate.file_version,
            "package_version": candidate.package_version,
        }
        if compatibility != expected_identity:
            return _fail(args, "HOST_VERSION_MISMATCH", {"actual": expected_identity})
        _, root = connect_to_host(candidate.hwnd)
        activate_host(root)
        controls = selectors["controls"]
        composer = resolve_control(root, controls["composer"], label="composer")
        before = composer_empty_observation(composer, selectors["reset_contract"]["composer_empty"])
        if not before["empty"]:
            # Refuse before invoking New Chat: never discard an actual host draft.
            return _fail(args, "COMPOSER_NOT_EMPTY", {"before": before})
        new_chat = resolve_control(root, controls["new_chat"], label="new_chat")
        new_chat.invoke()

        deadline = time.monotonic() + args.timeout_seconds
        after: dict[str, object] | None = None
        fresh: dict[str, object] | None = None
        last_observer_error: str | None = None
        while time.monotonic() < deadline:
            try:
                # New Chat replaces Chromium's document; reconnect so selector
                # resolution never relies on stale UIA wrappers.
                _, root = connect_to_host(candidate.hwnd)
                composer = resolve_control(root, controls["composer"], label="composer")
                region = resolve_control(root, controls["primary_content_region"], label="primary_content_region")
                after = composer_empty_observation(composer, selectors["reset_contract"]["composer_empty"])
                fresh = fresh_chat_observation(region, selectors["reset_contract"]["fresh_chat"])
                if after["empty"] and fresh["fresh"]:
                    composer.set_focus()
                    break
            except Exception as exc:
                last_observer_error = _failure_code(exc)
            time.sleep(0.2)
        else:
            return _fail(
                args,
                "FRESH_CHAT_NOT_PROVED",
                {
                    "composer": after or {},
                    "conversation": fresh or {},
                    "last_observer_error": last_observer_error,
                },
            )

        record = {
            "schema_version": "r6o-h2-d1-reset-log-1",
            "status": "CODEX_TEST_SESSION_READY",
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "host": {
                "hwnd": candidate.hwnd,
                "pid": candidate.pid,
                **expected_identity,
            },
            "selectors_sha256": sha256_file(selectors_path),
            "new_chat_action": "UIA_INVOKE_PATTERN",
            "composer_before": before,
            "composer_after": after,
            "fresh_chat": fresh,
            "composer_focused_after_reset": bool(composer.has_keyboard_focus()),
        }
        _write_log(args.output, record)
    except (KeyError, HostDiscoveryError, UiaContractError, OSError) as exc:
        return _fail(args, _failure_code(exc))
    print("CODEX_TEST_SESSION_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
