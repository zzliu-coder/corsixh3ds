from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from old3ds_ftp import DeployError, load_manifest, safe_relative_path


class Old3dsFtpTests(unittest.TestCase):
    def make_package(self, root: Path) -> None:
        binary = root / "CorsixTH-3DS.3dsx"
        binary.write_bytes(b"3DSX")
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        payload = {
            "format": 1,
            "root": "sdmc:/3ds/corsixth",
            "files": [{"path": binary.name, "size": 4, "sha256": digest}],
        }
        (root / "sd-manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_manifest_accepts_exact_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root)
            entries = load_manifest(root)
            self.assertEqual(entries[0].path, "CorsixTH-3DS.3dsx")

    def test_manifest_rejects_extra_or_traversal_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root)
            (root / "extra.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaises(DeployError):
                load_manifest(root)
        for unsafe in ("../escape", "/absolute", "a/../../escape"):
            with self.assertRaises(DeployError):
                safe_relative_path(unsafe)


if __name__ == "__main__":
    unittest.main()
