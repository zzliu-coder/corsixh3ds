"""Offline coverage for the device log fetcher."""

from __future__ import annotations

import ftplib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "cth3ds_fetch_log", ROOT / "tools" / "old3ds_fetch_log.py"
)
fetch_log = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = fetch_log
spec.loader.exec_module(fetch_log)


class FakeFtp:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def retrbinary(self, command: str, callback) -> None:
        remote = command.split(" ", 1)[1]
        if remote not in self.files:
            raise ftplib.error_perm("550 not found")
        callback(self.files[remote])


class FetchLogTests(unittest.TestCase):
    def test_writes_file_and_reports_size(self) -> None:
        payload = b"boot line 1\nboot line 2\n"
        ftp = FakeFtp({"/3ds/corsixth/boot.log": payload})
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "logs" / "boot.log"
            size = fetch_log.fetch_one(ftp, "/3ds/corsixth/boot.log", destination)
            self.assertEqual(size, len(payload))
            self.assertEqual(destination.read_bytes(), payload)

    def test_missing_remote_file_raises(self) -> None:
        ftp = FakeFtp({})
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(fetch_log.FetchError):
                fetch_log.fetch_one(ftp, "/3ds/corsixth/boot.log", Path(temporary) / "x")

    def test_default_set_includes_the_boot_log_and_version_stamp(self) -> None:
        self.assertIn("/3ds/corsixth/boot.log", fetch_log.DEFAULT_REMOTE_FILES)
        self.assertIn(
            "/3ds/corsixth/cth3ds-overlay-version.txt", fetch_log.DEFAULT_REMOTE_FILES
        )


if __name__ == "__main__":
    unittest.main()
