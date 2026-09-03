from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from make_release import FIXED_TIME, main


class ReleaseArchiveTests(unittest.TestCase):
    def test_archives_are_reproducible_and_never_future_dated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            project = workspace / "project"
            output = workspace / "dist"
            (project / "docs").mkdir(parents=True)
            (project / "artifacts" / "verification").mkdir(parents=True)
            (project / "artifacts" / "preview").mkdir(parents=True)
            (project / "work" / "hardmac-runs").mkdir(parents=True)
            (project / "VERSION").write_text("9.8.7\n", encoding="utf-8")
            (project / "README.md").write_text("readme\n", encoding="utf-8")
            (project / "docs" / "VM_VERIFICATION.md").write_text("ok\n", encoding="utf-8")
            (project / "docs" / "HARDWARE_TEST_PLAN.md").write_text("plan\n", encoding="utf-8")
            (project / "artifacts" / "verification" / "summary.json").write_text("{}\n", encoding="utf-8")
            (project / "artifacts" / "preview" / "preview.txt").write_text("preview\n", encoding="utf-8")
            (project / "work" / "hardmac-runs" / "private.bin").write_bytes(b"private")

            self.assertEqual(main(["--root", str(project), "--output", str(output)]), 0)
            source = output / "corsixth-3ds-old3ds-v9.8.7-source.zip"
            first_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(main(["--root", str(project), "--output", str(output)]), 0)
            self.assertEqual(first_digest, hashlib.sha256(source.read_bytes()).hexdigest())

            fixed = datetime(*FIXED_TIME, tzinfo=timezone.utc)
            self.assertLess(fixed, datetime.now(timezone.utc))
            with zipfile.ZipFile(source) as archive:
                self.assertTrue(archive.infolist())
                self.assertTrue(all(info.date_time == FIXED_TIME for info in archive.infolist()))
                self.assertFalse(any("/work/" in info.filename for info in archive.infolist()))

            checksum_lines = (output / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(checksum_lines), 2)
            self.assertIn(source.name, checksum_lines[0])


if __name__ == "__main__":
    unittest.main()
