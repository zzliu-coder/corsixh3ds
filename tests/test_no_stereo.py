from __future__ import annotations

import unittest
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoStereoscopicRenderingTests(unittest.TestCase):
    def test_runtime_has_no_stereoscopic_path(self) -> None:
        forbidden = (
            "gfxSet3D(",
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
        # libctru uses the left framebuffer selector for ordinary mono output.
        # Require both LCD outputs to use that selector; no alternate eye path.
        renderer = (ROOT / "src/3ds/runtime/gpu_renderer.cpp").read_text()
        outputs = re.findall(
            r"C3D_RenderTargetSetOutput\(enable\?(top_target|bottom_target):nullptr,"
            r"(GFX_TOP|GFX_BOTTOM),(GFX_LEFT),", renderer
        )
        self.assertEqual(outputs, [
            ("top_target", "GFX_TOP", "GFX_LEFT"),
            ("bottom_target", "GFX_BOTTOM", "GFX_LEFT"),
        ])
        self.assertEqual(renderer.count("C3D_RenderTargetSetOutput("), 2)
        # R54 also reads the ordinary framebuffer for startup diagnostics.
        # Validate each consumer's selector, independently of the number of
        # output registrations; readback must not become a second-eye path.
        reads = re.findall(r"gfxGetFramebuffer\(\s*(\w+)\s*,\s*(\w+)\s*,", renderer)
        self.assertEqual(reads, [("screen", "GFX_LEFT")])
        self.assertEqual(renderer.count("GFX_LEFT"), len(outputs) + len(reads))


if __name__ == "__main__":
    unittest.main()
