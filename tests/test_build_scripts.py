from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BuildScriptTests(unittest.TestCase):
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

    def test_host_verification_keeps_generated_report_under_artifacts(self) -> None:
        script = (ROOT / "scripts/test_all.sh").read_text(encoding="utf-8")
        self.assertIn('HOST_MATRIX="${CTH3DS_HOST_MATRIX:-all}"', script)
        self.assertIn('PREVIEW_DIR="${LOG_DIR}/preview"', script)
        self.assertIn('"${LOG_DIR}/summary.json" "${LOG_DIR}/report.md"', script)
        self.assertNotIn('docs/VM_VERIFICATION.md', script)

    def test_container_build_uses_immutable_image_without_rolling_upgrade(self) -> None:
        script = (ROOT / "scripts/build_3ds_docker.sh").read_text(
            encoding="utf-8"
        )
        self.assertRegex(script, r"devkitpro/devkitarm@sha256:[0-9a-f]{64}")
        self.assertNotIn("dkp-pacman -Syu", script)
        self.assertIn("dkp-pacman -S --needed", script)

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
        self.assertIn('"${CTH3DS_DIST_DIR}/sd-card" --no-pack', text)

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
