# Allocator ledger contract v1

This contract defines the Runtime Core allocation success path. It applies to
raw payloads, derived payloads, and the shared scratch arena.

## Quantities

| Symbol | Field | Meaning |
|---|---|---|
| R | `requested_bytes` | Logical payload requested by the caller. |
| A | `alignment_bytes` | Validated alignment; Runtime Core accepts 64 or 4096. |
| P | `aligned_payload_bytes` | Checked `align_up(R, A)`. |
| B | `backend_request_bytes` | Bytes passed to the selected backend. |
| U | `usable_bytes` | Backend-local usable-size observation when available. |
| Q | `budget_charge_bytes` | Pool charge; equal to P in v1. |
| T | `backend_accounted_bytes` | U when exact usable size exists, otherwise B. |

Pool limits sum Q only. Backend telemetry sums T only. `U > P` is a valid
allocator observation and never causes a pool rejection. These dimensions and
touched pages are orthogonal and must not be added together.

## Record lifecycle

Allocation IDs increase monotonically and are never reused. Allocation first
creates a `Reserved` record and reserves Q. A successful backend allocation and
usable-size observation atomically publish the record as `Live`. Backend failure
removes the reservation and restores every counter. Release validates allocation
ID, pointer identity, and backend before freeing, subtracting Q and T, and moving
the record to `Freed`. Foreign, repeated, pointer-mismatched, and backend-
mismatched releases leave all counters unchanged.

Reallocation is `allocate(new) -> copy(min(old.R,new.R)) -> owner swap ->
free(old)`. Failure leaves the old record and bytes live. A zero new size performs
an exact release and returns an empty handle. The linear path uses this algorithm
and never calls `linearRealloc`.

Zero-size requests fail before a backend call. Alignment, align-up, counter, page,
and reconciliation arithmetic is checked and fails closed. Runtime Core pool and
backend enums must be valid.

## Backends and observations

Regular host allocations use aligned allocation and `malloc_size` on Apple or
`malloc_usable_size` on glibc/newlib. libctru linear allocations use
`linearMemAlign`, `linearGetSize`, and `linearFree`. Unknown or injected backends
fall back to B and label the quality `BackendRequestFallback`.

Reconciliation is signed:

```text
D_regular = measured_regular_live_delta - sum(T of live regular records)
D_linear  = measured_linear_live_delta  - sum(T of live linear records)
```

Positive, zero, and negative deltas are preserved. Missing aggregate probes are
reported through measurement-availability fields. `unclassified_bytes` is
derived from the signed regular reconciliation when measurement is available;
it is never clamped or forced to zero. STL nodes, strings, trace capacity, and
catalog storage remain residual observations for the later ownership-closure
stage. `allocation_overhead_bytes` and `metadata_baseline_bytes` are compatibility
fields and no longer contain fixed `sizeof` estimates.

Touched pages are tracked per live allocation ID. Ranges use the runtime page
size and snapshots compute the union of live page IDs, so overlapping ranges are
counted once. Page totals do not change Q or T.

## Runtime session observation surface

`RuntimeSessionSnapshot.mount_generation` and `catalog_generation` are read-only.
Each increments once when startup publishes the mounted bundle and its catalog.
No-op snapshots, level entry, menu entry, save/load, suspend/resume, and shutdown
do not increment them in A0. A0 does not change level selection, package or
catalog content, transition behavior, or H1/H2 product behavior.
