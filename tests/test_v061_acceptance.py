from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from v061_acceptance import build


class V061AcceptanceTests(unittest.TestCase):
    def test_host_pass_does_not_claim_device_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            package.mkdir()
            host = {
                "actual_upstream_api_checked": True,
                "cpp_failed": 0,
                "cpp_tests": 62,
                "python_tests": 60,
                "python_skipped": 0,
                "matrices": [{"name": "gcc-sanitized", "ctest_failed": 0}],
                "arm_codegen_checked": True,
                "true_3ds_cross_build_executed": True,
            }
            (root / "host.json").write_text(json.dumps(host))
            (root / "heap.json").write_text(json.dumps({"pass": True, "valueBytes": 8388608}))
            args = argparse.Namespace(
                host_summary=root / "host.json",
                heap_budget=root / "heap.json",
                package=package,
                deploy_report=None,
                boot_log=None,
            )
            result = build(args)
            self.assertEqual(result["gates"]["A_host_cross"], "PASS")
            self.assertEqual(result["gates"]["C_real_device"], "OPEN")
            self.assertEqual(result["release"], "NOT_PROVEN")


if __name__ == "__main__":
    unittest.main()
