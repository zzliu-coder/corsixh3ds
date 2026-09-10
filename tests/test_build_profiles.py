"""AR6 two-profile identity and real generated-source boundaries (no ARM claim)."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from integration.build_profile import common_groups, common_sources, validate_profile, cmake_contract
from integration.common import IntegrationError
from integration.generated_view import RECEIPT, verify_view, inventory
from integrate_corsixth import generate_private
from source_view import binding, independent_environment
from support.pinned_upstream import original_sources
from check_resource_link import proof, REQUIRED, EXPERIMENT_FAMILIES


class BuildProfileTests(unittest.TestCase):
    def configure(self, source, build, *options, env=None):
        environment = dict(os.environ if env is None else env)
        # CTest supplies the actual parent CMake selection. Direct focused runs
        # still work on a declared Ninja-only host without a Make dependency.
        if not environment.get("CMAKE_GENERATOR") and shutil.which("ninja"):
            environment["CMAKE_GENERATOR"] = "Ninja"
        result = subprocess.run(["cmake", "-S", str(source), "-B", str(build), *options],
                                env=environment, capture_output=True, text=True)
        if result.returncode == 0:
            cache = (build / "CMakeCache.txt").read_text()
            if environment.get("CMAKE_GENERATOR"):
                self.assertIn("CMAKE_GENERATOR:INTERNAL=" + environment["CMAKE_GENERATOR"], cache)
            if environment.get("CXX"):
                resolved = str(Path(shutil.which(environment["CXX"]) or environment["CXX"]).resolve())
                actual = next(line.split("=", 1)[1] for line in cache.splitlines()
                              if line.startswith("CMAKE_CXX_COMPILER:FILEPATH="))
                self.assertEqual(str(Path(actual).resolve()), resolved)
        return result

    def test_default_bootstrap_keeps_persistent_external_view_and_reuses_pin(self):
        with tempfile.TemporaryDirectory() as temp:
            area = Path(temp).resolve(); overlay = area / "overlay"
            # Export the current tracked bytes. The real scripts, validator,
            # integrator and owner run unchanged; only downloads are preseeded.
            names = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"],
                                            text=True).split("\0")
            for name in filter(None, names):
                target = overlay / name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            pin = original_sources(overlay / "external/CorsixTH-pin")
            # The original 44-file transform fixture omits this API-only input.
            # Retain the exact full file from the same pinned upstream commit.
            edit_room = (ROOT / "tests/fixtures/edit_room.lua.pinned").read_bytes()
            self.assertEqual(hashlib.sha256(edit_room).hexdigest(),
                             "db2cdc5cdfe72af22f1c3fb39d236ece4dcb099d933aad67cedeb0c8829e22b6")
            (pin / "CorsixTH/Lua/dialogs/edit_room.lua").write_bytes(edit_room)
            pins = json.loads((overlay / "config/upstream-pins.json").read_text())["corsixth"]
            (pin / ".cth3ds-source.json").write_text(json.dumps(
                {"repository": pins["repository"], "commit": pins["commit"]}))
            before = inventory(pin)
            environment = {key: value for key, value in independent_environment().items()
                           if not key.startswith("CTH3DS_") or key == "CTH3DS_CANCEL_DOMAIN"}
            call = ["bash", str(overlay / "scripts/bootstrap_upstream.sh")]
            first = subprocess.run(call, env=environment, capture_output=True, text=True, timeout=45)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            alias = overlay / "external/CorsixTH"
            generated = area / "overlay-generated"
            self.assertTrue(alias.is_symlink())
            selected = alias.resolve(strict=True)
            self.assertIn(generated, selected.parents)
            self.assertNotIn(overlay, selected.parents)
            self.assertEqual(verify_view(alias, overlay)["build_profile"], "loose")
            self.assertTrue((overlay / "external/.source-owner.lock").is_file())
            owners = sorted(generated.iterdir())
            second = subprocess.run(call, env=environment, capture_output=True, text=True, timeout=45)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("verified existing complete source view", second.stdout)
            self.assertEqual(alias.resolve(strict=True), selected)
            self.assertEqual(sorted(generated.iterdir()), owners)
            self.assertEqual(inventory(pin), before)
            # Explicit unsafe overrides continue through the production guard.
            denied = subprocess.run(call, env=dict(environment,
                CTH3DS_BUILD_PROFILE="resource-experiment", CTH3DS_GENERATED_DIR=str(pin / "unsafe")),
                capture_output=True, text=True, timeout=45)
            self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
            self.assertIn("output must be separate from source and overlay", denied.stderr)
            self.assertEqual(alias.resolve(strict=True), selected)

    def test_complete_profiles_seal_distinct_sources_and_reject_cross_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            area = Path(temp).resolve()
            original = original_sources(area / "original")
            binary = area / "binary"; binary.write_bytes(b"identity-only fixture")
            receipts = {}
            for profile in ("loose", "resource-experiment"):
                view = area / profile
                receipts[profile] = generate_private(original, ROOT, view, profile)
                receipt = verify_view(view, ROOT, profile)
                self.assertEqual(receipt["build_profile"], profile)
                common = view / "CorsixTH/Src/3ds/common"
                self.assertEqual({p.name for p in common.glob("*.cpp")},
                                 set(common_sources(ROOT, profile)))
                self.assertNotIn("resource_pack.cpp", common_sources(ROOT, profile))
                self.assertEqual(binding(view, ROOT, binary, profile)["build_profile"], profile)
                other = "resource-experiment" if profile == "loose" else "loose"
                # Execute the exact generated configuration contract in CMake.
                cmake_source = area / ("cmake-" + profile); cmake_source.mkdir()
                (cmake_source / "empty.cpp").write_text("")
                (cmake_source / "CMakeLists.txt").write_text(
                    "cmake_minimum_required(VERSION 3.16)\nproject(profile LANGUAGES CXX)\n"
                    "add_library(CorsixTH_lib STATIC empty.cpp)\n" +
                    cmake_contract(profile, common_sources(ROOT, profile)))
                for selected, expected in ((profile, 0), (other, 1)):
                    result = self.configure(cmake_source,
                        area / ("cmake-build-" + profile + "-" + selected),
                        "-DCTH3DS_BUILD_PROFILE=" + selected)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                with self.assertRaises(IntegrationError):
                    verify_view(view, ROOT, other)
                with self.assertRaises(IntegrationError):
                    binding(view, ROOT, binary, other)
                original_receipt = (view / RECEIPT).read_text()
                forged = json.loads(original_receipt); forged["build_profile"] = other
                (view / RECEIPT).write_text(json.dumps(forged))
                with self.assertRaises(IntegrationError):
                    verify_view(view, ROOT, other)
                (view / RECEIPT).write_text(original_receipt)
            self.assertNotEqual(receipts["loose"]["input_sha256"],
                                receipts["resource-experiment"]["input_sha256"])
            self.assertNotEqual(receipts["loose"]["view_sha256"],
                                receipts["resource-experiment"]["view_sha256"])
            self.assertEqual(receipts["loose"]["inputs"], receipts["resource-experiment"]["inputs"])
            self.assertEqual(len(common_groups(ROOT)["RESOURCE_EXPERIMENT"]), 5)
            for invalid in ("", "th3ds", "LOOSE", None):
                with self.assertRaises(IntegrationError):
                    validate_profile(invalid)

    def test_owner_and_shell_reject_profile_changes_before_work(self):
        with tempfile.TemporaryDirectory() as temp:
            area = Path(temp); lock = area / "owner.lock"
            owner = ROOT / "tools/source_view.py"
            environment = independent_environment()
            environment["CTH3DS_BUILD_PROFILE"] = "loose"
            code = ("import os,subprocess,sys; os.environ['CTH3DS_BUILD_PROFILE']='resource-experiment'; "
                    "sys.exit(subprocess.call([sys.executable,sys.argv[1],'check-owner','--lock',sys.argv[2]],"
                    "pass_fds=(int(os.environ['CTH3DS_SOURCE_OWNER_FD']),)))")
            result = subprocess.run([sys.executable, str(owner), "run", "--lock", str(lock), "--",
                                     sys.executable, "-c", code, str(owner), str(lock)],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("source owner build profile mismatch", result.stderr)
            environment["CTH3DS_BUILD_PROFILE"] = "invalid"
            result = subprocess.run(["bash", "-c", 'source "$1"; echo REACHED', "-", str(ROOT/"scripts/common.sh")],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("REACHED", result.stdout)
            for profile, expected in ((None, 0), ("invalid", 1)):
                options = []
                if profile is not None:
                    options.append("-DCTH3DS_BUILD_PROFILE=" + profile)
                build = area / ("root-" + str(profile))
                result = self.configure(ROOT, build, *options, env=environment)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                if profile is None:
                    self.assertIn("CTH3DS_BUILD_PROFILE:STRING=loose",
                                  (area / "root-None/CMakeCache.txt").read_text())
                    cache = (build / "CMakeCache.txt").read_text()
                    selected = dict(line.split("=", 1) for line in cache.splitlines()
                                    if line.startswith(("CMAKE_GENERATOR:INTERNAL=", "CMAKE_CXX_COMPILER:FILEPATH=")))
                    ctest = json.loads(subprocess.check_output(
                        ["ctest", "--test-dir", str(build), "--show-only=json-v1"], text=True))
                    command = next(test["command"] for test in ctest["tests"]
                                   if test["name"] == "python-integration-tests")
                    self.assertIn("CMAKE_GENERATOR=" + selected["CMAKE_GENERATOR:INTERNAL"], command)
                    self.assertIn("CXX=" + selected["CMAKE_CXX_COMPILER:FILEPATH"], command)
            for profile, mode in (("loose", "th3ds"), ("resource-experiment", "loose")):
                environment.update(CTH3DS_BUILD_PROFILE=profile,
                                   CTH3DS_SOURCE_OWNER_LOCK=str(lock),
                                   CTH3DS_DIST_DIR=str(area/"must-not-exist"))
                result = subprocess.run(["bash", str(ROOT/"scripts/package_sd.sh"), "--asset-mode", mode],
                                        env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("build profile", result.stderr)
                self.assertFalse((area/"must-not-exist").exists())

    def test_final_link_positive_and_negative_contracts_fail_closed(self):
        # Parser fixtures only. Actual ARM proof remains a build_3ds consumer.
        root = "cth3ds::runtime_initialize(lua_State*, char const*)"
        session = "cth3ds::RuntimeSession::start()"
        base = ("100 <" + root + ">:\n"
                "200 <mainloop(lua_State*)>:\n  202: bl 300 <cth3ds::runtime_assert_ready(lua_State*)>\n")
        symbols = "\n".join(REQUIRED.values())
        self.assertTrue(proof("", "", base, False, "loose")["pass"])
        for family in EXPERIMENT_FAMILIES:
            self.assertFalse(proof(family, "", base, False, "loose")["pass"])
            self.assertFalse(proof("", family, base, False, "loose")["pass"])
        linked = base.replace("100 <" + root + ">:\n", "100 <" + root + ">:\n  102: bl 400 <" + session + ">\n")
        linked += "400 <" + session + ">:\n"
        self.assertTrue(proof(symbols, symbols, linked, False, "resource-experiment")["pass"])
        self.assertFalse(proof(symbols, symbols, base, False, "resource-experiment")["pass"])
        self.assertFalse(proof(symbols, symbols, linked, True, "resource-experiment")["pass"])
        self.assertFalse(proof("", "", base, True, "loose")["pass"])
        self.assertFalse(proof("", "", "", False, "loose")["pass"])


if __name__ == "__main__":
    unittest.main()
