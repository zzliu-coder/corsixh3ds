# Runtime Core v2 C3 red oracle

This document freezes observations, derivations, and verdict semantics for C3.
The producer records raw facts only. The consumer derives every delta and verdict.

## RH09-H1

Oracle ID: `H1_LEVEL_REQUIRES_DECLARED_PACKAGE`.

The accepted A0 red observation requests `hospital-01` from a synthetic bundle
whose declared level count is zero. `RuntimeSession::enter_level(2)` returns
`OK`, publishes `LEVEL_STABLE`, leaves transition inactive, and changes none of
the mounted-package identities, mount/catalog generations, catalog fingerprint,
resource counts, allocation-record count, pool/backend byte totals, or
reconciliation counters.

Protocol gate: `PASS`. Product verdict: `FAIL`.
Failure code: `H1_LEVEL_NOT_DECLARED_ACCEPTED`.

The future V2-01 green observation returns `E_LEVEL_NOT_DECLARED`, remains in
`MENU_STABLE`, leaves transition inactive, and has zero deltas for every listed
identity, count, byte total, and reconciliation counter.

## RH07-H2

Oracle ID: `H2_TRANSITION_CAPABILITY_ROLLBACK`.

The accepted A0 red observation injects `after-first-staged-acquire` and returns
`E_TEST_PREPARE_ABORT`. State is `MENU_STABLE` before and after; transition is
inactive before and after. The escaped lease remains valid. Mounted packages,
pins, and dependencies have zero deltas. Entries, leases, and allocation
records each change by +1. Pool deltas are `[0,0,64,0,0,0,0]`; backend deltas
are `[64,0]`; the linear reconciliation delta is zero.

`regular_reconciliation_before` and `regular_reconciliation_after` are
authenticated diagnostics only. They measure the process default allocator
domain minus Runtime Core backend records; the values include allocator-,
sanitizer-, STL-, file-stream-, and observer-specific storage. No exact value
or delta participates in H2 acceptance.

`stable_state_published` is derived as state-after being one of the reviewer
policy stable states while transition-active-after is false. It is true for the
A0 red observation.

The observer emits its raw observation and exits successfully only after both
`escaped.release()` and `session.shutdown()` succeed. This execution gate proves
that ledger-managed resources can return to the RuntimeSession lifecycle
baseline. Absence of leaks in metadata outside the ledger owner domain remains
`NOT_PROVEN` in C3.

Protocol gate: `PASS`. Product verdict: `FAIL`.
Failure code: `H2_ESCAPED_CAPABILITY_PUBLISHED_STABLE`.

The future V2-02 green oracle accepts complete rollback with all deltas zero and
an invalid escaped lease, or blocked rollback with `E_TRANSACTION_UNRESOLVED`,
`ROLLBACK_BLOCKED`, transition active, and no stable state published.

## Sanitizer and provenance

A complete authenticated sanitizer report produces protocol/product `FAIL` and
`SANITIZER_PRODUCT_FAILURE`. Missing instrumentation, symbol evidence, or full
streams produces `NOT_PROVEN`.

RH10 freezes two independent statements: the fixture payload origin is
`generated_synthetic` and contains no original Theme Hospital data; the embedded
TH3DSR1 container safety classification remains
`contains_user_game_data=true, redistributable=false`.

The frozen upstream archive establishes snapshot bytes only. Git provenance,
Old-3DS runtime, and S70 device memory remain `NOT_PROVEN` in C3.

## C3-R4 fresh-chain authority

Construction and independent review use the same one-shot entry point:

```text
evidence_protocol_adversarial.py --fresh-chain
  --candidate-root CANDIDATE --session-root EMPTY_SESSION
  --archive ARCHIVE --deps-prefix DEPS
  --matrix FROZEN_60 --expected-matrix-sha256 SHA256
  --base-acceptance-cases FROZEN_32 --expected-base-cases-sha256 SHA256
  --cycle-acceptance-cases R4_22 --expected-cycle-cases-sha256 SHA256
```

The session root must be absent or empty. The entry point accepts no prior
facts, fixture, receipt, seal, run ID, or review-session ID. It creates a new
review session and executes the frozen 18-node acyclic order. The reviewer-owned
closure fixture is `CLOSURE_TEST_ONLY`, remains `NOT_PROVEN`, and is consumed
once by the five closure cases. The legacy `--matrix-evaluate` seal path is
disabled. The finalizer is the sole writer of a final review seal and runs only
after an externally anchored 60/60 receipt exists.
