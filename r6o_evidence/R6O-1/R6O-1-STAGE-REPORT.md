# R6O-1 — Stage Report

Status: **READY_FOR_H1** (mechanical candidate complete; human gate pending)
Work repository: `PDL-Standard-R6O` (local-only, NOT published)
Candidate commit: `c5882eae54fae9be584d2a092af02ae36190014a`
Baseline oracle: `PDL-Standard-REPL-Harness@60d982f3328b45a351879d67dc4bb525172b65fd` (READ-ONLY)

## What was implemented

- Language-neutral R6O contracts: Model Port (`r6o-model-port-1`), FocusProjection, PresentationAction, SessionInvocation, tightened InputEnvelope, ViewModelCommandResult (with `STALE_PROJECTION`), CloseResult, HandoffEnvelope, and versioned `CANONICAL_REVIEW_MESSAGES.json`.
- Current MVVM Model binding adapter (`LocalRuntimeModelBinding`) over the frozen `PDLtHost`/R6S runtime; opaque artifact refs resolved only inside the binding.
- In-memory non-path Model Port + artifact provider for storage-substitution proof.
- ViewModel: projection builder, dynamic action projection, structured-action dispatcher with stale/unknown fail-closed, mechanical CloseResult and HandoffEnvelope compilers.
- Conformance tests and `scripts/verify_r6o1.py`.

## Verification results

| Check | Result |
| --- | --- |
| Baseline verifier (frozen repo) | PASS (exit 0) |
| Baseline pytest (frozen repo) | PASS, 9/9 |
| R6O-1 pytest (work repo) | PASS, 33/33 |
| G06 ViewModel vs direct runtime parity | PASS (CLOSED_SUCCESS, identical Prompt/Plan bodies) |
| A02 ViewModel free-response vs direct runtime parity | PASS (PROMPT_REVIEW, identical revised Prompt) |
| Frozen baseline mutation audit | PASS (clean, bound commit unchanged) |

## Key invariants demonstrated

- Structured actions dispatch canonical ordinary review text (`Yes, that is what I mean.` / `Confirm the plan and execute.`) through the same semantic path as direct input.
- Stale/unknown actions fail closed with no domain mutation.
- Projection construction is pure: no LLM call, no domain transition, reconstructable from the same authoritative revision.
- A non-path in-memory provider passes the same ViewModel suite; no `Path` leaks into public projections/contracts.
- ViewModel modules contain no runtime/controller/workspace imports.
- HandoffEnvelope is mechanically compiled from authoritative state and persisted before CloseResult is observable.

## H1 — human checklist

1. Review this stage report, the parity evidence, and the projection/action trace demonstration.
2. Optionally run `python -m pytest r6o\tests -q` and `python scripts\verify_r6o1.py` yourself.
3. Record disposition: `USER_ACCEPT` / `USER_ACCEPT_WITH_FINDINGS` / `USER_REJECT`.

R6O-2 (TUI + Sidecar) remains blocked until `USER_ACCEPT`.
