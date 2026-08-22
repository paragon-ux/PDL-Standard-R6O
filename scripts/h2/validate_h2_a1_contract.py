from __future__ import annotations

"""Fail-closed mechanical validator for the draft H2-A1 contract freeze."""

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "h2"
INTERACTION_PATH = DOCS / "H2-A1-INTERACTION-CONTRACT.md"
TRANSITIONS_PATH = DOCS / "H2-A1-STATE-TRANSITIONS.json"
SCOPE_PATH = DOCS / "H2-A1-SCOPE-BOUNDARY.md"

FORBIDDEN_LANGUAGE = (
    "tbd",
    "implementation decides",
    "where applicable",
    "as applicable",
    "e.g.",
    "something like",
)

EXPECTED_STATES = {
    "G06": [
        {"id": "G06-S0", "name": "NEW"},
        {"id": "G06-S1", "name": "PROMPT_REVIEW"},
        {"id": "G06-S2", "name": "PLAN_REVIEW"},
        {"id": "G06-S3", "name": "CLOSED_SUCCESS"},
    ],
    "A02-FULL": [
        {"id": "A02-S0", "name": "NEW"},
        {"id": "A02-S1", "name": "PROMPT_REVIEW_INITIAL"},
        {"id": "A02-S2", "name": "PROMPT_REVIEW_REVISED"},
        {"id": "A02-S3", "name": "PLAN_REVIEW"},
        {"id": "A02-S4", "name": "CLOSED_SUCCESS"},
    ],
}

EXPECTED_ARTIFACT_REF_TOKENS = {
    "PROMPT_PROJECTION_REF": "The non-empty opaque FocusProjection.artifact.artifact_ref for the expected prompt artifact",
    "PLAN_PROJECTION_REF": "The non-empty opaque FocusProjection.artifact.artifact_ref for the expected plan artifact",
}

EXPECTED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "status",
    "decision",
    "artifact_ref_tokens",
    "state_models",
    "transitions",
}

EXPECTED_DECISION_FIELDS = {
    "id",
    "selected_option",
    "presentation_action_kind",
    "sidecar_action_submits_semantic_text",
    "protected_contract_amendment_required",
}

INTERACTION_SECTION_RULES: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    (
        "1. Preserved R6O-1 semantics",
        105,
        (
            "`action_id = something_else`",
            "`kind = FREE_RESPONSE_FOCUS`",
            "no Model Port user message and no worker operation",
            "Option B is not selected",
        ),
    ),
    (
        "2. TUI free-response interaction",
        105,
        (
            "`source = TUI_TEXT`",
            "submitted exactly once",
            "no second Send control",
        ),
    ),
    (
        "3. Actual Codex free-response interaction",
        185,
        (
            "actual Codex composer",
            "presses unmodified Enter",
            "before it reaches normal Codex conversation/model dispatch",
            "`source = HOST_COMPOSER_TEXT`",
            "native Codex submit button is not part of the approved H2 human flow",
            "Shift+Enter remains a composer editing gesture",
        ),
    ),
    (
        "4. Observable suppression boundary for H2-E1",
        100,
        (
            "exactly one `HOST_COMPOSER_TEXT` envelope",
            "no user message containing that text appears in the Codex conversation",
            "no normal Codex-model request containing that text is initiated",
            "does not suspend an in-flight host model",
        ),
    ),
    (
        "5. Structured actions",
        60,
        (
            "`action_id = confirm_prompt`",
            "`action_id = confirm_plan`",
            "Structured actions do not use either free-response surface",
        ),
    ),
    (
        "6. Terminal behavior",
        55,
        (
            "TUI exits with status 0",
            "Codex Sidecar dismisses",
            "does not mechanically deliver the terminal result",
        ),
    ),
    (
        "7. Session-start and artifact-reference notation",
        90,
        (
            "`ModelPort.start_or_resume(ModelSessionRequest)`",
            "`input_envelope_source` is exactly null",
            "`PROMPT_PROJECTION_REF` and `PLAN_PROJECTION_REF`",
            "both artifact kind and reference are exactly null",
        ),
    ),
)

SCOPE_SECTION_RULES: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    (
        "H2 includes",
        120,
        (
            "actual Codex top-level window discovery and unique selection",
            "actual Codex version, Windows environment, geometry, DPI, and monitor capture",
            "actual Codex New Chat, composer, and conversation-control discovery",
            "native Codex submit control is not required by approved Option A",
            "Sidecar ownership and placement relative to the actual Codex window/composer",
            "steady-state z-order without evidence-induced foreground or raise operations",
            "focus transfer and Codex non-interference while the Sidecar is present",
            "the Option A native composer routing contract frozen by H2-A1",
            "exactly one `HOST_COMPOSER_TEXT` envelope",
            "zero normal Codex conversation/model submissions",
            "real-host G06 through `CLOSED_SUCCESS`",
            "real-host A02-FULL through revised Prompt, Plan, and `CLOSED_SUCCESS`",
            "cross-View parity plus actual-host presentation lifecycle qualification",
            "H2-E1 input-routing requirement",
            "freezes it but does not implement it",
        ),
    ),
    (
        "R6O-3 retains",
        75,
        (
            "automatic PDLt invocation from arbitrary host conversations",
            "a host-model interaction lease",
            "suspension or coordination of host-model tokens and waiting",
            "management of already-running host-model requests",
            "on-close mechanical handoff-envelope delivery",
            "automatic host-LLM wakeup or return after terminal state",
            "production-grade Codex lifecycle monitoring",
            "multi-host discovery abstractions",
            "Claude or other host adapters",
            "does not authorize any item in this R6O-3 list",
        ),
    ),
    (
        "Protected boundary",
        55,
        (
            "r6o/model_binding/**",
            "r6o/viewmodel/**",
            "r6o/contracts/**",
            "r6o_evidence/R6O-1/**",
            "`MechanicalController`, `SessionEngine`",
            "`WorkerAdapter`, `ReviewDecision` constructors",
            "workspace filesystem authority",
            "actual host or TUI interaction",
            "InputEnvelope",
            "PresentationAdapter",
            "accepted ViewModel",
            "Model Port",
            "authoritative PDLt runtime",
        ),
    ),
    (
        "Gate boundary",
        35,
        (
            "contract documents and their validator only",
            "does not create fixtures, Views, Codex selectors, host bindings, evidence, or later-gate status",
            "only a human can assign `HUMAN_PASS` to H2-A1",
        ),
    ),
)

REQUIRED_TRANSITION_FIELDS = {
    "id",
    "case",
    "view",
    "phase",
    "from_state",
    "human_gesture",
    "input_envelope_source",
    "action_id_or_text_source",
    "expected_worker_operations",
    "expected_next_state",
    "expected_next_stage",
    "expected_artifact",
    "expected_focus_owner",
    "expected_sidecar_visibility",
}

OPS = {
    "G06_START": [{"operation_id": "G06:0001", "operation": "DRAFT_PROMPT"}],
    "G06_PROMPT": [
        {"operation_id": "G06:0002", "operation": "INTERPRET_PROMPT_REVIEW"},
        {"operation_id": "G06:0003", "operation": "DRAFT_PLAN"},
    ],
    "G06_PLAN": [
        {"operation_id": "G06:0004", "operation": "INTERPRET_PLAN_REVIEW"},
        {"operation_id": "G06:0005", "operation": "EXECUTE"},
    ],
    "A02_START": [{"operation_id": "A02F:0001", "operation": "DRAFT_PROMPT"}],
    "A02_REVISE": [
        {"operation_id": "A02F:0002", "operation": "INTERPRET_PROMPT_REVIEW"},
        {"operation_id": "A02F:0003", "operation": "REVISE_PROMPT"},
    ],
    "A02_PROMPT": [
        {"operation_id": "A02F:0004", "operation": "INTERPRET_PROMPT_REVIEW"},
        {"operation_id": "A02F:0005", "operation": "DRAFT_PLAN"},
    ],
    "A02_PLAN": [
        {"operation_id": "A02F:0006", "operation": "INTERPRET_PLAN_REVIEW"},
        {"operation_id": "A02F:0007", "operation": "EXECUTE"},
    ],
}


def expected_transition_matrix() -> dict[tuple[str, str, str], dict[str, Any]]:
    matrix: dict[tuple[str, str, str], dict[str, Any]] = {}
    for view in ("TUI", "CODEX_SIDECAR"):
        sidecar = view == "CODEX_SIDECAR"
        suffix = "CODEX" if sidecar else "TUI"
        matrix[("G06", view, "START")] = {
            "id": f"G06-T0-{suffix}",
            "human_gesture": (
                "Run python scripts\\h2\\run_codex_h2_e2.py --case G06 --record"
                if sidecar
                else "Run python scripts\\run_r6o2_tui.py --recorded --case G06"
            ),
            "from_state": "G06-S0",
            "input_envelope_source": None,
            "action_id_or_text_source": "MODEL_SESSION_REQUEST_TASK_TEXT_G06_FIXTURE",
            "expected_worker_operations": OPS["G06_START"],
            "expected_next_state": "G06-S1",
            "expected_next_stage": "PROMPT_REVIEW",
            "expected_artifact": artifact("prompt", "PROMPT_PROJECTION_REF", "NEW_NON_EMPTY_REVISION"),
            "expected_focus_owner": "SIDECAR_ACTION_CONFIRM_PROMPT" if sidecar else "TUI_ACTION_CONFIRM_PROMPT",
            "expected_sidecar_visibility": "VISIBLE_STANDARD" if sidecar else "NOT_PRESENT",
        }
        matrix[("G06", view, "CONFIRM_PROMPT")] = {
            "id": f"G06-T1-{suffix}",
            "human_gesture": "Click Confirm prompt in the Sidecar" if sidecar else "Press Enter while Confirm prompt owns TUI action focus",
            "from_state": "G06-S1",
            "input_envelope_source": "STRUCTURED_ACTION",
            "action_id_or_text_source": "confirm_prompt",
            "expected_worker_operations": OPS["G06_PROMPT"],
            "expected_next_state": "G06-S2",
            "expected_next_stage": "PLAN_REVIEW",
            "expected_artifact": artifact("plan", "PLAN_PROJECTION_REF", "NEW_NON_EMPTY_REVISION"),
            "expected_focus_owner": "SIDECAR_ACTION_CONFIRM_PLAN" if sidecar else "TUI_ACTION_CONFIRM_PLAN",
            "expected_sidecar_visibility": "VISIBLE_STANDARD" if sidecar else "NOT_PRESENT",
        }
        matrix[("G06", view, "CONFIRM_PLAN")] = terminal_transition(
            transition_id=f"G06-T2-{suffix}",
            human_gesture="Click Confirm plan in the Sidecar" if sidecar else "Press Enter while Confirm plan owns TUI action focus",
            from_state="G06-S2",
            next_state="G06-S3",
            operations=OPS["G06_PLAN"],
            sidecar=sidecar,
        )

        matrix[("A02-FULL", view, "START")] = {
            "id": f"A02-T0-{suffix}",
            "human_gesture": (
                "Run python scripts\\h2\\run_codex_h2_e3.py --case A02-FULL --record"
                if sidecar
                else "Run python scripts\\run_r6o2_tui.py --recorded --case A02-FULL"
            ),
            "from_state": "A02-S0",
            "input_envelope_source": None,
            "action_id_or_text_source": "MODEL_SESSION_REQUEST_TASK_TEXT_A02_FULL_FIXTURE",
            "expected_worker_operations": OPS["A02_START"],
            "expected_next_state": "A02-S1",
            "expected_next_stage": "PROMPT_REVIEW",
            "expected_artifact": artifact("prompt", "PROMPT_PROJECTION_REF", "NEW_NON_EMPTY_REVISION"),
            "expected_focus_owner": "SIDECAR_ACTION_CONFIRM_PROMPT" if sidecar else "TUI_ACTION_CONFIRM_PROMPT",
            "expected_sidecar_visibility": "VISIBLE_STANDARD" if sidecar else "NOT_PRESENT",
        }
        matrix[("A02-FULL", view, "FOCUS_FREE_RESPONSE")] = {
            "id": f"A02-T1-FOCUS-{suffix}",
            "human_gesture": "Click Something else... in the Sidecar" if sidecar else "Move TUI action focus to Something else... and press Enter",
            "from_state": "A02-S1",
            "input_envelope_source": "STRUCTURED_ACTION",
            "action_id_or_text_source": "something_else",
            "expected_worker_operations": [],
            "expected_next_state": "A02-S1",
            "expected_next_stage": "PROMPT_REVIEW",
            "expected_artifact": artifact("prompt", "PROMPT_PROJECTION_REF", "UNCHANGED"),
            "expected_focus_owner": "ACTUAL_CODEX_COMPOSER" if sidecar else "TUI_FREE_RESPONSE_INPUT",
            "expected_sidecar_visibility": "VISIBLE_STANDARD" if sidecar else "NOT_PRESENT",
        }
        matrix[("A02-FULL", view, "SUBMIT_PROMPT_REVISION")] = {
            "id": f"A02-T2-REVISE-{suffix}",
            "human_gesture": (
                "Type the A02-FULL review text in the focused actual Codex composer and press unmodified Enter once"
                if sidecar
                else "Type the A02-FULL review text in the focused TUI input and press Enter once"
            ),
            "from_state": "A02-S1",
            "input_envelope_source": "HOST_COMPOSER_TEXT" if sidecar else "TUI_TEXT",
            "action_id_or_text_source": "ACTUAL_CODEX_COMPOSER_TEXT" if sidecar else "TUI_FREE_RESPONSE_INPUT_TEXT",
            "expected_worker_operations": OPS["A02_REVISE"],
            "expected_next_state": "A02-S2",
            "expected_next_stage": "PROMPT_REVIEW",
            "expected_artifact": artifact("prompt", "PROMPT_PROJECTION_REF", "CHANGED_FROM_A02_S1"),
            "expected_focus_owner": "SIDECAR_ACTION_CONFIRM_PROMPT" if sidecar else "TUI_ACTION_CONFIRM_PROMPT",
            "expected_sidecar_visibility": "VISIBLE_STANDARD" if sidecar else "NOT_PRESENT",
        }
        matrix[("A02-FULL", view, "CONFIRM_REVISED_PROMPT")] = {
            "id": f"A02-T3-{suffix}",
            "human_gesture": "Click Confirm prompt in the Sidecar" if sidecar else "Press Enter while Confirm prompt owns TUI action focus",
            "from_state": "A02-S2",
            "input_envelope_source": "STRUCTURED_ACTION",
            "action_id_or_text_source": "confirm_prompt",
            "expected_worker_operations": OPS["A02_PROMPT"],
            "expected_next_state": "A02-S3",
            "expected_next_stage": "PLAN_REVIEW",
            "expected_artifact": artifact("plan", "PLAN_PROJECTION_REF", "NEW_NON_EMPTY_REVISION"),
            "expected_focus_owner": "SIDECAR_ACTION_CONFIRM_PLAN" if sidecar else "TUI_ACTION_CONFIRM_PLAN",
            "expected_sidecar_visibility": "VISIBLE_STANDARD" if sidecar else "NOT_PRESENT",
        }
        matrix[("A02-FULL", view, "CONFIRM_PLAN")] = terminal_transition(
            transition_id=f"A02-T4-{suffix}",
            human_gesture="Click Confirm plan in the Sidecar" if sidecar else "Press Enter while Confirm plan owns TUI action focus",
            from_state="A02-S3",
            next_state="A02-S4",
            operations=OPS["A02_PLAN"],
            sidecar=sidecar,
        )
    return matrix


def artifact(kind: str | None, ref: str | None, relation: str) -> dict[str, str | None]:
    return {
        "artifact_kind": kind,
        "artifact_ref": ref,
        "artifact_revision_relation": relation,
    }


def terminal_transition(
    transition_id: str,
    human_gesture: str,
    from_state: str,
    next_state: str,
    operations: list[dict[str, str]],
    sidecar: bool,
) -> dict[str, Any]:
    return {
        "id": transition_id,
        "human_gesture": human_gesture,
        "from_state": from_state,
        "input_envelope_source": "STRUCTURED_ACTION",
        "action_id_or_text_source": "confirm_plan",
        "expected_worker_operations": operations,
        "expected_next_state": next_state,
        "expected_next_stage": "CLOSED_SUCCESS",
        "expected_artifact": artifact(None, None, "NO_ACTIVE_REVIEW_ARTIFACT"),
        "expected_focus_owner": "ACTUAL_CODEX_COMPOSER" if sidecar else "CALLING_SHELL",
        "expected_sidecar_visibility": "DISMISSED" if sidecar else "NOT_PRESENT",
    }


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def validate_no_placeholders(path: Path, text: str, failures: list[str]) -> None:
    lowered = text.lower()
    for phrase in FORBIDDEN_LANGUAGE:
        require(phrase not in lowered, f"{path}: prohibited placeholder language: {phrase!r}", failures)


def markdown_sections(text: str) -> tuple[list[str], dict[str, str]]:
    order: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            order.append(current)
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return order, {heading: "\n".join(body).strip() for heading, body in sections.items()}


def validate_sectioned_doc(
    label: str,
    text: str,
    rules: tuple[tuple[str, int, tuple[str, ...]], ...],
    failures: list[str],
) -> None:
    order, sections = markdown_sections(text)
    expected_order = [heading for heading, _, _ in rules]
    require(order == expected_order, f"{label} section order or membership differs from the freeze", failures)
    for heading, minimum_words, markers in rules:
        body = sections.get(heading, "")
        normalized_body = " ".join(body.split())
        require(len(body.split()) >= minimum_words, f"{label} section {heading!r} is incomplete", failures)
        for marker in markers:
            normalized_marker = " ".join(marker.split())
            require(normalized_marker in normalized_body, f"{label} section {heading!r} missing normative assertion: {marker}", failures)


def validate_docs(interaction: str, scope: str, data: Any, failures: list[str]) -> None:
    require(interaction.startswith("# H2-A1 Interaction Contract\n"), "interaction contract title differs from the freeze", failures)
    require(scope.startswith("# H2-A1 Scope Boundary\n"), "scope boundary title differs from the freeze", failures)
    require("**A1-D1 decision:** OPTION A" in interaction, "interaction contract does not select Option A", failures)
    require("**A1-D1 decision:** OPTION A" in scope, "scope boundary does not select Option A", failures)
    validate_sectioned_doc("interaction contract", interaction, INTERACTION_SECTION_RULES, failures)
    validate_sectioned_doc("scope boundary", scope, SCOPE_SECTION_RULES, failures)

    if not isinstance(data, dict):
        return
    decision = data.get("decision")
    transitions = data.get("transitions")
    if not isinstance(decision, dict) or not isinstance(transitions, list):
        return
    require(decision.get("selected_option") == "OPTION_A", "documents and transition decision do not agree on Option A", failures)
    sources = {item.get("input_envelope_source") for item in transitions if isinstance(item, dict)}
    require(sources == {None, "STRUCTURED_ACTION", "TUI_TEXT", "HOST_COMPOSER_TEXT"}, "documented InputEnvelope sources differ from transition sources", failures)
    focus_events = [item for item in transitions if isinstance(item, dict) and item.get("phase") == "FOCUS_FREE_RESPONSE"]
    require(len(focus_events) == 2, "exactly one focus-only event per View is required", failures)
    for event in focus_events:
        require(event.get("expected_worker_operations") == [], "Something else focus event must run no worker operation", failures)
        require(event.get("from_state") == event.get("expected_next_state"), "Something else focus event must not change semantic state", failures)
    codex_text_events = [item for item in transitions if isinstance(item, dict) and item.get("input_envelope_source") == "HOST_COMPOSER_TEXT"]
    require(len(codex_text_events) == 1, "A02-FULL must contain exactly one canonical Codex text submission", failures)
    require("no normal Codex-model request containing that text is initiated" in interaction, "Codex suppression observation is absent", failures)
    require("native Codex submit control is not required by approved Option A" in scope, "scope does not exclude unused native submit-control discovery", failures)


def validate_transitions(data: dict[str, Any], failures: list[str]) -> None:
    require(set(data) == EXPECTED_TOP_LEVEL_FIELDS, "transition document top-level fields differ from the freeze", failures)
    require(data.get("schema_version") == "h2-a1-state-transitions-1", "wrong transition schema_version", failures)
    require(data.get("status") == "DRAFT_PENDING_HUMAN_ARTIFACT_APPROVAL", "wrong draft status", failures)
    require(data.get("state_models") == EXPECTED_STATES, "state models differ from the H2-A1 freeze", failures)
    require(data.get("artifact_ref_tokens") == EXPECTED_ARTIFACT_REF_TOKENS, "artifact reference tokens differ from the H2-A1 freeze", failures)

    decision = data.get("decision")
    require(isinstance(decision, dict), "decision must be an object", failures)
    if isinstance(decision, dict):
        require(set(decision) == EXPECTED_DECISION_FIELDS, "decision fields differ from the freeze", failures)
        require(decision.get("id") == "A1-D1", "decision id must be A1-D1", failures)
        require(decision.get("selected_option") == "OPTION_A", "A1-D1 must select OPTION_A", failures)
        require(decision.get("presentation_action_kind") == "FREE_RESPONSE_FOCUS", "Option A must preserve FREE_RESPONSE_FOCUS", failures)
        require(decision.get("sidecar_action_submits_semantic_text") is False, "Sidecar focus action must submit no semantic text", failures)
        require(decision.get("protected_contract_amendment_required") is False, "Option A must not require a protected-contract amendment", failures)

    transitions = data.get("transitions")
    require(isinstance(transitions, list), "transitions must be an array", failures)
    if not isinstance(transitions, list):
        return

    expected = expected_transition_matrix()
    observed: dict[tuple[str, str, str], dict[str, Any]] = {}
    ids: set[str] = set()
    for index, transition in enumerate(transitions):
        label = f"transition[{index}]"
        if not isinstance(transition, dict):
            failures.append(f"{label} must be an object")
            continue
        missing = REQUIRED_TRANSITION_FIELDS - transition.keys()
        require(not missing, f"{label} missing fields: {sorted(missing)}", failures)
        extra = transition.keys() - REQUIRED_TRANSITION_FIELDS
        require(not extra, f"{label} contains unexpected fields: {sorted(extra)}", failures)
        transition_id = transition.get("id")
        require(isinstance(transition_id, str) and bool(transition_id.strip()), f"{label} id must be non-empty", failures)
        if isinstance(transition_id, str):
            require(transition_id not in ids, f"duplicate transition id: {transition_id}", failures)
            ids.add(transition_id)
        gesture = transition.get("human_gesture")
        require(isinstance(gesture, str) and bool(gesture.strip()), f"{label} human_gesture must be non-empty", failures)
        key = (transition.get("case"), transition.get("view"), transition.get("phase"))
        require(key not in observed, f"duplicate transition tuple: {key}", failures)
        observed[key] = transition

    require(set(observed) == set(expected), "transition case/view/phase matrix is incomplete or contains extras", failures)
    for key, expected_fields in expected.items():
        actual = observed.get(key)
        if actual is None:
            continue
        for field, expected_value in expected_fields.items():
            require(actual.get(field) == expected_value, f"{key} field {field} differs from frozen value", failures)


def validate_transition_document(data: Any, failures: list[str]) -> None:
    if not isinstance(data, dict):
        failures.append("transition document root must be a JSON object")
        return
    validate_transitions(data, failures)


def main() -> int:
    failures: list[str] = []
    paths = (INTERACTION_PATH, TRANSITIONS_PATH, SCOPE_PATH)
    for path in paths:
        require(path.is_file(), f"missing required artifact: {path.relative_to(ROOT)}", failures)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    interaction = INTERACTION_PATH.read_text(encoding="utf-8")
    transitions_text = TRANSITIONS_PATH.read_text(encoding="utf-8")
    scope = SCOPE_PATH.read_text(encoding="utf-8")
    for path, text in ((INTERACTION_PATH, interaction), (TRANSITIONS_PATH, transitions_text), (SCOPE_PATH, scope)):
        validate_no_placeholders(path.relative_to(ROOT), text, failures)

    try:
        transitions = json.loads(transitions_text)
    except json.JSONDecodeError as exc:
        failures.append(f"invalid transition JSON: {exc}")
        transitions = {}

    validate_docs(interaction, scope, transitions, failures)
    validate_transition_document(transitions, failures)

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"H2-A1 CONTRACT VALIDATION FAIL ({len(failures)} finding(s))")
        return 1

    print("H2-A1 CONTRACT VALIDATION PASS")
    print("STATUS=DRAFT_PENDING_HUMAN_ARTIFACT_APPROVAL")
    print("A1_D1=OPTION_A_FREE_RESPONSE_FOCUS")
    print("TRANSITIONS=16")
    return 0


if __name__ == "__main__":
    sys.exit(main())
