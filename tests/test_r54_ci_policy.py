"""Keep tex3ds skipping bound to one ID/reason and forbid it in the required lane."""
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import test_gpu_renderer
ROOT=Path(__file__).resolve().parents[1]
class CiPolicyTests(unittest.TestCase):
    def test_exact_tex3ds_skip_and_required_lane(self):
        spec=importlib.util.spec_from_file_location('r54_host_runner',ROOT/'scripts/run_host_python_suite.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        manifest=runner.load_manifest(ROOT/'tests/host-python-suite.json')
        identity='test_gpu_renderer.GpuRendererTests.test_upload_matches_official_tex3ds'
        reason='official tex3ds tool unavailable; required in 3DS device lane'
        row={'id':identity,'outcome':'skipped','detail':reason}
        with patch.dict(os.environ,{'CTH3DS_REQUIRE_TEX3DS':'0'}):
            self.assertTrue(runner.is_allowed_skip(manifest,row))
            self.assertFalse(runner.is_allowed_skip(manifest,dict(row,id='other.test')))
            self.assertFalse(runner.is_allowed_skip(manifest,dict(row,detail=reason+' extra')))
            with patch('test_gpu_renderer.shutil.which',return_value=None):
                result=unittest.TestResult()
                case=test_gpu_renderer.GpuRendererTests('test_upload_matches_official_tex3ds')
                case.run(result);self.assertEqual(len(result.skipped),1)
                self.assertEqual(result.skipped[0][1],reason)
        with patch.dict(os.environ,{'CTH3DS_REQUIRE_TEX3DS':'1'}):
            self.assertFalse(runner.is_allowed_skip(manifest,row))
            with patch('test_gpu_renderer.shutil.which',return_value=None):
                result=unittest.TestResult()
                case=test_gpu_renderer.GpuRendererTests('test_upload_matches_official_tex3ds')
                case.run(result);self.assertEqual(len(result.failures),1)
                self.assertFalse(result.errors or result.skipped)
        # One parent test may contain multiple failed/error/skipped subtests.
        # Keep its single selected ID and strongest outcome; later successes
        # cannot turn an earlier failure into a pass or an unstarted test.
        class Subtests(unittest.TestCase):
            def runTest(self):
                for item in range(3):
                    with self.subTest(item=item):
                        if item==0 and self.mode in ('failure','mixed'):
                            self.fail('first subtest failed')
                        if item==1 and self.mode in ('error','mixed'):
                            raise RuntimeError('second subtest errored')
                        if item==0 and self.mode=='skip':
                            self.skipTest('subtest-only skip')
        for mode,expected in (('pass','passed'),('failure','failed'),
                              ('error','errors'),('mixed','errors'),('skip','skipped')):
            case=Subtests();case.mode=mode
            result=runner.RecordingRunner(stream=io.StringIO(),selected_ids=[case.id()]).run(case)
            self.assertEqual(set(result.outcomes),{case.id()},mode)
            self.assertEqual(result.outcomes[case.id()]['outcome'],expected,mode)
            self.assertFalse(result.synthetic_events,mode)
if __name__=='__main__':unittest.main()
