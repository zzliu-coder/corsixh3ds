from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Dict, List, Optional


ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/run_verifier_python.sh"
DRIVER = ROOT / "scripts/verifier_driver.py"
LOCK = ROOT / "requirements/verifier.lock"
LOCK_SHA256 = "0bec73ce08a019ea3b7a78429f75d03e074d25c0599c8e5a770f25cbbe93bf37"
WORKERS = (
    ROOT / "scripts/verify_runtime_core_v2.py",
    ROOT / "scripts/consume_runtime_core_v2.py",
    ROOT / "tests/runtime_core_v2/evidence_protocol_adversarial.py",
)


class AuthorityContractTests(unittest.TestCase):
    evidence_root: Optional[pathlib.Path] = None
    sandbox: tempfile.TemporaryDirectory
    env_dir: pathlib.Path
    clean_environment: Dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        raw = os.environ.get("CTH3DS_AUTHORITY_NEGATIVE_EVIDENCE")
        cls.evidence_root = pathlib.Path(raw).absolute() if raw else None
        cls.sandbox = tempfile.TemporaryDirectory(prefix="cth3ds-authority-contract-")
        root = pathlib.Path(cls.sandbox.name).resolve()
        cls.env_dir = root / "verifier-environment"
        cls.clean_environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("CTH3DS_VERIFIER_") and
            key not in {"PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE",
                        "PYTHONSTARTUP", "PYTHONINSPECT", "VIRTUAL_ENV"}}
        bootstrap = subprocess.run([
            "bash", str(WRAPPER), "--bootstrap-python", sys.executable,
            "--env-dir", str(cls.env_dir), "--evidence-dir",
            str(root / "bootstrap"), "check-env"], cwd=ROOT,
            env=cls.clean_environment, text=True, capture_output=True,
            check=False)
        if bootstrap.returncode != 0:
            raise RuntimeError("authority test environment bootstrap failed: " +
                               bootstrap.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.sandbox.cleanup()

    def record(self, case_id: str, subcase: str,
               result: subprocess.CompletedProcess) -> None:
        if self.evidence_root is None:
            return
        root = self.evidence_root / case_id / subcase
        root.mkdir(parents=True, exist_ok=True)
        stdout = result.stdout if isinstance(result.stdout, str) else (result.stdout or b"").decode(errors="replace")
        stderr = result.stderr if isinstance(result.stderr, str) else (result.stderr or b"").decode(errors="replace")
        (root / "stdout").write_text(stdout, encoding="utf-8")
        (root / "stderr").write_text(stderr, encoding="utf-8")
        (root / "exit.json").write_text(json.dumps({
            "case": case_id, "subcase": subcase, "exit": result.returncode,
            "authoritative_result_exists": False,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def wrapper(self, case_id: str, subcase: str, args: List[str],
                extra_env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
        environment = self.clean_environment.copy()
        if extra_env:
            environment.update(extra_env)
        call_evidence = pathlib.Path(self.sandbox.name) / "calls" / case_id / subcase
        result = subprocess.run(["bash", str(WRAPPER),
                                "--bootstrap-python", sys.executable,
                                "--env-dir", str(self.env_dir),
                                "--evidence-dir", str(call_evidence), *args], cwd=ROOT,
                                env=environment, text=True, capture_output=True,
                                check=False)
        if self.evidence_root is not None and call_evidence.exists():
            target = self.evidence_root / case_id / subcase / "wrapper-evidence"
            shutil.copytree(call_evidence, target, dirs_exist_ok=True)
        self.record(case_id, subcase, result)
        return result

    def direct(self, case_id: str, subcase: str, argv: List[str],
               extra_env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        if extra_env:
            environment.update(extra_env)
        result = subprocess.run(argv, cwd=ROOT, env=environment, text=True,
                                capture_output=True, check=False)
        self.record(case_id, subcase, result)
        return result

    def test_positive_lock_and_closed_source_contract(self) -> None:
        self.assertEqual(hashlib.sha256(LOCK.read_bytes()).hexdigest(), LOCK_SHA256)
        text = LOCK.read_text(encoding="utf-8")
        for item in ("attrs==25.3.0", "jsonschema==4.25.1",
                     "jsonschema-specifications==2025.9.1", "referencing==0.36.2",
                     "rpds-py==0.27.1", "typing-extensions==4.14.1"):
            self.assertIn(item, text)
        wrapper = WRAPPER.read_text(encoding="utf-8")
        self.assertNotIn("CTH3DS_VERIFIER_LOCK:-", wrapper)
        self.assertIn("--require-hashes --only-binary=:all:", wrapper)
        driver = DRIVER.read_text(encoding="utf-8")
        self.assertIn("class VerifiedInvocation", driver)
        self.assertIn("allow_abbrev=False", driver)
        self.assertIn('"host_python_runner": "scripts/run_host_python_suite.py"', driver)
        self.assertIn('"host_python_manifest": "tests/host-python-suite.json"', driver)
        self.assertNotIn("_compat-embed-platform-check", driver)
        producer = WORKERS[0].read_text(encoding="utf-8")
        self.assertNotIn("pathlib.Path.write_text =", producer)
        self.assertNotIn("subprocess.run =", producer)
        consumer = WORKERS[1].read_text(encoding="utf-8")
        self.assertIn("parse_host_python_receipt", consumer)
        self.assertNotIn("python_counts = parse_unittest_counts", consumer)

    def test_W0_N01_wrapper_c(self) -> None:
        result = self.wrapper("W0-N01", "dash-c", ["-c", "print(1)"])
        self.assertEqual(result.returncode, 64)

    def test_W0_N02_wrapper_script(self) -> None:
        result = self.wrapper("W0-N02", "script", [str(WORKERS[0])])
        self.assertEqual(result.returncode, 64)

    def test_W0_N03_unknown_missing_repeated(self) -> None:
        for name, args in (("unknown", ["unknown"]), ("missing", []),
                           ("repeated", ["check-env", "check-env"])):
            result = self.wrapper("W0-N03", name, args)
            self.assertEqual(result.returncode, 64)

    def test_W0_N04_reserved_authority_environment(self) -> None:
        for name in ("CTH3DS_VERIFIER_CANONICAL", "CTH3DS_VERIFIER_LOCK_SHA256",
                     "CTH3DS_VERIFIER_PYTHON_DISPATCH"):
            result = self.wrapper("W0-N04", name, ["check-env"], {name: "forged"})
            self.assertEqual(result.returncode, 64)
            self.assertIn("RESERVED_AUTHORITY_ENV", result.stderr)

    def test_W0_N05_direct_protocol_forgery(self) -> None:
        result = self.direct("W0-N05", "forged", [sys.executable, str(WORKERS[2]),
            "--protocol-self-test", "--help"], {
            "CTH3DS_VERIFIER_CANONICAL": "1",
            "CTH3DS_VERIFIER_LOCK_SHA256": LOCK_SHA256,
            "CTH3DS_VERIFIER_PYTHON_DISPATCH": sys.executable})
        self.assertEqual(result.returncode, 64)
        self.assertIn("DIRECT_ENTRY_FORBIDDEN", result.stderr)

    def test_W0_N06_N07_driver_wrong_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = pathlib.Path(temporary) / "evidence"
            versioned = self.env_dir / "bin" / (
                "python%d.%d" % (sys.version_info.major, sys.version_info.minor))
            if not versioned.exists():
                versioned = pathlib.Path(temporary) / "python-version-alias"
                versioned.symlink_to(self.env_dir / "bin/python")
            for case_id, name, executable in (
                ("W0-N06", "other-prefix", sys.executable),
                ("W0-N07", "wrong-lexical-python3", str(self.env_dir / "bin/python3")),
                ("W0-N07", "wrong-lexical-version", str(versioned))):
                result = self.direct(case_id, name, [executable, "-I", str(DRIVER),
                    "--evidence-dir", str(evidence / name), "check-env"])
                self.assertEqual(result.returncode, 2)

    def test_W0_N08_dispatch_shapes_are_audited(self) -> None:
        dispatch = self.env_dir / "bin/cth3ds-verifier-python"
        original = dispatch.read_bytes()
        original_mode = dispatch.stat().st_mode
        changed = original.replace(b" -I ", b" -E ", 1)
        dispatch.write_bytes(changed)
        try:
            result = self.wrapper("W0-N08", "changed-content", ["check-env"])
            self.assertEqual(result.returncode, 2)
        finally:
            dispatch.write_bytes(original)
            dispatch.chmod(original_mode)
        for subcase in ("regular", "symlink", "hardlink"):
            backup = dispatch.with_name(dispatch.name + ".saved")
            dispatch.rename(backup)
            try:
                if subcase == "regular":
                    dispatch.write_bytes(b"#!/bin/sh\nexit 0\n")
                    dispatch.chmod(0o755)
                elif subcase == "symlink":
                    dispatch.symlink_to(backup)
                else:
                    os.link(backup, dispatch)
                result = self.wrapper("W0-N08", subcase, ["check-env"])
                self.assertEqual(result.returncode, 2)
            finally:
                dispatch.unlink(missing_ok=True)
                backup.rename(dispatch)

    def test_W0_N09_N10_N11_workers_forbid_all_direct_entry(self) -> None:
        for index, worker in enumerate(WORKERS, start=9):
            for subcase, tail in (("empty", []), ("help", ["--help"])):
                case_id = "W0-N%02d" % index
                result = self.direct(case_id, subcase,
                                     [sys.executable, str(worker), *tail])
                self.assertEqual(result.returncode, 64)
                self.assertIn("DIRECT_ENTRY_FORBIDDEN", result.stderr)

    def test_W0_N12_lock_change_fails_before_bootstrap(self) -> None:
        original = LOCK.read_bytes()
        try:
            LOCK.write_bytes(original + b"# mutation\n")
            result = self.wrapper("W0-N12", "lock", ["check-env"])
            self.assertEqual(result.returncode, 2)
        finally:
            LOCK.write_bytes(original)
        marker = self.env_dir / ".cth3ds-verifier-environment.json"
        original_marker = marker.read_bytes()
        try:
            marker.write_bytes(original_marker + b" ")
            result = self.wrapper("W0-N12", "marker", ["check-env"])
            self.assertEqual(result.returncode, 2)
        finally:
            marker.write_bytes(original_marker)

    def test_W0_N13_N14_dependency_file_inventory_is_exact(self) -> None:
        site_packages = next((self.env_dir / "lib").glob("python*/site-packages"))
        attrs_info = next(site_packages.glob("attrs-*.dist-info"))
        missing = attrs_info.with_name(attrs_info.name + ".missing")
        attrs_info.rename(missing)
        try:
            result = self.wrapper("W0-N13", "missing", ["check-env"])
            self.assertEqual(result.returncode, 2)
        finally:
            missing.rename(attrs_info)
        metadata = attrs_info / "METADATA"
        original_metadata = metadata.read_bytes()
        try:
            metadata.write_bytes(original_metadata.replace(
                b"Version: 25.3.0", b"Version: 00.0.0", 1))
            result = self.wrapper("W0-N13", "version", ["check-env"])
            self.assertEqual(result.returncode, 2)
        finally:
            metadata.write_bytes(original_metadata)
        dependency_file = site_packages / "attrs/__init__.py"
        original_file = dependency_file.read_bytes()
        try:
            dependency_file.write_bytes(original_file + b"# mutation\n")
            result = self.wrapper("W0-N14", "file-content", ["check-env"])
            self.assertEqual(result.returncode, 2)
        finally:
            dependency_file.write_bytes(original_file)

    def test_W0_N15_pythonpath_injection(self) -> None:
        result = self.wrapper("W0-N15", "pythonpath", ["check-env"],
                              {"PYTHONPATH": "/tmp/forged"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("FORBIDDEN_PYTHON_ENV", result.stderr)

    def test_W0_N16_user_site_injection(self) -> None:
        for name in ("PYTHONUSERBASE", "PYTHONSTARTUP"):
            result = self.wrapper("W0-N16", name, ["check-env"], {name: "/tmp/forged"})
            self.assertEqual(result.returncode, 2)

    def test_W0_N17_child_factory_is_closed(self) -> None:
        spec = importlib.util.spec_from_file_location("cth3ds_driver_child_test", DRIVER)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        invocation = module.VerifiedInvocation({
            "operation": "fresh-chain",
            "repository": {"realpath": str(ROOT)},
            "source_closure": {"driver": {"path": str(DRIVER)}},
            "python": {"executable": str(self.env_dir / "bin/python")},
        }, module._SENTINEL)
        child_args = ["--request", "/tmp/request.json",
                      "--output", "/tmp/result.json"]
        command = invocation.child_command("_case-evaluate", child_args)
        mutations = {
            "direct-worker": {2: str(WORKERS[0])},
            "another-interpreter": {0: sys.executable},
            "arbitrary-script": {2: str(ROOT / "tools/check_pins.py")},
            "dash-c": {1: "-c"},
            "dash-m": {1: "-m"},
            "nonallowlisted-driver-verb": {5: "check-env"},
        }
        for subcase, replacements in mutations.items():
            changed = list(command)
            for index, value in replacements.items():
                changed[index] = value
            with self.assertRaisesRegex(RuntimeError,
                                        "INTERNAL_CHILD_COMMAND_MISMATCH") as caught:
                invocation.validate_child_command(
                    changed, "_case-evaluate", child_args)
            self.record("W0-N17", subcase, subprocess.CompletedProcess(
                changed, 2, "", str(caught.exception)))
        self.assertNotIn("runpy.run_path", (ROOT / "scripts/verify_runtime_core_v2.py").read_text())
        self.assertNotIn("CTH3DS_VERIFIER_PYTHON_DISPATCH", (ROOT / "scripts/verify_runtime_core_v2.py").read_text())

    def test_W0_N18_atomic_publisher_rejects_preexisting_output(self) -> None:
        spec = importlib.util.spec_from_file_location("cth3ds_driver_test", DRIVER)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "result.json"
            path.write_text('{"status":"PASS"}\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "AUTHORITATIVE_OUTPUT_PREEXISTS"):
                module.atomic_json(path, {"status": "PASS"})
            self.assertEqual(json.loads(path.read_text())["status"], "PASS")
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            session = root / "session"
            result_path = root / "result.json"
            result_path.write_text('{"status":"PASS"}\n', encoding="utf-8")
            result = self.wrapper("W0-N18", "precreated-pass", [
                "protocol-self-test", "--session-root", str(session),
                "--result", str(result_path)])
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result_path.read_text())["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
