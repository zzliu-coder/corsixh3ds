from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = (ROOT / "src/3ds/runtime_3ds.cpp").read_text(encoding="utf-8")

    def test_static_lua_modules_are_preloaded(self) -> None:
        for module in ('preload("th3ds"', 'preload("lfs"', 'preload("lpeg"'):
            self.assertIn(module, self.runtime)

    def test_hid_scan_is_owned_by_sdl_event_pump(self) -> None:
        # The frame loop consumes SDL's scan. The fatal error page performs its
        # own bounded scan so B/Start can dismiss it.
        self.assertEqual(self.runtime.count("hidScanInput();"), 1)
        self.assertIn("hidKeysDown()", self.runtime)
        self.assertIn("hidKeysHeld()", self.runtime)
        self.assertIn("hidKeysUp()", self.runtime)

    def test_lifecycle_and_hardware_status_are_connected(self) -> None:
        for token in (
            "aptHook(",
            "PTMU_GetBatteryLevel",
            "HIDUSER_GetSoundVolume",
            "osGetWifiStrength()",
            "begin_critical_io",
            "end_critical_io",
        ):
            self.assertIn(token, self.runtime)

    def test_old3ds_heap_budget_and_real_allocator_metrics(self) -> None:
        self.assertIn("__ctru_linear_heap_size = 8U * 1024U * 1024U", self.runtime)
        for token in ("envGetHeapSize()", "mallinfo()", "linearSpaceFree()"):
            self.assertIn(token, self.runtime)
        self.assertNotIn("osGetMemRegionFree", self.runtime)
        for token in ("heap_available_low_water", "linear_low_water", "lua_peak_bytes"):
            self.assertIn(token, self.runtime)
        self.assertIn("memory_gate_policy(gate)", self.runtime)
        self.assertIn("gate_policy.probe_bytes", self.runtime)
        self.assertIn('set_function(state, "probe_regular_heap", l_probe)', self.runtime)

    def test_startup_is_visible_before_mainloop(self) -> None:
        for token in (
            'stage("S10", "NATIVE BOOTSTRAP")',
            'stage("S30", "GAME WINDOW READY")',
            'stage("S90", "STARTING RUNTIME")',
            'stage("S100", "READY")',
            "render_boot_page(true)",
            'set_function(state, "stage", l_stage)',
        ):
            self.assertIn(token, self.runtime)

    def test_mirror_contract_failure_is_explicit(self) -> None:
        self.assertIn('startup_code_ = "E-MIRROR"', self.runtime)
        self.assertNotIn("using panel", self.runtime)

    def test_legacy_panel_buffer_is_lazy(self) -> None:
        self.assertIn("std::unique_ptr<SoftwareCanvas> bottom_canvas_{}", self.runtime)
        self.assertIn("legacy panel canvas allocated on demand", self.runtime)
        self.assertNotIn(": bottom_canvas_(ScreenLayout", self.runtime)

    def test_packaged_config_has_deterministic_player_name(self) -> None:
        package_script = (ROOT / "scripts/package_sd.sh").read_text(encoding="utf-8")
        self.assertIn('player_name = "PLAYER"', package_script)


if __name__ == "__main__":
    unittest.main()
