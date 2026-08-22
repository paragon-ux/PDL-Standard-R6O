# H2-A1 Scope Boundary

**Status:** DRAFT / PENDING HUMAN ARTIFACT APPROVAL

**A1-D1 decision:** OPTION A - accepted R6O-1 contracts remain protected

## H2 includes

H2 includes only the real Codex presentation binding needed to prove:

- actual Codex top-level window discovery and unique selection;
- actual Codex version, Windows environment, geometry, DPI, and monitor capture;
- actual Codex New Chat, composer, and conversation-control discovery; the
  native Codex submit control is not required by approved Option A;
- Sidecar ownership and placement relative to the actual Codex window/composer;
- steady-state z-order without evidence-induced foreground or raise operations;
- focus transfer and Codex non-interference while the Sidecar is present;
- the Option A native composer routing contract frozen by H2-A1;
- one captured Enter producing exactly one `HOST_COMPOSER_TEXT` envelope and
  zero normal Codex conversation/model submissions for that captured text;
- real-host G06 through `CLOSED_SUCCESS`;
- real-host A02-FULL through revised Prompt, Plan, and `CLOSED_SUCCESS`; and
- cross-View parity plus actual-host presentation lifecycle qualification.

The Enter interception above is an H2-E1 input-routing requirement. H2-A1
freezes it but does not implement it.

## R6O-3 retains

R6O-3 retains:

- automatic PDLt invocation from arbitrary host conversations;
- a host-model interaction lease;
- suspension or coordination of host-model tokens and waiting;
- management of already-running host-model requests;
- on-close mechanical handoff-envelope delivery;
- automatic host-LLM wakeup or return after terminal state;
- production-grade Codex lifecycle monitoring;
- multi-host discovery abstractions; and
- Claude or other host adapters.

H2 suppression of one captured review submission does not authorize any item in
this R6O-3 list.

## Protected boundary

Unless a later human-approved versioned amendment is issued, these paths remain
protected:

```text
r6o/model_binding/**
r6o/viewmodel/**
r6o/contracts/**
r6o_evidence/R6O-1/**
```

Views and host bindings must not call `MechanicalController`, `SessionEngine`,
`WorkerAdapter`, `ReviewDecision` constructors, or workspace filesystem
authority. The only semantic path is:

```text
actual host or TUI interaction
    -> InputEnvelope
    -> PresentationAdapter
    -> accepted ViewModel
    -> Model Port
    -> authoritative PDLt runtime
```

## Gate boundary

This A1 change creates contract documents and their validator only. It does not
create fixtures, Views, Codex selectors, host bindings, evidence, or later-gate
status. Passing the validator means the draft is mechanically complete; only a human can assign `HUMAN_PASS` to H2-A1.
