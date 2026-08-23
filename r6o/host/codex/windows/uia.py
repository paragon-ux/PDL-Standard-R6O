from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

STABLE_CHROME_NAMES = frozenset({"Codex", "New chat", "Scheduled task folders"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class UiaContractError(RuntimeError):
    pass


def connect_to_host(hwnd: int) -> tuple[Any, Any]:
    try:
        from pywinauto import Application
    except ImportError as exc:  # pragma: no cover - Windows dependency failure
        raise UiaContractError("HOST_DEPENDENCY_MISSING") from exc
    app = Application(backend="uia").connect(handle=hwnd)
    return app, app.window(handle=hwnd)


def activate_host(
    root: Any,
    *,
    timeout: float = 10.0,
    foreground_getter: Any | None = None,
    poll_interval: float = 0.2,
) -> None:
    if foreground_getter is None:
        try:
            import win32con
            import win32gui
        except ImportError as exc:
            raise UiaContractError("HOST_DEPENDENCY_MISSING") from exc

        foreground_getter = win32gui.GetForegroundWindow
        if win32gui.IsIconic(root.handle):
            win32gui.ShowWindow(root.handle, win32con.SW_RESTORE)
    root.set_focus()
    deadline = time.monotonic() + timeout
    uia_ready = False
    while time.monotonic() < deadline:
        try:
            uia_ready = bool(root.is_visible() and root.is_enabled() and root.descendants())
            if uia_ready and int(foreground_getter()) == int(root.handle):
                return
        except Exception:
            pass
        time.sleep(poll_interval)
    if uia_ready:
        raise UiaContractError("HOST_FOREGROUND_UNVERIFIED")
    raise UiaContractError("HOST_UIA_UNAVAILABLE")


def _safe(callable_value: Any, default: Any = None) -> Any:
    try:
        return callable_value()
    except Exception:
        return default


def _rect(wrapper: Any) -> dict[str, int] | None:
    rectangle = _safe(wrapper.rectangle)
    if rectangle is None:
        return None
    return {
        "left": int(rectangle.left),
        "top": int(rectangle.top),
        "right": int(rectangle.right),
        "bottom": int(rectangle.bottom),
    }


def wrapper_record(wrapper: Any) -> dict[str, Any]:
    info = wrapper.element_info
    return {
        "control_type": str(info.control_type or ""),
        "automation_id": str(info.automation_id or ""),
        "class_name": str(info.class_name or ""),
        "name": str(info.name or ""),
        "visible": bool(_safe(wrapper.is_visible, False)),
        "enabled": bool(_safe(wrapper.is_enabled, False)),
        "rectangle": _rect(wrapper),
    }


def _public_name(name: str) -> dict[str, Any]:
    if not name:
        return {"name": "", "name_redacted": False, "name_length": 0}
    if name in STABLE_CHROME_NAMES:
        return {"name": name, "name_redacted": False, "name_length": len(name)}
    return {
        "name": None,
        "name_redacted": True,
        "name_length": len(name),
    }


def dump_uia_tree(root: Any) -> dict[str, Any]:
    """Dump structure and selector fields without recording conversation/composer text."""

    nodes: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def identity(wrapper: Any) -> tuple[Any, ...]:
        info = wrapper.element_info
        runtime_id = _safe(lambda: tuple(info.runtime_id), ())
        return runtime_id or (wrapper.handle, info.control_type, info.automation_id, info.name)

    def visit(wrapper: Any, parent_id: str | None, level: int) -> None:
        marker = identity(wrapper)
        if marker in seen:
            return
        seen.add(marker)
        raw = wrapper_record(wrapper)
        node_id = f"N{len(nodes):04d}"
        name = raw.pop("name")
        node = {"node_id": node_id, "parent_id": parent_id, "level": level, **raw, **_public_name(name)}
        nodes.append(node)
        for child in _safe(wrapper.children, []) or []:
            visit(child, node_id, level + 1)

    visit(root, None, 0)
    return {
        "schema_version": "r6o-h2-d1-codex-uia-1",
        "redaction_policy": {
            "uia_value_pattern_recorded": False,
            "dynamic_names_recorded": False,
            "stable_chrome_name_allowlist": sorted(STABLE_CHROME_NAMES),
        },
        "node_count": len(nodes),
        "nodes": nodes,
    }


def _match_property(actual: str, constraint: dict[str, Any] | None) -> bool:
    if constraint is None:
        return True
    mode = constraint.get("match")
    if mode == "ABSENT":
        return actual == ""
    if mode == "EXACT":
        return actual == constraint.get("value")
    if mode == "TOKEN":
        return constraint.get("value") in actual.split()
    if mode == "IGNORED_DYNAMIC":
        return True
    raise UiaContractError(f"SELECTOR_CONSTRAINT_INVALID:{mode}")


def matches_record(record: dict[str, Any], selector: dict[str, Any]) -> bool:
    return (
        record.get("control_type") == selector.get("control_type")
        and _match_property(str(record.get("automation_id") or ""), selector.get("automation_id"))
        and _match_property(str(record.get("name") or ""), selector.get("name"))
        and _match_property(str(record.get("class_name") or ""), selector.get("class_name"))
        and (not selector.get("visible", True) or record.get("visible") is True)
        and (not selector.get("enabled", True) or record.get("enabled") is True)
    )


def _ancestor_records(wrapper: Any) -> list[dict[str, Any]]:
    ancestors: list[dict[str, Any]] = []
    seen: set[int] = set()
    current = wrapper
    while True:
        parent = _safe(current.parent)
        if parent is None:
            return ancestors
        marker = id(parent.element_info)
        if marker in seen:
            return ancestors
        seen.add(marker)
        ancestors.append(wrapper_record(parent))
        current = parent


def matches_ancestor_chain(ancestors: list[dict[str, Any]], constraints: list[dict[str, Any]]) -> bool:
    cursor = 0
    for constraint in constraints:
        relation = constraint.get("relation")
        selector = constraint.get("selector")
        if not isinstance(selector, dict):
            raise UiaContractError("SELECTOR_ANCESTOR_INVALID")
        if relation == "DIRECT_PARENT":
            if cursor >= len(ancestors) or not matches_record(ancestors[cursor], selector):
                return False
            cursor += 1
            continue
        if relation != "ANCESTOR":
            raise UiaContractError("SELECTOR_ANCESTOR_RELATION_INVALID")
        while cursor < len(ancestors) and not matches_record(ancestors[cursor], selector):
            cursor += 1
        if cursor >= len(ancestors):
            return False
        cursor += 1
    return True


def resolve_control(root: Any, selector: dict[str, Any], *, label: str) -> Any:
    if selector.get("fallback") != "PROHIBITED":
        raise UiaContractError(f"SELECTOR_FALLBACK_NOT_PROHIBITED:{label}")
    matches = []
    for wrapper in root.descendants():
        if matches_record(wrapper_record(wrapper), selector) and matches_ancestor_chain(
            _ancestor_records(wrapper), selector.get("ancestor_chain", [])
        ):
            matches.append(wrapper)
    if len(matches) != 1:
        raise UiaContractError(f"SELECTOR_CARDINALITY:{label}:{len(matches)}")
    return matches[0]


def composer_content_lengths(composer: Any, *, placeholder: str | None = None) -> list[int]:
    """Return lengths of actual editor descendants, never their text."""

    lengths: list[int] = []
    for descendant in composer.descendants():
        if descendant.element_info.control_type != "Text" or not _safe(descendant.is_visible, False):
            continue
        text = str(descendant.element_info.name or "").strip()
        if text and text != placeholder:
            lengths.append(len(text))
    return lengths


def composer_empty_observation(composer: Any, contract: dict[str, Any]) -> dict[str, Any]:
    expected_name = contract.get("accessibility_name")
    expected_values = contract.get("uia_values")
    if not isinstance(expected_name, str) or not isinstance(expected_values, list) or not all(
        isinstance(value, str) for value in expected_values
    ):
        raise UiaContractError("COMPOSER_EMPTY_CONTRACT_INVALID")
    name = str(composer.element_info.name or "")
    value = str(_safe(lambda: composer.iface_value.CurrentValue, ""))
    empty_markers_match = name == expected_name and value in expected_values
    # Chromium may expose the visual placeholder as a Text descendant. It is
    # presentation, not submitted content, and is ignored only when both
    # independent empty markers match. A literal user draft changes the value.
    content_lengths = composer_content_lengths(
        composer,
        placeholder=expected_name if empty_markers_match else None,
    )
    return {
        "empty": empty_markers_match and not content_lengths,
        "accessibility_name_matches": name == expected_name,
        "uia_value_matches": value in expected_values,
        "descendant_text_count": len(content_lengths),
        "descendant_text_lengths": content_lengths,
    }


def fresh_chat_observation(region: Any, contract: dict[str, Any]) -> dict[str, Any]:
    surface_selector = contract.get("surface_selector")
    turn_class = contract.get("visible_turn_group_class")
    if not isinstance(surface_selector, dict) or not isinstance(turn_class, str) or not turn_class:
        raise UiaContractError("FRESH_CHAT_CONTRACT_INVALID")
    surface_constraints = surface_selector.get("ancestor_chain", [])
    surface_matches = [
        wrapper
        for wrapper in region.descendants()
        if matches_record(wrapper_record(wrapper), surface_selector)
        and (
            not surface_constraints
            or matches_ancestor_chain(_ancestor_records(wrapper), surface_constraints)
        )
    ]
    visible_turns = [
        wrapper
        for wrapper in region.descendants(control_type="Group")
        if wrapper.is_visible() and str(wrapper.element_info.class_name or "") == turn_class
    ]
    return {
        "fresh": len(surface_matches) == 1 and not visible_turns,
        "fresh_home_surface_match_count": len(surface_matches),
        "visible_turn_group_count": len(visible_turns),
    }


def load_selectors(path: Path, *, repository_root: Path | None = None) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UiaContractError("SELECTOR_DOCUMENT_UNREADABLE") from exc
    if not isinstance(document, dict) or document.get("schema_version") != "r6o-h2-d1-selectors-1":
        raise UiaContractError("SELECTOR_DOCUMENT_INVALID")
    if set(document) != {"schema_version", "captured_from", "host_compatibility", "controls", "reset_contract"}:
        raise UiaContractError("SELECTOR_DOCUMENT_KEYS_INVALID")

    captured = document.get("captured_from")
    if not isinstance(captured, dict) or set(captured) != {"host_environment", "uia_tree"}:
        raise UiaContractError("SELECTOR_PROVENANCE_INVALID")
    expected_paths = {
        "host_environment": "r6o_evidence/H2-D1/host-environment.json",
        "uia_tree": "r6o_evidence/H2-D1/codex-uia.json",
    }
    for label, expected_path in expected_paths.items():
        record = captured.get(label)
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256"}
            or record.get("path") != expected_path
            or not isinstance(record.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
        ):
            raise UiaContractError(f"SELECTOR_PROVENANCE_INVALID:{label}")
        root = (repository_root or REPOSITORY_ROOT).resolve()
        evidence_path = (root / expected_path).resolve()
        try:
            evidence_path.relative_to(root)
        except ValueError as exc:
            raise UiaContractError(f"SELECTOR_PROVENANCE_INVALID:{label}") from exc
        try:
            actual_sha256 = sha256_file(evidence_path)
        except OSError as exc:
            raise UiaContractError(f"SELECTOR_PROVENANCE_UNREADABLE:{label}") from exc
        if actual_sha256 != record["sha256"]:
            raise UiaContractError(f"SELECTOR_PROVENANCE_MISMATCH:{label}")

    compatibility = document.get("host_compatibility")
    if (
        not isinstance(compatibility, dict)
        or set(compatibility) != {"product_name", "product_version", "file_version", "package_version"}
        or compatibility.get("product_name") != "Codex"
        or any(not isinstance(compatibility.get(key), str) or not compatibility[key] for key in compatibility)
    ):
        raise UiaContractError("SELECTOR_HOST_COMPATIBILITY_INVALID")

    controls = document.get("controls")
    required = {"new_chat", "composer", "host_submit", "primary_content_region"}
    if not isinstance(controls, dict) or set(controls) != required:
        raise UiaContractError("SELECTOR_CONTROL_SET_INVALID")
    for label in ("new_chat", "composer", "primary_content_region"):
        selector = controls[label]
        _validate_selector(selector, label=label)
    host_submit = controls["host_submit"]
    if host_submit != {
        "usage": "PROHIBITED_BY_H2_A1_OPTION_A",
        "selector": None,
        "fallback": "PROHIBITED",
    }:
        raise UiaContractError("HOST_SUBMIT_SELECTOR_INVALID")

    reset = document.get("reset_contract")
    if not isinstance(reset, dict) or set(reset) != {"new_chat_action", "composer_empty", "fresh_chat"}:
        raise UiaContractError("RESET_CONTRACT_INVALID")
    if reset.get("new_chat_action") != "UIA_INVOKE_PATTERN":
        raise UiaContractError("RESET_ACTION_INVALID")
    composer_empty = reset.get("composer_empty")
    if (
        not isinstance(composer_empty, dict)
        or set(composer_empty) != {"accessibility_name", "uia_values", "actual_text_rule"}
        or composer_empty.get("accessibility_name") != "Do anything"
        or composer_empty.get("uia_values") != ["\nDo anything"]
        or composer_empty.get("actual_text_rule") != "ZERO_VISIBLE_TEXT_DESCENDANTS"
    ):
        raise UiaContractError("COMPOSER_EMPTY_CONTRACT_INVALID")
    fresh = reset.get("fresh_chat")
    if (
        not isinstance(fresh, dict)
        or set(fresh) != {"surface_selector", "visible_turn_group_class", "fresh_rule"}
        or fresh.get("visible_turn_group_class") != "group flex min-w-0 flex-col"
        or fresh.get("fresh_rule") != "EXACTLY_ONE_VISIBLE_HOME_SURFACE_AND_ZERO_VISIBLE_TURN_GROUPS"
    ):
        raise UiaContractError("FRESH_CHAT_CONTRACT_INVALID")
    _validate_selector(fresh.get("surface_selector"), label="fresh_chat.surface_selector")

    serialized = json.dumps(document, sort_keys=True).casefold()
    for forbidden in ("tbd", "implementation decides", "where applicable", "something like"):
        if forbidden in serialized:
            raise UiaContractError("SELECTOR_PLACEHOLDER_PROHIBITED")
    return document


def _validate_property_constraint(constraint: Any, *, label: str) -> None:
    if not isinstance(constraint, dict) or "match" not in constraint:
        raise UiaContractError(f"SELECTOR_CONSTRAINT_INVALID:{label}")
    mode = constraint.get("match")
    if mode in {"ABSENT", "IGNORED_DYNAMIC"}:
        if set(constraint) != {"match"}:
            raise UiaContractError(f"SELECTOR_CONSTRAINT_INVALID:{label}")
        return
    if mode in {"EXACT", "TOKEN"}:
        if set(constraint) != {"match", "value"} or not isinstance(constraint.get("value"), str):
            raise UiaContractError(f"SELECTOR_CONSTRAINT_INVALID:{label}")
        return
    raise UiaContractError(f"SELECTOR_CONSTRAINT_INVALID:{label}")


def _validate_selector(selector: Any, *, label: str) -> None:
    required_keys = {
        "control_type",
        "automation_id",
        "name",
        "class_name",
        "visible",
        "enabled",
        "ancestor_chain",
        "fallback",
    }
    if not isinstance(selector, dict) or set(selector) != required_keys:
        raise UiaContractError(f"SELECTOR_KEYS_INVALID:{label}")
    if not isinstance(selector["control_type"], str) or not selector["control_type"]:
        raise UiaContractError(f"SELECTOR_CONTROL_TYPE_INVALID:{label}")
    for field in ("automation_id", "name", "class_name"):
        _validate_property_constraint(selector[field], label=f"{label}.{field}")
    if selector["visible"] is not True or selector["enabled"] is not True:
        raise UiaContractError(f"SELECTOR_STATE_INVALID:{label}")
    if selector["fallback"] != "PROHIBITED" or not isinstance(selector["ancestor_chain"], list):
        raise UiaContractError(f"SELECTOR_FALLBACK_INVALID:{label}")
    for index, ancestor in enumerate(selector["ancestor_chain"]):
        if not isinstance(ancestor, dict) or set(ancestor) != {"relation", "selector"}:
            raise UiaContractError(f"SELECTOR_ANCESTOR_INVALID:{label}:{index}")
        if ancestor["relation"] not in {"DIRECT_PARENT", "ANCESTOR"}:
            raise UiaContractError(f"SELECTOR_ANCESTOR_INVALID:{label}:{index}")
        ancestor_selector = ancestor["selector"]
        if (
            not isinstance(ancestor_selector, dict)
            or "control_type" not in ancestor_selector
            or not set(ancestor_selector).issubset({"control_type", "automation_id", "name", "class_name"})
        ):
            raise UiaContractError(f"SELECTOR_ANCESTOR_INVALID:{label}:{index}")
        if not isinstance(ancestor_selector["control_type"], str) or not ancestor_selector["control_type"]:
            raise UiaContractError(f"SELECTOR_ANCESTOR_INVALID:{label}:{index}")
        for field in ("automation_id", "name", "class_name"):
            if field in ancestor_selector:
                _validate_property_constraint(ancestor_selector[field], label=f"{label}.ancestor.{field}")


def write_canonical_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
