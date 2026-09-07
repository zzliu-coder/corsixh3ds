"""The compiled-in Lua adapter must match lua/3ds/platform.lua exactly.

If they drift, a binary built from this tree would fall back to a different
adapter than the one under review, which is precisely the class of
binary/source mismatch this port is trying to eliminate.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EmbeddedAdapterTests(unittest.TestCase):
    def test_generator_uses_python39_exact_lf_write(self) -> None:
        source = (ROOT / "tools/embed_platform_lua.py").read_text(encoding="utf-8")
        self.assertIn('HEADER.open("w", encoding="utf-8", newline="\\n")', source)
        self.assertNotIn("write_text(expected", source)

    def test_generated_header_is_current(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "embed_platform_lua.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_header_contains_attach_entry_point(self) -> None:
        header = (ROOT / "src" / "3ds" / "embedded_platform_lua.hpp").read_text()
        self.assertIn("function module.attach(app, native, capabilities)", header)
        self.assertIn("kEmbeddedPlatformLua", header)

    def test_runtime_uses_the_embedded_fallback(self) -> None:
        runtime = (ROOT / "src" / "3ds" / "runtime_3ds.cpp").read_text()
        self.assertIn("embedded_platform_lua.hpp", runtime)
        self.assertIn("kEmbeddedPlatformLua", runtime)
        self.assertIn("ensure_adapter", runtime)


if __name__ == "__main__":
    unittest.main()
