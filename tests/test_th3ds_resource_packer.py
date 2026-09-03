from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from th3ds_assets import build_glyph_atlas, build_language_bundle, convert_fullscreen_image
from th3ds_container import (
    AUDIO_ALIGNMENT,
    HEADER_SIZE,
    INDEX_ENTRY_SIZE,
    MAGIC,
    inspect_bundle,
    inspect_package,
)
from th3ds_convert import Budgets, ImageSpec, build_resource_tree
from th3ds_resource import ResourceError, canonical_json
from th3ds_sound import EncodedSound, PACK_HEADER, build_sound_pack, parse_sound_archive
from th3ds_sprite import HEADER as SPRITE_HEADER
from th3ds_sprite import build_sprite_pack
from th3ds_pack import main as packer_main


def pcm_wave(samples: bytes, *, channels: int = 1, rate: int = 11025, bits: int = 8) -> bytes:
    align = channels * bits // 8
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * align, align, bits)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks


def sound_archive(entries: list[tuple[str, bytes]]) -> bytes:
    payload = bytearray()
    rows: list[tuple[str, int, int]] = []
    for name, wave in entries:
        rows.append((name, len(payload), len(wave)))
        payload.extend(wave)
    header_position = len(payload)
    header = bytearray(234)
    table_position = header_position + len(header)
    struct.pack_into("<I", header, 50, table_position)
    struct.pack_into("<I", header, 58, len(rows) * 32)
    table = bytearray()
    for name, position, length in rows:
        row = bytearray(32)
        encoded = name.encode("ascii")
        row[: len(encoded)] = encoded
        struct.pack_into("<I", row, 18, position)
        struct.pack_into("<I", row, 26, length)
        table.extend(row)
    return bytes(payload + header + table + struct.pack("<I", header_position))


def make_fixture(root: Path) -> tuple[Path, Path, Path]:
    source = root / "Hospital"
    for name in ("DATA", "LEVELS", "QDATA", "SOUND/DATA"):
        (source / name).mkdir(parents=True)
    (source / "LEVELS" / "SECRET-ORIGINAL-GAME-DATA.BIN").write_bytes(b"must-not-be-copied")
    (source / "DATA" / "LANG-0.DAT").write_bytes(b"synthetic original strings")
    (source / "SOUND" / "DATA" / "SOUND-0.DAT").write_bytes(
        sound_archive([("BEEP.WAV", pcm_wave(b"\x00\x40\x80\xff")), ("TONE.WAV", pcm_wave(b"\x11\x22"))])
    )
    sprite_dat = b"\x04\x01\x02\x03\x04" + b"\x82"
    (source / "DATA" / "TINY.DAT").write_bytes(sprite_dat)
    (source / "DATA" / "TINY.TAB").write_bytes(struct.pack("<IBBIBB", 0, 2, 2, 5, 2, 1))

    pixels = bytearray(640 * 480)
    pixels[0] = 1
    (source / "QDATA" / "SPLASH.DAT").write_bytes(pixels)
    palette = bytearray(256 * 3)
    palette[3:6] = bytes((63, 0, 0))
    (source / "QDATA" / "SPLASH.PAL").write_bytes(palette)

    languages = root / "languages"
    languages.mkdir()
    (languages / "original_strings.lua").write_text('Language("original_strings")\n', encoding="utf-8")
    (languages / "english.lua").write_text(
        'Font("cp437")\nLanguage("English", "English", "en")\nInherit("original_strings", 0)\n',
        encoding="utf-8",
    )
    (languages / "unused.lua").write_text(
        'Language("Unused", "Unused", "xx")\nInherit("original_strings", 7)\n', encoding="utf-8"
    )

    atlas = root / "atlas"
    atlas.mkdir()
    (atlas / "ui.bin").write_bytes(b"\x00\x00" * 256 * 256)
    metadata = {
        "format": 1,
        "glyphs": [
            {"advance": 3, "bearing_x": 0, "bearing_y": 3, "codepoint": 65, "height": 3, "width": 2, "x": 0, "y": 0}
        ],
        "height": 256,
        "image": "ui.bin",
        "name": "ui",
        "pixel_format": "rgba5551",
        "width": 256,
    }
    metadata_path = atlas / "ui.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return source, languages, metadata_path


def hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


class ResourcePackerTests(unittest.TestCase):
    def test_convert_cli_publishes_versioned_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, languages, _atlas = make_fixture(root)
            output = root / "cli-output"
            self.assertEqual(
                packer_main(
                    [
                        "convert",
                        str(source),
                        str(output),
                        "--language-dir",
                        str(languages),
                        "--language",
                        "en",
                    ]
                ),
                0,
            )
            bundle = inspect_bundle((output / "bundle.th3ds.json").read_bytes())
            self.assertEqual(bundle["format"], {"major": 1, "minor": 0})
            self.assertEqual(bundle["selected_language"], "en")
            self.assertEqual([item["path"] for item in bundle["packages"]], ["core.th3ds", "lang/en.th3ds"])

    def test_end_to_end_tree_is_byte_identical_and_excludes_loose_game_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, languages, atlas = make_fixture(root)
            first = root / "first"
            second = root / "second"
            first_manifest = build_resource_tree(
                source, first, language_dir=languages, glyph_atlases=[atlas]
            )
            second_manifest = build_resource_tree(
                source, second, language_dir=languages, glyph_atlases=[atlas]
            )
            self.assertEqual(hash_tree(first), hash_tree(second))
            self.assertEqual(first_manifest["bundle_sha256"], second_manifest["bundle_sha256"])
            self.assertTrue(first_manifest["budget"]["pass"])
            self.assertEqual(first_manifest["format"], {"major": 1, "minor": 0, "name": "TH3DSR1"})
            self.assertEqual(
                sorted(path.relative_to(first).as_posix() for path in first.rglob("*") if path.is_file()),
                ["bundle.th3ds.json", "core.th3ds", "lang/en.th3ds"],
            )
            self.assertFalse(any("SECRET" in path.as_posix() for path in first.rglob("*")))
            output_bytes = b"".join(path.read_bytes() for path in first.rglob("*") if path.is_file())
            self.assertNotIn(b"must-not-be-copied", output_bytes)
            self.assertNotIn(b'Language("Unused"', output_bytes)
            for relative in ("core.th3ds", "lang/en.th3ds"):
                inspected = inspect_package((first / relative).read_bytes(), verify=True)
                self.assertGreater(len(inspected["entries"]), 0)
                for resource in inspected["entries"]:
                    self.assertRegex(resource["resource_id"], r"^[0-9a-f]{32}$")
                    self.assertRegex(resource["stored_sha256"], r"^[0-9a-f]{64}$")

    def test_sound_pack_has_random_access_offsets_and_pcm_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "SOUND-0.DAT"
            path.write_bytes(sound_archive([("A.WAV", pcm_wave(b"abc")), ("B.WAV", pcm_wave(b"defg"))]))
            parsed = parse_sound_archive(path.read_bytes())
            self.assertEqual([sound.pcm for sound in parsed], [b"abc", b"defg"])
            result = build_sound_pack(path)
            magic, version, count, entry_size, _flags, index_offset, data_offset = PACK_HEADER.unpack_from(result.data)
            self.assertEqual((magic, version, count), (b"TH3DSND1", 1, 2))
            self.assertGreater(data_offset, index_offset + entry_size)
            self.assertEqual(data_offset % AUDIO_ALIGNMENT, 0)
            self.assertEqual([item["codec"] for item in result.entries], ["pcm_u8", "pcm_u8"])
            self.assertEqual([item["offset"] for item in result.entries], sorted(item["offset"] for item in result.entries))

    def test_sound_rejects_out_of_bounds_archive_entry(self) -> None:
        raw = bytearray(sound_archive([("A.WAV", pcm_wave(b"abc"))]))
        header = struct.unpack_from("<I", raw, len(raw) - 4)[0]
        table = struct.unpack_from("<I", raw, header + 50)[0]
        struct.pack_into("<I", raw, table + 26, len(raw) + 1)
        with self.assertRaisesRegex(ResourceError, "outside"):
            parse_sound_archive(bytes(raw))

    def test_sound_rejects_nondeterministic_encoder_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "SOUND-0.DAT"
            path.write_bytes(sound_archive([("A.WAV", pcm_wave(b"abc"))]))
            calls = 0

            def unstable(_sound):
                nonlocal calls
                calls += 1
                return EncodedSound("dspadpcm", bytes((calls,)))

            with self.assertRaisesRegex(ResourceError, "nondeterministic"):
                build_sound_pack(path, unstable)

    def test_sprite_pack_indexes_independent_compressed_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tab = root / "sheet.tab"
            dat = root / "sheet.dat"
            tab.write_bytes(struct.pack("<IBBIBB", 0, 2, 2, 5, 2, 1))
            dat.write_bytes(b"\x04abcd\x82")
            result = build_sprite_pack(tab, dat)
            magic, version, count, _entry_size, compression, _offset = SPRITE_HEADER.unpack_from(result.data)
            self.assertEqual((magic, version, count, compression), (b"TH3DSP1\0", 1, 2, 1))
            self.assertEqual(_offset % 64, 0)
            self.assertEqual(result.decoded_size, 6)
            self.assertEqual([item["source_size"] for item in result.entries], [5, 1])

    def test_sprite_pack_rejects_out_of_bounds_and_nonmonotonic_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dat = root / "sheet.dat"
            dat.write_bytes(b"1234")
            bad_oob = root / "oob.tab"
            bad_oob.write_bytes(struct.pack("<IBB", 4, 1, 1))
            with self.assertRaisesRegex(ResourceError, "outside"):
                build_sprite_pack(bad_oob, dat)
            bad_order = root / "order.tab"
            bad_order.write_bytes(struct.pack("<IBBIBB", 2, 1, 1, 1, 1, 1))
            with self.assertRaisesRegex(ResourceError, "monotonic"):
                build_sprite_pack(bad_order, dat)

    def test_image_conversion_has_fixed_dimensions_and_alpha_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pixels = root / "image.dat"
            palette = root / "image.pal"
            raw = bytearray(640 * 480)
            raw[0] = 1
            pixels.write_bytes(raw)
            colours = bytearray(256 * 3)
            colours[3:6] = bytes((63, 0, 63))
            palette.write_bytes(colours)
            rgba = convert_fullscreen_image(
                pixels, palette, pixel_format="rgba5551", transparent_index=0
            )
            self.assertEqual(len(rgba), 320 * 240 * 2)
            self.assertEqual(struct.unpack_from("<H", rgba)[0], 0xF83E)
            with self.assertRaisesRegex(ResourceError, "transparent"):
                convert_fullscreen_image(pixels, palette, pixel_format="rgb565", transparent_index=0)

    def test_language_dependency_closure_and_missing_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, languages, _atlas = make_fixture(root)
            bundle = build_language_bundle(languages, "en", source)
            self.assertEqual(bundle.original_ids, (0,))
            self.assertEqual([path for path, _ in bundle.files if path.endswith(".lua")], [
                "languages/lua/original_strings.lua", "languages/lua/english.lua"
            ])
            (languages / "english.lua").write_text(
                'Language("English", "English")\nInherit("missing")\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(ResourceError, "missing language"):
                build_language_bundle(languages, "English", source)

    def test_glyph_atlas_rejects_out_of_bounds_glyph(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _source, _languages, atlas = make_fixture(root)
            metadata = json.loads(atlas.read_text())
            metadata["glyphs"][0]["x"] = 256
            atlas.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(ResourceError, "outside"):
                build_glyph_atlas(atlas)

    def test_budget_failure_does_not_publish_partial_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, languages, _atlas = make_fixture(root)
            output = root / "too-small"
            with self.assertRaisesRegex(ResourceError, "budget exceeded"):
                build_resource_tree(
                    source,
                    output,
                    language_dir=languages,
                    image_specs=[],
                    budgets=Budgets(max_output_bytes=1, audio_bytes=1),
                )
            self.assertFalse(output.exists())

    def test_container_layout_and_integrity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, languages, _atlas = make_fixture(root)
            output = root / "packed"
            build_resource_tree(source, output, language_dir=languages, image_specs=[])
            raw = bytearray((output / "core.th3ds").read_bytes())
            self.assertEqual(raw[:8], MAGIC)
            self.assertEqual(struct.unpack_from("<H", raw, 8)[0], HEADER_SIZE)
            self.assertEqual(struct.unpack_from("<I", raw, 0x1C)[0], INDEX_ENTRY_SIZE)
            inspected = inspect_package(bytes(raw), verify=True)
            offsets = [entry["resource_id"] for entry in inspected["entries"]]
            self.assertEqual(offsets, sorted(offsets))

            corrupt = bytearray(raw)
            corrupt[-1] ^= 1
            with self.assertRaisesRegex(ResourceError, "SHA-256|padding"):
                inspect_package(bytes(corrupt), verify=True)

            reserved = bytearray(raw)
            reserved[0xF0] = 1
            with self.assertRaisesRegex(ResourceError, "reserved"):
                inspect_package(bytes(reserved), verify=True)

            with self.assertRaisesRegex(ResourceError, "truncated|bounds|region"):
                inspect_package(bytes(raw[:-1]), verify=True)

            unknown_feature = bytearray(raw)
            struct.pack_into("<I", unknown_feature, 0xEC, 1)
            with self.assertRaisesRegex(ResourceError, "unsupported runtime feature"):
                inspect_package(bytes(unknown_feature), verify=True)

            index_offset = struct.unpack_from("<Q", raw, 0x30)[0]
            duplicate = bytearray(raw)
            duplicate[index_offset + INDEX_ENTRY_SIZE : index_offset + INDEX_ENTRY_SIZE + 16] = duplicate[index_offset : index_offset + 16]
            with self.assertRaisesRegex(ResourceError, "duplicate or out of order"):
                inspect_package(bytes(duplicate), verify=True)

            bundle = bytearray((output / "bundle.th3ds.json").read_bytes())
            bundle[-1] ^= 1
            with self.assertRaises(ResourceError):
                inspect_bundle(bytes(bundle))

            non_ascii = json.loads((output / "bundle.th3ds.json").read_bytes())
            non_ascii["packages"][0]["path"] = "café.th3ds"
            non_ascii["bundle_sha256"] = "0" * 64
            non_ascii["bundle_sha256"] = hashlib.sha256(canonical_json(non_ascii)).hexdigest()
            with self.assertRaisesRegex(ResourceError, "path is invalid"):
                inspect_bundle(canonical_json(non_ascii))

    def test_existing_output_is_never_merged_or_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, languages, _atlas = make_fixture(root)
            output = root / "existing"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ResourceError, "already exists"):
                build_resource_tree(source, output, language_dir=languages, image_specs=[])
            self.assertEqual(sentinel.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
