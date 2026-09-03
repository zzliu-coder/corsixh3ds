from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from v061_acceptance import BOOT_IDENTITY_SCHEMA, REQUIRED_STAGES, build
from validate_sd_tree import validate_sd_tree, write_boot_contract, write_sd_manifest


CANDIDATE_COMMIT = "1" * 40
CANDIDATE_TREE = "2" * 40


class V061AcceptanceTests(unittest.TestCase):
    def make_package(self, root: Path) -> Path:
        package = root / "package"
        package.mkdir()
        (package / "CorsixTH-3DS.3dsx").write_bytes(
            b"3DSX" + struct.pack("<HH", 0x20, 4) + bytes(0x20 - 8)
        )
        (package / "CorsixTH.lua").write_text("-- synthetic\n", encoding="utf-8")
        (package / "config.txt").write_text("asset_mode = \"th3ds\"\n", encoding="utf-8")
        (package / "cth3ds-overlay-version.txt").write_text("0.6.1\n", encoding="utf-8")
        for name in ("Bitmap", "Campaigns", "Graphics", "Levels", "Lua"):
            directory = package / name
            directory.mkdir()
            (directory / "fixture.txt").write_text(name, encoding="utf-8")
        fixture = ROOT / "tests" / "runtime_core_v2" / "fixtures" / "no-level"
        resources = package / "resources"
        (resources / "lang").mkdir(parents=True)
        shutil.copy2(fixture / "bundle.json", resources / "bundle.th3ds.json")
        shutil.copy2(fixture / "core.package.bin", resources / "core.th3ds")
        shutil.copy2(fixture / "lang" / "en.package.bin", resources / "lang" / "en.th3ds")
        write_boot_contract(
            package,
            asset_mode="th3ds",
            candidate_commit=CANDIDATE_COMMIT,
            candidate_tree=CANDIDATE_TREE,
        )
        write_sd_manifest(package)
        return package

    def make_evidence(self, root: Path, *, python_status: str = "OK", python_skipped: int = 0) -> argparse.Namespace:
        package = self.make_package(root)
        host = {
            "actual_upstream_api_checked": True,
            "cpp_failed": 0,
            "cpp_tests": 62,
            "python_tests": 10,
            "python_skipped": python_skipped,
            "matrices": [{"name": "gcc-sanitized", "ctest_failed": 0, "ctest_total": 62}],
            "arm_codegen_checked": True,
            "true_3ds_cross_build_executed": True,
        }
        (root / "host.json").write_text(json.dumps(host), encoding="utf-8")
        (root / "heap.json").write_text(json.dumps({"pass": True, "valueBytes": 8388608}), encoding="utf-8")
        skip_line = (
            "test_optional (fixture.Case.test_optional) ... skipped 'fixture'\n"
            if python_skipped
            else ""
        )
        (root / "python-tests.log").write_text(
            skip_line
            + "..........\n"
            "----------------------------------------------------------------------\n"
            f"Ran 10 tests in 0.100s\n\n{python_status}\n",
            encoding="utf-8",
        )
        return argparse.Namespace(
            host_summary=root / "host.json",
            python_test_log=root / "python-tests.log",
            expected_python_skip=[],
            heap_budget=root / "heap.json",
            package=package,
            deploy_report=None,
            boot_log=None,
        )

    def add_deploy(self, args: argparse.Namespace, root: Path) -> dict[str, object]:
        package = validate_sd_tree(args.package)
        deploy = {
            "ok": True,
            "deploymentId": "deploy-001",
            "deviceId": "old3ds-unit-001",
            "deployedAt": "2026-09-03T10:00:00+00:00",
            "binarySha256": package["binary_sha256"],
            "manifestSha256": package["manifest_sha256"],
            "filesVerified": package["file_count"] + 1,
            "bytesVerified": package["total_bytes"],
        }
        args.deploy_report = root / "deploy.json"
        args.deploy_report.write_text(json.dumps(deploy), encoding="utf-8")
        return deploy

    def add_boot(
        self,
        args: argparse.Namespace,
        root: Path,
        deploy: dict[str, object],
        *,
        identity_overrides: dict[str, object] | None = None,
        stages: tuple[str, ...] = REQUIRED_STAGES,
        boot_started_at: str = "2026-09-03T10:01:00+00:00",
    ) -> None:
        package = validate_sd_tree(args.package)
        identity = {
            "schema": BOOT_IDENTITY_SCHEMA,
            "candidate_commit": package["candidate"]["commit"],
            "candidate_tree": package["candidate"]["tree"],
            "binary_sha256": package["binary_sha256"],
            "manifest_sha256": package["manifest_sha256"],
            "deployment_id": deploy["deploymentId"],
            "device_id": deploy["deviceId"],
            "boot_started_at": boot_started_at,
        }
        identity.update(identity_overrides or {})
        lines = ["acceptance-identity: " + json.dumps(identity, sort_keys=True)]
        lines.extend(f"stage[{stage}] fixture" for stage in stages)
        lines.extend(
            (
                "runtime: boot complete",
                "heap-probe[MAIN MENU]: PASS",
                "heap-probe[LEVEL READY]: PASS",
                "failure-injection[native-error]: PASS",
            )
        )
        args.boot_log = root / "boot.log"
        args.boot_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_host_pass_uses_raw_counts_and_does_not_claim_device_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_evidence(Path(temporary))
            result = build(args)
            self.assertEqual(result["host"]["H03"]["result"], "PASS")
            self.assertEqual(
                result["host"]["H03"]["evidence"]["counts"],
                {
                    "tests": 10,
                    "passed": 10,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                    "skip_records": [],
                },
            )
            self.assertEqual(result["gates"]["A_host_cross"], "PASS")
            self.assertEqual(result["gates"]["C_real_device"], "OPEN")
            self.assertEqual(result["release"], "NOT_PROVEN")

    def test_python_failure_error_and_skip_each_fail_with_exact_counts(self) -> None:
        cases = (
            ("FAILED (failures=1)", 0, {"failed": 1, "errors": 0, "skipped": 0, "passed": 9}),
            ("FAILED (errors=1)", 0, {"failed": 0, "errors": 1, "skipped": 0, "passed": 9}),
            ("OK (skipped=1)", 1, {"failed": 0, "errors": 0, "skipped": 1, "passed": 9}),
        )
        for status, skipped, expected in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                args = self.make_evidence(Path(temporary), python_status=status, python_skipped=skipped)
                row = build(args)["host"]["H03"]
                self.assertEqual(row["result"], "FAIL")
                for key, value in expected.items():
                    self.assertEqual(row["evidence"]["counts"][key], value)

    def test_explicit_expected_skip_is_counted_and_not_treated_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_evidence(
                Path(temporary), python_status="OK (skipped=1)", python_skipped=1
            )
            args.expected_python_skip = [
                "test_optional (fixture.Case.test_optional)"
            ]
            row = build(args)["host"]["H03"]
            self.assertEqual(row["result"], "PASS")
            self.assertEqual(row["evidence"]["counts"]["passed"], 9)
            self.assertEqual(row["evidence"]["counts"]["skipped"], 1)
            self.assertEqual(row["evidence"]["unexpected_skips"], [])

    def test_missing_or_unparseable_python_raw_log_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_evidence(root)
            args.python_test_log.unlink()
            self.assertEqual(build(args)["host"]["H03"]["result"], "FAIL")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_evidence(root)
            args.python_test_log.write_text("traceback without unittest summary", encoding="utf-8")
            self.assertEqual(build(args)["host"]["H03"]["result"], "FAIL")

    def test_empty_package_fails_host_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_evidence(root)
            empty = root / "empty"
            empty.mkdir()
            args.package = empty
            result = build(args)
            self.assertEqual(result["host"]["H07"]["result"], "FAIL")
            self.assertEqual(result["gates"]["A_host_cross"], "FAIL")
            self.assertEqual(result["release"], "FAIL")

    def test_deploy_readback_mismatch_fails_install_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_evidence(root)
            deploy = self.add_deploy(args, root)
            deploy["binarySha256"] = "0" * 64
            args.deploy_report.write_text(json.dumps(deploy), encoding="utf-8")
            result = build(args)
            self.assertEqual(result["device"]["D01"]["result"], "FAIL")
            self.assertEqual(result["gates"]["B_install_identity"], "FAIL")

    def test_empty_and_truncated_boot_logs_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_evidence(root)
            deploy = self.add_deploy(args, root)
            args.boot_log = root / "boot.log"
            args.boot_log.write_text("", encoding="utf-8")
            self.assertEqual(build(args)["device"]["D02"]["result"], "FAIL")
            self.add_boot(args, root, deploy, stages=REQUIRED_STAGES[:-1])
            self.assertEqual(build(args)["device"]["D02"]["result"], "FAIL")

    def test_old_boot_log_and_candidate_or_device_mismatch_fail(self) -> None:
        cases = (
            ({}, "2026-09-03T09:59:59+00:00"),
            ({"candidate_commit": "f" * 40}, "2026-09-03T10:01:00+00:00"),
            ({"device_id": "another-device"}, "2026-09-03T10:01:00+00:00"),
        )
        for overrides, started in cases:
            with self.subTest(overrides=overrides, started=started), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                args = self.make_evidence(root)
                deploy = self.add_deploy(args, root)
                self.add_boot(args, root, deploy, identity_overrides=overrides, boot_started_at=started)
                self.assertEqual(build(args)["device"]["D02"]["result"], "FAIL")

    def test_current_hash_bound_boot_passes_only_covered_device_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_evidence(root)
            deploy = self.add_deploy(args, root)
            self.add_boot(args, root, deploy)
            result = build(args)
            self.assertEqual(result["device"]["D01"]["result"], "PASS")
            self.assertEqual(result["device"]["D02"]["result"], "PASS")
            self.assertEqual(result["device"]["D10"]["result"], "PASS")
            self.assertEqual(result["device"]["D11"]["result"], "PASS")
            self.assertEqual(result["gates"]["C_real_device"], "OPEN")
            self.assertEqual(result["release"], "NOT_PROVEN")

    def test_malformed_json_input_becomes_fail_evidence_instead_of_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_evidence(root)
            args.host_summary.write_text("{broken", encoding="utf-8")
            result = build(args)
            self.assertEqual(result["host"]["H01"]["result"], "FAIL")
            self.assertEqual(result["release"], "FAIL")

    def test_cli_returns_nonzero_for_not_proven_ledger_after_writing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_evidence(root)
            output = root / "acceptance.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "v061_acceptance.py"),
                    "--host-summary",
                    str(args.host_summary),
                    "--python-test-log",
                    str(args.python_test_log),
                    "--heap-budget",
                    str(args.heap_budget),
                    "--package",
                    str(args.package),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(output.read_text())["release"], "NOT_PROVEN")


if __name__ == "__main__":
    unittest.main()
