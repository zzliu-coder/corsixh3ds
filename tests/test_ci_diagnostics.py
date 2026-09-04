from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiDiagnosticsTests(unittest.TestCase):
    def test_failure_injection_preserves_diagnostics_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_ci_command.sh"),
                    "injected-failure",
                    str(output),
                    "--",
                    "bash",
                    "-c",
                    "printf 'bounded failure marker\\n'; exit 23",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 23, result.stderr)
            summary = json.loads((output / "summary.json").read_text())
            identity = json.loads((output / "identity.json").read_text())
            command_log = (output / "command.log").read_text()

            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["matrix"], "injected-failure")
            self.assertEqual(summary["stage"], "command")
            self.assertEqual(summary["exit_code"], 23)
            self.assertIn("exit\\ 23", summary["failed_command"])
            self.assertIn("bounded failure marker", command_log)
            self.assertIn("bounded failure marker", result.stderr)
            self.assertIn("matrix: injected-failure", result.stderr)
            self.assertIn("failed command:", result.stderr)
            self.assertIn("machine summary:", result.stderr)
            self.assertEqual(
                identity["source"]["commit"],
                subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
            )
            self.assertEqual(
                identity["source"]["tree"],
                subprocess.check_output(
                    ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
                ).strip(),
            )
            self.assertEqual(
                identity["source"]["parents"],
                subprocess.check_output(
                    ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
                    cwd=ROOT,
                    text=True,
                ).split()[1:],
            )

    def test_success_path_writes_machine_readable_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_ci_command.sh"),
                    "injected-success",
                    str(output),
                    "--",
                    "bash",
                    "-c",
                    "printf 'success marker\\n'",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["exit_code"], 0)
            self.assertIsNone(summary["failed_command"])

    def test_fail_closed_preflight_keeps_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            command = 'source "{}"; source "{}"; ci_diag_init preflight-failure "{}"; ci_diag_step preflight; die "forced preflight failure"'.format(
                ROOT / "scripts" / "common.sh",
                ROOT / "scripts" / "ci_diagnostics.sh",
                output,
            )
            result = subprocess.run(
                ["bash", "-c", command],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["stage"], "preflight")
            self.assertEqual(summary["failed_command"], "forced preflight failure")
            self.assertIn("machine summary:", result.stderr)

            root = Path(temporary) / "not-a-repository"
            root.mkdir()
            non_git_output = Path(temporary) / "non-git-evidence"
            environment = os.environ.copy()
            non_git_command = (
                'set -euo pipefail; CTH3DS_ROOT="$1"; export CTH3DS_ROOT; '
                'source "$2"; ci_diag_init non-git-root "$3"; '
                "printf 'must not execute\\n'"
            )
            non_git_result = subprocess.run(
                [
                    "bash",
                    "-c",
                    non_git_command,
                    "non-git-test",
                    str(root),
                    str(ROOT / "scripts" / "ci_diagnostics.sh"),
                    str(non_git_output),
                ],
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(non_git_result.returncode, 0)
            non_git_summary = json.loads(
                (non_git_output / "summary.json").read_text()
            )
            identity = json.loads((non_git_output / "identity.json").read_text())
            self.assertEqual(non_git_summary["status"], "FAIL")
            self.assertEqual(non_git_summary["stage"], "source-identity")
            self.assertEqual(identity["source"]["status"], "FAIL")
            self.assertNotIn("commit", identity["source"])
            self.assertNotIn("tree", identity["source"])
            self.assertNotIn("dirty", identity["source"])
            self.assertNotIn("must not execute", non_git_result.stdout)

if __name__ == "__main__":
    unittest.main()
