"""Offline voice preparation and the actual generated native DAT consumer.

Synthetic defaults are redistributable. CTH3DS_TEST_VOICES opts into a private
local corpus; no user audio is copied into this repository or normal fixtures.
"""
import hashlib
import io
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave

from prepare_loose_assets import parse_original_sound
from prepare_voice_banks import prepare, LANGUAGES
from th3ds_resource import ResourceError
import test_sound_lifetime as sound_tests

ROOT=Path(__file__).resolve().parents[2]

def wav(value,rate=11025,bits=8):
    out=io.BytesIO()
    with wave.open(out,'wb') as stream:
        stream.setparams((1,bits//8,rate,0,'NONE','not compressed'))
        stream.writeframes(bytes([value])*2206*(bits//8))
    return out.getvalue()

def bank(sfx,voice,foreign=False):
    data=bytearray(sound_tests.helper('make_audio_fixtures').archive([sfx,voice,sfx]))
    header=struct.unpack_from('<I',data,len(data)-4)[0]
    table=struct.unpack_from('<I',data,header+50)[0]
    # Preserve an exact duplicate reference in original reserved-zero layout.
    data[table+3*32:table+4*32]=data[table+32:table+64]
    if foreign:data[table+32:table+50]=data[table+96:table+114]=b'OTHER.WAV'.ljust(18,b'\0')
    return bytes(data)

class VoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-voice-')
        cls.addClassCleanup(cls.temp.cleanup);cls.directory=Path(cls.temp.name)
        cls.library=cls.directory/'voice_pcm.dylib'
        cls.flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl2'],text=True))
        cls.compiler=shutil.which('clang++') or 'c++'
        subprocess.run([cls.compiler,'-std=c++17','-O2','-shared','-fPIC',
            str(ROOT/'tools/voice_pcm.cpp'),*cls.flags,'-o',str(cls.library)],check=True)
        sound_tests.SoundLifetimeTests.setUpClass()
        cls.addClassCleanup(sound_tests.SoundLifetimeTests.doClassCleanups)

    def native(self,path):
        result=subprocess.run([str(sound_tests.SoundLifetimeTests.binary),'prepared-bank',str(path)],
                              capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS prepared-bank',result.stdout)
        print(path.name+': '+result.stdout.strip())

    def test_converter_bounds_and_actual_sdl_conversion(self):
        binary=self.directory/'converter-probe'
        subprocess.run([self.compiler,'-std=c++17','-O2','-fsanitize=address,undefined',
            '-fno-omit-frame-pointer',str(ROOT/'tools/voice_pcm.cpp'),
            str(ROOT/'tests/runtime_support/voice_pcm_probe.cpp'),*self.flags,'-o',str(binary)],check=True)
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS voice PCM',result.stdout)
        print(result.stdout.strip())

    def test_seven_voices_canonical_effects_aliases_and_reuse(self):
        with tempfile.TemporaryDirectory(dir=self.directory) as temp:
            root=Path(temp);sources={};originals={};sfx=wav(0x85,22050,16)
            for i,code in enumerate(LANGUAGES):
                data=bank(sfx if code in ('zh','en') else wav(0x92),wav(140+i),code not in ('zh','en'))
                path=root/(code+'.dat');path.write_bytes(data)
                sources[code]=path;originals[code]=data
            stage=root/'prepared'
            report=prepare(sources,stage,self.library)
            self.assertEqual(report,prepare(sources,stage,self.library))
            self.assertEqual(report['default'],'zh')
            self.assertEqual(len(report['files']),7)
            effect_pcm=None
            for item in report['files']:
                path=stage/item['path'];data=path.read_bytes()
                sounds,indices,reserved=parse_original_sound(data)
                self.assertEqual((indices,reserved),([1,2,3],1))
                self.assertEqual(sounds[0],sounds[2])
                if effect_pcm is None:effect_pcm=sounds[0].pcm
                self.assertEqual(sounds[0].pcm,effect_pcm)
                self.assertEqual(sounds[0].name,'S0001.WAV')
                self.assertTrue(all(s.sample_rate==22050 and s.bits_per_sample==16 for s in sounds))
                self.assertEqual(hashlib.sha256(data).hexdigest(),item['sha256'])
                self.native(path)
            self.assertTrue(all(path.read_bytes()==originals[code]for code,path in sources.items()))
            # A mismatched input cannot silently overwrite a previously prepared bank.
            sources['zh'].write_bytes(bank(sfx,wav(180)))
            prior=(stage/'Voices/Sound-CN.dat').read_bytes()
            with self.assertRaisesRegex(ResourceError,'refuse different'):
                prepare(sources,stage,self.library)
            self.assertEqual((stage/'Voices/Sound-CN.dat').read_bytes(),prior)

    def test_missing_event_and_noncanonical_chinese_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.directory) as temp:
            root=Path(temp);sfx=wav(128)
            en=root/'en.dat';zh=root/'zh.dat';fr=root/'fr.dat'
            en.write_bytes(bank(sfx,wav(140)));zh.write_bytes(bank(sfx,wav(141)))
            fr.write_bytes(sound_tests.helper('make_audio_fixtures').archive([sfx]))
            with self.assertRaisesRegex(ResourceError,'voice events missing'):
                prepare({'en':en,'zh':zh,'fr':fr},root/'bad',self.library)
            zh.write_bytes(bank(sfx,wav(141),True))
            with self.assertRaisesRegex(ResourceError,'indices differ'):
                prepare({'en':en,'zh':zh},root/'bad-zh',self.library)

    @unittest.skipUnless(os.environ.get('CTH3DS_TEST_VOICES'),'private corpus opt-in')
    def test_private_prepared_banks_all_events_in_actual_consumer(self):
        root=Path(os.environ['CTH3DS_TEST_VOICES'])
        paths=sorted((root/'Voices').glob('Sound-*.dat'))
        self.assertEqual(len(paths),7)
        for path in paths:self.native(path)

if __name__=='__main__':unittest.main()
