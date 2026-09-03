# Runtime Core acceptance oracle

Status: frozen for the `TH3DSR1 v1.0` Runtime Core remediation.

Baseline: `2404f6c3b314bc767a89ec8416d1650d073c5541`
Rejected candidate: `939a8a7a5e897092aa91e676957baecefa27e5ef`

This document is the executable acceptance oracle for the seven remediation
commits.  It refines the runtime interpretation of
`OLD3DS_RESOURCE_ARCHITECTURE.md` and `OLD3DS_MEMORY_BUDGET.md`; it does not
change the external `TH3DSR1 v1.0` byte format or any budget ceiling.

## 1. Result boundaries

Every reported gate has one of three results:

- `PASS`: the named command and its assertions completed for the candidate.
- `FAIL`: the named command completed and a required assertion failed.
- `NOT_PROVEN`: the required environment or evidence is absent.

Host tests, sanitizers and cross-linking cannot satisfy an `RD` hardware gate.
The historical Old 3DS `S70 OOM` remains `FAIL` until a later same-candidate
device run supersedes it.  This remediation performs no device upload and uses
no original game data.

## 2. Frozen compatibility rules

1. Major version `1` is required.
2. Minor `0` is accepted.  A higher minor is accepted only when every required
   feature bit is known and every parsed field obeys this schema.  Unknown
   required features return `E_UNSUPPORTED_FEATURE`.
3. Header, package manifest and bundle declaration must agree on role, package
   ID, source-set hash, container hash, ABI and format.
4. Bundle paths are canonical and role-specific:
   `core.th3ds`, `lang/<canonical-tag>.th3ds`, and
   `level/<canonical-id>.th3ds`.  Each declared path is unique.  Exactly one
   core exists; the selected and explicit fallback tags each map to at most one
   language package; a start level maps to exactly one level package.
5. Core may contain shared UI, audio, sprites, palettes and bounded opaque
   compatibility data.  Language packages may contain only language bundles,
   font maps and font atlases.  Level packages may contain sprites, palettes,
   UI bitmaps, audio and bounded opaque level data.  Required language roots
   occur only in language packages.
6. `PIN_ON_MOUNT` is legal only for bounded boot/error UI, current-language
   roots and their font dependencies.  `STREAMABLE` is required for audio banks
   and sprite sheets and is illegal for language, font, palette and UI bitmap
   resources.  Audio alignment is 4096 bytes; every other resource uses 64
   bytes.
7. Every descriptor belongs to exactly one declared group.  Every group member
   exists in that package and appears once.  Every descriptor dependency exists,
   has an allowed kind, points to a mounted package dependency or the same
   package, and the dependency graph is acyclic.  Cross-group dependencies may
   only point from a shorter-lived group to a longer-lived group.
8. Package declarations and dependencies are explicit.  Directory scans are
   never a source of fallback or level selection.

## 3. Transaction invariants

All public Runtime Core APIs catch allocation, I/O, callback and container
exceptions and return `ResourceResult`.  Failure is atomic at the public
boundary.

### Mount and language fallback

The only publish point follows complete validation of bundle, core, selected or
fallback language, optional start level, catalog, dependency graph, budgets and
permanent pins.  A selected-language failure at any phase closes its file,
removes its metadata/catalog/ledger state and then tries the manifest's explicit
fallback.  Fallback starts from the core-only baseline.  Failed fallback closes
the complete transaction.

### World transition

The order is fixed:

1. quiesce new acquires for the old group;
2. reject or drain old leases according to the API mode;
3. evict old zero-reference entries;
4. jointly validate regular and linear totals and page-touch probes;
5. mount the target package and build its catalog delta;
6. prefetch through the authoritative manager;
7. publish the target group.

Cancel or failure removes target entries, pins, dependency references, package
state and ledger delta, then restores the old group.  Commit leaves no live
lease from the old level.

### Save, HOME and shutdown

Save/load uses the operation reserve without changing the active world.
HOME/suspend quiesces producers before the platform callback.  Shutdown
quiesces Lua, SDL, audio and renderer clients, cancels an active transaction,
drains leases, releases pins, reverse-unmounts level/language/core and returns
the allocator ledger to its captured baseline.  Outstanding leases return an
explicit error and keep the session alive.

## 4. Authoritative allocation oracle

Callers provide a resource ID and expected type.  They do not select pool,
resident bytes, scratch bytes, group, dependency, alignment or pin ownership.
Those fields come from the trusted descriptor, its validated metadata and the
resource/backend type.

Every allocation plan records:

- requested, aligned and allocator-committed payload bytes;
- object/index/key/control-block and dependency-edge overhead;
- regular or linear backend and resource pool;
- group, transaction and phase;
- lease, pin-owner and dependent reference counts;
- shared scratch reservation and actual high-water mark.

The manager reserves the full plan before allocating and publishes only after
payload, hash, backend object, index node and dependency edges are complete.
Rollback is the exact reverse sequence.  A second scratch user returns
`E_SCRATCH_BUSY`.  One owner's unpin cannot release another owner's pin or the
mount pin.  `sum(classified) + unclassified_delta` reconciles with measured
regular/linear deltas; `unclassified_delta > 1 MiB` fails the gate.

Every allocation gate jointly checks the phase limit, `heap_total >= 52 MiB`,
`linear_total == 8 MiB`, linear resident `<= 6 MiB`, and a page-touch probe.
Each successful probe writes and reads at least one byte on every 4096-byte page
and the last byte.

## 5. Fault matrix

The tests inject failure before and after every publish-affecting operation:

| Boundary | Required failures | Required postcondition |
|---|---|---|
| bundle/package mount | open, read, parse, hash, schema, catalog, dependency, pin | package count, ledger and handles equal baseline |
| selected language | declaration, file, header, hash, schema, catalog, allocation | selected state fully absent before fallback |
| fallback language | same complete matrix | closed session and baseline ledger |
| resource acquire | plan, reserve, payload, scratch, read, decode, hash, index, edge, telemetry | no exception, entry absent, counts at baseline |
| world transition | quiesce, lease drain, reserve, page probe, mount, prefetch, publish | target delta zero; old world restored |
| save/load | reserve, stream callback, commit | active world unchanged; workspace zero |
| shutdown | active transition, outstanding lease, callback quiesce | explicit error or fully closed; never partial destruction |

## 6. RH01-RH10 executable mapping

`scripts/verify_runtime_core.sh` is the single entry point added by R7.  It
writes immutable candidate evidence under `docs/evidence/` and fails unless
RH01-RH10 all pass.

| Gate | Executable assertion |
|---|---|
| RH01 | pack/inspect/decode synthetic fixtures for every resource kind and compare logical bytes |
| RH02 | build each fixture twice in separate roots and compare bundle and package SHA-256 values |
| RH03 | semantic mutation, truncation/bounds/overlap/order/hash tests under ASan/UBSan |
| RH04 | file-open trace contains only core and selected or explicit fallback language |
| RH05 | audio spy reads at most one 4096-frame block and regular audio ledger never exceeds 3 MiB |
| RH06 | sprite spy initially reads only its index; unrequested pixel bytes are zero and a decoded block is at most 65,536 B |
| RH07 | live entries never evict; ID breaks LRU ties; texture precedes sprite dependency; 10,000 cycles return to baseline |
| RH08 | each pool cap at `cap-1`, `cap`, `cap+1`; reject has no object/count/fallback side effect |
| RH09 | core/lang/level, corruption, save reserve, regular and linear failures return the specified error and preserve error-page capacity |
| RH10 | tracked files and the no-game source/release manifests contain no original files or generated user `.th3ds` payloads |

The same run also requires:

- production vertical slice: entry → session → core/language/level → required
  UI acquire → menu/level/menu → save → shutdown;
- final ELF symbols for session start/shutdown, mount, acquire and rollback plus
  a real production-entry relocation/call edge;
- 10,000 mount/transition/acquire/save cycles with ledger and package counts at
  baseline;
- `git diff --check` and a clean candidate worktree after evidence commit;
- AppleClang ASan/UBSan with LeakSanitizer recorded as unavailable on macOS;
- devkitARM cross-build evidence reported independently from host evidence.

## 7. R1-R7 commit gates

| Commit | Gate |
|---|---|
| R1 contract-oracle | this document maps every frozen rule and RH gate without changing the format |
| R2 semantic-mount | semantic mutation and complete selected/fallback failure matrix pass |
| R3 authoritative-ledger | derived allocation plans, exception-safe publication, multi-owner pins and 10,000-cycle baseline pass |
| R4 runtime-session | mount/transition/save/HOME/shutdown traces and rollback tests pass |
| R5 production-composition | production owner exists and final ELF has a genuine call edge |
| R6 lua-lifecycle-map | menu, level, save/load, HOME and exit callbacks reach the session API in order |
| R7 acceptance-evidence | RH01-RH10, sanitizers, cross-build report and repository hygiene pass |

## 8. Hardware boundary

RD01-RD14 remain `NOT_PROVEN` throughout R1-R7.  Their definitions and exact
thresholds remain those in `OLD3DS_MEMORY_BUDGET.md`.  Only a later run on the
same frozen source/build/source-set may change those results.
