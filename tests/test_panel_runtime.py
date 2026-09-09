"""Run actual Runtime Panel methods with real UI/canvas and bounded SDL stubs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_playable_path import function_body

ROOT = Path(__file__).resolve().parents[1]

class PanelRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures = ROOT/'tests/fixtures'
        metadata = json.loads((fixtures/'r73_panel_original.json').read_text())
        for name, expected in metadata['fixture_sha256'].items():
            if hashlib.sha256((fixtures/name).read_bytes()).hexdigest() != expected:
                raise RuntimeError('fixed R73 reference changed: ' + name)

    def test_actual_panel_contract_matches_fixed_original_and_game_leaves_gate_idle(self):
        runtime = (ROOT / 'src/3ds/runtime_3ds.cpp').read_text()
        methods = '\n'.join(function_body(runtime, signature) for signature in (
            '  void set_state(', '  void request_redraw()', '  void force_render_bottom()',
            '  void set_notice(', '  void render_bottom()', '  void present_bottom_canvas()'))
        tick = function_body(runtime, '  void tick(lua_State* state)')
        start = tick.rindex('    if (bottom_mode_ == BottomScreenMode::Panel &&')
        tail = '  void refresh_panel_tick(std::uint64_t frame_started) {\n' + tick[start:]
        original = (ROOT / 'tests/fixtures/r73_panel_runtime_original.inc').read_text()
        template = (ROOT / 'tests/runtime_support/panel_runtime_probe.cpp.in').read_text()
        code = template.replace('// INSERT_ORIGINAL', original).replace('// INSERT_CANDIDATE', methods + '\n' + tail)
        code = code.replace('// INSERT_SWAP', function_body(runtime, 'constexpr std::uint32_t byte_swap32('))
        with tempfile.TemporaryDirectory(prefix='cth3ds-panel-') as temp:
            source, binary = Path(temp)/'probe.cpp', Path(temp)/'probe'
            source.write_text(code)
            command = [os.environ.get('CXX', 'c++'), '-std=c++17', '-O1',
                       '-Wall', '-Wextra', '-Wpedantic', '-Werror',
                       '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                       '-I'+str(ROOT/'include'), '-I'+str(ROOT/'tests'), str(source)]
            command += [str(ROOT/'src/common'/name) for name in (
                'panel_refresh.cpp', 'bottom_ui.cpp', 'build_gesture.cpp',
                'software_canvas.cpp', 'screen_layout.cpp')]
            command += ['-o', str(binary)]
            built = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                         UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout, end='')

    def test_reset_and_mode_ownership_and_no_legacy_product_consumers(self):
        runtime = (ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        self.assertEqual(runtime.count('panel_refresh_.reset();'), 3)
        self.assertIn('panel_refresh_.reset();', function_body(runtime, '  bool initialize('))
        self.assertIn('panel_refresh_.reset();', function_body(runtime, '  void shutdown()'))
        lifecycle = function_body(runtime, '  void apply_lifecycle_decision(')
        resume = lifecycle[lifecycle.index('if (decision.resume_audio && lifecycle_audio_suspended_)'):]
        self.assertIn('panel_refresh_.reset();last_tick_us_=now_us();', resume)
        ensure = function_body(runtime, '  bool ensure_bottom_window()')
        self.assertIn('bottom_mode_ = BottomScreenMode::Game;', ensure)
        self.assertIn('std::fopen(kPanelModeMarker, "r")', ensure)
        self.assertIn('bottom_mode_ = BottomScreenMode::Panel;', ensure)
        self.assertEqual(runtime.count('bottom_mode_ = BottomScreenMode::'), 2)
        for name in ('  void set_state(', '  void request_redraw()', '  void set_notice(',
                     '  void refresh_system_status('):
            method = function_body(runtime, name)
            self.assertIn('if (bottom_mode_ == BottomScreenMode::Panel) panel_refresh_.request_redraw();', method)
        for directory in ('include', 'src', 'tools'):
            for path in (ROOT/directory).rglob('*'):
                if path.is_file() and path.suffix in ('.hpp', '.cpp', '.py', '.cmake'):
                    self.assertNotIn('FrameScheduler', path.read_text(), str(path))
        self.assertFalse((ROOT/'include/cth3ds/fixed_step.hpp').exists())
        self.assertFalse((ROOT/'src/common/fixed_step.cpp').exists())

if __name__ == '__main__':
    unittest.main()
