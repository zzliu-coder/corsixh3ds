from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from make_preview import PreviewError, build_preview, read_ppm


class PreviewTests(unittest.TestCase):
    @staticmethod
    def write_ppm(path: Path, width: int, height: int) -> None:
        pixels = bytes((index % 251 for index in range(width * height * 3)))
        path.write_bytes(f"P6\n{width} {height}\n255\n".encode() + pixels)

    def test_dual_screen_preview_is_valid_png(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            top, bottom, output = root / "top.ppm", root / "bottom.ppm", root / "out.png"
            self.write_ppm(top, 400, 240)
            self.write_ppm(bottom, 320, 240)
            build_preview(top, bottom, output)
            data = output.read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
            width, height = struct.unpack(">II", data[16:24])
            self.assertEqual((width, height), (440, 560))

    def test_wrong_screen_size_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            top, bottom = root / "top.ppm", root / "bottom.ppm"
            self.write_ppm(top, 399, 240)
            self.write_ppm(bottom, 320, 240)
            with self.assertRaises(PreviewError):
                build_preview(top, bottom, root / "out.png")


if __name__ == "__main__":
    unittest.main()
