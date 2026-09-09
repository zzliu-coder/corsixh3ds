"""R66 production arithmetic and collectable closed-file diagnostics."""
import os
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import test_lua_runtime
import test_save_stream_lua

ROOT = Path(__file__).resolve().parents[1]


class R66ThermalSaveTests(unittest.TestCase):
    def test_existing_r65_report_migrates_once(self):
        import sys
        with patch.object(sys, 'path', [str(ROOT/'tools/integration'), *sys.path]):
            spec = importlib.util.spec_from_file_location('r66_save_stream', ROOT/'tools/integration/save_stream.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix='cth-r66-migrate-') as name:
            root = Path(name)
            target = root/'CorsixTH/Lua/persistance.lua'
            target.parent.mkdir(parents=True)
            target.write_text(module.SAVE_TRANSACTION+module.FILE_PREFIX)
            _, first = next(module.transforms(root))
            self.assertEqual(first.count('saveDiagnostic(owner,operation,"closed_file_report",'
                'TH3DS and TH3DS.diagnostic_line or print,report)'),1)
            self.assertIn('local operation=owner and owner.current',first)
            self.assertIn('return owner:diagnostic(operation,site,callback,...)',first)
            self.assertNotIn(module.OLD_REPORT, first)
            target.write_text(first)
            self.assertEqual(next(module.transforms(root))[1], first)

    def test_production_uint16_cooling_exhaustive(self):
        with tempfile.TemporaryDirectory(prefix='cth-r66-cooling-') as name:
            directory = Path(name)
            source = directory/'probe.cpp'
            source.write_text('''#include <cassert>
#include "cth3ds/thermal_grid.hpp"
int main() {
  for (unsigned v=0; v<=65535U; ++v)
    assert(cth3ds::thermal_cool_uint16(static_cast<std::uint16_t>(v))==v*999U/1000U);
}
''')
            binary = directory/'probe'
            subprocess.run([shutil.which('clang++') or shutil.which('g++'),
                '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-I'+str(ROOT/'include'),
                str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True,
                env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                         UBSAN_OPTIONS='halt_on_error=1'))

    def test_native_diagnostic_failure_matrix_retry_and_commit_boundary(self):
        # Reuse the real generated transaction/Operations/file matrix. A closed
        # file report is one diagnostic category, independent of later commit.
        base = test_save_stream_lua.SaveStreamLuaTests
        base.setUpClass()
        self.addCleanup(base.doClassCleanups)
        run_lua = test_lua_runtime.LuaRuntimeTests.run_lua

        def instrument(instance, script):
            anchor = 'TH3DS=native\n'
            self.assertEqual(script.count(anchor), 1)
            script = script.replace(anchor, '''local closed_report_attempts=0
native.diagnostic_line=function(message)
 if not message:find('save-stream:',1,true) then messages[#messages+1]=message;return end
 closed_report_attempts=closed_report_attempts+1
 assert(closed==1 and cleaned==prepared and live=='LIVE' and commits==0)
 assert(#message<=240,'one native log line')
 assert(message:find('close_ok=1 commit_included=0',1,true))
 if failure=='closed_report' then error('injected closed report') end
 messages[#messages+1]=message
end
print=function()error('native outlet must be used')end
TH3DS=native
''')
            anchor = '-- The original string API still performs exactly one paired transaction.'
            self.assertEqual(script.count(anchor), 1)
            script = script.replace(anchor, '''-- A diagnostic-only failure must still reach one successful commit.
failure='closed_report';prepared=0;cleaned=0;closed=0;dumped=0;commits=0
write(final,'OLD');write(final..'.bak','OLDER')
local reports_before=#messages
assert(TheApp:save(final)==true and commits==1)
assert(read(final)==payload and read(final..'.bak')=='OLD')
assert(prepared==1 and cleaned==1 and closed==1 and live=='LIVE')
local result=TheApp._3ds.operations.last
assert(result.committed and result.ready and result.diagnostic_count==1 and result.cleanup_count==0)
assert(result.diagnostic_first:match('^closed_file_report: ') and
 result.diagnostic_first:find('injected closed report',1,true),result.diagnostic_first)
assert(TheApp._3ds.operations.current==nil)
-- The failed stream report did not appear; the owner emits its separate result.
assert(#messages==reports_before+1 and messages[#messages]:find('operation-result:',1,true))
-- A closed-file report cannot certify the later commit.
failure='';prepared=0;cleaned=0;closed=0;dumped=0;commits=0
write(final,'OLD');write(final..'.bak','OLDER')
local reports_before=#messages
native.atomic_commit=function()commits=commits+1;return nil,'injected commit' end
local ok=pcall(TheApp.save,TheApp,final)
assert(not ok and commits==1)
assert(read(final)=='OLD' and read(final..'.bak')=='OLDER')
assert(messages[reports_before+1]:find('save-stream:',1,true),'closed temporary report precedes commit failure report')
local added_stream_reports=0
for i=reports_before+1,#messages do
 if messages[i]:find('save-stream:',1,true) then added_stream_reports=added_stream_reports+1 end
end
assert(added_stream_reports==1,'failed commit has exactly one earlier closed-file report')
assert(not TheApp._3ds.operations.last.committed and TheApp._3ds.operations.last.ready)
successful_reports=successful_reports+1 -- writer/close succeeded; commit did not
assert(closed_report_attempts==successful_reports+1,'one additional rejected diagnostic attempt')
''' + anchor)
            return run_lua(instance, script)

        with patch.object(test_lua_runtime.LuaRuntimeTests, 'run_lua', instrument):
            base().test_generated_stream_transaction_failure_matrix_and_retry()


if __name__ == '__main__':
    unittest.main()
