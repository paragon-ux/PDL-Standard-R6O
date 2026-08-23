from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from r6o.host.codex.windows.discovery import (
    HostCandidate,
    HostDiscoveryError,
    select_unique_codex_host,
    validate_environment_record,
)
from r6o.host.codex.windows.uia import (
    UiaContractError,
    activate_host,
    composer_empty_observation,
    dump_uia_tree,
    fresh_chat_observation,
    load_selectors,
    matches_ancestor_chain,
    matches_record,
)
import scripts.h2.reset_codex_test_session as reset_module
import scripts.h2.inspect_codex_host as inspect_module

ROOT = Path(__file__).resolve().parents[3]
SELECTORS_PATH = ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json"
HOST_RECORD_PATH = ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json"
UIA_DUMP_PATH = ROOT / "r6o_evidence" / "H2-D1" / "codex-uia.json"
RESET_LOG_PATH = ROOT / "r6o_evidence" / "H2-D1" / "reset-session.log"


def candidate(**overrides: object) -> HostCandidate:
    values: dict[str, object] = {
        "hwnd": 100,
        "pid": 200,
        "executable": r"C:\Program Files\WindowsApps\OpenAI.Codex_1.0.0.0_x64__test\app\ChatGPT.exe",
        "product_name": "Codex",
        "product_version": "1.2.3.4",
        "file_version": "1.2.3.4",
        "package_version": "1.0.0.0",
        "title": "ChatGPT",
        "class_name": "Chrome_WidgetWin_1",
        "visible": True,
    }
    values.update(overrides)
    return HostCandidate(**values)  # type: ignore[arg-type]


def test_discovery_uses_product_metadata_not_generic_title() -> None:
    selected = select_unique_codex_host(
        [
            candidate(hwnd=1, pid=10, product_name="ChatGPT", title="Codex"),
            candidate(hwnd=2, pid=20, product_name="Codex", title="ChatGPT"),
        ],
        current_pid=999,
    )
    assert selected.hwnd == 2


def test_discovery_excludes_untitled_auxiliary_codex_windows() -> None:
    selected = select_unique_codex_host(
        [candidate(hwnd=1, title=""), candidate(hwnd=2, title="ChatGPT")],
        current_pid=999,
    )
    assert selected.hwnd == 2


@pytest.mark.parametrize(
    ("windows", "current_pid", "code", "candidate_count"),
    [
        ([], 999, "HOST_NOT_FOUND", 0),
        ([candidate(pid=999)], 999, "HOST_NOT_FOUND", 0),
        ([candidate(visible=False)], 999, "HOST_NOT_FOUND", 0),
        ([candidate(product_version="")], 999, "HOST_NOT_FOUND", 0),
        ([candidate(file_version="   ")], 999, "HOST_NOT_FOUND", 0),
        ([candidate(title="")], 999, "HOST_NOT_FOUND", 0),
        ([candidate(hwnd=1), candidate(hwnd=2, pid=201)], 999, "HOST_AMBIGUOUS", 2),
    ],
)
def test_discovery_fails_closed(
    windows: list[HostCandidate], current_pid: int, code: str, candidate_count: int
) -> None:
    with pytest.raises(HostDiscoveryError) as raised:
        select_unique_codex_host(windows, current_pid=current_pid)
    assert raised.value.code == code
    assert len(raised.value.candidates) == candidate_count


class FakeWrapper:
    def __init__(
        self,
        *,
        control_type: str,
        name: str = "",
        automation_id: str = "",
        class_name: str = "",
        visible: bool = True,
        enabled: bool = True,
        value: str = "",
        children: list["FakeWrapper"] | None = None,
        runtime_id: tuple[int, ...] = (),
    ) -> None:
        self.element_info = SimpleNamespace(
            control_type=control_type,
            name=name,
            automation_id=automation_id,
            class_name=class_name,
            runtime_id=runtime_id,
        )
        self._visible = visible
        self._enabled = enabled
        self._children = children or []
        self.iface_value = SimpleNamespace(CurrentValue=value)
        self.handle = runtime_id[0] if runtime_id else 1
        self.focus_calls = 0

    def is_visible(self) -> bool:
        return self._visible

    def is_enabled(self) -> bool:
        return self._enabled

    def rectangle(self) -> SimpleNamespace:
        return SimpleNamespace(left=0, top=0, right=10, bottom=10)

    def set_focus(self) -> None:
        self.focus_calls += 1

    def children(self) -> list["FakeWrapper"]:
        return self._children

    def descendants(self, control_type: str | None = None) -> list["FakeWrapper"]:
        result: list[FakeWrapper] = []
        for child in self._children:
            if control_type is None or child.element_info.control_type == control_type:
                result.append(child)
            result.extend(item for item in child.descendants(control_type) if item not in result)
        return result


def test_uia_dump_redacts_dynamic_names_and_never_reads_values() -> None:
    root = FakeWrapper(
        control_type="Window",
        runtime_id=(1,),
        children=[
            FakeWrapper(control_type="Button", name="New chat", runtime_id=(2,)),
            FakeWrapper(control_type="Text", name="private conversation text", value="secret", runtime_id=(3,)),
        ],
    )
    document = dump_uia_tree(root)
    assert document["node_count"] == 3
    assert document["nodes"][1]["name"] == "New chat"
    private = document["nodes"][2]
    assert private["name"] is None and private["name_redacted"] is True
    assert private["name_length"] == len("private conversation text")
    assert "name_sha256" not in private
    assert all("value" not in node for node in document["nodes"])
    assert "secret" not in json.dumps(document)


def test_composer_empty_contract_distinguishes_placeholder_from_actual_draft() -> None:
    contract = {"accessibility_name": "Do anything", "uia_values": ["\nDo anything"]}
    empty = FakeWrapper(
        control_type="Edit",
        name="Do anything",
        value="\nDo anything",
        children=[FakeWrapper(control_type="Text", name="Do anything")],
    )
    assert composer_empty_observation(empty, contract)["empty"] is True
    draft = FakeWrapper(
        control_type="Edit",
        name="Do anything",
        value="draft",
        children=[FakeWrapper(control_type="Text", name="private draft")],
    )
    observation = composer_empty_observation(draft, contract)
    assert observation["empty"] is False
    assert observation["descendant_text_lengths"] == [len("private draft")]
    assert "private draft" not in json.dumps(observation)

    literal_placeholder_draft = FakeWrapper(
        control_type="Edit",
        name="Do anything",
        value="Do anything",
        children=[FakeWrapper(control_type="Text", name="Do anything")],
    )
    assert composer_empty_observation(literal_placeholder_draft, contract)["empty"] is False


def test_fresh_chat_requires_home_surface_and_zero_visible_turns() -> None:
    selector = {
        "control_type": "Group",
        "automation_id": {"match": "ABSENT"},
        "name": {"match": "ABSENT"},
        "class_name": {"match": "TOKEN", "value": "[container-name:home-main-content]"},
        "visible": True,
        "enabled": True,
        "ancestor_chain": [],
        "fallback": "PROHIBITED",
    }
    contract = {
        "surface_selector": selector,
        "visible_turn_group_class": "group flex min-w-0 flex-col",
    }
    home = FakeWrapper(control_type="Group", class_name="flex [container-name:home-main-content]")
    region = FakeWrapper(control_type="Group", children=[home])
    assert fresh_chat_observation(region, contract)["fresh"] is True
    turn = FakeWrapper(control_type="Group", class_name="group flex min-w-0 flex-col")
    region_with_turn = FakeWrapper(control_type="Group", children=[home, turn])
    assert fresh_chat_observation(region_with_turn, contract)["fresh"] is False
    assert fresh_chat_observation(FakeWrapper(control_type="Group"), contract)["fresh"] is False


def test_activate_host_requires_actual_foreground_window() -> None:
    root = FakeWrapper(
        control_type="Window",
        runtime_id=(100,),
        children=[FakeWrapper(control_type="Group", runtime_id=(101,))],
    )
    with pytest.raises(UiaContractError, match="HOST_FOREGROUND_UNVERIFIED"):
        activate_host(root, timeout=0.01, poll_interval=0, foreground_getter=lambda: 999)
    activate_host(root, timeout=0.01, poll_interval=0, foreground_getter=lambda: 100)
    assert root.focus_calls == 2


def test_environment_capture_activates_host_before_measuring(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    root = FakeWrapper(control_type="Window", runtime_id=(100,))
    candidate_value = candidate(hwnd=100)
    record = {"codex": {}}

    monkeypatch.setattr(
        inspect_module,
        "connect_to_host",
        lambda hwnd: (calls.append(f"connect:{hwnd}") or object(), root),
    )
    monkeypatch.setattr(inspect_module, "activate_host", lambda wrapper: calls.append("activate"))
    monkeypatch.setattr(
        inspect_module,
        "build_environment_record",
        lambda selected: calls.append(f"measure:{selected.hwnd}") or record,
    )
    monkeypatch.setattr(inspect_module, "validate_environment_record", lambda document: calls.append("validate"))

    result = inspect_module.capture_environment_record(candidate_value)
    assert calls == ["connect:100", "activate", "measure:100", "validate"]
    assert result["codex"]["uia_connection"]["connected"] is True


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ancestor_records(node: dict[str, object], nodes: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    ancestors: list[dict[str, object]] = []
    parent_id = node["parent_id"]
    while parent_id is not None:
        parent = nodes[str(parent_id)]
        ancestors.append(parent)
        parent_id = parent["parent_id"]
    return ancestors


def test_frozen_selectors_are_derived_from_the_recorded_actual_tree() -> None:
    selectors = load_selectors(SELECTORS_PATH)
    tree = json.loads(UIA_DUMP_PATH.read_text(encoding="utf-8"))
    nodes = {node["node_id"]: node for node in tree["nodes"]}
    for label in ("new_chat", "composer", "primary_content_region"):
        selector = selectors["controls"][label]
        matches = [
            node
            for node in tree["nodes"]
            if matches_record(node, selector)
            and matches_ancestor_chain(_ancestor_records(node, nodes), selector["ancestor_chain"])
        ]
        assert len(matches) == 1, (label, len(matches))
    assert selectors["controls"]["host_submit"] == {
        "usage": "PROHIBITED_BY_H2_A1_OPTION_A",
        "selector": None,
        "fallback": "PROHIBITED",
    }
    fresh_selector = selectors["reset_contract"]["fresh_chat"]["surface_selector"]
    fresh_matches = [node for node in tree["nodes"] if matches_record(node, fresh_selector)]
    assert len(fresh_matches) == 1


def _selector_mutations(document: dict[str, object]) -> list[object]:
    mutations: list[object] = [[], None]

    missing_control = deepcopy(document)
    del missing_control["controls"]["composer"]  # type: ignore[index]
    mutations.append(missing_control)

    native_submit = deepcopy(document)
    native_submit["controls"]["host_submit"]["selector"] = {}  # type: ignore[index]
    mutations.append(native_submit)

    fallback = deepcopy(document)
    fallback["controls"]["composer"]["fallback"] = "NAME_ONLY"  # type: ignore[index]
    mutations.append(fallback)

    invalid_constraint = deepcopy(document)
    invalid_constraint["controls"]["composer"]["class_name"] = {"match": "TOKEN"}  # type: ignore[index]
    mutations.append(invalid_constraint)

    invalid_ancestor = deepcopy(document)
    invalid_ancestor["controls"]["new_chat"]["ancestor_chain"][0]["relation"] = "NEARBY"  # type: ignore[index]
    mutations.append(invalid_ancestor)

    guessed_placeholder = deepcopy(document)
    guessed_placeholder["reset_contract"]["composer_empty"]["uia_values"] = ["something like empty"]  # type: ignore[index]
    mutations.append(guessed_placeholder)

    weak_fresh_state = deepcopy(document)
    weak_fresh_state["reset_contract"]["fresh_chat"]["fresh_rule"] = "TITLE_ONLY"  # type: ignore[index]
    mutations.append(weak_fresh_state)

    wrong_product = deepcopy(document)
    wrong_product["host_compatibility"]["product_name"] = "ChatGPT"  # type: ignore[index]
    mutations.append(wrong_product)

    wrong_hash = deepcopy(document)
    wrong_hash["captured_from"]["uia_tree"]["sha256"] = "0"  # type: ignore[index]
    mutations.append(wrong_hash)
    return mutations


def test_selector_document_validation_is_fail_closed(tmp_path: Path) -> None:
    document = json.loads(SELECTORS_PATH.read_text(encoding="utf-8"))
    for index, mutation in enumerate(_selector_mutations(document)):
        path = tmp_path / f"mutation-{index}.json"
        path.write_text(json.dumps(mutation), encoding="utf-8")
        with pytest.raises(UiaContractError):
            load_selectors(path)


def test_selector_runtime_rejects_tampered_provenance(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    host_copy = repository_root / "r6o_evidence" / "H2-D1" / "host-environment.json"
    tree_copy = repository_root / "r6o_evidence" / "H2-D1" / "codex-uia.json"
    host_copy.parent.mkdir(parents=True)
    host_copy.write_bytes(HOST_RECORD_PATH.read_bytes())
    tree_copy.write_bytes(UIA_DUMP_PATH.read_bytes())
    selector_copy = tmp_path / "selectors.json"
    selector_copy.write_bytes(SELECTORS_PATH.read_bytes())

    load_selectors(selector_copy, repository_root=repository_root)
    host_copy.write_bytes(host_copy.read_bytes() + b" ")
    with pytest.raises(UiaContractError, match="SELECTOR_PROVENANCE_MISMATCH:host_environment"):
        load_selectors(selector_copy, repository_root=repository_root)


def test_evidence_identity_hashes_and_required_environment_fields_are_frozen() -> None:
    selectors = load_selectors(SELECTORS_PATH)
    assert selectors["captured_from"]["host_environment"]["sha256"] == _sha256(HOST_RECORD_PATH)
    assert selectors["captured_from"]["uia_tree"]["sha256"] == _sha256(UIA_DUMP_PATH)
    host = json.loads(HOST_RECORD_PATH.read_text(encoding="utf-8"))
    assert host["schema_version"] == "r6o-h2-d1-host-environment-1"
    assert host["status"] == "HOST_DISCOVERED"
    assert set(host["windows"]) == {"edition", "version", "build", "architecture"}
    required_codex = {
        "hwnd",
        "pid",
        "executable",
        "product_name",
        "product_version",
        "file_version",
        "package_version",
        "window_title",
        "window_class",
        "window_rectangle",
        "client_rectangle",
        "monitor",
        "dpi",
        "scale",
        "uia_connection",
    }
    assert set(host["codex"]) == required_codex
    assert host["codex"]["product_name"] == "Codex"
    assert PureWindowsPath(host["codex"]["executable"]).is_absolute()
    assert host["codex"]["uia_connection"]["connected"] is True
    assert tree_host_hash() == _sha256(HOST_RECORD_PATH)
    validate_environment_record(host)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("windows", "edition"), ""),
        (("windows", "build"), 0),
        (("windows", "build"), True),
        (("codex", "hwnd"), True),
        (("codex", "dpi"), 0),
        (("codex", "dpi"), True),
        (("codex", "scale"), float("nan")),
        (("codex", "scale"), True),
        (("codex", "window_rectangle", "width"), 0),
        (("codex", "window_rectangle", "width"), True),
        (("codex", "monitor", "handle"), True),
        (("codex", "monitor", "id"), ""),
    ],
)
def test_environment_record_rejects_missing_or_invalid_measurement(
    path: tuple[str, ...], value: object
) -> None:
    document = json.loads(HOST_RECORD_PATH.read_text(encoding="utf-8"))
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(HostDiscoveryError, match="HOST_ENVIRONMENT_INVALID"):
        validate_environment_record(document)


def tree_host_hash() -> str:
    tree = json.loads(UIA_DUMP_PATH.read_text(encoding="utf-8"))
    assert tree["schema_version"] == "r6o-h2-d1-codex-uia-1"
    assert tree["redaction_policy"]["uia_value_pattern_recorded"] is False
    assert all(node.get("name") in {None, "", "Codex", "New chat", "Scheduled task folders"} for node in tree["nodes"])
    return tree["host_record_sha256"]


def test_host_dependencies_are_exactly_pinned() -> None:
    assert (ROOT / "requirements-r6o2-host.txt").read_text(encoding="utf-8").splitlines() == [
        "pywinauto==0.6.9",
        "pywin32==312",
    ]


def test_d1_hashed_evidence_uses_lf_checkout_identity() -> None:
    paths = [
        "r6o/host/codex/windows/selectors.json",
        "r6o_evidence/H2-D1/host-environment.json",
        "r6o_evidence/H2-D1/codex-uia.json",
        "r6o_evidence/H2-D1/reset-session.log",
    ]
    result = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    for path in paths:
        assert f"{path}: text: set" in result.stdout
        assert f"{path}: eol: lf" in result.stdout


def test_required_reset_log_is_not_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", str(RESET_LOG_PATH.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr


def test_reset_failure_codes_preserve_contract_cause() -> None:
    assert reset_module._failure_code(HostDiscoveryError("HOST_NOT_FOUND")) == "HOST_NOT_FOUND"
    assert (
        reset_module._failure_code(UiaContractError("SELECTOR_DOCUMENT_INVALID"))
        == "SELECTOR_DOCUMENT_INVALID"
    )
    assert reset_module._failure_code(KeyError("controls")) == "RESET_CONTRACT_KEY_MISSING"
    assert reset_module._failure_code(OSError("private path")) == "HOST_IO_ERROR"
    assert reset_module._failure_code(RuntimeError("private runtime detail")) == "HOST_RESET_RUNTIME_ERROR"


def test_reset_runtime_failure_overwrites_stale_success_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "reset-session.log"
    output.write_text('{"status":"CODEX_TEST_SESSION_READY"}\n', encoding="utf-8")
    monkeypatch.setattr(
        reset_module,
        "parse_args",
        lambda: SimpleNamespace(selectors=SELECTORS_PATH, output=output, timeout_seconds=0.01),
    )
    monkeypatch.setattr(reset_module, "load_selectors", lambda path: (_ for _ in ()).throw(RuntimeError()))
    assert reset_module.main() == 1
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["status"] == "FAIL"
    assert record["code"] == "HOST_RESET_RUNTIME_ERROR"


def test_reset_requires_verified_composer_focus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "reset-session.log"
    selected = candidate(hwnd=100)
    selectors = {
        "host_compatibility": {
            "product_name": selected.product_name,
            "product_version": selected.product_version,
            "file_version": selected.file_version,
            "package_version": selected.package_version,
        },
        "controls": {"composer": {}, "new_chat": {}, "primary_content_region": {}},
        "reset_contract": {"composer_empty": {}, "fresh_chat": {}},
    }
    composer = SimpleNamespace(set_focus=lambda: None, has_keyboard_focus=lambda: False)
    new_chat = SimpleNamespace(invoke=lambda: None)
    monkeypatch.setattr(
        reset_module,
        "parse_args",
        lambda: SimpleNamespace(selectors=SELECTORS_PATH, output=output, timeout_seconds=0.001),
    )
    monkeypatch.setattr(reset_module, "load_selectors", lambda path: selectors)
    monkeypatch.setattr(reset_module, "discover_codex_host", lambda: selected)
    monkeypatch.setattr(reset_module, "connect_to_host", lambda hwnd: (object(), object()))
    monkeypatch.setattr(reset_module, "activate_host", lambda root: None)
    monkeypatch.setattr(
        reset_module,
        "resolve_control",
        lambda root, selector, *, label: composer if label == "composer" else new_chat if label == "new_chat" else object(),
    )
    monkeypatch.setattr(reset_module, "composer_empty_observation", lambda wrapper, contract: {"empty": True})
    monkeypatch.setattr(reset_module, "fresh_chat_observation", lambda wrapper, contract: {"fresh": True})
    assert reset_module.main() == 1
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["status"] == "FAIL"
    assert record["code"] == "FRESH_CHAT_NOT_PROVED"
    assert record["details"]["last_observer_error"] == "COMPOSER_FOCUS_UNVERIFIED"


def test_successful_reset_evidence_is_tracked_and_bound_to_current_host() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(RESET_LOG_PATH.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, "required reset-session.log is not tracked"
    record = json.loads(RESET_LOG_PATH.read_text(encoding="utf-8"))
    host = json.loads(HOST_RECORD_PATH.read_text(encoding="utf-8"))["codex"]
    assert record["schema_version"] == "r6o-h2-d1-reset-log-1"
    assert record["status"] == "CODEX_TEST_SESSION_READY"
    assert record["new_chat_action"] == "UIA_INVOKE_PATTERN"
    assert record["selectors_sha256"] == _sha256(SELECTORS_PATH)
    assert record["composer_before"]["empty"] is True
    assert record["composer_after"]["empty"] is True
    assert record["fresh_chat"]["fresh"] is True
    assert record["composer_focused_after_reset"] is True
    for key in ("hwnd", "pid", "product_name", "product_version", "file_version", "package_version"):
        assert record["host"][key] == host[key]


@pytest.mark.parametrize(
    "script",
    [
        "inspect_codex_host.py",
        "dump_codex_uia.py",
        "reset_codex_test_session.py",
    ],
)
def test_host_scripts_have_portable_help(script: str) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "h2" / script), "--help"],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_host_binding_does_not_cross_protected_semantic_boundary() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "r6o" / "host" / "codex" / "windows").glob("*.py"))
    ).lower()
    for forbidden in (
        "mechanicalcontroller",
        "sessionengine",
        "workeradapter",
        "reviewdecision",
        "r6o.viewmodel",
        "r6o.model_binding",
        "workspace filesystem",
    ):
        assert forbidden not in sources
