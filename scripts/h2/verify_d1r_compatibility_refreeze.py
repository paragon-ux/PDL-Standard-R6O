from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASE_COMMIT = "9816c9b848101678e654bfc14abbb6db269737d3"
SELECTOR_RELATIVE_PATH = Path("r6o/host/codex/windows/selectors.json")
HOST_RECORD_RELATIVE_PATH = Path("r6o_evidence/H2-D1/host-environment.json")
UIA_TREE_RELATIVE_PATH = Path("r6o_evidence/H2-D1/codex-uia.json")

FROM_PACKAGE_VERSION = "26.818.3698.0"
TO_PACKAGE_VERSION = "26.818.5229.0"
PRODUCT_NAME = "Codex"
PRODUCT_VERSION = "151.0.7922.170"
FILE_VERSION = "151.0.7922.170"

ALLOWED_POINTERS = frozenset(
    {
        "/captured_from/host_environment/sha256",
        "/captured_from/uia_tree/sha256",
        "/host_compatibility/package_version",
    }
)
REQUIRED_DEEP_EQUAL_POINTERS = (
    "/schema_version",
    "/captured_from/host_environment/path",
    "/captured_from/uia_tree/path",
    "/host_compatibility/product_name",
    "/host_compatibility/product_version",
    "/host_compatibility/file_version",
    "/controls",
    "/reset_contract",
)
READ_ONLY_D1_D2_PYTHON = (
    "r6o/host/codex/windows/discovery.py",
    "r6o/host/codex/windows/uia.py",
    "r6o/host/codex/windows/binding.py",
    "r6o/host/codex/windows/placement.py",
)


class D1RVerificationError(RuntimeError):
    """A stable fail-closed D1R verification failure."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the closed H2-D1R selector and evidence compatibility refreeze"
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--base-commit", default=BASE_COMMIT)
    parser.add_argument("--selectors", type=Path, default=SELECTOR_RELATIVE_PATH)
    parser.add_argument("--host-record", type=Path, default=HOST_RECORD_RELATIVE_PATH)
    parser.add_argument("--uia-tree", type=Path, default=UIA_TREE_RELATIVE_PATH)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def structural_deltas(before: object, after: object, pointer: str = "") -> list[str]:
    if type(before) is not type(after):
        return [pointer or "/"]
    if isinstance(before, dict):
        deltas: list[str] = []
        for key in sorted(set(before) | set(after)):
            child = f"{pointer}/{_pointer_token(key)}"
            if key not in before or key not in after:
                deltas.append(child)
            else:
                deltas.extend(structural_deltas(before[key], after[key], child))
        return deltas
    if isinstance(before, list):
        deltas = []
        for index in range(max(len(before), len(after))):
            child = f"{pointer}/{index}"
            if index >= len(before) or index >= len(after):
                deltas.append(child)
            else:
                deltas.extend(structural_deltas(before[index], after[index], child))
        return deltas
    return [] if before == after else [pointer or "/"]


def value_at_pointer(document: object, pointer: str) -> object:
    value = document
    for raw_token in pointer.lstrip("/").split("/") if pointer != "/" else ():
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[token]
        elif isinstance(value, list):
            value = value[int(token)]
        else:
            raise D1RVerificationError(f"JSON_POINTER_UNRESOLVED:{pointer}")
    return value


def read_base_selector(repository_root: Path, base_commit: str) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "show", f"{base_commit}:{SELECTOR_RELATIVE_PATH.as_posix()}"],
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise D1RVerificationError("BASE_SELECTOR_UNAVAILABLE")
    try:
        document = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D1RVerificationError("BASE_SELECTOR_INVALID") from exc
    if not isinstance(document, dict):
        raise D1RVerificationError("BASE_SELECTOR_INVALID")
    return document


def d1_d2_python_diff_empty(repository_root: Path, base_commit: str) -> bool:
    result = subprocess.run(
        ["git", "diff", "--quiet", base_commit, "--", *READ_ONLY_D1_D2_PYTHON],
        cwd=repository_root,
        check=False,
    )
    return result.returncode == 0


def verify_refreeze(
    *,
    base_selector: dict[str, Any],
    candidate_selector: dict[str, Any],
    host_record_path: Path,
    uia_tree_path: Path,
    python_diff_empty: bool,
) -> dict[str, Any]:
    actual_deltas = structural_deltas(base_selector, candidate_selector)
    if set(actual_deltas) != ALLOWED_POINTERS:
        raise D1RVerificationError("SELECTOR_DELTA_OUTSIDE_ALLOWLIST")

    for pointer in REQUIRED_DEEP_EQUAL_POINTERS:
        if value_at_pointer(base_selector, pointer) != value_at_pointer(candidate_selector, pointer):
            raise D1RVerificationError(f"REQUIRED_POINTER_CHANGED:{pointer}")

    before_compatibility = base_selector.get("host_compatibility")
    after_compatibility = candidate_selector.get("host_compatibility")
    expected_before = {
        "product_name": PRODUCT_NAME,
        "product_version": PRODUCT_VERSION,
        "file_version": FILE_VERSION,
        "package_version": FROM_PACKAGE_VERSION,
    }
    expected_after = {**expected_before, "package_version": TO_PACKAGE_VERSION}
    if before_compatibility != expected_before:
        raise D1RVerificationError("BASE_HOST_COMPATIBILITY_UNEXPECTED")
    if after_compatibility != expected_after:
        raise D1RVerificationError("CANDIDATE_HOST_COMPATIBILITY_UNEXPECTED")
    if not python_diff_empty:
        raise D1RVerificationError("D1_D2_PYTHON_PRODUCTION_DIFF_NONEMPTY")

    try:
        host_record = json.loads(host_record_path.read_text(encoding="utf-8"))
        uia_tree = json.loads(uia_tree_path.read_text(encoding="utf-8"))
        host = host_record["codex"]
        tree_identity = uia_tree["host_identity"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError) as exc:
        raise D1RVerificationError("D1_EVIDENCE_INVALID") from exc

    host_environment_sha256 = sha256_file(host_record_path)
    uia_tree_sha256 = sha256_file(uia_tree_path)
    if candidate_selector["captured_from"]["host_environment"]["sha256"] != host_environment_sha256:
        raise D1RVerificationError("HOST_ENVIRONMENT_PROVENANCE_MISMATCH")
    if candidate_selector["captured_from"]["uia_tree"]["sha256"] != uia_tree_sha256:
        raise D1RVerificationError("UIA_TREE_PROVENANCE_MISMATCH")
    if uia_tree.get("host_record_sha256") != host_environment_sha256:
        raise D1RVerificationError("UIA_HOST_RECORD_PROVENANCE_MISMATCH")

    required_identity = {
        "product_name": PRODUCT_NAME,
        "product_version": PRODUCT_VERSION,
        "file_version": FILE_VERSION,
        "package_version": TO_PACKAGE_VERSION,
    }
    if host_record.get("status") != "HOST_DISCOVERED" or any(
        host.get(key) != value for key, value in required_identity.items()
    ):
        raise D1RVerificationError("HOST_EVIDENCE_IDENTITY_MISMATCH")
    if any(tree_identity.get(key) != value for key, value in required_identity.items()):
        raise D1RVerificationError("UIA_EVIDENCE_IDENTITY_MISMATCH")

    controls_before = canonical_sha256(base_selector["controls"])
    controls_after = canonical_sha256(candidate_selector["controls"])
    reset_before = canonical_sha256(base_selector["reset_contract"])
    reset_after = canonical_sha256(candidate_selector["reset_contract"])
    return {
        "schema_version": "r6o-h2-d1r-compatibility-refreeze-1",
        "status": "D1R_COMPATIBILITY_REFREEZE_PASS",
        "base_commit": BASE_COMMIT,
        "previous_package_version": FROM_PACKAGE_VERSION,
        "current_package_version": TO_PACKAGE_VERSION,
        "product_version": PRODUCT_VERSION,
        "file_version": FILE_VERSION,
        "allowed_selector_delta": sorted(ALLOWED_POINTERS),
        "actual_selector_delta": actual_deltas,
        "allowed_delta_only": True,
        "controls_sha256_before": controls_before,
        "controls_sha256_after": controls_after,
        "controls_unchanged": controls_before == controls_after,
        "reset_contract_sha256_before": reset_before,
        "reset_contract_sha256_after": reset_after,
        "reset_contract_unchanged": reset_before == reset_after,
        "selector_semantics_unchanged": True,
        "new_host_environment_sha256": host_environment_sha256,
        "new_uia_tree_sha256": uia_tree_sha256,
        "selector_provenance_valid": True,
        "d1_python_production_diff_empty": True,
        "d2_python_production_diff_empty": True,
    }


def _resolve(root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def main() -> int:
    args = parse_args()
    repository_root = args.repository_root.resolve()
    try:
        base_selector = read_base_selector(repository_root, args.base_commit)
        candidate_path = _resolve(repository_root, args.selectors)
        candidate_selector = json.loads(candidate_path.read_text(encoding="utf-8"))
        if not isinstance(candidate_selector, dict):
            raise D1RVerificationError("CANDIDATE_SELECTOR_INVALID")
        result = verify_refreeze(
            base_selector=base_selector,
            candidate_selector=candidate_selector,
            host_record_path=_resolve(repository_root, args.host_record),
            uia_tree_path=_resolve(repository_root, args.uia_tree),
            python_diff_empty=d1_d2_python_diff_empty(repository_root, args.base_commit),
        )
        result["base_commit"] = args.base_commit
        if args.output is not None:
            output_path = _resolve(repository_root, args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    except (D1RVerificationError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        code = str(exc) if isinstance(exc, D1RVerificationError) else "D1R_INPUT_INVALID"
        print(json.dumps({"status": "FAIL", "code": code}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
