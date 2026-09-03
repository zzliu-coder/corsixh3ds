from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoStereoscopicRenderingTests(unittest.TestCase):
    def test_runtime_has_no_stereoscopic_path(self) -> None:
        forbidden = (
            "gfxSet3D(",
            "GFX_LEFT",
            "GFX_RIGHT",
            "stereoscopic",
            "slider3d",
            "3d_slider",
        )
        suffixes = {".cpp", ".hpp", ".c", ".h", ".lua", ".sh"}
        checked = 0
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if any(part.startswith("build") or part in {"external", "dist"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            checked += 1
            for token in forbidden:
                self.assertNotIn(token.lower(), text, f"{token} found in {path.relative_to(ROOT)}")
        self.assertGreater(checked, 20)


if __name__ == "__main__":
    unittest.main()
