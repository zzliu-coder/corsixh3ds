"""Literal production grammar and full unsigned/signed/UTF8 boundary differential."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from test_save_memory import native_inputs

ROOT=Path(__file__).resolve().parents[1]
CALL=re.compile(r'(?:boot_log|output\.line|line)\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)')
STRING=re.compile(r'"(?:[^"\\]|\\.)*"')
CONV=re.compile(r'%(?:llu|lu|u|d|s|\.\*s|%)')

class LogFormatTests(unittest.TestCase):
    def test_actual_literal_grammar_extremes_and_fallback(self):
        formats=set()
        for name in ('src/3ds/runtime/observation.cpp','src/3ds/runtime_3ds.cpp','include/cth3ds/slow_events.hpp'):
            for match in CALL.finditer((ROOT/name).read_text()):
                text=''.join(json.loads(part[0]) for part in STRING.finditer(match[1]))
                if '%' not in CONV.sub('',text): formats.add(text)
        cases=[]
        values={'%llu':'ULLONG_MAX','%lu':'ULONG_MAX','%u':'UINT_MAX','%d':'INT_MIN',
                '%s':'"中文:test"','%.*s':'5,"中文:test"','%%':None}
        for fmt in sorted(formats):
            args=[values[m[0]] for m in CONV.finditer(fmt) if values[m[0]] is not None]
            cases.append('compare('+json.dumps(fmt,ensure_ascii=False)+(' ,'+','.join(args) if args else '')+');')
        self.assertGreater(len(formats),50)
        # C++ concatenates adjacent literals before calling the real logger.
        # Cover the complete multi-line memory report, including its last field.
        self.assertTrue(any(fmt.startswith('memory[%s]') and 'lua_peak=%llu' in fmt for fmt in formats))
        with tempfile.TemporaryDirectory(prefix='cth-r71-format-') as temp:
            target=Path(temp)/'probe';source=Path(temp)/'probe.cpp'
            source.write_text((ROOT/'tests/runtime_support/log_format_probe.cpp').read_text().replace(
                '// INSERT_LITERAL_CASES','\n'.join(cases)))
            compiler,_,_=native_inputs()
            command=[*compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(ROOT/'include'),str(source),'-o',str(target)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(target)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print('production_literal_formats='+str(len(formats)),result.stdout,end='')

if __name__=='__main__':unittest.main()
