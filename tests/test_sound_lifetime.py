"""Real generated sound consumers and full platform adapter behavioral regressions."""
from pathlib import Path
import ctypes.util
import importlib.util
import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SUPPORT=ROOT/'tests/sound_lifetime_support'
sys.path.insert(0,str(ROOT/'tools'))
from integrate_corsixth import main as integrate
from test_playable_path import original_sources

def helper(name):
    spec=importlib.util.spec_from_file_location('sound_test_'+name,SUPPORT/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def library(name, override=None):
    value=os.environ.get(override) if override else None
    value=value or ctypes.util.find_library(name)
    if not value: raise RuntimeError('required test library missing: '+name)
    if '/' in value: return [value]
    if sys.platform=='darwin': return ['-l'+name]
    return ['-Wl,-l:'+value]

AUDIO_CASES=('success-747','native-failures','lua-cpp-failures','post-commit-lua-oom',
             'lua-preparation','retired-player','lua-finalizers','new-player-failure',
             'archive-cpp-failures','release-no-allocation','cache-eviction','bad-archives',
             'main-thread-callbacks')
LOAD_CASES=('primary-target','backup-target','alternate-target','normal-target','uppercase-fat-name',
            'windows-separator','save-false','save-throws','menu-load','failed-publication-recovery','quicksave-target')

class SoundLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='cth3ds-sound-lifetime-')
        cls.addClassCleanup(cls.temp.cleanup);cls.root=Path(cls.temp.name)
        cls.upstream=original_sources(cls.root/'upstream')
        assert integrate([str(cls.upstream),'--overlay-root',str(ROOT)])==0
        # Copy only generated consumers into the test seam include view.
        # Their bytes remain identical to full integrator output.
        cls.consumer=cls.root/'consumer';cls.consumer.mkdir()
        for name in ('th_sound.cpp','th_sound.h','th_lua_sound.cpp'):
            source=cls.upstream/'CorsixTH/Src'/name
            shutil.copy2(source,cls.consumer/name)
            assert source.read_bytes()==(cls.consumer/name).read_bytes()
        cls.fixtures=cls.root/'fixtures';helper('make_audio_fixtures').make(cls.fixtures)
        cls.binary=cls.root/'sound-lifetime'
        command=[os.environ.get('CXX','c++'),'-std=c++17','-O1','-DCORSIXTH_3DS',
                 '-I'+str(SUPPORT),'-I'+str(cls.consumer),
                 *shlex.split(subprocess.check_output(['pkg-config','--cflags','sdl2'],text=True)),
                 str(SUPPORT/'sound_lifetime_harness.cpp'),str(cls.consumer/'th_sound.cpp'),
                 *library('lua5.4','CTH3DS_LUA_LIBRARY'),
                 *shlex.split(subprocess.check_output(['pkg-config','--libs','sdl2'],text=True)),
                 '-pthread','-o',str(cls.binary)]
        if os.environ.get('CTH3DS_SOUND_SANITIZERS'):
            command[1:1]=['-fsanitize='+os.environ['CTH3DS_SOUND_SANITIZERS'],'-fno-omit-frame-pointer','-g']
        built=subprocess.run(command,capture_output=True,text=True)
        assert built.returncode==0,built.stdout+built.stderr

    def run_case(self,case):
        result=subprocess.run([str(self.binary),case,str(self.fixtures)],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS '+case,result.stdout)

    def test_generated_pcm_preflight_rejects_32bit_total_overflow(self):
        path=self.root/'arithmetic32.cpp';path.write_text(helper('arithmetic32').source(self.upstream/'CorsixTH/Src/th_sound.cpp'))
        binary=self.root/'arithmetic32'
        result=subprocess.run([os.environ.get('CXX','c++'),'-std=c++17',str(path),'-o',str(binary)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        result=subprocess.run([str(binary)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('accepted_overflow=0',result.stdout)

    def test_sound_callbacks_are_connected_to_actual_mainloop(self):
        core=(self.upstream/'CorsixTH/Src/sdl_core.cpp').read_text()
        self.assertIn('cth3ds_poll_sound_callbacks(SDL_GetTicks());',core)
        self.assertIn('if (!cth3ds_consume_sound_callback(e)) { nargs = 0; break; }',core)
        self.assertIn('lua_pushinteger(L, e.user.code);',core)
        self.assertIn('cth3ds_clear_sound_callbacks();\n  cth3ds::runtime_shutdown(L);',core)
        runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        self.assertIn('cth3ds_suspend_sound_callbacks(true, SDL_GetTicks());',runtime)
        self.assertIn('cth3ds_suspend_sound_callbacks(false, SDL_GetTicks());',runtime)
        self.assertIn('decision.pause_audio && !lifecycle_audio_suspended_',runtime)
        self.assertIn('decision.resume_audio && lifecycle_audio_suspended_',runtime)
        self.assertEqual(integrate([str(self.upstream),'--overlay-root',str(ROOT),'--check']),0)

class LoadRecoveryTests(unittest.TestCase):
    def run_case(self,case):
        with tempfile.TemporaryDirectory(prefix='cth3ds-load-recovery-') as temp:
            prefix='MODULE_FILE='+json.dumps(str(ROOT/'lua/3ds/platform.lua'))+'\nTESTDIR='+json.dumps(temp)+'\nCASE='+json.dumps(case)+'\n'
            script=Path(temp)/'case.lua';script.write_text(prefix+(SUPPORT/'load_recovery_cases.lua').read_text())
            # Keep Lua panics or allocator diagnostics isolated from unittest.
            result=subprocess.run([sys.executable,str(SUPPORT/'run_lua_file.py'),str(script)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS load-recovery',result.stdout)

def bind(case):
    def test(self):self.run_case(case)
    return test
for case in AUDIO_CASES:setattr(SoundLifetimeTests,'test_'+case.replace('-','_'),bind(case))
for case in LOAD_CASES:setattr(LoadRecoveryTests,'test_'+case.replace('-','_'),bind(case))
