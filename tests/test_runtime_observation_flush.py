"""Link the real observation component; no extraction from native globals."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class RuntimeObservationFlushTests(unittest.TestCase):
    def test_production_short_run_and_terminal_open_span_are_retained(self):
        with tempfile.TemporaryDirectory(prefix='cth3ds-observation-') as temp:
            binary=Path(temp)/'probe'
            command=[os.environ.get('CXX','c++'),'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(ROOT/'include'),'-I'+str(ROOT/'src/3ds'),
                str(ROOT/'tests/runtime_support/observation_probe.cpp'),
                str(ROOT/'src/3ds/runtime/observation.cpp'),str(ROOT/'src/common/telemetry.cpp'),
                '-o',str(binary)]
            if os.environ.get('CTH3DS_SOUND_SANITIZERS'):
                command[1:1]=['-fsanitize='+os.environ['CTH3DS_SOUND_SANITIZERS'],'-fno-omit-frame-pointer']
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS compact throttle',result.stdout)
            self.assertIn('PASS in-place reset stale records retired tokens invalidated',result.stdout)
