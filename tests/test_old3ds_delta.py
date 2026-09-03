from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from old3ds_delta import DEFAULT_FILES, DeltaError, safe_relative


class Old3dsDeltaTests(unittest.TestCase):
    def test_delta_scope_excludes_user_data(self) -> None:
        self.assertIn("CorsixTH-3DS.3dsx", DEFAULT_FILES)
        self.assertIn("Lua/app.lua", DEFAULT_FILES)
        for protected in ("game", "Saves", "config.txt", "Logs"):
            self.assertNotIn(protected, DEFAULT_FILES)

    def test_relative_paths_are_bounded(self) -> None:
        self.assertEqual(safe_relative("Lua/app.lua"), "Lua/app.lua")
        for unsafe in ("../game", "/3ds/corsixth", "Lua/../../escape"):
            with self.assertRaises(DeltaError):
                safe_relative(unsafe)


if __name__ == "__main__":
    unittest.main()
