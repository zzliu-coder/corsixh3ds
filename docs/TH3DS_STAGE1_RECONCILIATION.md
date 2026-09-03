# TH3DS stage-1 reconciliation record

Baseline: `9fbaeb6210108e27363c2bbc39769d70f2d41ea2`

Authoritative result: **TH3DSR1 version 1.0**. This matrix was completed before
the reconciliation edits and records why the frozen architecture or executable
packer won each decision.

| Area | Frozen architecture | Cherry-picked packer | v1.0 resolution |
|---|---|---|---|
| Top-level output | bundle + core/language/level `.th3ds` | loose resource tree | TH3DSR1 package family only; current lane emits core + one language |
| Container | 256-byte header, 128-byte index | independent TH3DSND1/TH3DSP1 | implement TH3DSR1 outer container; typed layouts are nested kind payloads |
| Alignment | 64-byte regions, 4096-byte audio | packed consecutively | enforce zero 64/4096-byte padding and validate it |
| Audio | resampled S16LE IMA blocks | source PCM or external DSP payload | preserve source PCM semantics or deterministic DSP output; random access per clip; 3 MiB per-clip gate |
| Sprite | LZ4 pixel blocks | zlib of source chunk stream per sprite | use deterministic zlib source-stream blocks; 307,200 pixel and 1 MiB scratch gates |
| Language | execute and flatten arbitrary Lua | static selected inheritance closure | package only the statically proven closure; dynamic inheritance fails; runtime adapter remains separate |
| UI/font | typed metadata, 256x256 font pages | loose pixels and JSON | typed TH3DS resources; exact 256x256 pages, at most 16, map depends on atlas |
| Identity/hash | source/package/resource IDs plus catalog/payload/container/bundle SHA | file CRC/SHA and tree hash | implement every contract ID/hash; resource hash excludes padding, package payload hash includes it |
| JSON | canonical manifest | sorted compact plus trailing LF | sorted compact UTF-8, no float/BOM/trailing LF |
| Budget | runtime pools 3/8/6/3/1/1 MiB | total output/decoded/resident 256/64/12 MiB | runtime pool and per-resource/scratch gates; disk output cap remains separate |
| Telemetry | available/used and canonical pools | headroom wording, legacy categories, 2 MiB probe | explicit estimate wording; canonical pools separated from diagnostics; S100 36/16/8/4 gate |
| Legacy archive | CTH3DPK1 rejected by runtime | `pack`/`stage` audit artifact | retain and name it legacy audit-only; never use `.th3ds` or claim runtime compatibility |

The audio, language, and sprite changes amend the earlier design because the
existing executable converter cannot safely promise a resampler, arbitrary Lua
evaluation, LZ4 decoder contract, or final sprite pixels it does not produce.
The selected formats retain the memory objective: runtime random access,
bounded working sets, deterministic bytes, and fail-closed descriptors.

## Evidence boundary

Stage 1 owns the host writer/inspector, deterministic conversion, package
integrity, source-set identity, packer budget rejection, and telemetry contract
constants. It does not own runtime resource semantics or hardware acceptance.
