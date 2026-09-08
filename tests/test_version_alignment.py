from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VersionAlignmentTests(unittest.TestCase):
    def test_public_and_embedded_versions_match(self) -> None:
        version = (ROOT / "VERSION").read_text().strip()
        cmake = (ROOT / "CMakeLists.txt").read_text()
        integrator = (ROOT / "tools/integration/common.py").read_text()
        runtime = (ROOT / "src" / "3ds" / "runtime_3ds.cpp").read_text()
        self.assertRegex(cmake, rf"project\(corsixth_3ds_port VERSION {re.escape(version)}\b")
        self.assertIn(f'OVERLAY_VERSION = "{version}"', integrator)
        self.assertIn(f'lua_pushstring(state, "{version}");', runtime)
        # The displayed candidate and one-shot benchmark must identify this
        # revision too; a matching semantic version alone cannot distinguish
        # consecutive hardware candidates.
        self.assertIn('"R59 " + state.build_tag', runtime)
        self.assertIn('"CORSIXTH R59 "', runtime)
        self.assertIn('revision=R59', runtime)
        self.assertTrue(r'memcmp(magic,"R59\n",4)' in runtime,
                        'one-shot marker must match R59 exactly')
        self.assertTrue('sdmc:/3ds/corsixth/benchmark-used-r59.txt' in runtime,
                        'consumed benchmark marker must identify R59')
        self.assertNotIn('"CORSIXTH R53 "', runtime)
        self.assertTrue('benchmark-used-r53.txt' not in runtime,
                        'old benchmark marker must remain untouched')


if __name__ == "__main__":
    unittest.main()
