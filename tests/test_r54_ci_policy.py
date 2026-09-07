"""Keep tex3ds skipping bound to one ID/reason and forbid it in the required lane."""
import importlib.util
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
if __name__=='__main__':unittest.main()
