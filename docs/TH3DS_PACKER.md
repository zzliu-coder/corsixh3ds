# Old 3DS deterministic TH3DSR1 converter

`tools/th3ds_pack.py convert` consumes a local, user-owned Theme Hospital tree
and writes the authoritative TH3DSR1 v1.0 package family. It does not download
data, place data in Git, copy the loose game tree, or implement the runtime
loader. Publication occurs by atomic directory rename after every file is
re-read and fully inspected.

## Invocation

```sh
python3 tools/th3ds_pack.py convert /path/to/ThemeHospital /path/to/game-3ds \
  --language-dir /path/to/CorsixTH/Lua/languages \
  --language en
```

The destination must not exist. Runtime pool defaults are frozen at audio
3 MiB, sprite 8 MiB, texture 6 MiB, language/font 3 MiB, metadata 1 MiB, and
scratch 1 MiB. The independent disk-output safety cap is 256 MiB. CLI options
may only tighten these values for an acceptance candidate.

The image lane converts exact 640x480 `.DAT` files with a matching palette.
Explicit mappings use:

```sh
--image 'QDATA/START.DAT,QDATA/START.PAL,rgba5551,6,255'
```

Pre-rasterized font pages are opt-in. Each image must be exactly 256x256,
16-bit RGB565 or RGBA5551, and its metadata must pass glyph bounds and
duplicate-codepoint checks:

```sh
--glyph-atlas /path/to/ui-atlas.json
```

## Output

```text
game-3ds/
  bundle.th3ds.json
  core.th3ds
  lang/<normalized-bcp47>.th3ds
```

`core.th3ds` carries the audio bank, independently compressed sprite sheets,
and converted UI bitmaps. The language package carries only the statically
proven selected-language inheritance closure plus explicit pre-rasterized font
resources. The current converter has no level-package lane; that missing lane
does not change the v1.0 container.

## Determinism and fail-closed behavior

The converter fixes traversal, IDs, JSON encoding, zlib level, byte order,
alignment, zero padding, and output paths. Package manifests record the input
source-set fingerprint and packer commit. Identical source bytes, options, and
packer commit produce byte-identical output.

Conversion rejects unsafe or changing inputs, FAT case collisions, malformed
SOUND/TAB/DAT/palette/glyph structures, dynamic or cyclic language inheritance,
unstable external audio encoding, resource and scratch budget excess, region
or integer bounds errors, non-zero reserved bytes, and any hash/readback
mismatch. Failed conversion leaves no destination tree.

## Format and game-data boundary

The exact bytes are frozen by `docs/TH3DS_PACKER_FORMAT.md`. `CTH3DPK1` made by
the older `pack` command remains explicitly a legacy audit-only archive used by
the existing loose-file staging workflow. It is never a `.th3ds` runtime pack.

Generated `.th3ds` files contain user-derived game resources and must stay out
of Git and source/no-game-data releases. Synthetic tests create temporary
fixtures and scan the generated package bytes for an unrelated game-data
sentinel. Runtime mounting, audio playback, language execution, sprite decode,
graphics behavior, FTP deployment, and Old 3DS acceptance remain separate
tasks.
