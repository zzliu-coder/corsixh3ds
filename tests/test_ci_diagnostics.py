from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXACT_STRESS_RUNTIME = sys.version_info[:2] in {(3, 9), (3, 14)}
SERIAL_RUNS = 100 if EXACT_STRESS_RUNTIME else 1
CONCURRENT_RUNS = 100 if EXACT_STRESS_RUNTIME else 20
CONCURRENT_WORKERS = 20


def run_command_case(output: Path, matrix: str, marker: str, exit_code: int):
    return subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "run_ci_command.sh"),
            matrix,
            str(output),
            "--",
            "bash",
            "-c",
            'printf "%s\\n" "$1"; exit "$2"',
            "diagnostic-case",
            marker,
            str(exit_code),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def read_summary_and_log(output: Path):
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    log_path = output / "command.log"
    content = log_path.read_bytes()
    return summary, log_path, content


class CiDiagnosticsTests(unittest.TestCase):
    def assert_log_artifact(self, summary, log_path: Path, content: bytes) -> None:
        self.assertEqual(summary["logs"], [str(log_path)])
        self.assertEqual(summary["log_validation_errors"], [])
        self.assertEqual(
            summary["log_artifacts"],
            [
                {
                    "path": str(log_path),
                    "byte_size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ],
        )

    def assert_failure_case(self, output: Path, result, marker: str) -> None:
        self.assertEqual(result.returncode, 23, result.stderr)
        summary, log_path, content = read_summary_and_log(output)
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["stage"], "command")
        self.assertEqual(summary["exit_code"], 23)
        self.assertIn("exit", summary["failed_command"])
        self.assertEqual(content, f"{marker}\n".encode())
        self.assert_log_artifact(summary, log_path, content)
        tail_header = result.stderr.index(f"[cth3ds-ci] tail: {log_path}")
        raw_marker = result.stderr.index(marker, tail_header)
        machine_summary = result.stderr.index(
            "[cth3ds-ci] machine summary:", raw_marker
        )
        self.assertLess(tail_header, raw_marker)
        self.assertLess(raw_marker, machine_summary)

    def test_failure_injection_preserves_diagnostics_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            first_summary = None
            first_identity = None
            for index in range(SERIAL_RUNS):
                output = temporary_root / f"failure-{index}"
                marker = f"bounded failure marker {index}"
                result = run_command_case(
                    output, "injected-failure", marker, 23
                )
                self.assert_failure_case(output, result, marker)
                if index == 0:
                    first_summary = json.loads(
                        (output / "summary.json").read_text(encoding="utf-8")
                    )
                    first_identity = json.loads(
                        (output / "identity.json").read_text(encoding="utf-8")
                    )

            assert first_summary is not None
            assert first_identity is not None
            summary = first_summary
            identity = first_identity
            self.assertEqual(summary["matrix"], "injected-failure")
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
            temporary_root = Path(temporary)
            for index in range(SERIAL_RUNS):
                output = temporary_root / f"success-{index}"
                marker = f"success marker {index}"
                result = run_command_case(
                    output, "injected-success", marker, 0
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                summary, log_path, content = read_summary_and_log(output)
                self.assertEqual(summary["status"], "PASS")
                self.assertEqual(summary["exit_code"], 0)
                self.assertIsNone(summary["failed_command"])
                self.assertEqual(content, f"{marker}\n".encode())
                self.assert_log_artifact(summary, log_path, content)

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

            missing_output = Path(temporary) / "missing-log-evidence"
            missing_log = Path(temporary) / "missing.log"
            missing_command = (
                'source "$1"; ci_diag_init missing-log "$2"; '
                'ci_diag_step validation "$3"; ci_diag_mark_pass'
            )
            missing_result = subprocess.run(
                [
                    "bash",
                    "-c",
                    missing_command,
                    "missing-log-test",
                    str(ROOT / "scripts" / "ci_diagnostics.sh"),
                    str(missing_output),
                    str(missing_log),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(missing_result.returncode, 74, missing_result.stderr)
            missing_summary = json.loads(
                (missing_output / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(missing_summary["status"], "FAIL")
            self.assertEqual(missing_summary["exit_code"], 74)
            self.assertTrue(missing_summary["log_validation_errors"])
            self.assertIn("error", missing_summary["log_artifacts"][0])

            concurrent_root = Path(temporary) / "concurrent"

            def execute(index: int):
                output = concurrent_root / str(index)
                marker = f"concurrent raw marker {index}"
                return output, marker, run_command_case(
                    output, "concurrent-failure", marker, 23
                )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=CONCURRENT_WORKERS
            ) as executor:
                outcomes = list(executor.map(execute, range(CONCURRENT_RUNS)))
            for output, marker, concurrent_result in outcomes:
                self.assert_failure_case(output, concurrent_result, marker)

if __name__ == "__main__":
    unittest.main()
