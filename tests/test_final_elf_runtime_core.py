from __future__ import annotations

import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FinalElfRuntimeCoreTests(unittest.TestCase):
    def test_production_runtime_constructs_and_owns_the_session(self) -> None:
        source = (ROOT / "src/3ds/runtime_3ds.cpp").read_text(encoding="utf-8")
        self.assertIn("RuntimeSession::start(kResourceBundlePath", source)
        self.assertIn("std::unique_ptr<RuntimeSession> resource_session_", source)
        self.assertIn("resource_session_->shutdown()", source)
        self.assertIn("runtime-core: mount commit", source)
        self.assertIn("runtime-core: mount rollback", source)

        integrator = (ROOT / "tools/integrate_corsixth.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("${CTH3DS_COMMON_SOURCES}", integrator)
        self.assertIn("cth3ds::runtime_initialize(L)", integrator)
        self.assertIn("cth3ds::runtime_shutdown(L)", integrator)

    def test_cross_build_gate_requires_real_call_edge_without_whole_archive(self) -> None:
        script = (ROOT / "scripts/build_3ds.sh").read_text(encoding="utf-8")
        for required in (
            "runtime_session_start",
            "runtime_session_shutdown",
            "bundle_mount",
            "resource_acquire",
            "transition_rollback",
            "runtime_session_call_path",
            "production_entry",
        ):
            self.assertIn(required, script)
        self.assertIn('not whole_archive', script)
        self.assertNotIn('"-Wl,--whole-archive"', script)
        self.assertIn('"TransitionToken::~TransitionToken("', script)

    def test_current_cross_build_proof_when_supplied(self) -> None:
        path = os.environ.get("CTH3DS_RUNTIME_LINK_PROOF")
        if not path:
            self.skipTest("current devkitARM final-ELF proof was not supplied")
        proof = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertTrue(proof["pass"], proof)
        self.assertFalse(proof["whole_archive_used"], proof)
        self.assertTrue(proof["runtime_session_call_path"], proof)
        self.assertTrue(all(proof["archive_symbols"].values()), proof)
        self.assertTrue(all(proof["elf_symbols"].values()), proof)


if __name__ == "__main__":
    unittest.main()
