"""Strict SOUND-0.DAT parser and deterministic random-access sound pack."""

from __future__ import annotations

import dataclasses
import hashlib
import struct
from pathlib import Path
from typing import Callable

try:
    from th3ds_resource import ResourceError, crc32_hex, read_stable, sha256_bytes
except ModuleNotFoundError:
    from .th3ds_resource import ResourceError, crc32_hex, read_stable, sha256_bytes

ARCHIVE_HEADER_SIZE = 234
TABLE_POSITION_OFFSET = 50
TABLE_LENGTH_OFFSET = 58
SOUND_ENTRY_SIZE = 32
SOUND_POSITION_OFFSET = 18
SOUND_LENGTH_OFFSET = 26

PACK_MAGIC = b"TH3DSND1"
PACK_VERSION = 1
PACK_HEADER = struct.Struct("<8sIIIIQQ")
PACK_ENTRY = struct.Struct("<HBBIHHQQQI32s")
CODECS = {"pcm_u8": 1, "pcm_s16le": 2, "dspadpcm": 3}
AUDIO_ALIGNMENT = 4096
AUDIO_POOL_LIMIT = 3 * 1024 * 1024


@dataclasses.dataclass(frozen=True)
class PcmSound:
    name: str
    channels: int
    sample_rate: int
    bits_per_sample: int
    pcm: bytes


@dataclasses.dataclass(frozen=True)
class EncodedSound:
    codec: str
    data: bytes


@dataclasses.dataclass(frozen=True)
class SoundPackResult:
    data: bytes
    decoded_size: int
    decoded_sha256: str
    entries: tuple[dict[str, object], ...]


SoundEncoder = Callable[[PcmSound], EncodedSound]


def _u32(data: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ResourceError(f"SOUND-0.DAT is truncated while reading {label}")
    return struct.unpack_from("<I", data, offset)[0]


def _parse_wave(data: bytes, name: str) -> PcmSound:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ResourceError(f"sound {name!r} is not a RIFF/WAVE entry")
    riff_size = _u32(data, 4, f"RIFF size for {name}")
    if riff_size + 8 > len(data):
        raise ResourceError(f"sound {name!r} has an out-of-bounds RIFF length")
    limit = riff_size + 8
    cursor = 12
    fmt: tuple[int, int, int, int, int] | None = None
    pcm: bytes | None = None
    while cursor < limit:
        if cursor + 8 > limit:
            raise ResourceError(f"sound {name!r} has a truncated RIFF chunk header")
        chunk_id = data[cursor : cursor + 4]
        chunk_size = _u32(data, cursor + 4, f"chunk size for {name}")
        start = cursor + 8
        end = start + chunk_size
        if end > limit:
            raise ResourceError(f"sound {name!r} has an out-of-bounds RIFF chunk")
        if chunk_id == b"fmt ":
            if chunk_size < 16:
                raise ResourceError(f"sound {name!r} has a truncated PCM format chunk")
            audio_format, channels, rate, _byte_rate, block_align, bits = struct.unpack_from(
                "<HHIIHH", data, start
            )
            fmt = (audio_format, channels, rate, block_align, bits)
        elif chunk_id == b"data" and pcm is None:
            pcm = data[start:end]
        cursor = end + (chunk_size & 1)
    if fmt is None or pcm is None:
        raise ResourceError(f"sound {name!r} is missing fmt or data chunks")
    audio_format, channels, rate, block_align, bits = fmt
    if audio_format != 1 or channels not in (1, 2) or bits not in (8, 16):
        raise ResourceError(
            f"sound {name!r} must be PCM mono/stereo 8/16-bit; "
            f"got format={audio_format}, channels={channels}, bits={bits}"
        )
    if not 4000 <= rate <= 192000:
        raise ResourceError(f"sound {name!r} has invalid sample rate {rate}")
    expected_align = channels * (bits // 8)
    if block_align != expected_align or len(pcm) % block_align:
        raise ResourceError(f"sound {name!r} has inconsistent PCM block alignment")
    return PcmSound(name, channels, rate, bits, pcm)


def parse_sound_archive(data: bytes) -> list[PcmSound]:
    if len(data) < ARCHIVE_HEADER_SIZE + 4:
        raise ResourceError("SOUND-0.DAT is smaller than its archive header")
    header_position = _u32(data, len(data) - 4, "archive header position")
    if header_position + ARCHIVE_HEADER_SIZE > len(data) - 4:
        raise ResourceError("SOUND-0.DAT archive header is out of bounds")
    table_position = _u32(data, header_position + TABLE_POSITION_OFFSET, "sound table position")
    table_length = _u32(data, header_position + TABLE_LENGTH_OFFSET, "sound table length")
    if table_length == 0 or table_length % SOUND_ENTRY_SIZE:
        raise ResourceError("SOUND-0.DAT sound table length is not a non-zero multiple of 32")
    if table_position > len(data) or table_length > len(data) - table_position:
        raise ResourceError("SOUND-0.DAT sound table is out of bounds")

    result: list[PcmSound] = []
    seen_names: set[str] = set()
    ranges: list[tuple[int, int, str]] = []
    for index in range(table_length // SOUND_ENTRY_SIZE):
        entry = table_position + index * SOUND_ENTRY_SIZE
        raw_name = data[entry : entry + 18].split(b"\0", 1)[0]
        try:
            name = raw_name.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ResourceError(f"sound entry {index} has a non-ASCII name") from exc
        if not name or any(ord(character) < 32 for character in name):
            raise ResourceError(f"sound entry {index} has an invalid name")
        folded = name.casefold()
        if folded in seen_names:
            raise ResourceError(f"duplicate sound name: {name}")
        seen_names.add(folded)
        position = _u32(data, entry + SOUND_POSITION_OFFSET, f"position for sound {name}")
        length = _u32(data, entry + SOUND_LENGTH_OFFSET, f"length for sound {name}")
        if length == 0 or position > len(data) or length > len(data) - position:
            raise ResourceError(f"sound {name!r} points outside SOUND-0.DAT")
        ranges.append((position, position + length, name))
        result.append(_parse_wave(data[position : position + length], name))
    for previous, current in zip(sorted(ranges), sorted(ranges)[1:]):
        if current[0] < previous[1]:
            raise ResourceError(f"sound payloads overlap: {previous[2]!r} and {current[2]!r}")
    return result


def _pcm_fallback(sound: PcmSound) -> EncodedSound:
    return EncodedSound("pcm_u8" if sound.bits_per_sample == 8 else "pcm_s16le", sound.pcm)


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & -alignment


def build_sound_pack(path: Path, encoder: SoundEncoder | None = None) -> SoundPackResult:
    sounds = parse_sound_archive(read_stable(path))
    encoder = encoder or _pcm_fallback
    encoded: list[tuple[PcmSound, EncodedSound]] = []
    for sound in sounds:
        first = encoder(sound)
        second = encoder(sound)
        if first != second:
            raise ResourceError(f"audio encoder is nondeterministic for sound {sound.name!r}")
        if first.codec not in CODECS or not first.data:
            raise ResourceError(f"audio encoder returned an unsupported or empty result for {sound.name!r}")
        if len(sound.pcm) > AUDIO_POOL_LIMIT:
            raise ResourceError(
                f"sound {sound.name!r} decodes to {len(sound.pcm)} bytes, "
                f"exceeding the {AUDIO_POOL_LIMIT}-byte audio pool"
            )
        encoded.append((sound, first))

    index_size = sum(PACK_ENTRY.size + len(sound.name.encode("utf-8")) for sound, _ in encoded)
    index_offset = PACK_HEADER.size
    data_offset = _align_up(index_offset + index_size, AUDIO_ALIGNMENT)
    cursor = data_offset
    index = bytearray()
    payload = bytearray(data_offset - (index_offset + index_size))
    decoded_digest = hashlib.sha256()
    entries: list[dict[str, object]] = []
    for sound, output in encoded:
        aligned = _align_up(cursor, AUDIO_ALIGNMENT)
        payload.extend(bytes(aligned - cursor))
        cursor = aligned
        name_bytes = sound.name.encode("utf-8")
        digest = bytes.fromhex(sha256_bytes(output.data))
        checksum = int(crc32_hex(output.data), 16)
        index.extend(
            PACK_ENTRY.pack(
                len(name_bytes),
                CODECS[output.codec],
                sound.channels,
                sound.sample_rate,
                sound.bits_per_sample,
                0,
                cursor,
                len(output.data),
                len(sound.pcm),
                checksum,
                digest,
            )
        )
        index.extend(name_bytes)
        payload.extend(output.data)
        decoded_digest.update(struct.pack("<H", len(name_bytes)))
        decoded_digest.update(name_bytes)
        decoded_digest.update(sound.pcm)
        entries.append(
            {
                "bits_per_sample": sound.bits_per_sample,
                "channels": sound.channels,
                "codec": output.codec,
                "crc32": f"{checksum:08x}",
                "decoded_size": len(sound.pcm),
                "name": sound.name,
                "offset": cursor,
                "packed_size": len(output.data),
                "sample_rate": sound.sample_rate,
                "sha256": digest.hex(),
            }
        )
        cursor += len(output.data)
    header = PACK_HEADER.pack(
        PACK_MAGIC, PACK_VERSION, len(encoded), PACK_ENTRY.size, 0, index_offset, data_offset
    )
    return SoundPackResult(
        bytes(header + index + payload),
        sum(len(item.pcm) for item, _ in encoded),
        decoded_digest.hexdigest(),
        tuple(entries),
    )
