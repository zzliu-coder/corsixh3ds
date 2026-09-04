from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import shutil
import re
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]

AUTHORITY_CASE_METHODS = (
    "authority_extra_one_fails_at_preflight",
    "authority_missing_one_fails_at_preflight",
    "authority_same_count_replacement_fails_at_preflight",
    "authority_build_policy_consumes_verified_authority_and_serializes_policy",
    "authority_builder_projection_drift_fails_at_bundle_preflight",
    "authority_dirty_and_wrong_parent_fail_before_policy_or_journal",
    "authority_old_bundle_replay_dag_drift_fails_at_preflight",
    "authority_producer_projection_drift_fails_before_produce",
    "authority_schema_cardinality_gate_fails_at_preflight",
)


class BuildScriptTests(unittest.TestCase):
    def test_host_python_manifest_retains_frozen_baseline(self) -> None:
        manifest = json.loads(
            (ROOT / "tests/host-python-suite.json").read_text(encoding="utf-8")
        )
        baseline = manifest["baseline"]
        payload = ("\n".join(baseline["test_ids"]) + "\n").encode("utf-8")
        self.assertEqual(baseline["count"], 143)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "b525c8905c59ec4193581f16781045ebc7382a35800dff9e8db28eefec1a0d2b",
        )
        self.assertTrue(set(baseline["test_ids"]).issubset(manifest["test_ids"]))

    def test_all_host_python_entries_use_one_runner_and_manifest(self) -> None:
        runner = "scripts/run_host_python_suite.py"
        manifest = "tests/host-python-suite.json"
        for path in (
            ROOT / "scripts/test_all.sh",
            ROOT / "CMakeLists.txt",
            ROOT / ".github/workflows/old3ds-validation.yml",
            ROOT / "scripts/verifier_driver.py",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn(runner, text, path)
            self.assertIn(manifest, text, path)

    def test_fresh_chain_has_no_python_semantic_override_or_test_filter(self) -> None:
        text = (ROOT / "scripts/verify_runtime_core_v2.py").read_text(encoding="utf-8")
        for forbidden in (
            "pathlib.Path.write_text =",
            "subprocess.run =",
            "_compat-embed-platform-check",
            'if "test_verifier_python_environment." in test_id',
            'test_id.endswith("test_cli_returns_nonzero_for_not_proven_ledger_after_writing_it")',
        ):
            self.assertNotIn(forbidden, text)
        builder = (ROOT / "scripts/build_verifier_input_bundle.py").read_text(
            encoding="utf-8")
        workflow = (ROOT / ".github/workflows/old3ds-validation.yml").read_text(
            encoding="utf-8")
        self.assertNotIn("ALLOWLIST =", text)
        self.assertNotIn("ALLOWLIST =", builder)
        self.assertIn("validation_change_authority", text)
        self.assertIn("authority_binding_from_dag_bytes", builder)
        self.assertIn("authority-binding.json", workflow)
        policy_schema = json.loads(
            (ROOT / "tests/runtime_core_v2/review-policy.schema.json").read_text())
        node = policy_schema["properties"]["product_boundary"]["properties"][
            "allowlist_exact"]
        self.assertEqual(node["type"], "array")
        self.assertEqual(node["items"]["type"], "string")
        self.assertTrue(node["uniqueItems"])
        for forbidden in ("minItems", "maxItems", "const", "enum", "prefixItems"):
            self.assertNotIn(forbidden, node)
        bundle_schema = json.loads(
            (ROOT / "tests/runtime_core_v2/input-bundle.schema.json").read_text())
        self.assertIn("validation_change_authority", bundle_schema["required"])
        result = unittest.TestResult()
        authority_projection_suite().run(result)
        self.assertEqual(result.testsRun, 9)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.expectedFailures, [])
        self.assertEqual(result.unexpectedSuccesses, [])

    def test_all_shell_scripts_parse_and_have_no_placeholders(self) -> None:
        scripts = sorted((ROOT / "scripts").glob("*.sh"))
        self.assertGreaterEqual(len(scripts), 8)
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#!/usr/bin/env bash"), script)
            self.assertIn("set -euo pipefail", text, script)
            self.assertNotRegex(text, r"TODO|PLACEHOLDER|YOUR_PATH", script)

    def test_cross_build_disables_desktop_only_features(self) -> None:
        text = (ROOT / "scripts/build_3ds.sh").read_text(encoding="utf-8")
        for option in (
            "-DWITH_MOVIES=OFF",
            "-DWITH_UPDATE_CHECK=OFF",
            "-DWITH_MIDI_DEVICE=OFF",
            "-DFETCH_SOUNDFONT=OFF",
            "-DFETCH_UNICODE_FONT=OFF",
            "-DCORSIXTH_3DS=ON",
        ):
            self.assertIn(option, text)
        self.assertIn("corsixth_3dsx", text)

    def test_ci_matrices_are_isolated_and_failure_evidence_is_always_uploaded(self) -> None:
        workflow = (ROOT / ".github/workflows/old3ds-validation.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("fail-fast: false", workflow)
        for matrix in (
            "gcc-debug",
            "gcc-release",
            "gcc-sanitized",
            "clang-debug",
        ):
            self.assertIn(f"name: {matrix}", workflow)
        self.assertGreaterEqual(workflow.count("if: always()"), 2)
        self.assertIn("apt-get install", workflow)
        self.assertIn("dkp-pacman -S --needed", workflow)
        self.assertNotIn("dkp-pacman -Syu", workflow)
        self.assertEqual(
            workflow.count("- name: Install locked host test dependencies"), 2
        )
        self.assertEqual(
            workflow.count("--require-hashes --only-binary=:all:"),
            2,
        )
        self.assertIn('python3 -m venv "$test_env"', workflow)
        self.assertIn('echo "$test_env/bin" >> "$GITHUB_PATH"', workflow)
        self.assertRegex(
            workflow,
            r"devkitpro/devkitarm@sha256:[0-9a-f]{64}",
        )
        action_references = re.findall(
            r"(?m)^\s*(?:-\s*)?uses:\s*(actions/[A-Za-z0-9_.-]+@[^\s#]+)\s*$",
            workflow,
        )
        self.assertEqual(
            Counter(action_references),
            Counter(
                {
                    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1": 6,
                    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97": 3,
                    "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c": 1,
                    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a": 6,
                }
            ),
        )
        for reference in action_references:
            revision = reference.rsplit("@", 1)[1]
            self.assertRegex(revision, r"^[0-9a-f]{40}$", reference)
            self.assertNotIn(revision, {"main", "master", "latest"})
        checkouts = list(
            re.finditer(
                r"(?m)^\s*- uses: actions/checkout@"
                r"3d3c42e5aac5ba805825da76410c181273ba90b1\n"
                r"\s+with:\n"
                r"\s+fetch-depth: 0$",
                workflow,
            )
        )
        self.assertEqual(len(checkouts), 6)
        self.assertEqual(workflow.count("git rev-parse --is-shallow-repository"), 5)
        self.assertEqual(
            len(
                re.findall(
                    r"git rev-parse HEAD HEAD\^\{tree\} HEAD\^ > artifacts/ci/source-identity-",
                    workflow,
                )
            ),
            5,
        )
        self.assertEqual(workflow.count("git rev-list --parents -n 1 HEAD"), 5)
        host_python = workflow.split("  protocol-self-test:", 1)[0]
        for token in (
            "needs: old3ds-cross-build",
            "lua5.4",
            "cth3ds-simulator",
            "cth3ds-runtime-probe",
            "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
            "name: corsixth-old3ds",
            "CTH3DS_SIMULATOR:",
            "CTH3DS_RUNTIME_PROBE:",
            "CTH3DS_RUNTIME_LINK_PROOF:",
            "149 passed, 0 failed, 0 errors, 0 skipped",
        ):
            self.assertIn(token, host_python)
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/artifacts/ci/", ignored)
        self.assertIn("git status --porcelain=v1 --untracked-files=all", workflow)
        verifier = (ROOT / "scripts/verifier_driver.py").read_text(encoding="utf-8")
        self.assertIn("--untracked-files=all", verifier)
        cross = workflow.split("  old3ds-cross-build:", 1)[1]
        for token in (
            "DEVKITPRO: /opt/devkitpro",
            "DEVKITARM: /opt/devkitpro/devkitARM",
            'git config --global --add safe.directory "$GITHUB_WORKSPACE"',
            'echo "$DEVKITARM/bin" >> "$GITHUB_PATH"',
            "command -v arm-none-eabi-gcc",
            "/opt/devkitpro/devkitARM/bin/arm-none-eabi-gcc",
            "arm-none-eabi-gcc --version",
        ):
            self.assertIn(token, cross)

    def test_host_verification_keeps_generated_report_under_artifacts(self) -> None:
        script = (ROOT / "scripts/test_all.sh").read_text(encoding="utf-8")
        self.assertIn('HOST_MATRIX="${CTH3DS_HOST_MATRIX:-all}"', script)
        self.assertIn('PREVIEW_DIR="${LOG_DIR}/preview"', script)
        self.assertIn('"${LOG_DIR}/summary.json" "${LOG_DIR}/report.md"', script)
        self.assertNotIn('docs/VM_VERIFICATION.md', script)
        for token in (
            "CMakeCXXCompiler.cmake",
            "CMAKE_CXX_COMPILER_ID",
            "CMAKE_CXX_COMPILER_VERSION",
            "compiler_path",
            "expected_ids",
            "gcc-",
            "AppleClang",
            "if common_ran:",
            "python_receipt = None",
        ):
            self.assertIn(token, script)
        source = (ROOT / "src/common/resource_manager.cpp").read_text(
            encoding="utf-8"
        )
        self.assertEqual(source.count("resource_package_budget_cap("), 3)
        self.assertEqual(source.count("budgets.bytes[pool_index]"), 1)
        self.assertIn("pool_index >= budgets.bytes.size()", source)

    def test_container_build_uses_immutable_image_without_rolling_upgrade(self) -> None:
        script = (ROOT / "scripts/build_3ds_docker.sh").read_text(
            encoding="utf-8"
        )
        self.assertRegex(script, r"devkitpro/devkitarm@sha256:[0-9a-f]{64}")
        self.assertNotIn("dkp-pacman -Syu", script)
        self.assertIn("dkp-pacman -S --needed", script)
        self.assertIn('CTH3DS_PACKAGE_ASSET_MODE:-th3ds', script)
        self.assertIn('--asset-mode ${PACKAGE_ASSET_MODE}', script)
        self.assertIn('--theme-hospital /theme-hospital', script)
        self.assertIn('loose diagnostic package only', script)

    def test_public_cross_build_does_not_claim_a_package_without_game_data(self) -> None:
        workflow = (ROOT / ".github/workflows/old3ds-validation.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("package_sd.sh", workflow)
        self.assertNotIn("dist/sd-card", workflow)

    def test_dependency_build_uses_pins_and_static_lua_modules(self) -> None:
        text = (ROOT / "scripts/bootstrap_3ds_deps.sh").read_text(encoding="utf-8")
        self.assertIn("patch_sdl2_n3ds.py", text)
        self.assertIn("liblfs.a", text)
        self.assertIn("liblpeg.a", text)
        self.assertIn("liblua.a", text)
        self.assertNotIn("LUA_USE_C89", text)
        self.assertNotRegex(text, r"git\s+checkout\s+(?:master|main)\b")

    def test_sd_package_uses_640_by_480_logical_canvas(self) -> None:
        text = (ROOT / "scripts/package_sd.sh").read_text(encoding="utf-8")
        self.assertRegex(text, r"width = 640\nheight = 480")
        self.assertIn('theme_hospital_install = "sdmc:/3ds/corsixth/game"', text)
        self.assertIn('player_name = "PLAYER"', text)
        self.assertNotIn('"${PACK_ARGS[@]}"', text)
        self.assertIn('--asset-mode must be th3ds or loose', text)
        self.assertIn('tools/validate_sd_tree.py', text)
        self.assertIn('--require-mode "${ASSET_MODE}"', text)

    def test_cycle_captures_deploy_and_debug_evidence(self) -> None:
        text = (ROOT / "scripts/old3ds_cycle.sh").read_text(encoding="utf-8")
        for token in (
            "old3ds_delta.py",
            "deploy-report.json",
            "info os processes",
            "gdb-processes-after-deploy.log",
            "target extended-remote ${HOST}:4003",
            "realDeviceRunning",
        ):
            self.assertIn(token, text)
        self.assertIn('--deploy-mode', text)
        self.assertIn('--disable-legacy', text)


class AuthorityProjectionNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.builder = cls._load("authority_test_builder",
                                ROOT / "scripts/build_verifier_input_bundle.py")
        cls.driver = cls._load("authority_test_driver",
                               ROOT / "scripts/verifier_driver.py")
        cls.producer = cls._load("authority_test_producer",
                                 ROOT / "scripts/verify_runtime_core_v2.py")
        cls.runner = cls._load(
            "authority_test_runner",
            ROOT / "tests/runtime_core_v2/evidence_protocol_adversarial.py")

    @staticmethod
    def _load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load test module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _authority(paths: list[str]) -> dict:
        lines = ("\n".join(paths) + "\n").encode()
        return {
            "schema": "cth3ds.test-validation-authority/v1",
            "owner": "test-scheduler",
            "baseline": {"commit": "0" * 40, "tree": "1" * 40},
            "authorized_diff_count": len(paths),
            "authorized_diff_lines_sha256": hashlib.sha256(lines).hexdigest(),
            "authorized_diff_exact": paths,
            "review_policy_schema_role": {
                "json_pointer": "/properties/product_boundary/properties/allowlist_exact",
                "required_keywords": ["type", "items", "uniqueItems"],
                "forbidden_keywords": ["minItems", "maxItems", "const", "enum",
                                       "prefixItems"],
            },
            "product_boundary": {"entry_count": 1, "sha256": "2" * 64},
            "candidate_constraints": {"sole_parent": True, "clean": True,
                                      "repair_commits": 0},
        }

    def assertRejected(self, case_id: str, callback, expected: str) -> None:
        with tempfile.TemporaryDirectory(prefix="cth3ds-authority-observation-") as temporary:
            result = self.runner.authority_negative_observation(
                case_id, callback, Path(temporary))
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["failure_code"], expected)
        self.assertFalse(result["policy_created"])
        self.assertFalse(result["journal_created"])

    def authority_missing_one_fails_at_preflight(self) -> None:
        authority = self._authority(["a", "b"])
        authority["authorized_diff_exact"].pop()
        self.assertRejected("missing-one",
                            lambda: self.driver.validate_authority_object(authority),
                            "VALIDATION_AUTHORITY_PATH_COUNT_MISMATCH")

    def authority_extra_one_fails_at_preflight(self) -> None:
        authority = self._authority(["a", "b"])
        authority["authorized_diff_exact"].append("c")
        self.assertRejected("extra-one",
                            lambda: self.driver.validate_authority_object(authority),
                            "VALIDATION_AUTHORITY_PATH_COUNT_MISMATCH")

    def authority_same_count_replacement_fails_at_preflight(self) -> None:
        authority = self._authority(["a", "b"])
        authority["authorized_diff_exact"] = ["a", "c"]
        self.assertRejected("same-count-replacement",
                            lambda: self.driver.validate_authority_object(authority),
                            "VALIDATION_AUTHORITY_PATH_DIGEST_MISMATCH")

    def authority_schema_cardinality_gate_fails_at_preflight(self) -> None:
        authority = self._authority(["a", "b"])
        schema = json.loads(
            (ROOT / "tests/runtime_core_v2/review-policy.schema.json").read_text())
        node = schema["properties"]["product_boundary"]["properties"]["allowlist_exact"]
        node["minItems"] = 1
        self.assertRejected("schema-cardinality",
                            lambda: self.driver.validate_schema_role(schema, authority),
                            "VALIDATION_AUTHORITY_SCHEMA_ROLE_MISMATCH")

    def authority_producer_projection_drift_fails_before_produce(self) -> None:
        authority = self._authority(["a", "b"])
        policy = {"validation_change_authority": authority,
                  "product_boundary": {"allowlist_exact": ["a", "c"]}}
        self.assertRejected("producer-projection",
            lambda: self.driver.verify_policy_authority_projection(authority, policy),
            "VALIDATION_AUTHORITY_PRODUCER_PROJECTION_MISMATCH")

    def authority_builder_projection_drift_fails_at_bundle_preflight(self) -> None:
        authority = self._authority(["a", "b"])
        raw = (json.dumps({"e0_r11_validation_change_authority": authority},
                          sort_keys=True, separators=(",", ":")) + "\n").encode()
        binding = self.builder.authority_binding_from_dag_bytes(raw)
        binding["projection"]["owner"] = "drift"
        self.assertRejected("builder-projection",
                            lambda: self.builder.validate_authority_binding(binding, raw),
                            "VALIDATION_AUTHORITY_BUILDER_PROJECTION_MISMATCH")

    def authority_old_bundle_replay_dag_drift_fails_at_preflight(self) -> None:
        authority = self._authority(["a", "b"])
        raw = (json.dumps({"e0_r11_validation_change_authority": authority},
                          sort_keys=True, separators=(",", ":")) + "\n").encode()
        binding = self.driver.authority_binding_from_dag_bytes(raw)
        old_raw = raw.rstrip() + b" \n"
        self.assertRejected("old-bd-bundle-replay",
                            lambda: self.driver.validate_authority_binding(binding, old_raw),
                            "VALIDATION_AUTHORITY_DAG_HASH_MISMATCH")

    def authority_dirty_and_wrong_parent_fail_before_policy_or_journal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cth3ds-authority-negative-") as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            subprocess.run(["/usr/bin/git", "init", "-q", str(repo)], check=True)
            subprocess.run(["/usr/bin/git", "-C", str(repo), "config", "user.name",
                            "Authority Test"], check=True)
            subprocess.run(["/usr/bin/git", "-C", str(repo), "config", "user.email",
                            "authority@example.invalid"], check=True)
            (repo / "a").write_text("base\n")
            (repo / "b").write_text("base\n")
            schema = repo / "tests/runtime_core_v2/review-policy.schema.json"
            schema.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "tests/runtime_core_v2/review-policy.schema.json", schema)
            subprocess.run(["/usr/bin/git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["/usr/bin/git", "-C", str(repo), "commit", "-qm", "base"],
                           check=True)
            base = subprocess.check_output(
                ["/usr/bin/git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            tree = subprocess.check_output(
                ["/usr/bin/git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
                text=True).strip()
            authority = self._authority(["a", "b"])
            authority["baseline"] = {"commit": base, "tree": tree}
            (repo / "a").write_text("candidate\n")
            (repo / "b").write_text("candidate\n")
            subprocess.run(["/usr/bin/git", "-C", str(repo), "commit", "-qam",
                            "candidate"], check=True)
            raw = (json.dumps({"e0_r11_validation_change_authority": authority},
                              sort_keys=True, separators=(",", ":")) + "\n").encode()
            binding = self.driver.authority_binding_from_dag_bytes(raw)
            invocation = self.driver.VerifiedInvocation(
                {"operation": "fresh-chain"}, self.driver._SENTINEL)
            token = self.driver.VerifiedAuthorityProjection(
                authority, binding, self.driver._SENTINEL)
            invocation.verify_candidate_authority(token, repo)
            (repo / "dirty").write_text("x\n")
            self.assertRejected("candidate-dirty-or-wrong-parent",
                                lambda: invocation.verify_candidate_authority(token, repo),
                                "CANDIDATE_DIRTY")
            (repo / "dirty").unlink()
            subprocess.run(["/usr/bin/git", "-C", str(repo), "checkout", "-q", base],
                           check=True)
            self.assertRejected("candidate-dirty-or-wrong-parent",
                                lambda: invocation.verify_candidate_authority(token, repo),
                                "CANDIDATE_PARENT_MISMATCH")
            self.assertFalse((repo / "10-policy").exists())
            self.assertFalse((repo / "00-preflight/execution-journal.jsonl").exists())

    def authority_build_policy_consumes_verified_authority_and_serializes_policy(
            self) -> None:
        authorized_paths = [
            ".github/workflows/old3ds-validation.yml",
            "requirements/verifier-wheelhouse-manifest.json",
            "scripts/build_verifier_input_bundle.py",
            "scripts/ci_diagnostics.sh",
            "scripts/run_ci_command.sh",
            "scripts/run_verifier_python.sh",
            "scripts/verifier_driver.py",
            "scripts/verify_runtime_core_v2.py",
            "tests/runtime_core_v2/evidence_protocol_adversarial.py",
            "tests/runtime_core_v2/input-bundle.schema.json",
            "tests/runtime_core_v2/review-policy.schema.json",
            "tests/test_build_scripts.py",
            "tests/test_ci_diagnostics.py",
        ]
        authority = self._authority(authorized_paths)
        authority["product_boundary"] = {
            "entry_count": 54,
            "sha256": "4b027341762b902c75c10b522a8edc15330e0723b73512e9fcdc9e24841f0ca6",
        }
        token = object()
        head, tree, root_commit = "3" * 40, "4" * 40, "5" * 40
        base = {
            "commit": authority["baseline"]["commit"],
            "tree": authority["baseline"]["tree"],
            "parent": root_commit,
            "tracked_fingerprint_v3": "6" * 64,
            "tracked_entries": 208,
        }
        ancestry = {
            "algorithm": "raw-full-parent-closure-v1",
            "object_format": "sha1",
            "head": head,
            "head_tree": tree,
            "head_parents": [base["commit"]],
            "first_parent_chain": [head, base["commit"], root_commit],
            "roots": [root_commit],
            "commit_count": 3,
            "edge_count": 2,
            "commits": [
                {"oid": head, "tree": tree, "parents": [base["commit"]],
                 "raw_sha256": "7" * 64},
                {"oid": base["commit"], "tree": base["tree"],
                 "parents": [root_commit], "raw_sha256": "8" * 64},
                {"oid": root_commit, "tree": "9" * 40, "parents": [],
                 "raw_sha256": "a" * 64},
            ],
            "forbidden_intersection": [],
            "closure_sha256": "b" * 64,
        }

        source = (ROOT / "scripts/verify_runtime_core_v2.py").read_text(
            encoding="utf-8")
        tree_ast = ast.parse(source)
        tool_function = next(
            node for node in tree_ast.body
            if isinstance(node, ast.FunctionDef) and node.name == "tool_paths")
        self.assertNotIn(
            "args", {node.id for node in ast.walk(tool_function)
                     if isinstance(node, ast.Name)})
        self.assertNotIn(
            "validation_change_authority",
            {node.attr for node in ast.walk(tool_function)
             if isinstance(node, ast.Attribute)})

        class VerifiedInvocation:
            def __init__(inner_self) -> None:
                source_closure = {}
                for role, relative in (
                    ("producer", "scripts/verify_runtime_core_v2.py"),
                    ("consumer", "scripts/consume_runtime_core_v2.py"),
                    ("runner", "tests/runtime_core_v2/evidence_protocol_adversarial.py"),
                    ("driver", "scripts/verifier_driver.py"),
                    ("host_python_runner", "scripts/run_host_python_suite.py"),
                    ("host_python_manifest", "tests/host-python-suite.json"),
                ):
                    source_closure[role] = {
                        "sha256": self.producer.sha_file(ROOT / relative)}
                inner_self.record = {
                    "operation": "fresh-chain",
                    "repository": {"head": head},
                    "baseline_identity": {
                        "commit": base["commit"], "tree": base["tree"]},
                    "source_closure": source_closure,
                    "python": {
                        "executable": "/usr/bin/true", "version": "3.test",
                        "implementation_sha256": "c" * 64},
                }
                inner_self.digest = "d" * 64
                inner_self.repo = ROOT
                inner_self.python = Path("/usr/bin/true")
                inner_self.driver = ROOT / "scripts/verifier_driver.py"
                inner_self.authority_calls = []

            def require(inner_self, operations) -> None:
                self.assertEqual(tuple(operations), ("fresh-chain",))

            def require_validation_authority(inner_self, supplied):
                inner_self.authority_calls.append(supplied)
                if supplied is not token:
                    raise RuntimeError("wrong authority token")
                return json.loads(json.dumps(authority))

            def child_command(inner_self, verb, arguments):
                return ["/usr/bin/true", verb, *arguments]

        tools = {role: "/usr/bin/true" for role in self.producer.TOOL_ROLES}
        tool_identity = {
            "algorithm": "dispatched-tool-identity-v1",
            "developer_dir": "/test/developer",
            "macos_sdk_realpath": "/test/sdk",
            "host_target": "test-target",
            "tools": [
                {"role": role, "dispatch_realpath": "/usr/bin/true",
                 "dispatch_sha256": "e" * 64,
                 "implementation_realpath": "/usr/bin/true",
                 "implementation_bytes": 1,
                 "implementation_sha256": "e" * 64,
                 "version_sha256": "f" * 64}
                for role in self.producer.TOOL_ROLES
            ],
            "sha256": "0" * 64,
        }

        def fake_lstat_closure(path: Path) -> dict:
            return {
                "algorithm": "lstat-tree-v1",
                "root_realpath": str(path),
                "node_count": 1,
                "nodes": [{"path": ".", "type": "directory", "mode": "040755"}],
                "sha256": "1" * 64,
            }

        def fake_git(repo: Path, *arguments: str, **_kwargs) -> bytes:
            if arguments == ("rev-parse", "HEAD^{commit}"):
                return (head + "\n").encode()
            if arguments[:3] == ("ls-files", "-s", "--"):
                return ("100644 " + "2" * 40 + " 0\t" + arguments[3] + "\n").encode()
            raise AssertionError(arguments)

        temporary_path = None
        with tempfile.TemporaryDirectory(prefix="cth3ds-policy-dataflow-") as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "input.tar.gz"
            with archive.open("wb") as handle:
                handle.truncate(4416083)
            deps = temporary_path / "deps"
            deps.mkdir()
            session_root = temporary_path / "session"
            session_root.mkdir()
            run_root = session_root / "20-canonical-run"
            reviewer_root = session_root / "10-policy"
            context = VerifiedInvocation()
            args = argparse.Namespace(
                repo=ROOT,
                run_root=run_root,
                reviewer_root=reviewer_root,
                archive=archive,
                deps_prefix=deps,
                review_session_id="3" * 32,
                session_root=session_root,
                validation_change_authority=token,
            )
            real_sha_file = self.producer.sha_file

            def fake_sha_file(path: Path) -> str:
                if Path(path).name == "CorsixTH.tar.gz":
                    return self.producer.ARCHIVE_SHA
                return real_sha_file(Path(path))

            with mock.patch.object(self.producer, "tool_paths", return_value=tools), \
                 mock.patch.object(self.producer, "reviewer_ancestry_commitment",
                                   return_value=ancestry), \
                 mock.patch.object(self.producer, "baseline_identity", return_value=base), \
                 mock.patch.object(self.producer, "fingerprint",
                                   side_effect=[("4" * 64, 209),
                                                (self.producer.PRODUCT_FP, 54)]), \
                 mock.patch.object(self.producer, "prepare_sources", return_value=(
                     {"file_count": 644, "tree_digest": self.producer.UPSTREAM_DIGEST},
                     {"file_count": 700, "tree_digest": "5" * 64})), \
                 mock.patch.object(self.producer, "tool_implementation_identity",
                                   return_value=tool_identity), \
                 mock.patch.object(self.producer, "lstat_closure",
                                   side_effect=fake_lstat_closure), \
                 mock.patch.object(self.producer, "git", side_effect=fake_git), \
                 mock.patch.object(self.producer, "sha_file", side_effect=fake_sha_file):
                self.assertEqual(self.producer.build_policy(context, object(), args), 0)

            policy_path = reviewer_root / "review-policy.json"
            self.assertTrue(policy_path.is_file())
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            self.assertEqual(context.authority_calls, [token])
            self.assertEqual(policy["validation_change_authority"], authority)
            self.assertEqual(
                policy["product_boundary"]["allowlist_exact"], authorized_paths)
            self.assertNotIn("authority", vars(self.producer))
            self.assertNotIn("args", vars(self.producer))
            policy_path.chmod(0o644)
            (reviewer_root / "CorsixTH.tar.gz").chmod(0o644)
            reviewer_root.chmod(0o755)
        self.assertIsNotNone(temporary_path)
        self.assertFalse(temporary_path.exists())


def authority_projection_suite() -> unittest.TestSuite:
    return unittest.TestSuite(
        AuthorityProjectionNegativeTests(method_name)
        for method_name in AUTHORITY_CASE_METHODS
    )


if __name__ == "__main__":
    unittest.main()
