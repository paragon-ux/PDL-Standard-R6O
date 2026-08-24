from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.h2.verify_d1r_compatibility_refreeze import (
    ALLOWED_POINTERS,
    BASE_COMMIT,
    D1RVerificationError,
    FILE_VERSION,
    FROM_PACKAGE_VERSION,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    READ_ONLY_D1_D2_PYTHON,
    TO_PACKAGE_VERSION,
    canonical_sha256,
    read_base_selector,
    structural_deltas,
    verify_refreeze,
)


ROOT = Path(__file__).resolve().parents[3]
SELECTORS_PATH = ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json"
HOST_RECORD_PATH = ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json"
UIA_TREE_PATH = ROOT / "r6o_evidence" / "H2-D1" / "codex-uia.json"
ACCEPTED_SELECTOR_CANONICAL_SHA256 = "7a6ba40dbaef5d7528047858548bab08bec2cd3fb4a2a86be093d17920eb375c"
ACCEPTED_PYTHON_SHA256 = {
    "r6o/host/codex/windows/discovery.py": "77d2af8e4c853d182752177b9c6f51402f8f5e8355553fbb1f1ff1d6a7670fa2",
    "r6o/host/codex/windows/uia.py": "79cfb3cff0b206f27b589f366a3fc73d32083b9d4cabbe2b4f74d68119333841",
    "r6o/host/codex/windows/binding.py": "eed2c7db45ff56ebad2ccec542dc795ce86a02652ac6ed1d33e38e7ab295413c",
    "r6o/host/codex/windows/placement.py": "8d01b1b2d2e6c77965decadcf2b34f27ee90728f72b8f0ce8ad770d0d1b43ddb",
}


def _candidate() -> dict[str, object]:
    return json.loads(SELECTORS_PATH.read_text(encoding="utf-8"))


def _accepted_base_from_candidate(candidate: dict[str, object]) -> dict[str, object]:
    base = deepcopy(candidate)
    base["host_compatibility"]["package_version"] = FROM_PACKAGE_VERSION  # type: ignore[index]
    base["captured_from"]["host_environment"]["sha256"] = (  # type: ignore[index]
        "7cf1b2219f38b2d7e1f610dd25467969c688b681b3ac0632041eff3978ce9db5"
    )
    base["captured_from"]["uia_tree"]["sha256"] = (  # type: ignore[index]
        "2687e9c4eb0ad2291dd79bd0abafb2cbd45e029077204e890b3893d8b0e71f22"
    )
    assert canonical_sha256(base) == ACCEPTED_SELECTOR_CANONICAL_SHA256
    return base


def _verify(candidate: dict[str, object]) -> dict[str, object]:
    return verify_refreeze(
        base_selector=_accepted_base_from_candidate(_candidate()),
        candidate_selector=candidate,
        host_record_path=HOST_RECORD_PATH,
        uia_tree_path=UIA_TREE_PATH,
        python_diff_empty=True,
    )


def test_current_refreeze_changes_exactly_the_three_authorized_metadata_leaves() -> None:
    candidate = _candidate()
    base = _accepted_base_from_candidate(candidate)
    result = _verify(candidate)
    assert set(structural_deltas(base, candidate)) == ALLOWED_POINTERS
    assert result["status"] == "D1R_COMPATIBILITY_REFREEZE_PASS"
    assert result["allowed_delta_only"] is True
    assert result["controls_unchanged"] is True
    assert result["reset_contract_unchanged"] is True
    assert result["selector_semantics_unchanged"] is True
    assert result["selector_provenance_valid"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        ("controls", "composer", "fallback", "NAME_ONLY"),
        ("reset_contract", "new_chat_action", "DIRECT_CLICK"),
        ("host_compatibility", "product_name", "ChatGPT"),
        ("host_compatibility", "product_version", "wrong"),
        ("host_compatibility", "file_version", "wrong"),
    ],
)
def test_refreeze_rejects_any_semantic_or_compatibility_delta(mutation: tuple[str, ...]) -> None:
    candidate = _candidate()
    target = candidate
    for key in mutation[:-2]:
        target = target[key]  # type: ignore[assignment,index]
    target[mutation[-2]] = mutation[-1]  # type: ignore[index]
    with pytest.raises(D1RVerificationError):
        _verify(candidate)


def test_refreeze_rejects_tampered_evidence_provenance() -> None:
    candidate = _candidate()
    candidate["captured_from"]["uia_tree"]["sha256"] = "0" * 64  # type: ignore[index]
    with pytest.raises(D1RVerificationError, match="UIA_TREE_PROVENANCE_MISMATCH"):
        _verify(candidate)


def test_refreeze_rejects_d1_or_d2_python_production_delta() -> None:
    candidate = _candidate()
    with pytest.raises(D1RVerificationError, match="D1_D2_PYTHON_PRODUCTION_DIFF_NONEMPTY"):
        verify_refreeze(
            base_selector=_accepted_base_from_candidate(candidate),
            candidate_selector=candidate,
            host_record_path=HOST_RECORD_PATH,
            uia_tree_path=UIA_TREE_PATH,
            python_diff_empty=False,
        )


def test_d1_d2_python_production_files_match_the_accepted_base() -> None:
    assert set(READ_ONLY_D1_D2_PYTHON) == set(ACCEPTED_PYTHON_SHA256)
    for relative_path, expected in ACCEPTED_PYTHON_SHA256.items():
        # Hash Git's canonical text identity so Windows CRLF checkout policy
        # cannot make unchanged production sources appear different on CI.
        canonical_bytes = (ROOT / relative_path).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(canonical_bytes).hexdigest() == expected


def test_refreeze_identity_is_closed_to_the_authorized_transition() -> None:
    candidate = _candidate()
    assert candidate["host_compatibility"] == {
        "product_name": PRODUCT_NAME,
        "product_version": PRODUCT_VERSION,
        "file_version": FILE_VERSION,
        "package_version": TO_PACKAGE_VERSION,
    }
    host = json.loads(HOST_RECORD_PATH.read_text(encoding="utf-8"))["codex"]
    assert {key: host[key] for key in candidate["host_compatibility"]} == candidate[  # type: ignore[index]
        "host_compatibility"
    ]


def test_verifier_loads_the_exact_accepted_selector_when_history_is_available() -> None:
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{BASE_COMMIT}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("accepted base commit is unavailable in this shallow CI checkout")
    assert canonical_sha256(read_base_selector(ROOT, BASE_COMMIT)) == ACCEPTED_SELECTOR_CANONICAL_SHA256


def test_d1r_verifier_has_portable_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "h2" / "verify_d1r_compatibility_refreeze.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_readme_contains_the_current_d1r_qualification_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    assert "codex/h2-d1r-host-compatibility-refreeze" in readme
    assert "D1R COMPATIBILITY REFREEZE VERIFIED" in readme
    assert "verify_d1r_compatibility_refreeze.py" in readme
    assert "--evidence-dir r6o_evidence\\H2-D1R\\d2-actual-host" in readme
    assert "26.818.3698.0 -> 26.818.5229.0" in readme
    assert "only the three authorized selector metadata leaves" in normalized
