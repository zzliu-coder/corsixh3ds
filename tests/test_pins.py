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

from check_pins import PinError, load_manifest, lookup, main


class PinManifestTests(unittest.TestCase):
    def test_repository_manifest_is_valid_and_immutable(self) -> None:
        manifest = load_manifest(ROOT / "config/upstream-pins.json")
        self.assertEqual(lookup(manifest, "corsixth.tag"), "v0.70.1")
        self.assertEqual(len(lookup(manifest, "corsixth.commit")), 40)
        self.assertEqual(len(lookup(manifest, "lpeg.sha256")), 64)
        self.assertEqual(lookup(manifest, "devkitpro.docker_image"), "devkitpro/devkitarm:20260610")

    def test_invalid_commit_is_rejected(self) -> None:
        manifest = json.loads((ROOT / "config/upstream-pins.json").read_text())
        manifest["sdl2"]["commit"] = "moving-branch"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pins.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(PinError):
                load_manifest(path)

    def test_cli_query(self) -> None:
        self.assertEqual(main(["--manifest", str(ROOT / "config/upstream-pins.json"), "--get", "lua.tag"]), 0)


if __name__ == "__main__":
    unittest.main()
