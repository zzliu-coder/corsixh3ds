# External Audit Handoff

Generated: 2026-09-03 16:57 CST

## Next Session Goal

Independently review the frozen CorsixTH Old 3DS port source and identify reproducible correctness, ownership, integration, build-evidence, and device-validation gaps.

## Current State

- Internal frozen source commit: `9ff2b84114df9070d578c88fe927255369c12b6d`
- Internal frozen source tree: `a0827cfe96655a2660d33752654c70de007152c3`
- Sole parent: `bedf567a4810d0479fba5ebcae7b49020d2988f3`
- Evidence protocol: `FAIL` at the frozen baseline; C3-R5 remediation is diagnosed but has not been constructed or independently accepted.
- Runtime product correctness: `FAIL`.
- Real product resource integration: `FAIL`.
- Old 3DS memory peak and device runtime: `NOT_PROVEN`.
- Host tests and devkitARM compile/link results exist, but do not establish product or device acceptance.
- Further construction and automated progression were paused before this publication.

## User Intent And Scope

- Review the source as a work in progress.
- Keep host, cross-build, final-artifact, and real-device conclusions separate.
- Require a concrete source path or reproducible result for every formal finding.
- The repository intentionally contains no proprietary Theme Hospital game data.

## Source Layout

- `include/cth3ds`, `src/common`, `src/3ds`: Runtime Core and platform implementation.
- `lua/3ds`: Lua platform adapter.
- `tools`, `scripts`: upstream integration, resource conversion, build, packaging, and evidence tooling.
- `tests`: host, simulator, integration, cross-build, and evidence-protocol tests.
- `docs`: architecture and prior evidence documentation.

The CorsixTH upstream source is intentionally not vendored. Run `scripts/bootstrap_upstream.sh` to obtain pinned CorsixTH `v0.70.1` commit `56bd5d00f76331c7f76d7b696726a7926303ca0c` and apply this port. That operation still does not provide the proprietary Theme Hospital data required to play.

## Publication Transformations

This public repository is a single-commit source snapshot rather than the internal Git history. Program source bytes come from the frozen tree above. Two local absolute paths in `docs/evidence/runtime-core-acceptance.json` were replaced with `<LOCAL_WORKSPACE>` to avoid publishing a workstation username and directory layout. No executable source was altered by publication.

## First Audit Actions

1. Verify `PUBLICATION_MANIFEST.json` and the repository tree.
2. Run the host test and upstream integration checks documented in `README.md`.
3. Trace real graphics, audio, font, sprite, and level resource consumption to `RuntimeSession` rather than accepting symbol presence alone.
4. Review level-transition commit/rollback, HOME and exit saving, lease release, and failure atomicity.
5. Record real Old 3DS behavior as `NOT_PROVEN` until device evidence is collected.

## Important Boundary

This snapshot is suitable for source review. It is not a release claim and is not evidence that the game is currently playable on Old 3DS.
