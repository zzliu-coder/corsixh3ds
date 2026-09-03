from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VersionAlignmentTests(unittest.TestCase):
    def test_public_and_embedded_versions_match(self) -> None:
        version = (ROOT / "VERSION").read_text().strip()
        cmake = (ROOT / "CMakeLists.txt").read_text()
        integrator = (ROOT / "tools" / "integrate_corsixth.py").read_text()
        runtime = (ROOT / "src" / "3ds" / "runtime_3ds.cpp").read_text()
        self.assertRegex(cmake, rf"project\(corsixth_3ds_port VERSION {re.escape(version)}\b")
        self.assertIn(f'OVERLAY_VERSION = "{version}"', integrator)
        self.assertIn(f'lua_pushstring(state, "{version}");', runtime)


if __name__ == "__main__":
    unittest.main()
