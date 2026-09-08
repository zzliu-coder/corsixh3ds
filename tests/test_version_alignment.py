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
        revision = "R63"
        for token in (f'"{revision} " + state.build_tag',
                      f'"CORSIXTH {revision} "', f'revision={revision}',
                      f'memcmp(magic,"{revision}\\n",4)',
                      f'sdmc:/3ds/corsixth/benchmark-used-{revision.lower()}.txt'):
            self.assertTrue(token in runtime, f'candidate identity is missing: {token}')
        self.assertNotIn('benchmark-used-r62.txt', runtime,
                         'previous candidate marker must remain untouched')
        self.assertNotIn('"CORSIXTH R53 "', runtime)
        self.assertTrue('benchmark-used-r53.txt' not in runtime,
                        'old benchmark marker must remain untouched')


if __name__ == "__main__":
    unittest.main()
