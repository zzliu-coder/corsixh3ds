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
        # Product displays identify the current build. The existing one-shot
        # request protocol remains R63 so installed runner/marker files work.
        revision = "R74"
        for token in (f'"{revision} " + state.build_tag',
                      f'"CORSIXTH {revision} "', f'diagnostics: revision={revision}'):
            self.assertTrue(token in runtime, f'candidate identity is missing: {token}')
        self.assertNotIn('"R67 " + state.build_tag',runtime,'old status-strip identity must be detected')
        self.assertIn('memcmp(magic,"R63\\n",4)',runtime)
        self.assertIn('sdmc:/3ds/corsixth/benchmark-used-r63.txt',runtime)
        self.assertNotIn('benchmark-used-r62.txt', runtime,
                         'previous candidate marker must remain untouched')
        self.assertNotIn('"CORSIXTH R53 "', runtime)
        self.assertTrue('benchmark-used-r53.txt' not in runtime,
                        'old benchmark marker must remain untouched')


if __name__ == "__main__":
    unittest.main()
