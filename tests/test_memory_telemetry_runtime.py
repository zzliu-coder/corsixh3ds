from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MemoryTelemetryRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = (ROOT / "src/3ds/runtime_3ds.cpp").read_text(encoding="utf-8")
        cls.platform = (ROOT / "lua/3ds/platform.lua").read_text(encoding="utf-8")

    def test_allocator_fields_and_caveat_are_explicit(self) -> None:
        for field in (
            "env_heap_total",
            "arena",
            "uordblks",
            "fordblks",
            "heap_available_estimate",
            "heap_used_estimate",
            "linear_total",
            "linear_free",
            "lua_current",
            "lua_peak",
            "elapsed_ms",
        ):
            self.assertIn(field, self.runtime)
        self.assertNotIn('lua_setfield(state, -2, "heap_free")', self.runtime)
        self.assertNotIn("heap_headroom_estimate", self.runtime)
        self.assertIn("largest-allocation ", self.runtime)
        self.assertIn('"guarantee"', self.runtime)

    def test_watermarks_start_after_the_process_heaps_are_available(self) -> None:
        register = self.runtime.index("void register_lua_module")
        initialize = self.runtime.index("initialize_heap_watermarks();", register)
        first_memory_log = self.runtime.index('boot_log_memory("S10")', register)
        self.assertLess(initialize, first_memory_log)
        self.assertIn("g_heap_watermarks_initialized", self.runtime)
        self.assertIn("low_water_valid", self.runtime)

    def test_failure_and_resource_bridges_preserve_identity_and_size(self) -> None:
        for binding in (
            'set_function(state, "resource_memory", l_resource_memory)',
            'set_function(state, "checkpoint", l_checkpoint)',
            'set_function(state, "allocation_failure", l_allocation_failure)',
        ):
            self.assertIn(binding, self.runtime)
        self.assertIn("resource=%s", self.runtime)
        self.assertIn("requested=%llu", self.runtime)

    def test_required_checkpoint_vocabulary_is_available(self) -> None:
        header = (ROOT / "include/cth3ds/memory_telemetry.hpp").read_text(
            encoding="utf-8"
        )
        for checkpoint in (
            "language_discovery",
            "language_selected",
            "sound_archive_read",
            "sound_archive_copy",
            "sound_decode",
            "vspr_table",
            "vspr_data",
            "vspr_decode",
            "adapter_attach",
            "menu",
            "first_level",
            "save_load",
            "transition",
        ):
            self.assertIn(f'"{checkpoint}"', header)

    def test_adapter_menu_level_save_load_and_transition_are_emitted(self) -> None:
        self.assertIn('boot_log_checkpoint("adapter_attach", "begin")', self.runtime)
        for token in (
            '"language_selected", "observed-at-adapter-attach"',
            '"menu", "ready"',
            '"first_level", "ready"',
            '"transition", "world-changed"',
            '"save_load", "save-begin"',
            '"save_load", "load-begin"',
        ):
            self.assertIn(token, self.platform)
        self.assertIn('set_function(state, "resource_event", l_resource_event)', self.runtime)
        for event in ("menu", "level", "save-begin", "save-end", "load-begin", "load-end"):
            self.assertIn(f'"{event}"', self.platform)

    def test_probe_is_bounded_and_described_as_lower_bound(self) -> None:
        self.assertIn("probe_largest_contiguous", self.runtime)
        self.assertIn("result=verified-lower-bound", self.runtime)
        header = (ROOT / "include/cth3ds/memory_telemetry.hpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("maximum_probe_bytes{8U * 1024U * 1024U}", header)
        self.assertIn("MemoryGate::MenuStable", header)
        self.assertIn("36U * kMiB, 16U * kMiB, 8U * kMiB, 4U * kMiB", header)
        self.assertIn("memory-gate[%s]", self.runtime)

    def test_runtime_distinguishes_legacy_diagnostics_from_contract_pools(self) -> None:
        header = (ROOT / "include/cth3ds/memory_telemetry.hpp").read_text(
            encoding="utf-8"
        )
        for pool in ("audio", "sprite", "texture", "language_font", "metadata", "scratch", "unclassified"):
            self.assertIn(f'"{pool}"', header)
        self.assertIn('lua_setfield(state, -2, "diagnostic_resources")', self.runtime)
        self.assertNotIn('lua_setfield(state, -2, "resources")', self.runtime)

    def test_lua_adapter_emits_runtime_checkpoint_sequence(self) -> None:
        lua = shutil.which("lua")
        if lua is None:
            self.skipTest("Lua command is unavailable")
        adapter = json.dumps(str((ROOT / "lua/3ds/platform.lua").resolve()))
        with tempfile.TemporaryDirectory() as temporary:
            save_root = json.dumps(str(Path(temporary).resolve()) + "/")
            script = f"""
local module = assert(loadfile({adapter}))()
local checkpoints = {{}}
local resource_events = {{}}
local fail_save = false
local fail_load = false
local function saw(name, phase)
  return checkpoints[name .. ":" .. phase] == true
end
local native = {{
  checkpoint = function(name, phase)
    checkpoints[name .. ":" .. phase] = true
  end,
  resource_event = function(event, identity, success)
    resource_events[#resource_events + 1] = event .. ":" .. tostring(success)
    return true, nil
  end,
  begin_critical_io = function() end,
  end_critical_io = function() end,
  atomic_commit = function(temporary, final)
    local ok, err = os.rename(temporary, final)
    return ok ~= nil, err
  end,
  recover_atomic = function() return true end,
  set_notice = function() end,
  set_state = function() end,
  request_redraw = function() end,
}}
local app = {{
  config = {{language = "simplified_chinese"}},
  savegame_dir = {save_root},
  ui = {{windows = {{}}, bottom_panel = {{visible = true,
          message_queue = {{}}, message_windows = {{}}}}}},
  dispatch = function() end,
  save = function(self, filename)
    if fail_save then error("synthetic save failure") end
    local handle = assert(io.open(filename, "wb"))
    handle:write("SAVE")
    handle:close()
    return "saved"
  end,
  load = function(self, filename)
    if fail_load then error("synthetic load failure") end
    return filename, nil, 3
  end,
}}
local platform = module.attach(app, native)
assert(saw("language_selected", "observed-at-adapter-attach"))
assert(saw("menu", "ready"))
assert(resource_events[1] == "menu:true")
app.world = {{}}
platform:syncBottomState()
assert(saw("transition", "world-changed"))
assert(saw("first_level", "ready"))
assert(resource_events[2] == "level:true")
assert(app:save({save_root} .. "slot.sav") == "saved")
assert(saw("save_load", "save-begin"))
assert(saw("save_load", "save-complete"))
assert(resource_events[3] == "save-begin:true")
assert(resource_events[4] == "save-end:true")
local first, second, third = app:load("slot.sav")
assert(first == "slot.sav" and second == nil and third == 3)
assert(saw("save_load", "load-begin"))
assert(saw("save_load", "load-complete"))
assert(resource_events[5] == "load-begin:true")
assert(resource_events[6] == "load-end:true")
fail_save = true
assert(not pcall(app.save, app, {save_root} .. "failed.sav"))
assert(resource_events[7] == "save-begin:true")
assert(resource_events[8] == "save-end:false")
fail_load = true
assert(not pcall(app.load, app, "failed.sav"))
assert(resource_events[9] == "load-begin:true")
assert(resource_events[10] == "load-end:false")
"""
            result = subprocess.run(
                [lua, "-"], input=script, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class MeasurementComponentRuntimeTests(unittest.TestCase):
    """Execute the actual public components with fixed clock/allocator inputs."""

    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which("clang++") or shutil.which("g++")
        if compiler is None:
            raise RuntimeError("C++ compiler required for measurement contract")
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        source = root / "measurement.cpp"
        source.write_text(r'''
#include "cth3ds/telemetry.hpp"
#include "cth3ds/memory_telemetry.hpp"
#include <iostream>
int main() {
  cth3ds::Telemetry timing;
  timing.present_complete(0, cth3ds::PresentResult::Success);
  auto save = timing.begin_span(cth3ds::TimingStage::Save, 1000);
  timing.end_span(save, 70001000, false);
  timing.present_complete(70002000, cth3ds::PresentResult::Success);
  const auto t = timing.snapshot();
  cth3ds::MemoryTelemetry memory;
  cth3ds::MemorySample sample{7, 5200, 3000, 2400, 600, 800, 300, 1000, true};
  memory.observe("save", cth3ds::memory_observation(sample,
      cth3ds::MemoryGate::Operation, "save", "failed", "state", 4096, true,
      128, true, true));
  const auto& m = memory.checkpoints()[21];
  std::cout << "{\"interval_us\":" << t.intervals.total_us
    << ",\"save_failed\":" << t.stages[7].failed
    << ",\"heap_used\":" << sample.heap_used_estimate()
    << ",\"failure_request\":" << memory.last_failure().requested_bytes
    << ",\"timing_bytes\":" << sizeof(timing)
    << ",\"memory_bytes\":" << sizeof(memory) << "}";
  (void)m;
}
''', encoding="utf-8")
        binary = root / "measurement"
        built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I" + str(ROOT / "include"), str(source),
            str(ROOT / "src/common/telemetry.cpp"), "-o", str(binary)],
            text=True, capture_output=True)
        if built.returncode:
            raise RuntimeError(built.stderr)
        run = subprocess.run([str(binary)], text=True, capture_output=True, check=True)
        cls.observed = json.loads(run.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_save_without_frames_contributes_full_interval_and_failure(self) -> None:
        self.assertEqual(self.observed["interval_us"], 70002000)
        self.assertEqual(self.observed["save_failed"], 1)

    def test_known_allocator_values_and_fixed_storage(self) -> None:
        self.assertEqual(self.observed["heap_used"], 2400)
        self.assertEqual(self.observed["failure_request"], 4096)
        self.assertLessEqual(self.observed["timing_bytes"], 20 * 1024)
        self.assertLessEqual(self.observed["memory_bytes"], 16 * 1024)


if __name__ == "__main__":
    unittest.main()
