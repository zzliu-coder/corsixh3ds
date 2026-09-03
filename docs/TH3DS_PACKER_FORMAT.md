# TH3DSR1 authoritative resource format 1.0

Status: **implementation-ready host format / runtime loader pending**

This file is the byte-level companion to `OLD3DS_RESOURCE_ARCHITECTURE.md`.
The only runtime package format named `.th3ds` is `TH3DSR1`, version 1.0.
`TH3DSND1`, `TH3DSP1`, and `TH3DSLG1` are kind payload layouts carried inside
a `TH3DSR1` resource. They are never mounted as top-level packages.
`CTH3DPK1` is a legacy audit archive and a runtime must reject it with
`E_LEGACY_AUDIT_PACK`.

All integers are unsigned little-endian unless a field says otherwise. JSON is
UTF-8, key-sorted, compact (`','` and `':'` separators), contains no floats or
BOM, and has no trailing newline. Every unspecified or reserved byte is zero.

## 1. Package family

```text
bundle.th3ds.json
core.th3ds
lang/<normalized-bcp47>.th3ds
level/<stable-level-id>.th3ds   # later packer lane; same container
```

The current converter emits core plus exactly one language package. It does
not claim a level-resource conversion lane. Every package in one bundle has
the same `source_set_sha256` and runtime ABI.

## 2. TH3DSR1 fixed header

The header is exactly 256 bytes. Its magic bytes are `54 48 33 44 53 52 31 00`.

| Offset | Size | Field | v1.0 value |
|---:|---:|---|---|
| 0x00 | 8 | magic | `TH3DSR1\0` |
| 0x08 | 2 | header_size | 256 |
| 0x0A | 2 | version_major | 1 |
| 0x0C | 2 | version_minor | 0 |
| 0x0E | 2 | header_flags | 0 |
| 0x10 | 4 | endian_tag | 0x01020304 |
| 0x14 | 4 | default_alignment | 64 |
| 0x18 | 4 | package_role | 1 core, 2 language, 3 level |
| 0x1C | 4 | index_entry_size | 128 |
| 0x20 | 8 | manifest_offset | absolute, 64-byte aligned |
| 0x28 | 8 | manifest_size | exact canonical JSON bytes |
| 0x30 | 8 | index_offset | absolute, 64-byte aligned |
| 0x38 | 4 | index_count | 1..65,535 |
| 0x3C | 4 | reserved_0 | 0 |
| 0x40 | 8 | metadata_offset | absolute, 64-byte aligned |
| 0x48 | 8 | metadata_size | exact metadata-region bytes |
| 0x50 | 8 | data_offset | absolute, 64-byte aligned |
| 0x58 | 8 | data_size | includes inter-resource zero padding |
| 0x60 | 8 | build_epoch | 0 |
| 0x68 | 32 | catalog_sha256 | SHA-256(`index || metadata`) |
| 0x88 | 32 | payload_sha256 | SHA-256(entire data region) |
| 0xA8 | 32 | container_sha256 | whole file with this field zeroed |
| 0xC8 | 32 | source_set_sha256 | canonical consumed-source fingerprint |
| 0xE8 | 4 | required_runtime_abi | 1 |
| 0xEC | 4 | required_feature_bits | 0 in v1.0 |
| 0xF0 | 16 | reserved_1 | zero |

Regions occur in header, manifest, index, metadata, data order and never
overlap. Gaps and padding are zero. No bytes may follow the declared data
region.

## 3. Common resource index

Entries are sorted by the raw 16 resource-ID bytes and are exactly 128 bytes,
encoded by `<16sHHIIB3xQIIQIHH32s32s>`.

| Offset | Size | Field |
|---:|---:|---|
| 0x00 | 16 | resource_id |
| 0x10 | 2 | kind |
| 0x12 | 2 | outer codec |
| 0x14 | 4 | flags |
| 0x18 | 4 | group_id |
| 0x1C | 1 | alignment_log2: 6 or 12 |
| 0x1D | 3 | zero |
| 0x20 | 8 | absolute data_offset |
| 0x28 | 4 | stored_size, maximum 64 MiB |
| 0x2C | 4 | kind-defined logical decoded_size |
| 0x30 | 8 | metadata-region-relative meta_offset |
| 0x38 | 4 | meta_size, maximum 1 MiB/resource |
| 0x3C | 2 | dependency_count |
| 0x3E | 2 | zero |
| 0x40 | 32 | SHA-256 of the exact stored payload |
| 0x60 | 32 | SHA-256 of the kind-defined logical bytes |

Inter-resource alignment bytes are outside `stored_size` and the per-resource
hash. They are inside the package payload hash. Metadata begins with
`dependency_count` raw 16-byte resource IDs, followed by canonical JSON.

Kinds: 1 `AUDIO_BANK`, 2 `LANGUAGE_BUNDLE`, 3 `SPRITE_SHEET`, 4 `UI_BITMAP`,
5 `FONT_ATLAS`, 6 `FONT_MAP`, 7 `PALETTE`, 255 `OPAQUE_BLOB`. Outer codecs are
0 `NONE`, 1 `ZLIB`, 2 `DSP_ADPCM`; current kind containers use outer `NONE`.
Flags are `REQUIRED=1`, `PIN_ON_MOUNT=2`, `STREAMABLE=4`.

Resource ID is the first 16 bytes of:

```text
SHA-256("th3ds-resource-id-v1\0" || kind_name || "\0" || logical_name)
```

Logical names are safe normalized relative UTF-8 paths. Duplicate IDs fail the
build and the loader.

## 4. Package and bundle manifests

The package manifest contains `format`, `package`, `runtime_abi`, `source`,
`toolchain`, `catalog`, `dependencies`, `groups`, `language`, `level`,
`budgets`, and `provenance`. Package ID is the first 16 bytes of:

```text
SHA-256("th3ds-package-id-v1\0" || role || "\0" || name || "\0" ||
        source_set_sha256_bytes || runtime_abi_le32)
```

The bundle contains `format`, `runtime_abi`, `source_set_sha256`,
`selected_language`, `fallback_language`, `start_level`, `packages`, and
`bundle_sha256`. Each package row contains path, role, package ID, file size,
and container SHA-256. Its path is lowercase safe relative ASCII, limited to
`a-z`, `0-9`, `.`, `_`, `-`, and `/`.
To calculate `bundle_sha256`, replace its value with 64 ASCII zeroes, encode
the canonical JSON, and hash those bytes.

Source-set records sort by path UTF-8 bytes and concatenate:

```text
path_length_u16 || path_bytes || file_size_u64 || file_sha256_32bytes
```

The converter fingerprints the input game tree, language source directory,
and explicit glyph inputs. Source payload does not enter Git or logs.

## 5. AUDIO_BANK payload: TH3DSND1

The payload header is `<8sIIIIQQ>`: magic `TH3DSND1`, version 1, entry count,
fixed-entry bytes, zero flags, index offset, and first payload offset. Each
variable index row is `<HBBIHHQQQI32s>` followed by its UTF-8 name: name bytes,
codec, channels, sample rate, source bits, zero, absolute offset within the
bank, stored bytes, decoded PCM bytes, CRC-32, stored SHA-256.

Codec 1 is source PCM U8, 2 is source PCM S16LE, and 3 is a deterministic
external DSP-ADPCM result. Each clip begins at a 4096-byte boundary. The
default converter preserves source sample rate, channels, and PCM width so it
does not invent resampling semantics. A runtime acquires one clip, and each
clip's decoded bytes must fit the 3 MiB audio pool. The logical decoded hash is
the bank-order concatenation `name_bytes_u16 || name || original_pcm`.

## 6. SPRITE_SHEET payload: TH3DSP1

The payload header is `<8sIIIIQ>`: magic `TH3DSP1\0`, version 1, TAB row count,
fixed-entry bytes, compression 1 (zlib stream, level 9), and data offset.
Every fixed row is `<QQQQHHIII32s>`: compressed offset/size, source DAT
offset/size, width, height, final indexed8 pixel bytes, decoding-candidate
flags, compressed CRC-32, and compressed SHA-256.

Each non-empty TAB row owns one 64-byte-aligned zlib block containing the exact
Theme Hospital chunk stream. Candidate bit 0 is simple decoding and bit 1 is
complex decoding. Invalid under both fails packing. Final pixel bytes are at
most 307,200. `source_size + pixel_bytes` must fit the 1 MiB scratch ceiling.
The outer logical decoded bytes concatenate `source_size_u32 || chunk_stream`
for each non-empty source row. Pixel cache accounting uses the per-row final
pixel byte field.

## 7. LANGUAGE_BUNDLE payload: TH3DSLG1

Static inspection proves the selected language's dependency-first `Inherit`
closure. Dynamic inheritance, missing inputs, and cycles fail packing. The
payload contains only that closure; unrelated language files are excluded.

Header `<8sIIIIQQ>` contains magic `TH3DSLG1`, version 1, entry count,
fixed-entry bytes, zero flags, index offset, and first payload offset. Each row
is `<HBBQQ32s>` plus path: path bytes, kind (1 Lua source, 2 original strings),
zero, 64-byte-aligned offset, size, and SHA-256. Logical decoded bytes are the
dependency-order concatenation `path_bytes_u16 || path || content`.

This is the executable amendment to the earlier flattened-table proposal.
Static Python parsing cannot faithfully evaluate arbitrary CorsixTH Lua. The
format bounds the input to one proven closure and leaves language execution to
the later typed runtime adapter. That adapter and its device behavior are not
implemented in stage 1.

## 8. UI and font payloads

`UI_BITMAP` stores tightly packed 320x240 RGB565 or RGBA5551 little-endian
pixels with width, height, stride, and format in resource metadata.
`FONT_ATLAS` is exactly 256x256 16-bit input. At most 16 pages enter one
language package. `FONT_MAP` is canonical JSON version 1 sorted by codepoint;
it depends on its atlas resource ID. Font rasterization is outside the packer;
only explicit pre-rasterized inputs are accepted.

## 9. Fail-closed checks

The writer and inspector reject truncation, integer/range errors, overlapping
regions or payloads, non-zero padding/reserved bytes, unordered or duplicate
IDs, unknown kinds/codecs/flags/features, alignment errors, non-canonical JSON,
and resource/catalog/payload/container/bundle hash errors. Output publishes by
atomic directory rename only after file readback and full inspection.
