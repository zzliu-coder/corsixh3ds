"""AR6 two-profile identity and real generated-source boundaries (no ARM claim)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from integration.build_profile import common_groups, common_sources, validate_profile, cmake_contract
from integration.common import IntegrationError
from integration.generated_view import RECEIPT, verify_view
from integrate_corsixth import generate_private
from source_view import binding, independent_environment
from support.pinned_upstream import original_sources
from check_resource_link import proof, REQUIRED, EXPERIMENT_FAMILIES


class BuildProfileTests(unittest.TestCase):
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
                    result = subprocess.run(["cmake", "-S", str(cmake_source), "-B",
                        str(area / ("cmake-build-" + profile + "-" + selected)),
                        "-DCTH3DS_BUILD_PROFILE=" + selected], capture_output=True, text=True)
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
                command = ["cmake", "-S", str(ROOT), "-B", str(area / ("root-" + str(profile)))]
                if profile is not None:
                    command.append("-DCTH3DS_BUILD_PROFILE=" + profile)
                result = subprocess.run(command, env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                if profile is None:
                    self.assertIn("CTH3DS_BUILD_PROFILE:STRING=loose",
                                  (area / "root-None/CMakeCache.txt").read_text())
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
