"""Actual native methods in both build profiles, real save and experimental core."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_playable_path import function_body
from test_th3ds_resource_packer import make_fixture
from th3ds_convert import build_resource_tree
from integration.build_profile import common_sources

ROOT = Path(__file__).resolve().parents[1]


class ResourceProfileRuntimeTests(unittest.TestCase):
    def test_actual_initialize_lifecycle_save_and_resource_profiles(self):
        runtime = (ROOT/"src/3ds/runtime_3ds.cpp").read_text()
        signatures = ("  bool initialize(", "  bool mark_ready(", "  void shutdown()",
                      "  void begin_critical_io()", "  void end_critical_io()",
                      "  void apply_lifecycle_decision(")
        methods = "\n".join(function_body(runtime, signature) for signature in signatures)
        methods += "\n#if CTH3DS_RESOURCE_EXPERIMENT\n" + function_body(
            runtime, "  ResourceResult<void> resource_event(") + "\n#endif\n"
        template = (ROOT/"tests/runtime_support/resource_profile_probe.cpp.in").read_text()
        code = template.replace("// INSERT_METHODS", methods).replace(
            "// INSERT_LUA", function_body(runtime, "int l_resource_event(")).replace(
            "// INSERT_GROUP", function_body(runtime, "std::uint32_t resource_group_id("))
        with tempfile.TemporaryDirectory(prefix="cth3ds-resource-profile-") as temp:
            area = Path(temp)
            source, languages, atlas = make_fixture(area)
            bundle = area/"resource-bundle"
            build_resource_tree(source, bundle, language_dir=languages, glyph_atlases=[atlas])
            cpp = area/"probe.cpp"; cpp.write_text(code)
            for profile, enabled in (("loose", "0"), ("resource-experiment", "1")):
                binary = area/profile
                command = [os.environ.get("CXX","c++"), "-std=c++17", "-O1",
                           "-Wall", "-Wextra", "-Wpedantic", "-Werror",
                           "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                           "-DCTH3DS_STUB_BUILD=1", "-DCTH3DS_RESOURCE_EXPERIMENT="+enabled,
                           "-I"+str(ROOT/"include"), str(cpp)]
                names = ["atomic_save.cpp", "lifecycle.cpp", "panel_refresh.cpp", "interval_gate.cpp"]
                if enabled == "1":
                    names += [n for n in common_sources(ROOT, profile) if n not in common_sources(ROOT)]
                command += [str(ROOT/"src/common"/name) for name in names]
                command += ["-o", str(binary)]
                built = subprocess.run(command, text=True, capture_output=True)
                self.assertEqual(built.returncode, 0, built.stdout+built.stderr)
                result = subprocess.run([str(binary), str(bundle/"bundle.th3ds.json"), str(area/(profile+".sav"))],
                                        text=True, capture_output=True, timeout=30,
                                        env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
                                                 UBSAN_OPTIONS="halt_on_error=1"))
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                print(result.stdout, end="")
                print(json.dumps({"profile":profile, "runtime_sha256":hashlib.sha256(runtime.encode()).hexdigest(),
                                  "extracted_cpp_sha256":hashlib.sha256(code.encode()).hexdigest(),
                                  "bundle_sha256":hashlib.sha256((bundle/"bundle.th3ds.json").read_bytes()).hexdigest(),
                                  "compile_command":command}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
