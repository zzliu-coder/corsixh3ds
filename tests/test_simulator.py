from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class SimulatorTests(unittest.TestCase):
    def test_simulator_output_is_deterministic_when_binary_is_supplied(self) -> None:
        binary = os.environ.get("CTH3DS_SIMULATOR")
        if not binary:
            self.skipTest("CTH3DS_SIMULATOR not supplied")
        executable = Path(binary)
        if not executable.is_file():
            self.skipTest(f"simulator binary missing: {executable}")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "one", root / "two"
            subprocess.run([str(executable), str(first)], check=True, capture_output=True, text=True)
            subprocess.run([str(executable), str(second)], check=True, capture_output=True, text=True)
            for name in ("top.ppm", "bottom.ppm", "trace.json"):
                self.assertEqual(
                    hashlib.sha256((first / name).read_bytes()).hexdigest(),
                    hashlib.sha256((second / name).read_bytes()).hexdigest(),
                )
            trace = json.loads((first / "trace.json").read_text())
            self.assertEqual(trace["top"], [400, 240])
            self.assertEqual(trace["bottom"], [320, 240])


if __name__ == "__main__":
    unittest.main()
