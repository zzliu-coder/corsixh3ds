from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
TESTS = ROOT / "tests"
for directory in (TOOLS, TESTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from test_th3ds_resource_packer import make_fixture
from validate_sd_tree import validate_sd_tree


class PackageSdScriptTests(unittest.TestCase):
    def make_environment(self, root: Path) -> tuple[dict[str, str], Path]:
        source, languages, _atlas = make_fixture(root)
        runtime = root / "external" / "CorsixTH" / "CorsixTH"
        runtime.mkdir(parents=True)
        (runtime / "CorsixTH.lua").write_text("-- synthetic runtime\n", encoding="utf-8")
        for name in ("Bitmap", "Campaigns", "Graphics", "Levels", "Lua"):
            directory = runtime / name
            directory.mkdir()
            (directory / "fixture.txt").write_text(name, encoding="utf-8")
        shutil.copytree(languages, runtime / "Lua/languages")

        build = root / "build"
        binary = build / "CorsixTH" / "CorsixTH-3DS.3dsx"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(
            b"3DSX" + struct.pack("<HH", 0x20, 4) + bytes(0x20 - 8)
        )

        fake_bin = root / "fake-bin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        fake_git.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  *'status --porcelain'*) exit 0 ;;\n"
            "  *'HEAD^{tree}'*) printf '%040d\\n' 2 ;;\n"
            "  *) printf '%040d\\n' 1 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        fake_git.chmod(0o755)
        environment = os.environ.copy()
        environment.update(
            {
                "CTH3DS_BUILD_DIR": str(build),
                "CTH3DS_DEPS_PREFIX": str(root / "deps"),
                "CTH3DS_EXTERNAL_DIR": str(root / "external"),
                "PATH": str(fake_bin) + os.pathsep + environment["PATH"],
            }
        )
        return environment, source

    def run_package(
        self, environment: dict[str, str], source: Path, dist: Path, mode: str
    ) -> subprocess.CompletedProcess[str]:
        run_environment = dict(environment)
        run_environment["CTH3DS_DIST_DIR"] = str(dist)
        return subprocess.run(
            [
                str(ROOT / "scripts" / "package_sd.sh"),
                "--asset-mode",
                mode,
                "--theme-hospital",
                str(source),
                "--language",
                "en",
            ],
            cwd=ROOT,
            env=run_environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_th3ds_candidate_is_complete_atomic_and_excludes_loose_originals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, source = self.make_environment(root)
            dist = root / "dist-th3ds"
            completed = self.run_package(environment, source, dist, "th3ds")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            package = dist / "sd-card" / "3ds" / "corsixth"
            report = validate_sd_tree(package, require_mode="th3ds")
            self.assertFalse(report["product_ready_eligible"])
            self.assertFalse((package / "game").exists())
            output = b"".join(
                path.read_bytes() for path in package.rglob("*") if path.is_file()
            )
            self.assertNotIn(b"must-not-be-copied", output)

            manifest_before = (package / "sd-manifest.json").read_bytes()
            repeated = self.run_package(environment, source, dist, "th3ds")
            self.assertEqual(repeated.returncode, 2)
            self.assertEqual(
                (package / "sd-manifest.json").read_bytes(), manifest_before
            )

    def test_loose_mode_is_diagnostic_and_excludes_user_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, source = self.make_environment(root)
            save = source / "SAVE"
            save.mkdir()
            (save / "private.sav").write_bytes(b"private save")
            dist = root / "dist-loose"
            completed = self.run_package(environment, source, dist, "loose")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            package = dist / "sd-card" / "3ds" / "corsixth"
            report = validate_sd_tree(package, require_mode="loose")
            self.assertTrue(report["product_ready_eligible"])
            self.assertFalse((package / "game" / "SAVE").exists())


if __name__ == "__main__":
    unittest.main()
