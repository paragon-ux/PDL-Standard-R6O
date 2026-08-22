# H2-A1 Interaction Contract

**Status:** DRAFT / PENDING HUMAN ARTIFACT APPROVAL

**Decision authority:** Human H2-A1 decision, 2026-08-22

**A1-D1 decision:** OPTION A - preserve accepted R6O-1 `FREE_RESPONSE_FOCUS`

## 1. Preserved R6O-1 semantics

`Something else...` is the projected action with `action_id = something_else`
and `kind = FREE_RESPONSE_FOCUS`.

Activating it emits one `STRUCTURED_ACTION` envelope containing the current
`model_revision`, `projection_id`, and `action_id = something_else`. It contains
no review text. The accepted ViewModel returns `FOCUS_REQUIRED` with
`focus_role = FREE_RESPONSE`; no Model Port user message and no worker operation
occurs from that action.

The free-response surface owns text entry. A later user submission emits a
separate text envelope. The ViewModel owns semantic interpretation through the
Model Port. No protected R6O-1 contract is amended.

Option B is not selected. A Sidecar action cannot submit semantic review text,
cannot synthesize placeholder review text, and cannot trigger the native Codex
submission gesture.

## 2. TUI free-response interaction

The exact TUI sequence is:

1. The user moves TUI action focus to `Something else...` and presses Enter.
2. The TUI emits one `STRUCTURED_ACTION` for `action_id = something_else`.
3. After `FOCUS_REQUIRED`, focus moves to the TUI free-response input surface.
4. The user types review text in that surface.
5. The user presses Enter while that surface owns focus.
6. The TUI emits one `InputEnvelope` with `source = TUI_TEXT` and the exact
   entered text. `action_id` and `projection_id` are null for this text envelope.
7. The text is submitted exactly once to the accepted ViewModel. The returned
   projection is rendered, and focus moves to its primary structured action.

There is no preloaded magic text and no second Send control. An empty or
whitespace-only Enter is not a review submission.

## 3. Actual Codex free-response interaction

The exact Sidecar/Codex sequence is:

1. The user clicks `Something else...` in the Sidecar.
2. The Sidecar emits one `STRUCTURED_ACTION` for
   `action_id = something_else`.
3. After `FOCUS_REQUIRED`, the H2 Codex binding focuses the actual Codex
   composer selected by the H2-D1 frozen selector.
4. The user types review text in the actual Codex composer.
5. The user presses unmodified Enter while that composer owns focus.
6. While the H2 PDLt review binding is active, the H2 input binding captures
   that single native composer submission before it reaches normal Codex
   conversation/model dispatch.
7. The binding emits one `InputEnvelope` with
   `source = HOST_COMPOSER_TEXT` and the exact captured composer text.
   `action_id` and `projection_id` are null for this text envelope.
8. The captured text is submitted exactly once to the accepted ViewModel. The
   returned projection is rendered in the Sidecar, the native composer is
   empty, and focus moves to the projection's primary Sidecar action.

The native Codex submit button is not part of the approved H2 human flow and
must not be used as E1 or E3 acceptance evidence. A Sidecar control never causes
native composer submission. Unmodified Enter is the only approved Codex
free-response submit gesture. Shift+Enter remains a composer editing gesture
and does not emit an H2 review envelope.

## 4. Observable suppression boundary for H2-E1

For the captured Enter gesture, all of these observations are required:

- exactly one `HOST_COMPOSER_TEXT` envelope crosses the H2
  presentation-binding boundary;
- its text equals the composer content at the captured gesture;
- no user message containing that text appears in the Codex conversation;
- no normal Codex-model request containing that text is initiated;
- no duplicate PDLt submission occurs;
- the actual Codex application remains visible and interactive; and
- the next authoritative ViewModel projection is rendered in the Sidecar.

Suppression is limited to routing the captured native composer gesture while a
PDLt review projection is active. It does not suspend an in-flight host model,
reserve tokens, wait on a host LLM, automatically invoke PDLt, or deliver a
terminal handoff. Those lifecycle responsibilities remain R6O-3.

## 5. Structured actions

For both Views, `Confirm prompt` emits one `STRUCTURED_ACTION` with
`action_id = confirm_prompt`. `Confirm plan` emits one `STRUCTURED_ACTION` with
`action_id = confirm_plan`. Their semantic text comes only from the accepted
R6O-1 `canonical_review_messages.json` mapping.

In the TUI, the user presses Enter while the action owns focus. In the Sidecar,
the user clicks the displayed action. Structured actions do not use either
free-response surface.

## 6. Terminal behavior

After `CLOSED_SUCCESS`, the TUI exits with status 0 and returns control to the
calling shell. The Codex Sidecar dismisses and returns focus to the actual Codex
composer. H2 does not mechanically deliver the terminal result to the host
conversation.

The exact G06 and A02-FULL gestures, operations, projections, focus owners, and
Sidecar visibility are normative in `H2-A1-STATE-TRANSITIONS.json`.

## 7. Session-start and artifact-reference notation

The `NEW` to first-review transition is initiated by the explicit H2 gate
runner through `ModelPort.start_or_resume(ModelSessionRequest)`. It does not emit
an `InputEnvelope`, so its `input_envelope_source` is exactly null. This manual,
fixture-selected start does not authorize automatic invocation from a Codex
conversation.

Accepted R6O-1 projection artifact references are opaque. In the transition
file, `PROMPT_PROJECTION_REF` and `PLAN_PROJECTION_REF` mean the exact non-empty
`FocusProjection.artifact.artifact_ref` returned for that projection. They are
normative reference-source tokens, not literal Model Port artifact IDs and not
workspace paths. Terminal projections have no active review artifact, so both
artifact kind and reference are exactly null at `CLOSED_SUCCESS`.
