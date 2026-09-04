from __future__ import annotations

import hashlib
import json
import re
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    unittest.main()
