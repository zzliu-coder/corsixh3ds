from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from th3ds_pack import PackError, build_pack, collect_files, inspect_pack, stage_sd_tree


class PackerTests(unittest.TestCase):
    def make_source(self, root: Path) -> Path:
        source = root / "Hospital"
        for name in ("DATA", "LEVELS", "QDATA", "SOUND"):
            directory = source / name
            directory.mkdir(parents=True)
            (directory / f"{name.lower()}.bin").write_bytes((name + " payload").encode())
        (source / "ANIMS").mkdir()
        (source / "ANIMS" / "anim.dat").write_bytes(b"animation")
        (source / "SAVE").mkdir()
        (source / "SAVE" / "player.sav").write_bytes(b"private mutable state")
        return source

    def test_collect_validates_required_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "empty"
            source.mkdir()
            with self.assertRaises(PackError):
                collect_files(source)

    def test_pack_is_deterministic_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            files = collect_files(source)
            first = root / "first.thp"
            second = root / "second.thp"
            build_pack(files, first)
            build_pack(list(reversed(files)), second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            entries = inspect_pack(first, verify=True)
            self.assertEqual(len(entries), len(files))
            self.assertEqual([entry.path for entry in entries], sorted(item.relative_path for item in files))

    def test_corruption_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            pack = root / "data.thp"
            build_pack(collect_files(source), pack)
            raw = bytearray(pack.read_bytes())
            raw[-1] ^= 0xFF
            pack.write_bytes(raw)
            with self.assertRaises(PackError):
                inspect_pack(pack, verify=True)

    def test_stage_writes_config_manifest_and_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            output = root / "sd"
            manifest = stage_sd_tree(source, output)
            staged = output / "3ds" / "corsixth"
            self.assertTrue((staged / "config.txt").is_file())
            self.assertTrue((staged / "theme-hospital.thp").is_file())
            self.assertTrue((staged / "game" / "DATA" / "data.bin").is_file())
            config = (staged / "config.txt").read_text(encoding="utf-8")
            self.assertIn("width = 640", config)
            self.assertIn("height = 480", config)
            self.assertIn("ui_scale = 1", config)
            self.assertNotIn("ui_scale = 0.5", config)
            on_disk = json.loads((staged / "manifest.json").read_text())
            self.assertEqual(on_disk["file_count"], manifest["file_count"])
            self.assertFalse(on_disk["pack_runtime_mounted"])
            self.assertEqual(on_disk["runtime_data_path"], "game")
            self.assertFalse((staged / "game" / "SAVE").exists())
            self.assertNotIn(b"private mutable state", (staged / "theme-hospital.thp").read_bytes())

    def test_case_insensitive_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            # macOS commonly uses a case-insensitive filesystem. Such a
            # volume cannot represent the two distinct directory entries
            # required to exercise the packer's collision guard, so record
            # the environmental limitation instead of silently overwriting
            # the first file.
            probe = source / "DATA" / "cth3ds-case-probe"
            probe.write_bytes(b"probe")
            if (source / "DATA" / "CTH3DS-CASE-PROBE").exists():
                self.skipTest("case-insensitive filesystem cannot create collision fixture")
            probe.unlink()
            (source / "DATA" / "Case.dat").write_bytes(b"a")
            (source / "DATA" / "case.DAT").write_bytes(b"b")
            with self.assertRaises(PackError):
                collect_files(source)


if __name__ == "__main__":
    unittest.main()
