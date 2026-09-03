"""Theme Hospital TAB/DAT sprite indexing for lazy Old 3DS decode."""

from __future__ import annotations

import dataclasses
import hashlib
import struct
import zlib
from pathlib import Path

try:
    from th3ds_resource import ResourceError, crc32_hex, read_stable, sha256_bytes
except ModuleNotFoundError:
    from .th3ds_resource import ResourceError, crc32_hex, read_stable, sha256_bytes

MAGIC = b"TH3DSP1\0"
VERSION = 1
HEADER = struct.Struct("<8sIIIIQ")
ENTRY = struct.Struct("<QQQQHHIII32s")
TAB_ENTRY = struct.Struct("<IBB")
BLOCK_ALIGNMENT = 64
MAX_SPRITE_PIXELS = 307_200
SCRATCH_LIMIT = 1024 * 1024


@dataclasses.dataclass(frozen=True)
class SpritePackResult:
    data: bytes
    decoded_size: int
    decoded_sha256: str
    pixel_bytes: int
    entries: tuple[dict[str, object], ...]


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & -alignment


def _valid_chunk_stream(data: bytes, pixels: int, width: int, *, complex_chunks: bool) -> bool:
    produced = 0
    x = 0
    cursor = 0
    skip_eol = False

    def advance(amount: int) -> bool:
        nonlocal produced, x, skip_eol
        if amount < 0 or produced + amount > pixels:
            return False
        produced += amount
        x = (x + amount) % width
        skip_eol = True
        return True

    while produced < pixels and cursor < len(data):
        command = data[cursor]
        cursor += 1
        if command == 0:
            if x != 0 or not skip_eol:
                if not advance(width - x):
                    return False
            skip_eol = False
            continue
        if complex_chunks:
            if command < 0x40:
                amount = command
                if cursor + amount > len(data) or not advance(amount):
                    return False
                cursor += amount
            elif command & 0xC0 == 0x80:
                if not advance(command - 0x80):
                    return False
            else:
                if command == 0xFF:
                    if cursor + 2 > len(data):
                        return False
                    amount = data[cursor]
                    cursor += 2
                else:
                    if cursor >= len(data):
                        return False
                    amount = command - 60 - (command & 0x80) // 2
                    cursor += 1
                if not advance(amount):
                    return False
        elif command < 0x80:
            amount = command
            if cursor + amount > len(data) or not advance(amount):
                return False
            cursor += amount
        elif not advance(0x100 - command):
            return False
    return produced == pixels and all(byte == 0 for byte in data[cursor:])


def build_sprite_pack(tab_path: Path, dat_path: Path) -> SpritePackResult:
    tab = read_stable(tab_path)
    source = read_stable(dat_path)
    if not tab or len(tab) % TAB_ENTRY.size:
        raise ResourceError(f"sprite TAB length must be a non-zero multiple of 6: {tab_path}")
    raw_entries = [TAB_ENTRY.unpack_from(tab, offset) for offset in range(0, len(tab), TAB_ENTRY.size)]
    live_positions = [position for position, width, height in raw_entries if width and height]
    if live_positions != sorted(live_positions):
        raise ResourceError(f"non-empty sprite offsets are not monotonic: {tab_path}")
    if len(live_positions) != len(set(live_positions)):
        raise ResourceError(f"non-empty sprites share an ambiguous source offset: {tab_path}")
    if any(position >= len(source) for position in live_positions):
        raise ResourceError(f"sprite offset points outside DAT payload: {dat_path}")

    next_position: dict[int, int] = {}
    for index, position in enumerate(live_positions):
        next_position[position] = live_positions[index + 1] if index + 1 < len(live_positions) else len(source)

    blocks: list[bytes] = []
    metadata: list[dict[str, object]] = []
    data_offset = _align_up(HEADER.size + len(raw_entries) * ENTRY.size, BLOCK_ALIGNMENT)
    cursor = data_offset
    decoded_digest = hashlib.sha256()
    restored_size = 0
    pixel_bytes = 0
    for index, (position, width, height) in enumerate(raw_entries):
        decoded_size = width * height
        if decoded_size == 0:
            block = b""
            source_size = 0
            encoding_flags = 0
        else:
            end = next_position[position]
            if end <= position:
                raise ResourceError(f"sprite {index} has an empty or reversed source range")
            raw = source[position:end]
            source_size = len(raw)
            if decoded_size > MAX_SPRITE_PIXELS:
                raise ResourceError(
                    f"sprite {index} has {decoded_size} pixels, exceeding {MAX_SPRITE_PIXELS}"
                )
            if source_size + decoded_size > SCRATCH_LIMIT:
                raise ResourceError(
                    f"sprite {index} needs {source_size + decoded_size} scratch bytes, "
                    f"exceeding {SCRATCH_LIMIT}"
                )
            encoding_flags = int(_valid_chunk_stream(raw, decoded_size, width, complex_chunks=False))
            encoding_flags |= 2 * int(_valid_chunk_stream(raw, decoded_size, width, complex_chunks=True))
            if encoding_flags == 0:
                raise ResourceError(
                    f"sprite {index} is malformed for both simple and complex chunk decoding"
                )
            block = zlib.compress(raw, level=9)
            if zlib.decompress(block) != raw:
                raise ResourceError(f"internal compression verification failed for sprite {index}")
            decoded_digest.update(struct.pack("<I", source_size))
            decoded_digest.update(raw)
            restored_size += source_size
            pixel_bytes += decoded_size
        aligned = _align_up(cursor, BLOCK_ALIGNMENT) if block else 0
        blocks.append(block)
        digest = sha256_bytes(block)
        checksum = int(crc32_hex(block), 16)
        metadata.append(
            {
                "compressed_offset": aligned,
                "compressed_size": len(block),
                "crc32": f"{checksum:08x}",
                "decoded_size": decoded_size,
                "encoding_candidates": [
                    name
                    for flag, name in ((1, "simple"), (2, "complex"))
                    if encoding_flags & flag
                ],
                "encoding_flags": encoding_flags,
                "height": height,
                "index": index,
                "sha256": digest,
                "source_offset": position,
                "source_size": source_size,
                "width": width,
            }
        )
        if block:
            cursor = aligned + len(block)

    output = bytearray(HEADER.pack(MAGIC, VERSION, len(raw_entries), ENTRY.size, 1, data_offset))
    for item in metadata:
        output.extend(
            ENTRY.pack(
                item["compressed_offset"],
                item["compressed_size"],
                item["source_offset"],
                item["source_size"],
                item["width"],
                item["height"],
                item["decoded_size"],
                item["encoding_flags"],
                int(item["crc32"], 16),
                bytes.fromhex(str(item["sha256"])),
            )
        )
    if len(output) < data_offset:
        output.extend(bytes(data_offset - len(output)))
    for item, block in zip(metadata, blocks):
        if not block:
            continue
        offset = int(item["compressed_offset"])
        output.extend(bytes(offset - len(output)))
        output.extend(block)
    return SpritePackResult(
        bytes(output), restored_size, decoded_digest.hexdigest(), pixel_bytes, tuple(metadata)
    )
